"""
Columna vertebral compartida entre las 7 fuentes de la app.

La app pasó de 2 fuentes (SAE Compras + SAE Ventas) a 7 sin que existiera un
lugar único que supiera qué fuentes hay, qué cubren, y cómo se presenta un
importe que falta. Resultado: cada página inventaba su propia regla del "—", su
propia tarjeta de KPI, y "gasto" terminó significando dos cosas distintas en
Compras y en Facturación sin que ninguna lo declarara.

Este módulo es sin dependencias de Streamlit — recibe `session` como dict
(`st.session_state` lo es) para que se pueda probar con un dict normal, igual
que `core/conciliacion.py` y `core/cruce_ventas.py`.
"""

import pandas as pd

from core.catalogos import label_mes
from core.conciliacion import (
    NAT_GASTO,
    NAT_NO_OPERATIVO,
    NAT_SIN_CLASIFICAR,
    aplicar_catalogo_cuentas,
    conciliar_con_sae,
    gasto_empresa_por_periodo,
    marcar_publicables,
)
from core.etl_balanza import totales_por_cuenta

# ── Regla única del dato faltante ──────────────────────────────────────────────
# Un importe que falta NUNCA se disfraza de cero. Las funciones de este módulo
# devuelven `None` cuando no hay con qué calcular una cifra; estos formateadores
# son el único lugar donde `None` se convierte en el guión — y la única prueba
# válida es `is None`, nunca `> 0` (un cero real también debe imprimirse).
SIN_DATO = "—"


def fmt_money(v, decimals=2):
    """`None` -> "—". Un 0.0 real se imprime "$0.00M", nunca se esconde."""
    if v is None:
        return SIN_DATO
    return f"${v / 1e6:,.{decimals}f}M"


def fmt_pct(v, decimals=1):
    if v is None:
        return SIN_DATO
    return f"{v:.{decimals}f}%"


def fmt_dias(v):
    if v is None:
        return SIN_DATO
    return f"{v:.0f} días"


# ── Tarjeta de KPI compartida ──────────────────────────────────────────────────
# Antes vivía duplicada 5 veces (Compras, Ventas, Resultados Financieros,
# Cuadre Contable, Facturación) con 3 firmas distintas — cualquier regla de
# presentación había que escribirla 5 veces para que se cumpliera.
def kpi_card(label, value, color, desc=None, fuente=None):
    """
    `value` ya viene formateado (usa `fmt_money`/`fmt_pct`/`fmt_dias` antes de
    llamar esta función) — este helper solo arma el HTML de la tarjeta.

    `desc`: nota larga, colapsada en un tooltip "ⓘ" (no estorba si no se abre).
    `fuente`: de dónde salió el número — siempre visible, nunca escondida en el
    tooltip, porque en esta app decir de dónde sale una cifra es tan importante
    como la cifra misma.
    """
    info = ""
    if desc:
        info = (
            "<details style='display:inline-block;margin-left:5px;vertical-align:middle;'>"
            "<summary style='cursor:pointer;color:#9CA3AF;font-size:.78rem;"
            "list-style:none;outline:none;user-select:none;'>ⓘ</summary>"
            "<div style='margin-top:6px;padding:8px 10px;background:#F9FAFB;"
            "border:1px solid #E5E7EB;border-radius:6px;font-size:.75rem;"
            "color:#374151;font-weight:400;text-transform:none;letter-spacing:0;"
            f"line-height:1.5;white-space:normal;'>{desc}</div></details>"
        )
    fuente_html = (
        f"<p style='margin:2px 0 0;font-size:.68rem;color:#9CA3AF;'>{fuente}</p>"
        if fuente else ""
    )
    return f"""
    <div style="background:#fff;border:1px solid #E1E7EC;border-radius:10px;
                padding:1rem 1.25rem;box-shadow:0 1px 4px rgba(0,0,0,.05);">
      <p style="margin:0 0 4px;font-size:.72rem;font-weight:600;color:#6B7280;
                text-transform:uppercase;letter-spacing:.5px;">{label}{info}</p>
      <p style="margin:0;font-size:1.65rem;font-weight:700;color:{color};
                line-height:1.2;">{value}</p>
      {fuente_html}
    </div>"""


