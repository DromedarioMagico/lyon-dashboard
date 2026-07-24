import os
import sqlite3
from pathlib import Path

# ── Backend detection ─────────────────────────────────────────────────────────
# Local dev:  SQLite at data/lyon.db (default, no config needed)
# Cloud:      PostgreSQL via SUPABASE_DB_URL env var or st.secrets["supabase_db_url"]

def _detect_pg_url():
    url = os.environ.get("SUPABASE_DB_URL")
    if url:
        return url
    try:
        import streamlit as st
        return st.secrets.get("supabase_db_url")
    except Exception:
        return None


_PG_URL = _detect_pg_url()
DB_PATH = Path(__file__).parent.parent / "data" / "lyon.db"
_PH     = "%s" if _PG_URL else "?"   # SQL parameter placeholder


class _Conn:
    """Unified connection wrapper: same API for SQLite (local) and PostgreSQL (cloud)."""

    def __init__(self):
        if _PG_URL:
            import psycopg2
            self._c = psycopg2.connect(_PG_URL)
        else:
            DB_PATH.parent.mkdir(exist_ok=True)
            self._c = sqlite3.connect(DB_PATH)

    def execute(self, sql, params=None):
        cur = self._c.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return cur

    def executescript(self, script):
        """Run a multi-statement DDL block (no params)."""
        if _PG_URL:
            cur = self._c.cursor()
            for stmt in (s.strip() for s in script.split(";") if s.strip()):
                cur.execute(stmt)
        else:
            self._c.executescript(script)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        try:
            if exc_type:
                self._c.rollback()
            else:
                self._c.commit()
        finally:
            self._c.close()


def _conn():
    return _Conn()


def init_db():
    try:
        _conn_test = _Conn()
        _conn_test._c.close()
    except Exception as e:
        import streamlit as st
        st.error(
            f"**Error de conexión a la base de datos**\n\n"
            f"```\n{type(e).__name__}: {e}\n```\n\n"
            f"Revisa que el `supabase_db_url` en los secrets de Streamlit Cloud sea correcto."
        )
        st.stop()

    with _conn() as con:
        if _PG_URL:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS proveedores_clasificacion (
                    proveedor_exacto_sae TEXT PRIMARY KEY,
                    categoria            TEXT NOT NULL,
                    notas                TEXT DEFAULT '',
                    origen               TEXT NOT NULL DEFAULT 'usuario',
                    fecha_creacion       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fecha_modificacion   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_prov_cat
                    ON proveedores_clasificacion(categoria);
                CREATE TABLE IF NOT EXISTS vendedor_cliente (
                    cliente_exacto_sae TEXT PRIMARY KEY,
                    vendedor           TEXT NOT NULL,
                    origen             TEXT NOT NULL DEFAULT 'usuario',
                    fecha_modificacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS eventos (
                    id        BIGSERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    tipo      TEXT NOT NULL,
                    detalle   TEXT
                )
            """)
        else:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS proveedores_clasificacion (
                    proveedor_exacto_sae TEXT PRIMARY KEY,
                    categoria            TEXT NOT NULL,
                    notas                TEXT DEFAULT '',
                    origen               TEXT NOT NULL DEFAULT 'usuario',
                    fecha_creacion       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fecha_modificacion   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_proveedores_categoria
                    ON proveedores_clasificacion(categoria);
                CREATE TABLE IF NOT EXISTS vendedor_cliente (
                    cliente_exacto_sae TEXT PRIMARY KEY,
                    vendedor           TEXT NOT NULL,
                    origen             TEXT NOT NULL DEFAULT 'usuario',
                    fecha_modificacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS eventos (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    tipo      TEXT NOT NULL,
                    detalle   TEXT
                )
            """)


def get_clasificaciones():
    """Returns dict: {proveedor: {categoria, notas, origen}}"""
    with _conn() as con:
        rows = con.execute(
            "SELECT proveedor_exacto_sae, categoria, notas, origen "
            "FROM proveedores_clasificacion"
        ).fetchall()
    return {
        row[0]: {"categoria": row[1], "notas": row[2], "origen": row[3]}
        for row in rows
    }


def upsert_clasificacion(proveedor, categoria, notas="", origen="usuario"):
    with _conn() as con:
        con.execute(
            f"""
            INSERT INTO proveedores_clasificacion
                (proveedor_exacto_sae, categoria, notas, origen, fecha_modificacion)
            VALUES ({_PH}, {_PH}, {_PH}, {_PH}, CURRENT_TIMESTAMP)
            ON CONFLICT(proveedor_exacto_sae) DO UPDATE SET
                categoria          = EXCLUDED.categoria,
                notas              = EXCLUDED.notas,
                origen             = EXCLUDED.origen,
                fecha_modificacion = CURRENT_TIMESTAMP
            """,
            (proveedor, categoria, notas, origen),
        )


def get_stats():
    """Returns summary stats for the Home page."""
    with _conn() as con:
        total    = con.execute(
            "SELECT COUNT(*) FROM proveedores_clasificacion"
        ).fetchone()[0]
        last_mod = con.execute(
            "SELECT MAX(fecha_modificacion) FROM proveedores_clasificacion"
        ).fetchone()[0]
    return {"total_clasificados": total, "ultima_modificacion": last_mod}


def get_vendedor_clientes():
    """Returns dict: {cliente: vendedor} for all DB-assigned clients."""
    with _conn() as con:
        rows = con.execute(
            "SELECT cliente_exacto_sae, vendedor FROM vendedor_cliente"
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def upsert_vendedor_cliente(cliente, vendedor, origen="usuario"):
    with _conn() as con:
        con.execute(
            f"""
            INSERT INTO vendedor_cliente
                (cliente_exacto_sae, vendedor, origen, fecha_modificacion)
            VALUES ({_PH}, {_PH}, {_PH}, CURRENT_TIMESTAMP)
            ON CONFLICT(cliente_exacto_sae) DO UPDATE SET
                vendedor           = EXCLUDED.vendedor,
                origen             = EXCLUDED.origen,
                fecha_modificacion = CURRENT_TIMESTAMP
            """,
            (cliente, vendedor, origen),
        )


def log_evento(tipo, detalle=None):
    with _conn() as con:
        con.execute(
            f"INSERT INTO eventos (tipo, detalle) VALUES ({_PH}, {_PH})",
            (tipo, detalle),
        )
