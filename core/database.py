import os
import sqlite3
import threading
import time
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


# ── Pool de conexiones Postgres ───────────────────────────────────────────────
# Cada función de este módulo abre su propia conexión, y una sola carga de página
# llama a una docena de ellas. Contra Supabase eso agota el cupo de conexiones
# rápido, y el pooler empieza a rechazar handshakes ("server didn't return client
# encoding"). El pool acota el total a _PG_MAXCONN por réplica y las reutiliza.
_PG_MAXCONN = 5
_PG_POOL    = None
_POOL_LOCK  = threading.Lock()

# Sin connect_timeout, psycopg2 hereda el del sistema (decenas de segundos). Con
# la base caída eso deja cada carga de página colgada hasta que el navegador se
# rinde, en vez de mostrar el error. 5s alcanza de sobra para una base sana.
_CONNECT_TIMEOUT = 5


def _pool():
    """Pool perezoso. Devuelve None si no se puede crear (se cae a conexión directa)."""
    global _PG_POOL
    if _PG_POOL is not None:
        return _PG_POOL
    with _POOL_LOCK:
        if _PG_POOL is None:
            try:
                from psycopg2.pool import ThreadedConnectionPool
                _PG_POOL = ThreadedConnectionPool(
                    1, _PG_MAXCONN, _PG_URL, connect_timeout=_CONNECT_TIMEOUT
                )
            except Exception:
                _PG_POOL = False        # marca "no disponible", no reintentar
    return _PG_POOL or None


def _reset_pool():
    """Tira el pool completo. Para cuando el servidor reinició y todo está muerto."""
    global _PG_POOL
    with _POOL_LOCK:
        pool, _PG_POOL = _PG_POOL, None
    if pool:
        try:
            pool.closeall()
        except Exception:
            pass


class _Conn:
    """Unified connection wrapper: same API for SQLite (local) and PostgreSQL (cloud)."""

    def __init__(self):
        self._pooled = False
        if _PG_URL:
            self._c = self._connect_pg()
            # Sin esto, una sesión que espera un lock se queda colgada hasta que
            # el servidor detecta el deadlock y mata a alguien. Con lock_timeout
            # falla rápido y el siguiente rerun de Streamlit lo reintenta solo.
            cur = self._c.cursor()
            cur.execute("SET lock_timeout = '5s'")
            cur.close()
        else:
            DB_PATH.parent.mkdir(exist_ok=True)
            self._c = sqlite3.connect(DB_PATH)

    def _connect_pg(self):
        """
        Saca una conexión del pool. Si viene muerta (el servidor se durmió o
        reinició), tira el pool y reintenta una vez con uno limpio.
        """
        import psycopg2

        for intento in (0, 1):
            pool = _pool()
            if pool is None:
                # fallback sin pool
                return psycopg2.connect(_PG_URL, connect_timeout=_CONNECT_TIMEOUT)
            try:
                con = pool.getconn()
                if con.closed:
                    pool.putconn(con, close=True)
                    raise psycopg2.OperationalError("conexión cerrada en el pool")
                self._pooled = True
                return con
            except Exception:
                _reset_pool()
                if intento:
                    raise
                time.sleep(0.5)

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
        roto = False
        try:
            if exc_type:
                self._c.rollback()
            else:
                self._c.commit()
        except Exception:
            # Si ni el commit/rollback pasa, la conexión ya no sirve: no vuelve
            # al pool o envenenaría a la siguiente sesión que la saque.
            roto = True
            raise
        finally:
            if self._pooled:
                pool = _pool()
                if pool is None:
                    self._c.close()
                else:
                    # Una transacción abortada también se descarta: devolverla
                    # con estado sucio rompe al siguiente que la use.
                    pool.putconn(self._c, close=roto or bool(exc_type))
            else:
                self._c.close()


def _conn():
    return _Conn()


