"""
ETL de la Balanza de Comprobación.

Contabilidad manda este archivo junto con el libro de movimientos: es el resumen
oficial y auditado del gasto por cuenta y por mes, con el nombre real de cada
cuenta. No trae detalle de proveedor (por eso no reemplaza al libro), pero es la
cifra que debe cuadrar contra él — y sirve para nombrar el catálogo de cuentas
sin teclear.

Igual que el resto de lo que sube Contabilidad, no se persiste — se carga en
`app.py` (Carga de Archivos) y `core/conciliacion.py` / `pages/3_Cuadre_Contable.py`
lo consumen desde `st.session_state`.

Sin dependencias de Streamlit. `cargar_balanza(f) -> (df, warnings)`.
"""

import io
import re
import unicodedata

import pandas as pd

# La balanza es jerárquica: una cuenta de nivel 1 ("mayor") es la SUMA de sus
# cuentas hijas (nivel 2, 3...). Sumar todos los niveles duplicaría el gasto.
# Nivel 1 es la cifra que hay que usar para cualquier total.
NIVEL_MAYOR = 1

_MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}

# "600000000042000000003" -> cuenta "6000-000-00042", nivel 3 (último dígito).
# Mismo formato de cuenta que ya usa el catálogo (core/database.py: cuentas_contables),
# así que decodificar aquí es lo que permite pre-llenar el nombre en Clasificaciones.
_RE_FILA = re.compile(r"^(\d{21})\s+(.+)$")

# La primera fecha del título trae año de 2 dígitos ("31/Ene/26"), la segunda de
# 4 ("31/Ago/2026") — se ve en el archivo real. El regex acepta ambos formatos.
_RE_TITULO = re.compile(
    r"(\d{1,2})\s*/\s*([A-Za-zÁÉÍÓÚáéíóú]+)\s*/\s*(\d{2,4}).*?"
    r"(\d{1,2})\s*/\s*([A-Za-zÁÉÍÓÚáéíóú]+)\s*/\s*(\d{2,4})",
    re.IGNORECASE,
)


def _sin_acentos(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", str(s))
        if unicodedata.category(c) != "Mn"
    )


def _mes_num(nombre):
    return _MESES.get(_sin_acentos(nombre).upper().strip())


def _detectar_hoja(xls):
    """Primera hoja con un encabezado 'No. de cuenta' + bloques Saldo/Debe/Haber."""
    for sheet in xls.sheet_names:
        try:
            sample = pd.read_excel(xls, sheet_name=sheet, header=None, nrows=15)
        except Exception:
            continue
        celdas = {
            _sin_acentos(v).upper().strip()
            for v in sample.values.flatten() if pd.notna(v)
        }
        if any("NO. DE CUENTA" in c or "NO DE CUENTA" in c for c in celdas) and \
           any("SALDO INICIAL" in c for c in celdas) and \
           any(c == "DEBE" for c in celdas):
            return sheet
    return None


def _localizar_titulo(raw):
    """Busca el texto 'al DD/Mes/AA al DD/Mes/AAAA' en cualquier celda de la hoja."""
    for r in range(min(raw.shape[0], 20)):
        for c in range(raw.shape[1]):
            v = raw.iat[r, c]
            if pd.isna(v):
                continue
            m = _RE_TITULO.search(str(v))
            if m:
                return m
    return None


def _anio_de(anio_txt):
    anio = int(anio_txt)
    return 2000 + anio if anio < 100 else anio