# ── Registro de las 7 fuentes ──────────────────────────────────────────────────
# Los dos reportes CFDI comparten `df_cfdi` (mismas 15 columnas, se distinguen
# por Tipo_Doc) — se listan como dos fuentes porque cubren preguntas de negocio
# distintas (ingreso facturado vs. devoluciones), aunque compartan sesión.
FUENTES = [
    {"clave": "compras",      "label": "Compras (SAE)",
     "session_key": "df_compras", "meta_key": "df_compras_meta"},
    {"clave": "ventas",       "label": "Ventas / Pedidos (SAE)",
     "session_key": "df_ventas", "meta_key": "df_ventas_meta"},
    # Facturación es la única fuente que acumula varios archivos (uno por mes)
    # en la misma sesión — se resuelve aparte en `_estado_facturacion()`, no
    # por el camino genérico de abajo.
    {"clave": "facturacion",  "label": "Facturación mensual"},
    {"clave": "contabilidad", "label": "Libro contable",
     "session_key": "df_contabilidad", "meta_key": "df_contabilidad_meta"},
    {"clave": "balanza",      "label": "Balanza de comprobación",
     "session_key": "df_balanza", "meta_key": "df_balanza_meta"},
    {"clave": "cfdi_ventas",  "label": "Reporte CFDI — Ventas",
     "session_key": "df_cfdi", "meta_key": "df_cfdi_meta", "tipo_doc": "Factura"},
    {"clave": "cfdi_notas",   "label": "Reporte CFDI — Notas de crédito",
     "session_key": "df_cfdi", "meta_key": "df_cfdi_meta", "tipo_doc": "Nota Cred"},
]

_FUENTES_POR_CLAVE = {f["clave"]: f for f in FUENTES}


def _vacio():
    """Dict nuevo en cada llamada — nunca comparte la lista `warnings` entre
    fuentes distintas (un `dict(_VACIO)` fijo compartiría la misma lista)."""
    return {
        "cargada": False, "archivo": None, "filas": 0,
        "cobertura": None, "uploaded_at": None, "warnings": [],
    }


def _df_fuente(fuente, session):
    """El DataFrame de esta fuente, ya filtrado por Tipo_Doc si aplica. `None`
    si no hay nada cargado (o el filtro deja el df vacío)."""
    df = session.get(fuente["session_key"])
    if df is None or len(df) == 0:
        return None
    if "tipo_doc" in fuente:
        df = df[df["Tipo_Doc"] == fuente["tipo_doc"]]
        if len(df) == 0:
            return None
    return df


def _estado_facturacion(session):
    """
    Facturación acumula un bundle por mes en `df_facturacion_meses`
    (`{Period: {"bundle": <salida de cargar_facturacion>, "meta": {...}}}`).
    `df_facturacion`/`df_facturacion_meta` (singular) siguen apuntando nada más
    al mes más reciente — eso es lo que sigue leyendo `pages/5_Facturacion.py`
    sin cambios — pero la cobertura y las filas de ESTA función se calculan
    sobre TODOS los meses acumulados, no solo el activo.
    """
    meses = session.get("df_facturacion_meses") or {}
    if not meses:
        return _vacio()

    periodos = sorted(meses.keys())
    filas = sum(len(v["bundle"]["facturas"]) for v in meses.values())
    archivos = [v["meta"].get("archivo") for v in meses.values() if v["meta"].get("archivo")]
    warns = [w for v in meses.values() for w in (v["meta"].get("warnings") or [])]
    subidas = [v["meta"].get("uploaded_at") for v in meses.values() if v["meta"].get("uploaded_at")]

    return {
        "cargada": True,
        "archivo": archivos[0] if len(archivos) == 1 else f"{len(archivos)} archivo(s)",
        "filas": filas,
        "cobertura": f"{label_mes(periodos[0])} – {label_mes(periodos[-1])}",
        "uploaded_at": max(subidas) if subidas else None,
        "warnings": warns,
    }


