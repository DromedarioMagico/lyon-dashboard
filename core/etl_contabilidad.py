"""
ETL de la base consolidada de Contabilidad.

A diferencia del SAE, este archivo lo mantiene el usuario: Contabilidad le manda una
sola base con todos los movimientos del año y él la re-sube conforme la actualizan.
Cada carga reemplaza a la anterior por completo.

Sin dependencias de Streamlit. `cargar_contabilidad(f) -> (df, warnings)`.
"""

import io
import re
import unicodedata

import pandas as pd

# Etiquetas de relleno para filas incompletas — nunca se descarta un monto válido
# por no traer cuenta o proveedor, se agrupa bajo una etiqueta visible.
SIN_CUENTA    = "SIN CUENTA"
SIN_PROVEEDOR = "SIN PROVEEDOR"

# El archivo trae el mes como texto largo en español con año de dos dígitos
# ("abril-26"). `catalogos.ESPANOL_MES` solo tiene abreviaturas, así que va aparte.
_MESES_LARGOS = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
    # Variantes que aparecen en captura manual
    "SETIEMBRE": 9, "SEPT": 9, "SET": 9,
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "JUN": 6, "JUL": 7, "AGO": 8,
    "OCT": 10, "NOV": 11, "DIC": 12,
}

# Sufijos societarios que sobran al comparar nombres de proveedor entre sistemas.
_SUFIJOS_SOC = re.compile(
    r"\b(S\s*A\s*P\s*I|S\s*A|S\s*DE\s*R\s*L|S\s*R\s*L|DE\s*C\s*V|C\s*V|S\s*C|S\s*AB)\b"
)

COLS_REQ = ["MES", "CUENTA CONTABLE", "PROVEEDOR", "MONTO"]


def _sin_acentos(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", str(s))
        if unicodedata.category(c) != "Mn"
    )


