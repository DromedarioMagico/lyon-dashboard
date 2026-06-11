@echo off
if not exist .venv (
    echo Creando entorno virtual...
    python -m venv .venv
)
call .venv\Scripts\activate
pip install -r requirements.txt -q
streamlit run app.py