def _localizar_bloques_mes(raw):
    """
    Encuentra, por contenido, cada bloque de mes: la fila con los nombres de mes y,
    debajo, la fila con Saldo inicial/Debe/Haber/Saldo final.

    Nunca se asume una posición fija: la balanza crece cada mes que Contabilidad
    agrega una columna nueva, y asumir el layout de hoy rompería el archivo del
    mes que viene.

    Returns: (fila_meses, fila_subencabezado, [(col, mes_num), ...])
    """
    fila_meses = fila_sub = None
    for r in range(min(raw.shape[0], 20)):
        vals = [str(v).strip().upper() if pd.notna(v) else "" for v in raw.iloc[r]]
        if sum(1 for v in vals if _sin_acentos(v) in _MESES) >= 2:
            fila_meses = r
            break
    if fila_meses is None:
        return None, None, []

    for r in range(fila_meses + 1, min(fila_meses + 4, raw.shape[0])):
        vals = [str(v).strip().upper() if pd.notna(v) else "" for v in raw.iloc[r]]
        if any("SALDO INICIAL" in v for v in vals) and any(v == "DEBE" for v in vals):
            fila_sub = r
            break
    if fila_sub is None:
        return fila_meses, None, []

    bloques = []
    for c in range(raw.shape[1]):
        v = raw.iat[fila_meses, c]
        if pd.isna(v):
            continue
        mes = _mes_num(str(v))
        if mes is None:
            continue
        # El sub-encabezado de ESTE bloque debe caer en la misma columna o muy
        # cerca (tolera una columna de por medio si el layout se corre).
        sub = str(raw.iat[fila_sub, c]).strip().upper() if pd.notna(raw.iat[fila_sub, c]) else ""
        if "SALDO INICIAL" not in sub:
            for dc in (1, -1, 2, -2):
                cc = c + dc
                if 0 <= cc < raw.shape[1]:
                    alt = raw.iat[fila_sub, cc]
                    if pd.notna(alt) and "SALDO INICIAL" in str(alt).strip().upper():
                        c = cc
                        break
        bloques.append((c, mes))
    return fila_meses, fila_sub, bloques


