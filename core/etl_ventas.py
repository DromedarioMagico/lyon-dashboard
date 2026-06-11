import io
import pandas as pd

from core.catalogos import ESTATUS_VALIDOS_VENTAS, ABREVIACIONES

HOJA_VENTAS = "Pedidos"
COLS_REQ = [
    "Tipo", "Clave", "Nombre", "Estatus",
    "Fecha de elaboración", "Subtotal",
    "Total de comisiones", "Importe total",
    "Nombre del vendedor",
]


def _parse_num(v):
    if pd.isna(v):
        return 0.0
    s = str(v).strip().replace(",", "").replace("$", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def abreviar_cliente(nombre):
    if nombre in ABREVIACIONES:
        return ABREVIACIONES[nombre]
    return nombre if len(nombre) <= 32 else nombre[:30] + "…"


def _detectar_hoja(xls):
    if HOJA_VENTAS in xls.sheet_names:
        return HOJA_VENTAS
    candidatos = []
    for sheet in xls.sheet_names:
        try:
            sample = pd.read_excel(xls, sheet_name=sheet, nrows=5)
            cols = [str(c).strip() for c in sample.columns]
            if "Nombre" in cols and "Estatus" in cols and "Importe total" in cols:
                n = len(pd.read_excel(xls, sheet_name=sheet))
                candidatos.append((sheet, n))
        except Exception:
            continue
    if not candidatos:
        return None
    return max(candidatos, key=lambda x: x[1])[0]


def cargar_ventas(uploaded_file):
    """
    Loads and cleans a SAE pedidos file (Streamlit UploadedFile or raw bytes).
    Returns (df, warnings_list).
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
            f"No se encontró hoja de Pedidos válida. "
            f"Hojas disponibles: {xls.sheet_names}. "
            f"Se requieren columnas 'Nombre', 'Estatus' e 'Importe total'."
        )
    if hoja != HOJA_VENTAS:
        warnings_list.append(f"Hoja detectada: '{hoja}' (se esperaba '{HOJA_VENTAS}').")

    df_raw = pd.read_excel(io.BytesIO(content), sheet_name=hoja)
    df_raw.columns = df_raw.columns.astype(str).str.strip()

    faltantes = [c for c in COLS_REQ if c not in df_raw.columns]
    if faltantes:
        raise ValueError(
            f"Faltan columnas: {faltantes}.\n"
            f"Columnas detectadas: {list(df_raw.columns)}"
        )

    df = df_raw[df_raw["Estatus"].astype(str).str.strip().isin(ESTATUS_VALIDOS_VENTAS)].copy()
    descartadas = len(df_raw) - len(df)
    if descartadas:
        warnings_list.append(f"{descartadas:,} filas descartadas (estatus cancelado/inválido).")

    # Fechas — SAE exporta como strings dd/mm/yyyy
    df["Fecha"] = pd.to_datetime(df["Fecha de elaboración"], format="%d/%m/%Y", errors="coerce")
    mask_bad = df["Fecha"].isna()
    if mask_bad.any():
        df.loc[mask_bad, "Fecha"] = pd.to_datetime(
            df.loc[mask_bad, "Fecha de elaboración"], errors="coerce"
        )
    sin_fecha = df["Fecha"].isna().sum()
    if sin_fecha:
        warnings_list.append(f"{sin_fecha} fila(s) sin fecha válida descartadas.")
    df = df.dropna(subset=["Fecha"]).copy()

    if len(df) == 0:
        raise ValueError("El archivo no contiene pedidos válidos después del filtrado.")

    # Importes
    df["Subtotal_MXN"] = df["Subtotal"].apply(_parse_num)
    df["Comision_MXN"] = df["Total de comisiones"].apply(_parse_num)
    df["Importe_MXN"]  = df["Importe total"].apply(_parse_num)
    df["IVA_MXN"]      = df["Importe_MXN"] - df["Subtotal_MXN"]

    # Normalizaciones
    df["Vendedor"] = (
        df["Nombre del vendedor"].fillna("Sin asignar")
          .astype(str).str.strip().replace({"": "Sin asignar"})
    )
    df["Cliente_Nombre"]  = df["Nombre"].fillna("(sin nombre)").astype(str).str.strip()
    df["Cliente_Display"] = df["Cliente_Nombre"].apply(abreviar_cliente)
    df["_Mes"] = df["Fecha"].dt.to_period("M")

    return df, warnings_list


def aplicar_vendedores(df):
    """Re-applies vendor assignments from DB, overwriting 'Sin asignar' entries."""
    from core.database import get_vendedor_clientes
    asignaciones = get_vendedor_clientes()
    if not asignaciones:
        return df
    df = df.copy()
    mask_sin = df["Vendedor"] == "Sin asignar"
    df.loc[mask_sin, "Vendedor"] = (
        df.loc[mask_sin, "Cliente_Nombre"].map(asignaciones).fillna("Sin asignar")
    )
    return df
