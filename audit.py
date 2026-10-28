"""Read-only audit operations, isolated from the Streamlit interface."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager
import csv
import gzip
import io
import os
import shutil
import sqlite3
import tempfile
import time

import sqlglot
from sqlglot import expressions as exp

AGENCY = 1000
RESULT_COLUMNS = 'ID, FullName, Amount, Description, Vendor, TransactionDate, PostedDate, MCC'
AI_ROW_LIMIT = 5000


class AuditError(ValueError):
    """A short, user-facing error without secrets or system details."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool = False

    def csv_bytes(self) -> bytes:
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(self.columns)
        for row in self.rows:
            # Prevent exported text from becoming spreadsheet formulas on open.
            writer.writerow([
                "'" + value if isinstance(value,str) and value.lstrip().startswith(('=', '+', '-', '@')) else value
                for value in row
            ])
        return stream.getvalue().encode('utf-8-sig')


def database_path() -> Path:
    configured = os.environ.get('PCARD_DB_PATH','').strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise AuditError('The configured database was not found. Check PCARD_DB_PATH.')
        return path
    path = Path(__file__).parent / 'data' / 'pcards.db'
    compressed = path.with_suffix('.db.gz')
    if not path.is_file():
        if not compressed.is_file():
            raise AuditError('The database is missing. Follow the data preparation step in README.md.')
        # Unique temporary file + atomic replacement also supports concurrent sessions.
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.building',delete=False) as file:
            temporary = Path(file.name)
            try:
                with gzip.open(compressed,'rb') as source:
                    shutil.copyfileobj(source,file)
                file.flush()
                os.fsync(file.fileno())
            except Exception:
                temporary.unlink(missing_ok=True)
                raise AuditError('The packaged database could not be opened. Restore data/pcards.db.gz.') from None
        temporary.replace(path)
    return path


@contextmanager
def connection(path: Path):
    conn = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    conn.execute('PRAGMA query_only=ON')
    try:
        yield conn
    finally:
        conn.close()


def years(path: Path) -> list[int]:
    with connection(path) as conn:
        return [r[0] for r in conn.execute(
            'SELECT DISTINCT Year FROM pcards WHERE AgencyNumber=? ORDER BY Year', (AGENCY,))]


def overview(path: Path, year: int) -> dict:
    with connection(path) as conn:
        count, spend, people, start, end = conn.execute('''
            SELECT COUNT(*), COALESCE(SUM(Amount),0), COUNT(DISTINCT FullName),
                   MIN(TransactionDateISO), MAX(TransactionDateISO)
            FROM pcards WHERE AgencyNumber=? AND Year=?''',(AGENCY,year)).fetchone()
    return {'count':count,'spend':round(spend,2),'people':people,'first_date':start,'last_date':end}


def schema_text(path: Path) -> str:
    with connection(path) as conn:
        return ', '.join(f'{row[1]} {row[2]}' for row in conn.execute('PRAGMA table_info(pcards)'))


def search(path: Path, year: int, field: str, keyword: str) -> QueryResult:
    if field not in ('Description','Vendor'):
        raise AuditError('Choose Description or Vendor search.')
    keyword = keyword.strip()
    if not keyword:
        raise AuditError('Enter a keyword before searching.')
    if len(keyword)>150:
        raise AuditError('Use a keyword of 150 characters or fewer.')
    escaped=keyword.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
    sql=f'''SELECT {RESULT_COLUMNS} FROM pcards
        WHERE AgencyNumber=? AND Year=? AND {field} LIKE ? ESCAPE '\\'
        ORDER BY TransactionDateISO DESC, ID DESC'''
    with connection(path) as conn:
        cursor=conn.execute(sql,(AGENCY,year,'%'+escaped+'%'))
        return QueryResult([d[0] for d in cursor.description],cursor.fetchall())


ALLOWED_FUNCTIONS={
    'abs','avg','cast','coalesce','count','date','datetime','format','glob',
    'ifnull','iif','instr','julianday','length','like','log','log10','lower',
    'ltrim','max','min','mod','nullif','pow','power','printf','replace','round',
    'rtrim','sign','sqrt','strftime','substr','substring','sum','time','total',
    'trim','typeof','unixepoch','upper','row_number','rank','dense_rank',
    'lag','lead','first_value','last_value','nth_value','ntile','cume_dist',
    'percent_rank',
}


