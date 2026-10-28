"""SDU Assignment 1 Case 2: a local P-card audit website."""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from audit import (AuditError, QueryResult, database_path, years, overview,
                   schema_text, search, run_audit_query, EXAMPLES)
from ai_service import DEFAULT_MODEL, generate_query

st.set_page_config(page_title='P-card audit workspace',page_icon='📊',layout='wide')


@st.cache_data(show_spinner=False)
def available_years(path: str, stamp: int):
    return years(Path(path))


@st.cache_data(show_spinner=False)
def population_summary(path: str, stamp: int, year: int):
    return overview(Path(path),year)


def server_setting(name: str, default='') -> str:
    value=os.environ.get(name,'').strip()
    if value:return value
    try:
        return str(st.secrets.get(name,default)).strip()
    except (FileNotFoundError,st.errors.StreamlitSecretNotFoundError):
        return default


def show_result(result: QueryResult, filename: str, key: str):
    if not result.rows:
        st.info('No transactions matched this search. Try another keyword or year.')
    else:
        st.dataframe(pd.DataFrame(result.rows,columns=result.columns),hide_index=True,
                     width='stretch',height=min(460,40+35*min(len(result.rows),12)))
    if result.truncated:
        st.warning('This query returned more than 5,000 rows. The table and download contain the first 5,000 only. Narrow your question for a complete result.')
    st.download_button('Download these results as CSV',data=result.csv_bytes(),
                       file_name=filename,mime='text/csv',key=key)


try:
    path=database_path()
    stamp=path.stat().st_mtime_ns
    year_options=available_years(str(path),stamp)
    if not year_options:raise AuditError('The database contains no OSU transactions.')
except (AuditError,OSError) as error:
    st.title('P-card audit workspace')
    st.error(str(error))
    st.stop()

with st.sidebar:
    st.markdown('### Audit scope')
    st.caption('Oklahoma State University · Agency 1000')
    year=st.selectbox('Year',year_options,index=year_options.index(2014) if 2014 in year_options else len(year_options)-1,key='audit_year')
    st.caption('Changing the year updates both tabs.')
    st.divider()
    with st.expander('AI connection',expanded=False):
        configured_key=server_setting('GEMINI_API_KEY')
        if configured_key:
            st.success('An API key is configured on this server.')
            api_key=configured_key
        else:
            api_key=st.text_input('Gemini API key',type='password',key='gemini_session_key',
                help='Used only in this browser session; not written to a project file.')
            st.caption('Enter the key here, not in the question box. Do not share it in a screenshot or upload it to GitHub.')
        model=st.text_input('Model',value=server_setting('GEMINI_MODEL',DEFAULT_MODEL),key='gemini_model')
        st.caption('Only your question and the database structure are sent to Gemini. Transaction results stay in the app.')
    st.caption('AI connected' if api_key else 'AI key not connected · dashboard and verified examples are available')
    st.divider()
    st.markdown('**Reading the results**')
    st.caption('Positive amounts are charges. Negative amounts are credits. MCC describes the merchant category. Employee names are anonymized.')

st.title('P-card audit workspace')
st.write('Explore university purchasing-card activity and find transactions that need a closer look.')
summary=population_summary(str(path),stamp,year)
a,b,c=st.columns(3)
a.metric(f'{year} transactions',f'{summary["count"]:,}')
b.metric('Net spending',f'${summary["spend"]:,.2f}')
c.metric('Cardholders',f'{summary["people"]:,}')
st.caption(f'Recorded transaction dates: {summary["first_date"]} to {summary["last_date"]}. Net spending includes credits. Matches are review candidates, not confirmed violations.')

