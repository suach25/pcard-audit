# P-card audit workspace

Website for querying Oklahoma State University purchasing-card transactions.

## Files in this folder

- `app.py`: the website screens and forms.
- `audit.py`: database searches, calculations and read-only query checks.
- `ai_service.py`: Gemini connection and question-to-SQL translation.
- `requirements.txt`: software packages the host must install.
- `data/pcards.db.gz`: compressed database; automatically expanded on first run.
- `.streamlit/config.toml`: appearance and website settings.
- `.gitignore`: prevents local environments and real secret files being uploaded.
- `README.md`: these instructions.

Upload this folder's contents to GitHub, including the two hidden configuration
files and the compressed database. Do not upload any real API key.

## Run locally

Use Python 3.12. Open a terminal in this folder:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

On Windows replace `.venv/bin/python` with `.venv\Scripts\python.exe`.

## Connect AI and publish

For local testing, enter a Gemini API key in the sidebar's AI connection panel.
For hosting, configure `GEMINI_API_KEY` in the host's Secrets settings or
server environment. Never put it in a tracked source file. The default model
is gemini-3.5-flash-lite. A fallback handles temporary provider errors.

Deploy to a host that runs Python, such as Streamlit Community Cloud. Select
`app.py` as the entry point and Python 3.12 as the runtime. GitHub Pages alone
cannot run this Python website. This folder has not been published yet.

## Use

Select the year. The prohibited-purchase dashboard offers separate Description
and Vendor keyword searches, complete matching records and CSV downloads.
The Ask the database tab translates a question into read-only SQL and shows
its explanation, query and results. Saved examples work without Gemini and
are explicitly identified as saved queries, not live AI answers.

OSU scope and the selected year are enforced in the query engine. AI results
are capped at 5,000 rows with a visible warning when truncated. Dashboard CSVs
include all matches. Numeric totals include negative credits unless a query
explicitly restricts the population to positive purchases.

Use 2014 for the written assignment. A gift-card description search returns
2 transactions with a combined amount of $135.00. The annual-spending example
returns 127 employees above $50,000. Flags require supporting evidence before
concluding that a violation or fraud occurred.

## Submission

The assignment requires the completed Word document, a live website link,
and a GitHub repository link. This folder supplies the website source for the
repository and hosting. Parts II/III SQL files and CSV outputs are separate
supporting evidence, not files the website needs to run.