def estado_fuentes(session):
    """
    Returns {clave: {label, cargada, archivo, filas, cobertura, uploaded_at,
    warnings}} para las 7 fuentes, siempre las 7 — una `session` vacía regresa
    las 7 en "no cargada", nunca lanza.

    La cobertura se calcula de los meses reales que trae el DataFrame (`_Mes`),
    no del texto guardado en el meta de la carga — así nunca se desalinea de
    lo que la fuente realmente contiene. `warnings` son los avisos que dejó el
    ETL al cargar (filas descartadas, hoja detectada por patrón, etc.) — se
    guardan en el meta para no evaporarse en el siguiente rerun.
    """
    out = {}
    for f in FUENTES:
        if f["clave"] == "facturacion":
            out[f["clave"]] = {"label": f["label"], **_estado_facturacion(session)}
            continue

        df = _df_fuente(f, session)
        meta = session.get(f["meta_key"]) or {}
        if df is None:
            out[f["clave"]] = {"label": f["label"], **_vacio()}
            continue
        meses = sorted(df["_Mes"].dropna().unique()) if "_Mes" in df.columns else []
        cobertura = f"{label_mes(meses[0])} – {label_mes(meses[-1])}" if meses else None
        out[f["clave"]] = {
            "label": f["label"], "cargada": True,
            "archivo": meta.get("archivo"), "filas": int(len(df)),
            "cobertura": cobertura, "uploaded_at": meta.get("uploaded_at"),
            "warnings": meta.get("warnings") or [],
        }
    return out


# ── Matriz de capacidades ──────────────────────────────────────────────────────
# Qué fuentes necesita cada vista para mostrarse completa. Lo consume la futura
# página de Carga (Fase 1) para decir "con lo que subiste, esto sí se ve y esto
# no" — vive aquí porque es la misma pregunta que "¿qué fuente falta?".
# Un elemento puede ser una clave de `FUENTES` (obligatoria) o una tupla de
# claves ("cualquiera de estas basta") — Resultados Financieros necesita el CFDI
# de ventas sí o sí, pero el gasto le sirve de libro O de balanza, nunca los dos
# a la vez (ver `gasto_contable_desglosado`), así que exigir ambos sería pedir
# más de lo que la página en verdad necesita para mostrarse completa.
CAPACIDADES = {
    "compras":                ["compras"],
    "ventas":                 ["ventas"],
    "cuadre_contable":        ["contabilidad", "balanza"],
    "resultados_financieros": ["cfdi_ventas", ("contabilidad", "balanza")],
    "facturacion":            ["facturacion", "contabilidad", "cfdi_ventas", "cfdi_notas"],
}


def faltantes(vista, session):
    """
    Requisitos de `vista` que no están satisfechos en `session`.

    Cada elemento de `CAPACIDADES[vista]` es una clave de `FUENTES` (obligatoria)
    o una tupla de claves (basta con que una esté cargada). Regresa, por cada
    requisito no satisfecho, la clave (o la tupla completa, para que el llamador
    pueda armar un "X o Y" en vez de reportar las dos por separado).
    """
    estado = estado_fuentes(session)

    def _cargada(c):
        return estado[c]["cargada"]

    out = []
    for req in CAPACIDADES.get(vista, []):
        if isinstance(req, tuple):
            if not any(_cargada(c) for c in req):
                out.append(req)
        elif not _cargada(req):
            out.append(req)
    return out


