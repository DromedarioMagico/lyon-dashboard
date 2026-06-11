import io
import pandas as pd

from core.catalogos import ESTATUS_VALIDOS_COMPRAS, ETIQ_PENDIENTE, aplicar_ancla
from core.database import get_clasificaciones

HOJA_SAE = "2026"
COLS_REQ = [
    "Proveedor", "Estatus", "Referencia factura",
    "Fecha de documento", "Tipo de cambio", "Total del documento",
]


def _detectar_hoja(xls):
    """Returns best SAE sheet: configured HOJA_SAE if present, else the largest valid one."""
    candidatos = []
    for sheet in xls.sheet_names:
        try:
            sample = pd.read_excel(xls, sheet_name=sheet, header=1, nrows=5)
            cols = [str(c).strip() for c in sample.columns]
            if "Proveedor" in cols and "Tipo de cambio" in cols and "Estatus" in cols:
                n = len(pd.read_excel(xls, sheet_name=sheet, header=1))
                candidatos.append((sheet, n))
        except Exception:
            continue
    if not candidatos:
        return None
    for sheet, _ in candidatos:
        if sheet == HOJA_SAE:
            return sheet
    return max(candidatos, key=lambda x: x[1])[0]


def cargar_compras(uploaded_file):
    """
    Loads and cleans a SAE compras file (Streamlit UploadedFile or raw bytes).
    Returns (df, warnings_list).
    df has raw SAE columns + Gasto_Total_MXN + _Mes.
    Raises ValueError with a human-readable message on hard failures.
    """
    warnings_list = []
    content = uploaded_file.read() if hasattr(uploaded_file, "read") else uploaded_file

    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception as e:
        raise ValueError(f"No se pudo leer el archivo Excel: {e}")

    hoja = _detectar_hoja(xls)
    if hoja is None:
        raise ValueError(
            f"No se encontró una hoja SAE válida. "
            f"Hojas disponibles: {xls.sheet_names}. "
            f"Se requieren columnas 'Proveedor', 'Estatus' y 'Tipo de cambio'."
        )
    if hoja != HOJA_SAE:
        warnings_list.append(f"Hoja detectada: '{hoja}' (configurada: '{HOJA_SAE}').")

    df_raw = pd.read_excel(io.BytesIO(content), sheet_name=hoja, header=1)
    df_raw.columns = df_raw.columns.astype(str).str.strip()
    df_raw = df_raw.loc[:, ~df_raw.columns.str.startswith("Unnamed")]

    faltantes = [c for c in COLS_REQ if c not in df_raw.columns]
    if faltantes:
        raise ValueError(
            f"Faltan columnas en el SAE: {faltantes}.\n"
            f"Columnas detectadas: {list(df_raw.columns)}"
        )

    df = df_raw[df_raw["Estatus"].astype(str).str.strip().isin(ESTATUS_VALIDOS_COMPRAS)].copy()
    descartadas = len(df_raw) - len(df)
    if descartadas:
        warnings_list.append(f"{descartadas:,} filas descartadas (estatus cancelado/inválido).")

    df["Fecha de documento"] = pd.to_datetime(df["Fecha de documento"], errors="coerce")
    if "Fecha de recepción" in df.columns:
        df["Fecha de recepción"] = pd.to_datetime(df["Fecha de recepción"], errors="coerce")

    df["Total del documento"] = pd.to_numeric(df["Total del documento"], errors="coerce").fillna(0.0)
    df["Gasto_Total_MXN"]     = df["Total del documento"]

    sin_fecha = df["Fecha de documento"].isna().sum()
    if sin_fecha:
        warnings_list.append(f"{sin_fecha} fila(s) sin fecha válida descartadas.")
    df = df.dropna(subset=["Fecha de documento"]).copy()

    if len(df) == 0:
        raise ValueError("El archivo no contiene facturas válidas después del filtrado.")

    df["_Mes"] = df["Fecha de documento"].dt.to_period("M")
    return df, warnings_list


def aplicar_clasificaciones(df):
    """
    Returns df with Categoria + Origen refreshed from DB + anchors.
    Call on every page render so DB changes are reflected without re-upload.
    """
    clasificaciones = get_clasificaciones()
    df = df.copy()

    cats, origenes = [], []
    for prov in df["Proveedor"]:
        if pd.isna(prov):
            cats.append(ETIQ_PENDIENTE)
            origenes.append("pendiente")
            continue
        p = str(prov).strip()
        if p in clasificaciones:
            cats.append(clasificaciones[p]["categoria"])
            origenes.append(clasificaciones[p]["origen"])
        else:
            ancla = aplicar_ancla(p)
            if ancla:
                cats.append(ancla)
                origenes.append("ancla")
            else:
                cats.append(ETIQ_PENDIENTE)
                origenes.append("pendiente")

    df["Categoria"] = cats
    df["Origen"]    = origenes
    return df
