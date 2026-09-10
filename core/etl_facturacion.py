"""
ETL de `Facturación <MES> 2026 - LYON.xlsx` — el tramo pedido → factura.

Sin dependencias de Streamlit. Una función por hoja; cada una recorta su fila
de total embebida (el problema recurrente del archivo). Ver el anexo de
`docs/PLAN_FACTURACION.md` para la estructura verificada.

Trampas que se manejan aquí:
  - El nombre de la hoja lleva el mes (`FACTURAS AGOSTO 2026`) → detección por
    prefijo, no por nombre exacto.
  - Cada hoja trae su fila de total dentro del rango de datos → se corta por
    contenido (primera fila con la columna llave vacía / numérica), no por
    índice fijo.
  - `FECHA` viene como serial de Excel (46237 = 2026-08-01) → conversión con
    epoch 1899-12-30.
  - CONALITEG en `DEV Y DESC` aparece con IVA nulo (tasa 0 %) y como
    `COMISION NACIONAL DE LIBROS`.
"""
import io
import re

import pandas as pd

from core.etl_ventas import abreviar_cliente

_MESES_ES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}
_EXCEL_EPOCH = pd.Timestamp("1899-12-30")

# Segmentos de `HISTORICO`, en el orden en que se apilan.
SEGMENTOS = [
    "VENTA PRIVADA",
    "VENTA FILIAL",
    "VENTA PRIVADA/GOBIERNO",
    "VENTA GOBIERNO (CONALITEG)",
    "VENTA VARIOS (RENTA)",
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _num(v):
    """Celda de Excel → float. Vacío / no numérico → 0.0."""
    if v is None:
        return 0.0
    if isinstance(v, float) and pd.isna(v):
        return 0.0
    s = str(v).strip().replace(",", "").replace("$", "")
    if not s or s.lower() in ("nan", "none", "-"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _es_numero(v):
    """True si la celda parsea como número (para detectar filas de total)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    try:
        float(str(v).strip().replace(",", "").replace("$", ""))
        return True
    except ValueError:
        return False


def _fecha(v):
    """Serial de Excel o string → Timestamp. Vacío → NaT."""
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return pd.NaT
    try:
        return _EXCEL_EPOCH + pd.Timedelta(days=float(v))
    except (ValueError, TypeError):
        return pd.to_datetime(v, errors="coerce")


def _detectar_hoja(xls, prefijo):
    """Primera hoja cuyo nombre (normalizado) empieza con `prefijo`."""
    for s in xls.sheet_names:
        if s.strip().upper().startswith(prefijo):
            return s
    return None


def _mes_anio(nombre_hoja_facturas):
    """'FACTURAS AGOSTO 2026' → (8, 2026). (None, None) si no se puede parsear."""
    m = re.search(r"([A-ZÁÉÍÓÚ]+)\s+(\d{4})", (nombre_hoja_facturas or "").upper())
    if not m:
        return (None, None)
    return (_MESES_ES.get(m.group(1)), int(m.group(2)))


def _cliente_display(nombre):
    n = str(nombre).strip()
    if n.upper().startswith("COMISION NACIONAL DE LIBROS"):
        return "CONALITEG"
    return abreviar_cliente(n)


def _cut_por_columna_vacia(df, col):
    """Recorta el df en la primera fila donde `col` está vacía/NaN."""
    if col not in df.columns:
        return df
    vacio = df[col].isna() | (df[col].astype(str).str.strip() == "")
    if vacio.any():
        primera = int(vacio.to_numpy().argmax())
        return df.iloc[:primera].copy()
    return df


# ── una función por hoja ─────────────────────────────────────────────────────

def cargar_facturas(xls, mes, anio, warnings, es_ref=False):
    """`FACTURAS <MES> <AÑO>` (header=3). Devuelve el detalle de facturas del mes."""
    hoja = _detectar_hoja(xls, "FACTURAS")
    if hoja is None:
        raise ValueError("No se encontró la hoja 'FACTURAS <MES> <AÑO>'.")

    raw = pd.read_excel(xls, sheet_name=hoja, header=3)
    raw.columns = raw.columns.astype(str).str.strip()

    req = ["FECHA", "FACT", "Cliente", "Nombre", "Venta en M.N.", "IVA en M.N.", "Total"]
    faltan = [c for c in req if c not in raw.columns]
    if faltan:
        raise ValueError(f"Hoja '{hoja}': faltan columnas {faltan}. Están: {list(raw.columns)}")

    df = _cut_por_columna_vacia(raw, "FECHA")

    df = pd.DataFrame({
        "Fecha":          df["FECHA"].apply(_fecha),
        "Factura":        df["FACT"].astype(str).str.strip(),
        "Cliente_Codigo": pd.to_numeric(df["Cliente"], errors="coerce").astype("Int64"),
        "Cliente_Nombre": df["Nombre"].astype(str).str.strip(),
        "Subtotal_MXN":   df["Venta en M.N."].apply(_num),
        "IVA_MXN":        df["IVA en M.N."].apply(_num),
        "Importe_MXN":    df["Total"].apply(_num),
    })
    df["Cliente_Display"] = df["Cliente_Nombre"].apply(_cliente_display)
    df["_Mes"] = df["Fecha"].dt.to_period("M")

    _validar(warnings, "Facturas del mes", len(df), 107, es_ref)
    _validar(warnings, "Subtotal de facturas", df["Subtotal_MXN"].sum(), 9_424_794.39, es_ref)
    return df


def cargar_historico(xls, anio, warnings, es_ref=False):
    """`HISTORICO` (header=2). Matriz segmento × mes → formato largo (sin IVA)."""
    hoja = _detectar_hoja(xls, "HISTORICO")
    if hoja is None:
        raise ValueError("No se encontró la hoja 'HISTORICO'.")

    raw = pd.read_excel(xls, sheet_name=hoja, header=2)
    raw.columns = [str(c).strip() for c in raw.columns]
    col_seg = raw.columns[0]  # 'Unnamed: 0' o similar

    # Solo las filas cuyo primer campo es un segmento conocido (corta el total).
    raw["_seg"] = raw[col_seg].astype(str).str.strip()
    detalle = raw[raw["_seg"].isin(SEGMENTOS)]

    filas = []
    for _, r in detalle.iterrows():
        seg = r["_seg"]
        for nombre_mes, num in _MESES_ES.items():
            # las columnas de mes pueden traer espacios ('MAYO ') → normalizar
            col = next((c for c in raw.columns if c.strip().upper() == nombre_mes), None)
            if col is None:
                continue
            val = r[col]
            if val is None or (isinstance(val, float) and pd.isna(val)) or str(val).strip() == "":
                continue
            filas.append({
                "Segmento":     seg,
                "Segmento_Corto": seg.replace("VENTA ", "").title(),
                "_Mes":         pd.Period(year=anio, month=num, freq="M"),
                "Mes_Num":      num,
                "Subtotal_MXN": _num(val),
            })
    df = pd.DataFrame(filas)
    if not df.empty:
        _validar(warnings, "Total 2026 (HISTORICO)", df["Subtotal_MXN"].sum(),
                 191_944_219.94, es_ref)
    return df


def cargar_dev_desc(xls, warnings, es_ref=False):
    """`DEV Y DESC` (header=2). Penalizaciones y descuentos — las fugas."""
    hoja = _detectar_hoja(xls, "DEV Y DESC")
    if hoja is None:
        raise ValueError("No se encontró la hoja 'DEV Y DESC'.")

    raw = pd.read_excel(xls, sheet_name=hoja, header=2)
    raw.columns = [str(c).strip() for c in raw.columns]

    df = _cut_por_columna_vacia(raw, "FECHA")  # detalle son las filas con FECHA

    # El marcador '** PENALIZACION' / '** DESCUENTO' va por POSICIÓN (col 6).
    tipo_col = raw.columns[6] if len(raw.columns) > 6 else None
    tipos = (
        df[tipo_col].astype(str).str.replace("*", "", regex=False).str.strip()
        if tipo_col is not None else pd.Series([""] * len(df), index=df.index)
    )

    out = pd.DataFrame({
        "Fecha":          df["FECHA"].apply(_fecha),
        "Cliente_Nombre": df["CLIENTE"].astype(str).str.strip(),
        "Subtotal_MXN":   df["Total Sin IVA"].apply(_num),
        "IVA_MXN":        df["IVA"].apply(_num),
        "Tipo":           tipos.str.capitalize().values,
    })
    out["Cliente_Display"] = out["Cliente_Nombre"].apply(_cliente_display)
    out["Tasa_Cero"] = out["IVA_MXN"] == 0
    out["_Mes"] = out["Fecha"].dt.to_period("M")

    _validar(warnings, "Devoluciones y descuentos", out["Subtotal_MXN"].sum(),
             1_065_778.14, es_ref)
    return out


def cargar_remisiones(xls, mes, anio, warnings, es_ref=False):
    """`REMISIONES PTES FACTURAR` (header=3). Pendiente por facturar + anomalías."""
    hoja = _detectar_hoja(xls, "REMISIONES")
    if hoja is None:
        raise ValueError("No se encontró la hoja 'REMISIONES PTES FACTURAR'.")

    raw = pd.read_excel(xls, sheet_name=hoja, header=3)
    raw.columns = [str(c).strip() for c in raw.columns]

    df = _cut_por_columna_vacia(raw, "FECHA")

    # marca '*** REVISAR ***' por posición (col 7)
    rev_col = raw.columns[7] if len(raw.columns) > 7 else None
    revisar = (
        df[rev_col].astype(str).str.contains("REVISAR", case=False, na=False)
        if rev_col is not None else pd.Series([False] * len(df), index=df.index)
    )

    out = pd.DataFrame({
        "Fecha":          df["FECHA"].apply(_fecha),
        "Remision":       df["REMISION"].astype(str).str.strip(),
        "Cliente_Codigo": pd.to_numeric(df["Cliente"], errors="coerce").astype("Int64"),
        "Cliente_Nombre": df["Nombre"].astype(str).str.strip(),
        "Subtotal_MXN":   df["Venta en M.N."].apply(_num),
        "IVA_MXN":        df["IVA en M.N."].apply(_num),
        "Importe_MXN":    df["Total"].apply(_num),
        "Revisar":        revisar.values,
    })
    out["Cliente_Display"] = out["Cliente_Nombre"].apply(_cliente_display)
    out["_Mes"] = out["Fecha"].dt.to_period("M")

    periodo = pd.Period(year=anio, month=mes, freq="M") if mes else None
    out["Fuera_De_Mes"] = (out["_Mes"] != periodo) if periodo is not None else False
    corte = (periodo.to_timestamp(how="end").normalize() if periodo is not None
             else out["Fecha"].max())
    out["Antiguedad_Dias"] = (corte - out["Fecha"]).dt.days.clip(lower=0)

    _validar(warnings, "Remisiones pendientes", len(out), 76, es_ref)
    _validar(warnings, "Subtotal remisiones", out["Subtotal_MXN"].sum(), 2_854_575.63, es_ref)
    n_fuera = int(out["Fuera_De_Mes"].sum())
    if n_fuera:
        warnings.append(f"{n_fuera} remisión(es) con fecha fuera del mes del archivo.")
    if bool(out["Revisar"].any()):
        warnings.append(f"{int(out['Revisar'].sum())} remisión(es) marcada(s) *** REVISAR ***.")
    return out


def cargar_resumen(xls, warnings, es_ref=False):
    """`RESUMEN` (header=2). Concentrado por cliente — QA + segmento por cliente."""
    hoja = _detectar_hoja(xls, "RESUMEN")
    if hoja is None:
        raise ValueError("No se encontró la hoja 'RESUMEN'.")

    raw = pd.read_excel(xls, sheet_name=hoja, header=2)
    raw.columns = [str(c).strip() for c in raw.columns]

    # El detalle termina donde `Segmento` deja de ser texto (pasa a % numérico).
    seg_es_num = raw["Segmento"].apply(_es_numero) if "Segmento" in raw.columns else \
        pd.Series([False] * len(raw))
    cliente_vacio = raw["CLIENTE"].isna() | (raw["CLIENTE"].astype(str).str.strip() == "")
    fin = (seg_es_num | cliente_vacio)
    df = raw.iloc[:int(fin.to_numpy().argmax())].copy() if fin.any() else raw.copy()

    out = pd.DataFrame({
        "Cliente_Nombre": df["CLIENTE"].astype(str).str.strip(),
        "Segmento":       df["Segmento"].astype(str).str.strip(),
        "Subtotal_MXN":   df["Total Sin IVA"].apply(_num),
        "IVA_MXN":        df["IVA"].apply(_num),
    })
    out["Cliente_Display"] = out["Cliente_Nombre"].apply(_cliente_display)

    _validar(warnings, "Clientes en RESUMEN", len(out), 14, es_ref)
    return out


def _validar(warnings, etiqueta, obtenido, esperado, es_ref, tol=1.0):
    """
    Chequeo de control contra las cifras verificadas del archivo de agosto 2026.
    Solo aplica cuando `es_ref` es True (mes 8, año 2026) — para cualquier otro
    mes las cifras son otras y no tiene sentido comparar.
    """
    if not es_ref:
        return
    try:
        ok = abs(float(obtenido) - float(esperado)) <= max(tol, abs(esperado) * 0.005)
    except (TypeError, ValueError):
        ok = False
    if not ok:
        warnings.append(
            f"⚠ Control '{etiqueta}' no cuadra: {obtenido:,.2f} vs {esperado:,.2f} esperado "
            f"(archivo de agosto 2026)."
        )


# ── orquestador ─────────────────────────────────────────────────────────────

def cargar_facturacion(uploaded_file):
    """
    Carga completa de `Facturación <MES> 2026 - LYON.xlsx`.

    Devuelve `(data, warnings)` donde `data` es un dict con los 5 DataFrames
    (`facturas`, `historico`, `dev_desc`, `remisiones`, `resumen`) más
    `mes`, `anio`, `periodo` y `archivo`. Nada se persiste — vive en
    `st.session_state.df_facturacion`.
    """
    warnings = []
    content = uploaded_file.read() if hasattr(uploaded_file, "read") else uploaded_file
    nombre_archivo = getattr(uploaded_file, "name", "facturación.xlsx")

    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception as e:
        raise ValueError(f"No se pudo leer el archivo Excel: {e}")

    hoja_fac = _detectar_hoja(xls, "FACTURAS")
    if hoja_fac is None:
        raise ValueError(
            f"No parece un archivo de facturación de Lyon. "
            f"Hojas encontradas: {xls.sheet_names}. Se espera una que empiece con 'FACTURAS'."
        )
    mes, anio = _mes_anio(hoja_fac)
    if mes is None:
        anio = pd.Timestamp.now().year
        warnings.append(f"No se pudo leer el mes del nombre de hoja '{hoja_fac}'.")

    es_ref = (mes == 8 and anio == 2026)  # archivo de referencia con cifras verificadas

    facturas   = cargar_facturas(xls, mes, anio, warnings, es_ref)
    historico  = cargar_historico(
        xls, anio or facturas["_Mes"].dropna().max().year, warnings, es_ref)
    dev_desc   = cargar_dev_desc(xls, warnings, es_ref)
    remisiones = cargar_remisiones(xls, mes, anio, warnings, es_ref)
    resumen    = cargar_resumen(xls, warnings, es_ref)

    periodo = pd.Period(year=anio, month=mes, freq="M") if mes else None

    data = {
        "facturas":   facturas,
        "historico":  historico,
        "dev_desc":   dev_desc,
        "remisiones": remisiones,
        "resumen":    resumen,
        "mes":        mes,
        "anio":       anio,
        "periodo":    periodo,
        "archivo":    nombre_archivo,
    }
    return data, warnings