def validate_sql(sql: str) -> str:
    if not isinstance(sql,str) or not sql.strip():
        raise AuditError('No database query was generated. Try a more specific transaction question.')
    if len(sql)>16000:
        raise AuditError('The generated query is too long. Try a simpler question.')
    # Match the lecture contract: one SELECT/WITH, no comments or semicolons.
    if any(token in sql for token in (';', '--', '/*', '*/')):
        raise AuditError('The generated query contains unsupported comments or multiple-statement markers. Please retry.')
    try:
        parsed=sqlglot.parse(sql,read='sqlite')
    except sqlglot.errors.ParseError:
        raise AuditError('The generated SQL could not be understood. Try rephrasing the question.') from None
    if len(parsed)!=1 or not isinstance(parsed[0], exp.Query):
        raise AuditError('Only one read-only SELECT query is allowed.')
    tree=parsed[0]
    for node in tree.walk():
        if isinstance(node,(exp.DML,exp.DDL,exp.Command,exp.Into)):
            raise AuditError('Queries that change data or database settings are not allowed.')
    cte_names={cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables=list(tree.find_all(exp.Table))
    if not tables:
        raise AuditError('Ask a question about the P-card transactions.')
    for table in tables:
        if table.db or table.catalog or not isinstance(table.this,exp.Identifier):
            raise AuditError('Queries may only read the scoped P-card table.')
        if table.name.lower() not in {'pcards'} | cte_names:
            raise AuditError('Queries may only read pcards and their temporary query results.')
    # Execute the original SQL, avoiding differences between parser and SQLite dialects.
    return sql.strip()


def run_audit_query(path: Path, year: int, sql: str, row_limit: int=AI_ROW_LIMIT,
                    seconds: float=8.0) -> QueryResult:
    sql=validate_sql(sql)
    if year not in years(path):
        raise AuditError('Select a year available in the database.')
    conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        # Shadow the physical table with a scoped view. Every ordinary pcards
        # reference, including references inside CTEs/self-joins, uses this view.
        # Qualified names such as main.pcards are rejected above.
        conn.execute(f'''CREATE TEMP VIEW pcards AS
            SELECT * FROM main.pcards WHERE AgencyNumber={AGENCY} AND Year={int(year)}''')
        conn.execute('PRAGMA query_only=ON')
        def authorize(action,arg1,arg2,database,source):
            if action==sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action==sqlite3.SQLITE_READ:
                # Underlying reads are allowed only through our scoped view.
                if arg1=='pcards' and (database=='temp' or (database=='main' and source=='pcards')):
                    return sqlite3.SQLITE_OK
            if action==sqlite3.SQLITE_FUNCTION and str(arg2 or arg1).lower() in ALLOWED_FUNCTIONS:
                return sqlite3.SQLITE_OK
            if action==getattr(sqlite3,'SQLITE_RECURSIVE',33):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        conn.set_authorizer(authorize)
        started=time.monotonic()
        conn.set_progress_handler(lambda: int(time.monotonic()-started>seconds),1000)
        cursor=conn.execute(sql)
        columns=[d[0] for d in cursor.description]
        rows=cursor.fetchmany(row_limit+1)
        return QueryResult(columns,rows[:row_limit],len(rows)>row_limit)
    except sqlite3.Error as error:
        if 'interrupt' in str(error).lower():
            raise AuditError('This query took too long. Narrow the question or use a simpler comparison.') from None
        if 'not authorized' in str(error).lower() or 'prohibited' in str(error).lower():
            raise AuditError('This query uses a database operation that is not allowed. Please rephrase it.') from None
        # SQL contains no key. Keep diagnostics bounded and avoid system paths.
        message=str(error).replace(str(path),'database')[:180]
        raise AuditError('SQLite could not run the generated query: '+message) from None
    finally:
        conn.close()


EXAMPLES={
    'Employees spending more than $50,000 in the year': (
        'SELECT FullName, ROUND(SUM(Amount),2) AS TotalSpent FROM pcards '
        'GROUP BY FullName HAVING SUM(Amount)>50000 ORDER BY SUM(Amount) DESC',
        'Adds signed transaction amounts for each employee in the selected year, then lists annual net totals above $50,000. This follows the assignment annual screen, not the policy billing-cycle limit.'),
    'Individual purchases above $5,000': (
        f'SELECT {RESULT_COLUMNS} FROM pcards WHERE Amount>5000 ORDER BY Amount DESC, ID',
        'Shows individual purchases exceeding $5,000 in the selected year, largest first.'),
    'Gift cards mentioned in descriptions': (
        f"SELECT {RESULT_COLUMNS} FROM pcards WHERE Amount>0 AND "
        "(LOWER(Description) LIKE '%gift card%' OR LOWER(Description) LIKE '%gift certificate%' "
        "OR LOWER(Description) LIKE '%giftcard%') ORDER BY Amount DESC, ID",
        'Finds positive charges explicitly mentioning gift cards or gift certificates. Receipts are needed to confirm the purchased items.'),
    'The ten vendors with the highest net spending': (
        'SELECT Vendor, COUNT(*) AS Transactions, ROUND(SUM(Amount),2) AS NetSpend '
        'FROM pcards GROUP BY Vendor ORDER BY SUM(Amount) DESC, Vendor LIMIT 10',
        'Ranks vendors by net spending, including credits, for the selected year.'),
}
