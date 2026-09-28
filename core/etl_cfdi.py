"""
ETL de los reportes CFDI de Contabilidad: Ventas del año y Notas de Crédito.

Contabilidad manda dos archivos con la misma estructura de 15 columnas — el de
Ventas trae una hoja por mes, el de Notas de Crédito una sola hoja con el año
completo — y se distinguen únicamente por la columna `Tipo` ("Factura" /
"Nota Cred"). Un solo parser basta para los dos: cualquiera de los dos archivos
que suba el usuario cae en `cargar_cfdi()` y el router de la página decide qué
hacer con el resultado según qué `Tipo` trae.

A diferencia del archivo mensual de Facturación, este SÍ cubre el año completo y
SÍ dice qué facturas se cancelaron — pero no trae remisiones ni el desglose de
devoluciones vs descuentos, así que complementa al archivo mensual, no lo
reemplaza.

Sin dependencias de Streamlit. `cargar_cfdi(f) -> (df, warnings)`.
"""

import io

import pandas as pd

from core.etl_ventas import abreviar_cliente

# El encabezado real trae espacios al final en el reporte de Ventas
# ("Cliente ", "Fecha de elaboración ") pero no en el de Notas de Crédito
# ("Cliente", "TIPO" en mayúsculas) — se normaliza antes de mapear.
COLS_REQ_NORM = {"SERIE Y FOLIO", "UUID", "CLIENTE", "SUBTOTAL", "TIPO"}


def _cliente_display(nombre):
    n = str(nombre).strip()
    if n.upper().startswith("COMISION NACIONAL DE LIBROS"):
        return "CONALITEG"
    return abreviar_cliente(n)


def _norm_col(c):
    return str(c).strip().upper()


def _detectar_hoja_fecha(cols_norm):
    """La columna de fecha se llama 'Fecha' en algunas hojas y 'Fecha de
    elaboración' en otras del mismo archivo (pasa entre enero y febrero del
    reporte real) — se detecta por prefijo, excluyendo 'Fecha de timbrado'."""
    for c in cols_norm:
        if c.startswith("FECHA") and "TIMBRADO" not in c:
            return c
    return None