ask_tab,dashboard_tab=st.tabs(['Ask the database','Prohibited-purchase dashboard'])
with ask_tab:
    st.subheader('Ask an audit question')
    st.write('Ask about spending, employees or vendors in the selected year. The AI writes SQL; the database calculates the result.')
    if not api_key:
        st.caption('Question answering is not connected yet. You can use the dashboard and saved examples.')
    with st.form('question_form'):
        question=st.text_area('Your question',placeholder='Which employees spent more than $50,000 during the year?',height=95,key='question_text',max_chars=2000)
        submitted=st.form_submit_button('Ask the AI',type='primary',disabled=not bool(api_key))
    if submitted:
        st.session_state.pop('question_result',None)
        try:
            with st.spinner('Writing and checking the query, then reading the database…'):
                sql,explanation,used_model=generate_query(question,year,schema_text(path),api_key,model)
                result=run_audit_query(path,year,sql)
            st.session_state['question_result']=(year,question,sql,explanation,result,'Gemini · '+used_model)
        except AuditError as error:
            st.error(str(error))

    with st.expander('Try a verified example — no API key needed',expanded=not bool(api_key)):
        st.caption('These use saved SQL written and tested for this case. They do not call an AI service.')
        preset=st.selectbox('Example question',list(EXAMPLES),key='example_question')
        if st.button('Run verified example',key='run_example'):
            st.session_state.pop('question_result',None)
            try:
                sql,explanation=EXAMPLES[preset]
                result=run_audit_query(path,year,sql)
                st.session_state['question_result']=(year,preset,sql,explanation,result,'Verified example · saved SQL, no AI call')
            except AuditError as error:
                st.error(str(error))
    previous=st.session_state.get('question_result')
    if previous and previous[0]==year:
        result_year,asked,sql,explanation,result,method=previous
        st.divider()
        st.subheader('Query result')
        st.caption(f'{method} · OSU · {result_year}')
        st.write('**Question:** '+asked)
        st.write(explanation)
        st.caption('The app enforces OSU and the selected year even when those filters do not appear in the generated SQL.')
        st.markdown('**SQL used**')
        st.code(sql,language='sql')
        st.write(f'**{len(result.rows):,}{"+" if result.truncated else ""} result rows**')
        show_result(result,f'osu_{year}_question_results.csv','question_download')
    elif previous:
        st.caption('The previous answer was for a different year. Run a question or example for the selected year.')

GUIDE={
    'Alcohol':('alcohol, beer, wine','liquor, brewery'),
    'Cash and cash advances':('cash advance, cash withdrawal, ATM withdrawal','ATM'),
    'Decorations':('decoration, ornament','party'),
    'Donations and sponsorships':('donation, sponsorship','foundation'),
    'Gasoline':('gasoline, vehicle fuel','fuel, service station'),
    'Gifts and gift cards':('gift card, gift certificate','gift'),
    'Insurance':('insurance','insurance'),
    'Late fees':('late fee, late payment','bank'),
    'Mail and postage':('postage, stamps','USPS, post office'),
    'Moving expenses':('moving, relocation','moving'),
    'Personal purchases':('personal','enter a vendor to investigate'),
    'Personal memberships and dues':('membership, dues','association'),
    'Salaries, wages and benefits':('salary, wages, payroll','payroll'),
    'Employee service and incentive awards':('employee award, incentive','awards'),
}

with dashboard_tab:
    st.subheader('Search possible prohibited purchases')
    st.write('Choose the year in the sidebar, enter one keyword in either search, then inspect the matching transactions. Download the complete matches for follow-up.')
    with st.expander('Search guide and prohibited categories'):
        category=st.selectbox('Policy category',list(GUIDE),key='policy_category')
        description_hint,vendor_hint=GUIDE[category]
        st.write('**Description ideas:** '+description_hint)
        st.write('**Vendor ideas:** '+vendor_hint)
        st.caption('Use one phrase per search. These are suggestions, not an automatic policy classification. For example, “alcohol” can refer to laboratory supplies and a “gift” match can be part of a book title. Personal use or approval usually needs receipts and supporting records.')
    st.caption('Searches match the literal text you enter, ignoring letter case. They include both charges and credits and make no AI calls.')
    for field,label,placeholder in [('Description','Description search','e.g. gift card'),('Vendor','Vendor search','e.g. USPS')]:
        st.markdown('#### '+label)
        with st.form('search_form_'+field):
            keyword=st.text_input('Keyword in '+field.lower(),placeholder=placeholder,key='keyword_'+field,max_chars=150)
            clicked=st.form_submit_button('Search '+field.lower(),type='primary')
        state_key='search_result_'+field
        if clicked:
            st.session_state.pop(state_key,None)
            try:
                with st.spinner('Searching '+field.lower()+'s…'):
                    result=search(path,year,field,keyword)
                st.session_state[state_key]=(year,keyword.strip(),result)
            except AuditError as error:
                st.error(str(error))
        saved=st.session_state.get(state_key)
        if saved and saved[0]==year:
            _,term,result=saved
            st.caption(f'OSU · {year} · {field} contains “{term}”')
            left,right=st.columns(2)
            left.metric('Matching transactions',f'{len(result.rows):,}')
            total=sum(row[2] or 0 for row in result.rows)
            right.metric('Net amount of matching transactions',f'${total:,.2f}')
            st.caption('The amount covers whole matching transactions; it does not isolate the cost of any prohibited item.')
            show_result(result,f'osu_{year}_{field.lower()}_matches.csv','download_'+field)
        elif saved:
            st.caption('Run this search again to see matches for the selected year.')
        st.divider()

st.caption('Review supporting evidence before concluding that a control violation or fraud occurred.')
