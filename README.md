# Dashboards Lyon AG

Webapp local para control de compras y ventas — Planta QUMA.

## Arranque rápido

### Windows
```
run.bat
```

### macOS / Linux
```
chmod +x run.sh && ./run.sh
```

### Manual
```
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
streamlit run app.py
```

Se abre en `http://localhost:8501`.

## Backup

Para respaldar clasificaciones de proveedores: copiar `data/lyon.db`.