def cargar_cfdi(uploaded_file):
    """
    Lee un reporte CFDI de Contabilidad (Reporte de Ventas o Reporte de Notas de
    Crédito — Streamlit UploadedFile o bytes). Returns (df, warnings_list).

    df: Fecha · _Mes · Folio · UUID · Cliente_Codigo (Int64) · Cliente_Nombre ·
        Cliente_Display · Subtotal_MXN · IVA_MXN · Importe_MXN · Tipo_Doc ·
        Estatus · Cancelado (bool) · Metodo_Pago · Forma_Pago

    Itera TODAS las hojas del archivo y las concatena: el reporte de Ventas trae
    una hoja por mes, el de Notas de Crédito una sola. Levanta ValueError si
    ninguna hoja tiene la estructura esperada.
    """
    warnings_list = []
    content = uploaded_file.read() if hasattr(uploaded_file, "read") else uploaded_file

    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception as e:
        raise ValueError(f"No se pudo leer el archivo Excel: {e}")

    partes = []
    for hoja in xls.sheet_names:
        try:
            raw = pd.read_excel(io.BytesIO(content), sheet_name=hoja, header=1)
        except Exception:
            continue
        cols_norm = [_norm_col(c) for c in raw.columns]
        if not COLS_REQ_NORM.issubset(set(cols_norm)):
            continue
        raw.columns = cols_norm

        # La columna de fecha cambia de nombre entre hojas del MISMO archivo
        # ("Fecha" en enero, "Fecha de elaboración" después). Se unifica AQUÍ,
        # antes de concatenar: si no, pandas las trata como dos columnas
        # distintas y la mitad de las filas quedan sin fecha en silencio.
        col_fecha_hoja = _detectar_hoja_fecha(cols_norm)
        if col_fecha_hoja is None:
            continue
        raw = raw.rename(columns={col_fecha_hoja: "FECHA_DOC"})

        raw["_hoja"] = hoja
        partes.append(raw)

    if not partes:
        raise ValueError(
            f"Ninguna hoja tiene la estructura esperada de un reporte CFDI de "
            f"Contabilidad. Hojas disponibles: {xls.sheet_names}. Se requieren "
            f"columnas como 'Serie y Folio', 'UUID', 'Cliente', 'Subtotal', 'Tipo' "
            f"y una columna de fecha."
        )

    raw_all = pd.concat(partes, ignore_index=True, sort=False)

    df = pd.DataFrame(index=raw_all.index)
    df["Fecha"] = pd.to_datetime(raw_all["FECHA_DOC"], errors="coerce")

    n_sin_fecha = int(df["Fecha"].isna().sum())
    if n_sin_fecha:
        warnings_list.append(f"{n_sin_fecha} fila(s) sin fecha válida, descartadas.")
    keep = df["Fecha"].notna()
    df = df[keep].copy()
    raw_all = raw_all[keep].copy()

    df["_Mes"] = df["Fecha"].dt.to_period("M")
    df["Folio"] = raw_all["SERIE Y FOLIO"].astype(str).str.strip()
    df["UUID"] = raw_all["UUID"].astype(str).str.strip()
    df.loc[raw_all["UUID"].isna(), "UUID"] = ""

    df["Cliente_Codigo"] = pd.to_numeric(raw_all["CLIENTE"], errors="coerce").astype("Int64")
    df["Cliente_Nombre"] = raw_all.get("NOMBRE", raw_all["CLIENTE"]).fillna("").astype(str).str.strip()
    df["Cliente_Display"] = df["Cliente_Nombre"].map(_cliente_display)

    df["Subtotal_MXN"] = pd.to_numeric(raw_all["SUBTOTAL"], errors="coerce").fillna(0.0)
    df["IVA_MXN"] = pd.to_numeric(raw_all.get("IVA", 0), errors="coerce").fillna(0.0)
    if "IMPORTE TOTAL" in raw_all.columns:
        df["Importe_MXN"] = pd.to_numeric(raw_all["IMPORTE TOTAL"], errors="coerce").fillna(0.0)
    else:
        df["Importe_MXN"] = df["Subtotal_MXN"] + df["IVA_MXN"]

    df["Tipo_Doc"] = raw_all["TIPO"].astype(str).str.strip()
    df["Estatus"] = raw_all.get("ESTATUS", "").fillna("").astype(str).str.strip()
    df["Cancelado"] = df["Estatus"].str.upper().str.startswith("CANCEL")
    df["Metodo_Pago"] = raw_all.get("MÉTODO PAGO", "").fillna("").astype(str).str.strip()
    df["Forma_Pago"] = raw_all.get("FORMA DE PAGO SAT", "").fillna("").astype(str).str.strip()

    # Un UUID duplicado de verdad (no vacío, repetido) es la única señal digna de
    # advertencia — varias filas SIN uuid (típico de un CFDI cancelado) no son
    # duplicados entre sí, así que se excluyen antes de contar.
    con_uuid = df[df["UUID"] != ""]
    dup = con_uuid["UUID"].duplicated(keep=False)
    if dup.any():
        warnings_list.append(
            f"{int(dup.sum())} fila(s) comparten el mismo UUID — revisa si el "
            f"archivo trae registros repetidos."
        )

    tipos = sorted(df["Tipo_Doc"].unique())
    n_cancel = int(df["Cancelado"].sum())
    warnings_list.append(
        f"{len(df)} documento(s) · tipos: {', '.join(tipos)} · "
        f"{n_cancel} cancelado(s) · periodo {df['_Mes'].min()} → {df['_Mes'].max()}."
    )

    return df.reset_index(drop=True), warnings_list
