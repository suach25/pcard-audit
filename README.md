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