# ── Las dos medidas de "gasto" ─────────────────────────────────────────────────
# Compras y Facturación usaban la palabra "gasto" para dos cosas distintas sin
# decirlo — ese es el bug reportado (Costo Operativo Total de Compras nunca
# cuadraba con el Gasto Contable de Facturación). No es un error de cálculo: son
# dos definiciones legítimas que necesitaban dos nombres.
def gasto_fuera_de_compras(session, meses_sel=None):
    """
    Gasto contable que NO pasó por el proceso de compras (columna `Publicable`
    de `core/conciliacion.py`) — lo que Compras le suma al SAE para llegar al
    costo operativo completo.

    Solo el libro puede producir esta medida: la balanza no tiene proveedor ni
    movimiento, así que no hay forma de saber qué parte de su total pasó por el
    SAE. Si el libro no cubre TODOS los meses pedidos, se regresa `(None, None)`
    en vez de un total parcial que disfrazaría de "$0" un mes sin dato.

    Returns (monto | None, "libro" | None).
    """
    df_ctb = session.get("df_contabilidad")
    if df_ctb is None or len(df_ctb) == 0:
        return None, None

    cobertura_libro = set(df_ctb["_Mes"].unique())
    if meses_sel:
        if not set(meses_sel) <= cobertura_libro:
            return None, None
        periodos = meses_sel
    else:
        periodos = None  # todo lo que trae el libro

    conciliado = marcar_publicables(aplicar_catalogo_cuentas(
        conciliar_con_sae(df_ctb, session.get("df_compras")),
        _get_cuentas_contables(),
    ))
    por_periodo = gasto_empresa_por_periodo(conciliado, periodos)
    return float(sum(por_periodo.values())), "libro"