# Cada página llama init_db() en su preámbulo, y Streamlit re-ejecuta el script
# completo en cada interacción. Sin este guard el esquema se revisa decenas de
# veces por sesión; con Postgres eso son locks innecesarios en cada rerun.
# Los módulos sobreviven entre reruns, así que basta una bandera de módulo.
_DB_READY = False

_TABLAS = (
    "proveedores_clasificacion", "vendedor_cliente", "eventos",
    "gastos_empresa", "contabilidad_movimientos", "cuentas_contables",
)


def _tablas_existentes(con):
    if _PG_URL:
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {r[0] for r in rows}


def init_db(force=False):
    """
    Crea el esquema y corre las migraciones pendientes. Idempotente y barata:
    en el caso normal (todo ya existe) no ejecuta un solo statement de escritura.
    """
    global _DB_READY
    if _DB_READY and not force:
        return

    # Los fallos de handshake contra Supabase suelen ser transitorios (proyecto
    # despertando, pooler saturado). Se reintenta antes de darle un error al
    # usuario, que no puede hacer nada con un fallo pasajero.
    ultimo_error = None
    for intento in range(3):
        try:
            with _Conn():
                pass
            ultimo_error = None
            break
        except Exception as e:
            ultimo_error = e
            _reset_pool()
            if intento < 2:
                time.sleep(1.5 * (intento + 1))

    if ultimo_error is not None:
        import streamlit as st
        st.error(
            f"**Error de conexión a la base de datos** (3 intentos)\n\n"
            f"```\n{type(ultimo_error).__name__}: {ultimo_error}\n```\n\n"
            f"**Primero revisa el estado del proyecto en el panel de Supabase.** "
            f"Si ahí aparece *Database not usable* o un timeout de TCP, la base "
            f"está caída y no hay nada que la app pueda hacer: hay que "
            f"reactivarla o reiniciarla desde Supabase.\n\n"
            f"Causas más probables, en orden:\n\n"
            f"1. **Proyecto pausado.** El plan gratuito lo suspende tras varios "
            f"días sin uso. Se despierta desde el panel.\n"
            f"2. **Instancia caída o reiniciándose** (memoria o disco agotados). "
            f"Revisa *Reports* y *Logs*, y prueba *Settings → General → Restart "
            f"project*.\n"
            f"3. **Se agotaron las conexiones.** Revisa *Database → Connection "
            f"pooling*.\n"
            f"4. **El `supabase_db_url` de los secrets es incorrecto** o le falta "
            f"el puerto del pooler.\n\n"
            f"**Para trabajar mientras tanto:** quita el secret "
            f"`supabase_db_url` en la configuración de la app en Streamlit Cloud. "
            f"La app arranca sola con SQLite y puedes cargar archivos y ver los "
            f"dashboards. Lo que ya está guardado en Supabase **no se pierde** "
            f"—sigue ahí, solo inalcanzable— pero las clasificaciones que "
            f"captures en ese modo no persisten entre redeploys."
        )
        st.stop()

    with _conn() as con:
        # `CREATE TABLE IF NOT EXISTS` no es gratis en Postgres: toma locks
        # aunque no cree nada. Si el esquema ya está completo, ni se intenta.
        faltantes = set(_TABLAS) - _tablas_existentes(con)
        if not faltantes:
            pass                      # esquema completo — ni un statement más
        elif _PG_URL:
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
                );
                CREATE TABLE IF NOT EXISTS gastos_empresa (
                    concepto           TEXT NOT NULL,
                    periodo            TEXT NOT NULL,
                    monto_mxn          NUMERIC NOT NULL DEFAULT 0,
                    notas              TEXT DEFAULT '',
                    fecha_creacion     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fecha_modificacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (concepto, periodo)
                );
                CREATE TABLE IF NOT EXISTS contabilidad_movimientos (
                    id             BIGSERIAL PRIMARY KEY,
                    periodo        TEXT NOT NULL,
                    cuenta         TEXT NOT NULL,
                    proveedor      TEXT NOT NULL,
                    proveedor_norm TEXT NOT NULL,
                    monto_mxn      NUMERIC NOT NULL DEFAULT 0,
                    descripcion    TEXT DEFAULT '',
                    fecha_carga    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_ctb_periodo
                    ON contabilidad_movimientos(periodo);
                CREATE INDEX IF NOT EXISTS idx_ctb_cuenta
                    ON contabilidad_movimientos(cuenta);
                CREATE TABLE IF NOT EXISTS cuentas_contables (
                    cuenta             TEXT PRIMARY KEY,
                    nombre             TEXT NOT NULL DEFAULT '',
                    categoria          TEXT NOT NULL DEFAULT 'Otros / Sin clasificar',
                    naturaleza         TEXT NOT NULL DEFAULT 'Sin clasificar',
                    trato              TEXT NOT NULL DEFAULT 'Auto',
                    notas              TEXT DEFAULT '',
                    fecha_modificacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                );
                CREATE TABLE IF NOT EXISTS gastos_empresa (
                    concepto           TEXT NOT NULL,
                    periodo            TEXT NOT NULL,
                    monto_mxn          REAL NOT NULL DEFAULT 0,
                    notas              TEXT DEFAULT '',
                    fecha_creacion     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fecha_modificacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (concepto, periodo)
                );
                CREATE TABLE IF NOT EXISTS contabilidad_movimientos (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    periodo        TEXT NOT NULL,
                    cuenta         TEXT NOT NULL,
                    proveedor      TEXT NOT NULL,
                    proveedor_norm TEXT NOT NULL,
                    monto_mxn      REAL NOT NULL DEFAULT 0,
                    descripcion    TEXT DEFAULT '',
                    fecha_carga    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_ctb_periodo
                    ON contabilidad_movimientos(periodo);
                CREATE INDEX IF NOT EXISTS idx_ctb_cuenta
                    ON contabilidad_movimientos(cuenta);
                CREATE TABLE IF NOT EXISTS cuentas_contables (
                    cuenta             TEXT PRIMARY KEY,
                    nombre             TEXT NOT NULL DEFAULT '',
                    categoria          TEXT NOT NULL DEFAULT 'Otros / Sin clasificar',
                    naturaleza         TEXT NOT NULL DEFAULT 'Sin clasificar',
                    trato              TEXT NOT NULL DEFAULT 'Auto',
                    notas              TEXT DEFAULT '',
                    fecha_modificacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    # Cada migración va en su PROPIA transacción y toca una sola tabla. Si se
    # agrupan, dos sesiones concurrentes pueden tomar locks sobre las mismas
    # tablas en distinto orden y provocar un deadlock en Postgres.
    _migrar_maquila_externa()
    _migrar_origen_gastos()

    _DB_READY = True


def _migrar_maquila_externa():
    """
    "Maquila" se renombró a "Maquila Externa".

    Se consulta ANTES de escribir: un UPDATE incondicional en cada arranque toma
    un lock de escritura sobre `proveedores_clasificacion` aunque no haya nada
    que migrar, y eso fue justo lo que deadlockeaba en Streamlit Cloud.
    """
    with _conn() as con:
        pendientes = con.execute(
            "SELECT COUNT(*) FROM proveedores_clasificacion "
            "WHERE categoria = 'Maquila'"
        ).fetchone()[0]
        if not pendientes:
            return
        con.execute(
            "UPDATE proveedores_clasificacion SET categoria = 'Maquila Externa' "
            "WHERE categoria = 'Maquila'"
        )


def _migrar_origen_gastos():
    """
    `gastos_empresa` gana `origen` para distinguir la captura manual de lo
    publicado automáticamente desde Contabilidad. Lo que ya existía es manual.
    """
    with _conn() as con:
        if _columna_existe(con, "gastos_empresa", "origen"):
            return
        con.execute(
            "ALTER TABLE gastos_empresa "
            "ADD COLUMN origen TEXT NOT NULL DEFAULT 'manual'"
        )


def _columna_existe(con, tabla, columna):
    """
    ¿La tabla ya tiene esa columna?

    En Postgres se pregunta al catálogo en vez de usar
    `ALTER TABLE … ADD COLUMN IF NOT EXISTS`: ese ALTER toma un lock ACCESS
    EXCLUSIVE aunque la columna ya exista, y correría en cada carga de página.
    """
    if _PG_URL:
        row = con.execute(
            f"SELECT 1 FROM information_schema.columns "
            f"WHERE table_name = {_PH} AND column_name = {_PH}",
            (tabla, columna),
        ).fetchone()
        return row is not None

    cols = {r[1] for r in con.execute(f"PRAGMA table_info({tabla})").fetchall()}
    return columna in cols


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


def delete_clasificacion(proveedor):
    """Remove a provider's classification (returns it to 'Pendiente clasificar')."""
    with _conn() as con:
        con.execute(
            f"DELETE FROM proveedores_clasificacion WHERE proveedor_exacto_sae = {_PH}",
            (proveedor,),
        )


def bulk_upsert_clasificaciones(rows):
    """
    Upsert many classifications over a SINGLE connection (one commit at the end).
    rows: iterable of (proveedor, categoria, notas, origen).
    Returns the number of rows written.
    """
    sql = f"""
        INSERT INTO proveedores_clasificacion
            (proveedor_exacto_sae, categoria, notas, origen, fecha_modificacion)
        VALUES ({_PH}, {_PH}, {_PH}, {_PH}, CURRENT_TIMESTAMP)
        ON CONFLICT(proveedor_exacto_sae) DO UPDATE SET
            categoria          = EXCLUDED.categoria,
            notas              = EXCLUDED.notas,
            origen             = EXCLUDED.origen,
            fecha_modificacion = CURRENT_TIMESTAMP
    """
    n = 0
    with _conn() as con:
        for prov, categoria, notas, origen in rows:
            con.execute(sql, (prov, categoria, notas, origen))
            n += 1
    return n


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


def delete_vendedor_cliente(cliente):
    """Removes a client's vendor assignment (returns it to 'Sin asignar')."""
    with _conn() as con:
        con.execute(
            f"DELETE FROM vendedor_cliente WHERE cliente_exacto_sae = {_PH}",
            (cliente,),
        )


def log_evento(tipo, detalle=None):
    with _conn() as con:
        con.execute(
            f"INSERT INTO eventos (tipo, detalle) VALUES ({_PH}, {_PH})",
            (tipo, detalle),
        )


def get_conceptos_gastos_empresa():
    """
    Distinct concepto names ever entered by hand, across all years (sorted).

    Solo `origen='manual'`: la grilla de captura no debe dejar editar (ni borrar)
    lo que se publicó automáticamente desde Contabilidad.
    """
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT concepto FROM gastos_empresa "
            "WHERE origen = 'manual' ORDER BY concepto"
        ).fetchall()
    return [r[0] for r in rows]


def get_años_gastos_empresa():
    """Sorted list of distinct years that have at least one manual entry."""
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT periodo FROM gastos_empresa WHERE origen = 'manual'"
        ).fetchall()
    return sorted({int(r[0].split("-")[0]) for r in rows})


def get_gastos_empresa_año(year):
    """Returns {concepto: {mes_num(1-12): monto}} for the given year (manual only)."""
    with _conn() as con:
        rows = con.execute(
            f"SELECT concepto, periodo, monto_mxn FROM gastos_empresa "
            f"WHERE periodo LIKE {_PH} AND origen = 'manual'",
            (f"{year}-%",),
        ).fetchall()
    out = {}
    for concepto, periodo, monto in rows:
        mes = int(periodo.split("-")[1])
        out.setdefault(concepto, {})[mes] = float(monto)
    return out


def get_gastos_empresa_totales_por_periodo(periodos):
    """
    Suma manual + contabilidad a propósito: es el costo operativo total, que es
    lo que consumen Compras, Comparativa y el reporte.

    Returns {periodo_str "YYYY-MM": total_monto} for the given iterable of
    periodo strings — used to add "Gastos de Empresa" spend to charts/KPIs
    filtered by the sidebar's period selection.
    """
    periodos = list(periodos)
    if not periodos:
        return {}
    placeholders = ",".join([_PH] * len(periodos))
    with _conn() as con:
        rows = con.execute(
            f"SELECT periodo, SUM(monto_mxn) FROM gastos_empresa "
            f"WHERE periodo IN ({placeholders}) GROUP BY periodo",
            tuple(periodos),
        ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def get_gastos_empresa_por_concepto(periodos):
    """Returns {concepto: total_monto} for the given iterable of periodo strings."""
    periodos = list(periodos)
    if not periodos:
        return {}
    placeholders = ",".join([_PH] * len(periodos))
    with _conn() as con:
        rows = con.execute(
            f"SELECT concepto, SUM(monto_mxn) FROM gastos_empresa "
            f"WHERE periodo IN ({placeholders}) GROUP BY concepto "
            f"ORDER BY SUM(monto_mxn) DESC",
            tuple(periodos),
        ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


_SQL_UPSERT_GE = f"""
    INSERT INTO gastos_empresa (concepto, periodo, monto_mxn, notas, origen,
                                fecha_modificacion)
    VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, CURRENT_TIMESTAMP)
    ON CONFLICT(concepto, periodo) DO UPDATE SET
        monto_mxn          = EXCLUDED.monto_mxn,
        notas              = EXCLUDED.notas,
        origen             = EXCLUDED.origen,
        fecha_modificacion = CURRENT_TIMESTAMP
"""


def bulk_upsert_gastos_empresa(rows):
    """
    Upsert many (concepto, periodo, monto, notas) rows over a single connection.
    Always-overwrite semantics — safe to call with a full year's grid on every
    save (idempotent), no diffing needed given the small data volume.
    Escribe siempre `origen='manual'`.
    """
    n = 0
    with _conn() as con:
        for concepto, periodo, monto, notas in rows:
            con.execute(_SQL_UPSERT_GE, (concepto, periodo, monto, notas, "manual"))
            n += 1
    return n


def delete_concepto_año(concepto, year):
    """Removes all of a concept's manual entries for a given year (row removed from the grid)."""
    with _conn() as con:
        con.execute(
            f"DELETE FROM gastos_empresa WHERE concepto = {_PH} "
            f"AND periodo LIKE {_PH} AND origen = 'manual'",
            (concepto, f"{year}-%"),
        )


def reemplazar_gastos_contabilidad(rows):
    """
    Republica los gastos derivados de Contabilidad.

    Borra todo lo que tenga `origen='contabilidad'` y reinserta, en una sola
    transacción: el libro contable es la fuente de verdad completa, así que
    republicar tras corregir el catálogo tiene que dejar el resultado exacto, no
    acumulado. La captura manual no se toca.

    `rows` = iterable de (concepto, periodo, monto, notas). Returns n escritas.
    """
    rows = list(rows)
    n = 0
    with _conn() as con:
        con.execute("DELETE FROM gastos_empresa WHERE origen = 'contabilidad'")
        for concepto, periodo, monto, notas in rows:
            con.execute(
                _SQL_UPSERT_GE, (concepto, periodo, monto, notas, "contabilidad")
            )
            n += 1
    return n


def get_gastos_empresa_publicados():
    """
    Returns {(concepto, periodo): monto} de lo publicado desde Contabilidad.
    Sirve para avisar de choques de nombre con la captura manual.
    """
    with _conn() as con:
        rows = con.execute(
            "SELECT concepto, periodo, monto_mxn FROM gastos_empresa "
            "WHERE origen = 'contabilidad'"
        ).fetchall()
    return {(r[0], r[1]): float(r[2]) for r in rows}


# ── Contabilidad ──────────────────────────────────────────────────────────────

def reemplazar_contabilidad(rows):
    """
    Reemplaza por completo el libro contable con la carga nueva.

    Es "una sola base de datos que se va actualizando", no un histórico
    incremental: cada carga sustituye a la anterior dentro de una sola
    transacción, así que un archivo mal armado nunca deja la BD a medias.

    `rows` = iterable de (periodo, cuenta, proveedor, proveedor_norm, monto,
    descripcion). Returns n insertadas.
    """
    rows = list(rows)
    sql = (
        f"INSERT INTO contabilidad_movimientos "
        f"(periodo, cuenta, proveedor, proveedor_norm, monto_mxn, descripcion) "
        f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})"
    )
    with _conn() as con:
        con.execute("DELETE FROM contabilidad_movimientos")
        for r in rows:
            con.execute(sql, tuple(r))
    return len(rows)


def get_contabilidad(periodos=None):
    """
    Returns list[dict] de movimientos contables, opcionalmente filtrados por una
    lista de periodos "YYYY-MM". Lista vacía si no hay libro cargado.
    """
    sql = (
        "SELECT periodo, cuenta, proveedor, proveedor_norm, monto_mxn, descripcion "
        "FROM contabilidad_movimientos"
    )
    params = ()
    if periodos is not None:
        periodos = list(periodos)
        if not periodos:
            return []
        sql += f" WHERE periodo IN ({','.join([_PH] * len(periodos))})"
        params = tuple(periodos)

    with _conn() as con:
        rows = con.execute(sql, params).fetchall()

    return [
        {
            "periodo":        r[0],
            "cuenta":         r[1],
            "proveedor":      r[2],
            "proveedor_norm": r[3],
            "monto_mxn":      float(r[4]),
            "descripcion":    r[5] or "",
        }
        for r in rows
    ]


def get_meta_contabilidad():
    """Returns {"n_movimientos", "periodos", "ultima_carga"} para el sidebar."""
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*), MIN(periodo), MAX(periodo), MAX(fecha_carga) "
            "FROM contabilidad_movimientos"
        ).fetchone()
    n = int(row[0] or 0)
    return {
        "n_movimientos": n,
        "periodos":      (row[1], row[2]) if n else (None, None),
        "ultima_carga":  row[3] if n else None,
    }


