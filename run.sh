#!/bin/bash
if [ ! -d ".venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt -q
streamlit run app.py