def normalizar_proveedor(nombre):
    """
    Llave de cruce entre el nombre de proveedor de contabilidad y el del SAE.

    No hay RFC ni clave de proveedor en ninguno de los dos sistemas, así que el
    nombre normalizado es lo único con lo que se puede cruzar. Se mantiene
    conservadora a propósito: un falso positivo aquí borra gasto real de la vista.
    """
    if nombre is None or (isinstance(nombre, float) and pd.isna(nombre)):
        return ""
    s = _sin_acentos(nombre).upper()
    s = re.sub(r"[.,;:()\"']", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _SUFIJOS_SOC.sub(" ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_mes(valor):
    """'abril-26' → pd.Period('2026-04', 'M'). Devuelve None si no se entiende."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None

    # Si Excel ya lo entregó como fecha, respetarlo.
    if isinstance(valor, (pd.Timestamp,)):
        return valor.to_period("M")

    s = _sin_acentos(valor).upper().strip()
    s = s.replace("–", "-").replace("—", "-").replace("/", "-").replace(" DE ", "-")
    partes = [p.strip() for p in s.split("-") if p.strip()]
    if len(partes) < 2:
        return None

    mes = _MESES_LARGOS.get(partes[0])
    if mes is None:
        return None

    anio_txt = re.sub(r"[^0-9]", "", partes[-1])
    if not anio_txt:
        return None
    anio = int(anio_txt)
    if anio < 100:
        anio += 2000
    return pd.Period(year=anio, month=mes, freq="M")


def filas_para_bd(df):
    """
    df del ETL → filas para `database.reemplazar_contabilidad`.
    Returns list[(periodo, cuenta, proveedor, proveedor_norm, monto, descripcion)].
    """
    # zip sobre columnas y no itertuples: itertuples renombra los campos que
    # empiezan con guion bajo (`_Mes`) porque no son identificadores válidos.
    return [
        (
            f"{mes.year}-{mes.month:02d}",
            cuenta, prov, norm, float(monto), desc,
        )
        for mes, cuenta, prov, norm, monto, desc in zip(
            df["_Mes"], df["Cuenta"], df["Proveedor"],
            df["Proveedor_Norm"], df["Monto_MXN"], df["Descripcion"],
        )
    ]


def df_desde_bd(rows):
    """
    Filas de `database.get_contabilidad()` → el mismo DataFrame que produce
    `cargar_contabilidad`, para que las páginas no distingan entre el libro recién
    subido y el que ya estaba guardado.
    """
    if not rows:
        return pd.DataFrame(
            columns=["Mes_Raw", "_Mes", "Cuenta", "Proveedor", "Proveedor_Norm",
                     "Monto_MXN", "Descripcion"]
        )

    df = pd.DataFrame(rows)
    df["_Mes"] = df["periodo"].map(lambda p: pd.Period(p, freq="M"))
    return pd.DataFrame({
        "Mes_Raw":        df["periodo"],
        "_Mes":           df["_Mes"],
        "Cuenta":         df["cuenta"],
        "Proveedor":      df["proveedor"],
        "Proveedor_Norm": df["proveedor_norm"],
        "Monto_MXN":      df["monto_mxn"].astype(float),
        "Descripcion":    df["descripcion"],
    })


def _texto_o(serie, defecto):
    """
    Serie → texto limpio, con `defecto` donde venga vacío.

    `fillna` va ANTES de `astype(str)`: con el dtype `str` de pandas 3 los nulos
    sobreviven a la conversión y se colarían como float NaN corriente abajo.
    """
    s = serie.fillna("").astype(str).str.strip()
    return s.where(~s.isin(["", "nan", "None", "<NA>", "NaT"]), defecto)


def _detectar_hoja(xls):
    """Primera hoja cuyo encabezado traiga MES + PROVEEDOR + MONTO."""
    for sheet in xls.sheet_names:
        try:
            sample = pd.read_excel(xls, sheet_name=sheet, nrows=3)
        except Exception:
            continue
        cols = {_sin_acentos(c).upper().strip() for c in sample.columns}
        if {"MES", "PROVEEDOR", "MONTO"}.issubset(cols):
            return sheet
    return None


def cargar_contabilidad(uploaded_file):
    """
    Lee la base consolidada de contabilidad (Streamlit UploadedFile o bytes).
    Returns (df, warnings_list).

    df: _Mes (Period[M]) · Mes_Raw · Cuenta · Proveedor · Proveedor_Norm ·
        Monto_MXN · Descripcion
    Levanta ValueError con mensaje legible cuando el archivo no es utilizable.
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
            f"No se encontró una hoja de contabilidad válida. "
            f"Hojas disponibles: {xls.sheet_names}. "
            f"Se requieren las columnas 'MES', 'PROVEEDOR' y 'MONTO'."
        )

    df_raw = pd.read_excel(io.BytesIO(content), sheet_name=hoja)

    # Los encabezados llegan con acentos inconsistentes según cómo se exportó el
    # archivo (DESCRIPCIÓN a veces viene mojibake); se mapean sin acentos.
    df_raw.columns = [_sin_acentos(c).upper().strip() for c in df_raw.columns]
    df_raw = df_raw.loc[:, ~df_raw.columns.str.startswith("UNNAMED")]

    faltantes = [c for c in COLS_REQ if c not in df_raw.columns]
    if faltantes:
        raise ValueError(
            f"Faltan columnas en la base de contabilidad: {faltantes}.\n"
            f"Columnas detectadas: {list(df_raw.columns)}"
        )

    df = pd.DataFrame(index=df_raw.index)
    df["Mes_Raw"] = df_raw["MES"].astype(str).str.strip()
    df["_Mes"]    = df_raw["MES"].map(_parse_mes)

    df["Cuenta"]    = _texto_o(df_raw["CUENTA CONTABLE"], SIN_CUENTA)
    df["Proveedor"] = _texto_o(df_raw["PROVEEDOR"], SIN_PROVEEDOR)
    df["Proveedor_Norm"] = df["Proveedor"].map(normalizar_proveedor)

    montos = pd.to_numeric(df_raw["MONTO"], errors="coerce")
    df["Monto_MXN"] = montos

    if "DESCRIPCION" in df_raw.columns:
        df["Descripcion"] = df_raw["DESCRIPCION"].fillna("").astype(str).str.strip()
    else:
        df["Descripcion"] = ""
        warnings_list.append("La base no trae columna DESCRIPCIÓN.")

    # ── Filas inutilizables: se reportan, nunca se convierten en montos fantasma ──
    n_sin_monto = int(montos.isna().sum())
    if n_sin_monto:
        ejemplos = (
            df_raw.loc[montos.isna(), "MONTO"].dropna().astype(str).unique()[:3]
        )
        detalle = f" (ej. {', '.join(ejemplos)})" if len(ejemplos) else ""
        warnings_list.append(
            f"{n_sin_monto} fila(s) con MONTO no numérico, descartadas{detalle}."
        )
    df = df[montos.notna()].copy()

    n_sin_mes = int(df["_Mes"].isna().sum())
    if n_sin_mes:
        malos = df.loc[df["_Mes"].isna(), "Mes_Raw"].unique()[:3]
        warnings_list.append(
            f"{n_sin_mes} fila(s) con MES ilegible, descartadas (ej. {', '.join(malos)})."
        )
    df = df[df["_Mes"].notna()].copy()

    if len(df) == 0:
        raise ValueError("La base de contabilidad no contiene movimientos válidos.")

    n_sin_cuenta = int((df["Cuenta"] == SIN_CUENTA).sum())
    if n_sin_cuenta:
        warnings_list.append(
            f"{n_sin_cuenta} movimiento(s) sin cuenta contable, agrupados como "
            f"'{SIN_CUENTA}'."
        )

    n_sin_prov = int((df["Proveedor"] == SIN_PROVEEDOR).sum())
    if n_sin_prov:
        warnings_list.append(
            f"{n_sin_prov} movimiento(s) sin proveedor, agrupados como "
            f"'{SIN_PROVEEDOR}'."
        )

    n_negativos = int((df["Monto_MXN"] < 0).sum())
    if n_negativos:
        warnings_list.append(
            f"{n_negativos} movimiento(s) con monto negativo (notas de crédito o "
            f"ajustes) — se conservan tal cual."
        )

    df["Monto_MXN"] = df["Monto_MXN"].astype(float)
    return df.reset_index(drop=True), warnings_list