def get_cuentas_contables():
    """Returns {cuenta: {nombre, categoria, naturaleza, trato, notas}}"""
    with _conn() as con:
        rows = con.execute(
            "SELECT cuenta, nombre, categoria, naturaleza, trato, notas "
            "FROM cuentas_contables"
        ).fetchall()
    return {
        r[0]: {
            "nombre":     r[1] or "",
            "categoria":  r[2],
            "naturaleza": r[3],
            "trato":      r[4],
            "notas":      r[5] or "",
        }
        for r in rows
    }


def bulk_upsert_cuentas_contables(rows):
    """
    Upsert de (cuenta, nombre, categoria, naturaleza, trato, notas) sobre una sola
    conexión. Returns n escritas.
    """
    sql = f"""
        INSERT INTO cuentas_contables
            (cuenta, nombre, categoria, naturaleza, trato, notas, fecha_modificacion)
        VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, CURRENT_TIMESTAMP)
        ON CONFLICT(cuenta) DO UPDATE SET
            nombre             = EXCLUDED.nombre,
            categoria          = EXCLUDED.categoria,
            naturaleza         = EXCLUDED.naturaleza,
            trato              = EXCLUDED.trato,
            notas              = EXCLUDED.notas,
            fecha_modificacion = CURRENT_TIMESTAMP
    """
    n = 0
    with _conn() as con:
        for r in rows:
            con.execute(sql, tuple(r))
            n += 1
    return n


def delete_cuenta_contable(cuenta):
    """Regresa la cuenta a 'Sin clasificar' quitándola del catálogo."""
    with _conn() as con:
        con.execute(
            f"DELETE FROM cuentas_contables WHERE cuenta = {_PH}", (cuenta,)
        )