def gasto_contable_desglosado(session, meses_sel=None):
    """
    Resuelve la fuente del gasto operativo UNA sola vez para toda la ventana
    pedida, y desde esa misma fuente entrega el desglose por mes y por cuenta
    contable — para que ninguna pantalla pueda mostrar un total de una fuente
    y un desglose de otra, y para que la Categoria de concepto no entre en
    juego: a nivel Ene–Ago la única fuente que alcanza es la balanza, y la
    balanza no tiene Categoria, solo cuenta auxiliar (excepción documentada a
    la regla de agrupar por Categoria — aquí es lo único posible).

    Misma precedencia "todo o nada" que usaba `gasto_operativo_contable()`: si
    el libro cubre TODOS los meses pedidos, se usa el libro completo (trae
    proveedor); si no, la balanza para esos meses — nunca se mezclan las dos
    fuentes dentro de una misma cifra. Si ninguna alcanza, todo sale en `None`.

    Returns dict:
      fuente:                 "libro" | "balanza" | None
      meses_cubiertos:        set[pd.Period] — la ventana resuelta (vacío si None)
      por_mes:                {pd.Period: float}  Gasto operativo por mes
      por_mes_no_operativo:   {pd.Period: float}  ídem, No operativo
      por_mes_sin_clasificar: {pd.Period: float}  ídem, Sin clasificar
      por_cuenta_y_mes:       DataFrame[Cuenta, Cuenta_Nombre, _Mes, Monto_MXN]
                              (solo Naturaleza == Gasto operativo)
      gasto_operativo / no_operativo / sin_clasificar / total: float | None

    Los tres `por_mes*` solo traen los meses con movimiento en esa naturaleza
    — un mes sin pendiente simplemente no aparece en `por_mes_sin_clasificar`;
    el llamador lee con `.get(mes, 0.0)`, nunca asume que falta el mes entero.
    """
    _vacio = {
        "fuente": None, "meses_cubiertos": set(),
        "por_mes": {}, "por_mes_no_operativo": {}, "por_mes_sin_clasificar": {},
        "por_cuenta_y_mes": pd.DataFrame(columns=["Cuenta", "Cuenta_Nombre", "_Mes", "Monto_MXN"]),
        "gasto_operativo": None, "no_operativo": None, "sin_clasificar": None, "total": None,
    }

    def _serie_mensual(d):
        return {m: float(v) for m, v in d.groupby("_Mes")["Monto_MXN"].sum().items()}

    df_ctb = session.get("df_contabilidad")
    df_bal = session.get("df_balanza")

    cobertura_libro = set(df_ctb["_Mes"].unique()) if df_ctb is not None and len(df_ctb) else set()
    cobertura_bal = set(df_bal["_Mes"].unique()) if df_bal is not None and len(df_bal) else set()

    objetivo = set(meses_sel) if meses_sel else (cobertura_libro | cobertura_bal)
    if not objetivo:
        return _vacio

    if objetivo <= cobertura_libro:
        conciliado = marcar_publicables(aplicar_catalogo_cuentas(
            conciliar_con_sae(df_ctb, session.get("df_compras")),
            _get_cuentas_contables(),
        ))
        sub = conciliado[conciliado["_Mes"].isin(objetivo)] if meses_sel else conciliado

        gasto          = sub[sub["Naturaleza"] == NAT_GASTO]
        no_operativo   = sub[sub["Naturaleza"] == NAT_NO_OPERATIVO]
        sin_clasificar = sub[sub["Naturaleza"] == NAT_SIN_CLASIFICAR]
        por_cuenta_y_mes = (
            gasto.groupby(["Cuenta", "Cuenta_Nombre", "_Mes"], as_index=False)["Monto_MXN"]
            .sum()
        )
        return {
            "fuente": "libro", "meses_cubiertos": objetivo,
            "por_mes": _serie_mensual(gasto),
            "por_mes_no_operativo": _serie_mensual(no_operativo),
            "por_mes_sin_clasificar": _serie_mensual(sin_clasificar),
            "por_cuenta_y_mes": por_cuenta_y_mes,
            "gasto_operativo": float(gasto["Monto_MXN"].sum()),
            "no_operativo": float(no_operativo["Monto_MXN"].sum()),
            "sin_clasificar": float(sin_clasificar["Monto_MXN"].sum()),
            "total": float(sub["Monto_MXN"].sum()),
        }

    if objetivo <= cobertura_bal:
        # Mismo filtro que la rama del libro: solo cuenta lo que el usuario ya
        # marcó como Gasto operativo, cuenta por cuenta (`totales_por_cuenta`,
        # nunca `totales_por_mayor` — duplicaría el gasto).
        periodos = objetivo if meses_sel else None
        tot = totales_por_cuenta(df_bal, periodos=periodos)
        if len(tot) == 0:
            return {**_vacio, "fuente": "balanza", "meses_cubiertos": objetivo,
                    "gasto_operativo": 0.0, "no_operativo": 0.0,
                    "sin_clasificar": 0.0, "total": 0.0}

        cuentas = _get_cuentas_contables()
        naturaleza = tot["Cuenta"].map(
            lambda c: (cuentas.get(c) or {}).get("naturaleza", NAT_SIN_CLASIFICAR)
        )
        tot = tot.assign(Naturaleza=naturaleza, Cuenta_Nombre=tot["Nombre_Oficial"]) \
                 .rename(columns={"Debe": "Monto_MXN"})

        gasto          = tot[tot["Naturaleza"] == NAT_GASTO]
        no_operativo   = tot[tot["Naturaleza"] == NAT_NO_OPERATIVO]
        sin_clasificar = tot[tot["Naturaleza"] == NAT_SIN_CLASIFICAR]
        por_cuenta_y_mes = gasto[["Cuenta", "Cuenta_Nombre", "_Mes", "Monto_MXN"]].copy()
        return {
            "fuente": "balanza", "meses_cubiertos": objetivo,
            "por_mes": _serie_mensual(gasto),
            "por_mes_no_operativo": _serie_mensual(no_operativo),
            "por_mes_sin_clasificar": _serie_mensual(sin_clasificar),
            "por_cuenta_y_mes": por_cuenta_y_mes,
            "gasto_operativo": float(gasto["Monto_MXN"].sum()),
            "no_operativo": float(no_operativo["Monto_MXN"].sum()),
            "sin_clasificar": float(sin_clasificar["Monto_MXN"].sum()),
            "total": float(tot["Monto_MXN"].sum()),
        }

    return _vacio


def gasto_operativo_contable(session, meses_sel=None):
    """
    Todo el gasto operativo que reportó Contabilidad para el periodo — la
    medida que usan Facturación y Cuadre Contable. Envoltura delgada sobre
    `gasto_contable_desglosado()`: una sola implementación de la precedencia
    "todo o nada" libro-vs-balanza, nunca dos que puedan divergir.

    Returns (monto | None, "libro" | "balanza" | None).
    """
    d = gasto_contable_desglosado(session, meses_sel)
    return d["gasto_operativo"], d["fuente"]