def cargar_balanza(uploaded_file):
    """
    Lee la Balanza de Comprobación (Streamlit UploadedFile o bytes).
    Returns (df, warnings_list).

    df: Cuenta · Nombre_Oficial · Nivel · Mayor · _Mes · Saldo_Inicial · Debe ·
        Haber · Saldo_Final — una fila por cuenta y mes.
    Levanta ValueError cuando el archivo no es utilizable (hoja no encontrada,
    año no determinable) — nunca se adivina un año, un dato mal inferido aquí
    contamina todos los totales.
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
            f"No se encontró una hoja de balanza válida. "
            f"Hojas disponibles: {xls.sheet_names}. "
            f"Se requiere un encabezado 'No. de cuenta' con bloques Saldo/Debe/Haber."
        )

    raw = pd.read_excel(io.BytesIO(content), sheet_name=hoja, header=None)

    m_titulo = _localizar_titulo(raw)
    if m_titulo is None:
        raise ValueError(
            "No se pudo determinar el periodo de la balanza (se buscó un título "
            "con el formato 'al DD/Mes/AA al DD/Mes/AAAA'). Sin el año no se puede "
            "construir el periodo de cada columna con seguridad."
        )
    _, _, anio_ini_txt, _, _, anio_fin_txt = m_titulo.groups()
    anio_ini = _anio_de(anio_ini_txt)
    anio_fin = _anio_de(anio_fin_txt)

    fila_meses, fila_sub, bloques = _localizar_bloques_mes(raw)
    if not bloques:
        raise ValueError(
            "No se encontraron bloques de mes (Saldo inicial/Debe/Haber/Saldo "
            "final) bajo los nombres de los meses."
        )

    # Año por bloque: empieza en anio_ini y sube cada vez que el mes retrocede
    # (diciembre -> enero), para el caso de una balanza que cruza fin de año.
    anio_actual = anio_ini
    mes_prev = None
    periodos = []
    for _col, mes in bloques:
        if mes_prev is not None and mes < mes_prev:
            anio_actual += 1
        periodos.append(pd.Period(year=anio_actual, month=mes, freq="M"))
        mes_prev = mes
    if periodos and periodos[-1].year != anio_fin and anio_fin > anio_ini:
        warnings_list.append(
            f"El año del último bloque de mes ({periodos[-1].year}) no coincide "
            f"con el del título ({anio_fin}); revisa el periodo de la balanza."
        )

    filas = []
    sin_parsear = 0
    fila_datos_ini = (fila_sub if fila_sub is not None else fila_meses) + 1
    for r in range(fila_datos_ini, raw.shape[0]):
        celda = raw.iat[r, 1] if raw.shape[1] > 1 else None
        if pd.isna(celda) or not str(celda).strip():
            continue
        m = _RE_FILA.match(str(celda).strip())
        if not m:
            sin_parsear += 1
            continue
        num, desc = m.group(1), m.group(2).strip()
        cuenta = f"{num[0:4]}-{num[4:7]}-{num[7:12]}"
        nivel = int(num[20])
        mayor = num[0:4]

        for (col, _mes), periodo in zip(bloques, periodos):
            saldo_ini = pd.to_numeric(raw.iat[r, col], errors="coerce")
            debe      = pd.to_numeric(raw.iat[r, col + 1], errors="coerce")
            haber     = pd.to_numeric(raw.iat[r, col + 2], errors="coerce")
            saldo_fin = pd.to_numeric(raw.iat[r, col + 3], errors="coerce")
            filas.append({
                "Cuenta": cuenta, "Nombre_Oficial": desc, "Nivel": nivel,
                "Mayor": mayor, "_Mes": periodo,
                "Saldo_Inicial": float(saldo_ini) if pd.notna(saldo_ini) else 0.0,
                "Debe":          float(debe) if pd.notna(debe) else 0.0,
                "Haber":         float(haber) if pd.notna(haber) else 0.0,
                "Saldo_Final":   float(saldo_fin) if pd.notna(saldo_fin) else 0.0,
            })

    if sin_parsear:
        warnings_list.append(
            f"{sin_parsear} fila(s) en la columna de cuentas no siguieron el "
            f"formato esperado (21 dígitos + descripción) y se omitieron."
        )

    df = pd.DataFrame(filas)
    if len(df) == 0:
        raise ValueError("La balanza no contiene cuentas legibles.")

    n_mayores = df.loc[df["Nivel"] == NIVEL_MAYOR, "Cuenta"].nunique()
    warnings_list.append(
        f"Periodo detectado: {periodos[0]} → {periodos[-1]} "
        f"({len(bloques)} mes(es), {n_mayores} cuenta(s) mayor)."
    )

    return df.reset_index(drop=True), warnings_list


def totales_por_mayor(df, periodos=None):
    """
    Suma de Debe por cuenta mayor (Nivel 1) y mes — la cifra "oficial" de gasto.

    Sumar cualquier otro nivel además de este duplicaría el gasto: una cuenta de
    nivel 1 ya es la suma de sus auxiliares. Esta función es el único lugar del
    proyecto que debe tocar `Debe` de la balanza para totales — evita que ese
    error se repita en cada página que la consuma.
    """
    d = df[df["Nivel"] == NIVEL_MAYOR].copy()
    if periodos is not None:
        claves = {str(p) for p in periodos}
        d = d[d["_Mes"].astype(str).isin(claves)]
    if len(d) == 0:
        return pd.DataFrame(columns=["Mayor", "Nombre_Oficial", "_Mes", "Debe"])
    return (
        d.groupby(["Mayor", "Nombre_Oficial", "_Mes"], as_index=False)["Debe"]
        .sum()
    )


def totales_por_cuenta(df, periodos=None):
    """
    Suma de Debe por cuenta AUXILIAR (Nivel != NIVEL_MAYOR) y mes — al nivel de
    detalle que el catálogo de cuentas contables puede clasificar.

    Hermana de `totales_por_mayor()`, mismo motivo de existir (que nadie tenga
    que tocar `Debe` crudo por su cuenta): esta es la que usa `core.fuentes` para
    sumar solo lo que el usuario ya clasificó como Gasto operativo, cuenta por
    cuenta, en vez de todo el mayor de un golpe.

    No duplica contra `totales_por_mayor()`: verificado contra la balanza real,
    los auxiliares de un mayor SIEMPRE suman exacto a su nivel 1 (diferencia
    $0.00 en los 48 pares mayor×mes comprobados) — nivel 2 y 3 son hermanos bajo
    el mayor, no padre-hijo, así que agregarlos todos no duplica el gasto.
    """
    d = df[df["Nivel"] != NIVEL_MAYOR].copy()
    if periodos is not None:
        claves = {str(p) for p in periodos}
        d = d[d["_Mes"].astype(str).isin(claves)]
    if len(d) == 0:
        return pd.DataFrame(columns=["Cuenta", "Nombre_Oficial", "Mayor", "_Mes", "Debe"])
    return (
        d.groupby(["Cuenta", "Nombre_Oficial", "Mayor", "_Mes"], as_index=False)["Debe"]
        .sum()
    )