def ingresos_confirmados_por_mes(session, meses_sel=None):
    """
    Ventas confirmadas del Reporte CFDI, NETAS de notas de crédito, sin IVA
    (`Subtotal_MXN` — la base comparable contra el gasto contable, que tampoco
    trae IVA). Mismo filtrado que usa `pages/5_Facturacion.py`: facturas no
    canceladas en positivo, notas de crédito no canceladas en negativo.

    Returns (dict[pd.Period, float] | None, "cfdi" | None). `None` si no hay
    reporte CFDI de ventas cargado en la sesión — nunca un dict vacío, que se
    leería como "cero ingresos" en vez de "no hay con qué calcularlos".
    """
    df_cfdi = session.get("df_cfdi")
    if df_cfdi is None or len(df_cfdi) == 0:
        return None, None

    d = df_cfdi[~df_cfdi["Cancelado"]].copy()
    if meses_sel:
        d = d[d["_Mes"].isin(set(meses_sel))]
    if len(d) == 0:
        return {}, "cfdi"

    signo = d["Tipo_Doc"].map(lambda t: 1.0 if t == "Factura" else -1.0)
    neto = (d["Subtotal_MXN"] * signo).groupby(d["_Mes"]).sum()
    return {m: float(v) for m, v in neto.items()}, "cfdi"


def resultado_rango(ingresos, gasto_operativo, sin_clasificar):
    """
    El Resultado del periodo, como RANGO mientras haya gasto sin clasificar —
    es la regla de seguridad de Resultados Financieros: con cuentas sin
    clasificar, "Resultado = Ingresos − Gasto operativo" a secas disfraza de
    margen real un número que todavía puede bajar hasta el piso.

        piso  = ingresos − (gasto_operativo + sin_clasificar)   # peor caso
        techo = ingresos − gasto_operativo                      # mejor caso

    Returns (piso, techo, exacto). `exacto=True` (piso == techo) cuando
    `sin_clasificar == 0` — ahí el rango colapsa solo en un número. Si falta
    `ingresos` o `gasto_operativo`, regresa `(None, None, False)`: no hay
    resultado que mostrar, ni siquiera como rango.
    """
    if ingresos is None or gasto_operativo is None:
        return None, None, False
    sin_clasificar = sin_clasificar or 0.0
    techo = ingresos - gasto_operativo
    piso = techo - sin_clasificar
    return piso, techo, sin_clasificar == 0


def resumen_balanza(df_balanza, periodos=None, cuentas=None):
    """
    Las tres cifras de clasificación para la balanza — espejo de
    `conciliacion.resumen_conciliacion()`, pero a nivel de cuenta auxiliar de
    la balanza en vez del libro de movimientos. Un total parcial sin su
    pendiente al lado es un número engañoso (misma regla que ya aplica el
    libro): por eso esta función siempre regresa las tres cifras juntas.

    `cuentas` es opcional — el dict de `database.get_cuentas_contables()`; se
    resuelve solo si no se pasa, para que `gasto_operativo_contable()` no
    tenga que consultar la BD dos veces en la misma llamada.

    Returns {"gasto_operativo", "no_operativo", "sin_clasificar", "total"}.
    """
    tot = totales_por_cuenta(df_balanza, periodos=periodos)
    if len(tot) == 0:
        return {"gasto_operativo": 0.0, "no_operativo": 0.0, "sin_clasificar": 0.0, "total": 0.0}

    if cuentas is None:
        cuentas = _get_cuentas_contables()
    naturaleza = tot["Cuenta"].map(
        lambda c: (cuentas.get(c) or {}).get("naturaleza", NAT_SIN_CLASIFICAR)
    )

    def _suma(mask):
        return float(tot.loc[mask, "Debe"].sum())

    return {
        "gasto_operativo": _suma(naturaleza == NAT_GASTO),
        "no_operativo":    _suma(naturaleza == NAT_NO_OPERATIVO),
        "sin_clasificar":  _suma(naturaleza == NAT_SIN_CLASIFICAR),
        "total":           float(tot["Debe"].sum()),
    }


def _get_cuentas_contables():
    """Import perezoso: `core.database` toca disco/BD al importarse, y este
    módulo debe poder importarse (y probarse) sin que eso pase."""
    from core.database import get_cuentas_contables
    return get_cuentas_contables()
