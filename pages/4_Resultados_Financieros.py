import pandas as pd
import streamlit as st

from core.catalogos import COLOR_LYON, COLOR_VENTAS, COLOR_COMPRAS, label_mes
from core.database import init_db
from core.fuentes import (
    kpi_card as _kpi, fmt_money, fmt_pct, SIN_DATO,
    ingresos_confirmados_por_mes, gasto_contable_desglosado, resultado_rango,
    faltantes, estado_fuentes,
)
from core.navigation import (
    render_sidebar_search, render_sidebar_status,
    inject_custom_css, handle_pending_nav, render_periodo_filter,
)
from core.plots import (
    plot_cascada_mes, plot_cascada_anual, plot_gasto_por_cuenta_mes,
    plot_facturado_vs_gasto, plot_barras_temporales,
)

st.set_page_config(
    page_title="Resultados Financieros — Lyon AG",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_db()
inject_custom_css()
handle_pending_nav()

_GREEN = COLOR_VENTAS
_RED   = COLOR_COMPRAS
_AMBER = "#E97132"
_GRAY  = "#9E9E9E"
_BLUE  = COLOR_LYON

_FUENTE_GASTO_LABEL = {"libro": "Libro contable", "balanza": "Balanza de comprobación"}


def _esc_money(v):
    """fmt_money, con el "$" escapado — esta página combina SIEMPRE dos montos
    (piso y techo) en una sola tarjeta, y Streamlit interpreta un par de "$"
    sin escapar como delimitador de LaTeX (ver CLAUDE.md)."""
    s = fmt_money(v)
    return s.replace("$", "\\$") if s != SIN_DATO else s


def _kpi_rango(label, piso, techo, exacto, color, indicativo=False):
    """Tarjeta de KPI para una cifra que puede ser rango (piso–techo) o, una
    vez que no quede nada sin clasificar, un número exacto. `indicativo=True`
    rotula el KPI en ámbar — el caso en que lo sin clasificar pesa más que el
    propio gasto operativo, y el rango por sí solo ya no basta de aviso."""
    lbl = f"{label} (indicativo)" if indicativo else label
    col = _AMBER if indicativo else color
    if piso is None or techo is None:
        val = SIN_DATO
    elif exacto:
        val = _esc_money(techo)
    else:
        val = f"{_esc_money(piso)} – {_esc_money(techo)}"
    return _kpi(lbl, val, col)


def _kpi_rango_pct(label, piso_pct, techo_pct, exacto, color, indicativo=False):
    lbl = f"{label} (indicativo)" if indicativo else label
    col = _AMBER if indicativo else color
    if piso_pct is None or techo_pct is None:
        val = SIN_DATO
    elif exacto:
        val = fmt_pct(techo_pct)
    else:
        val = f"{fmt_pct(piso_pct)} – {fmt_pct(techo_pct)}"
    return _kpi(lbl, val, col)


def _color_resultado(v):
    if isinstance(v, (int, float)):
        if v < 0:
            return "color: #C00000; font-weight: 700"
        if v > 0:
            return "color: #548235; font-weight: 700"
    return ""


# ── Sidebar + header ─────────────────────────────────────────────────────────
with st.sidebar:
    render_sidebar_search()
    render_sidebar_status()

st.markdown(
    f"<h1 style='color:{COLOR_LYON}'>"
    "<span class='material-symbols-outlined'>insights</span>Resultados Financieros</h1>",
    unsafe_allow_html=True,
)
st.caption(
    "Lo único que mide esta página: ventas confirmadas (Reporte CFDI) contra el "
    "gasto operativo contable. Ni Compras ni pedidos entran aquí — para eso están "
    "las páginas de Compras y Ventas."
)

# ── Gate: necesita el CFDI de ventas y, de libro o balanza, cualquiera ────────
_falta = faltantes("resultados_financieros", st.session_state)
if _falta:
    _estado_f = estado_fuentes(st.session_state)
    _labels = [
        _estado_f[r]["label"] if isinstance(r, str)
        else " o ".join(_estado_f[x]["label"] for x in r)
        for r in _falta
    ]
    st.warning("Para ver Resultados Financieros falta: " + ", ".join(_labels) + ".")
    if st.button("Ir a Carga de Archivos", use_container_width=True, type="primary"):
        st.switch_page("app.py")
    st.stop()

# ── Universo de meses: unión de lo que cubre el CFDI y lo que cubre el gasto ──
_ing_full, _ = ingresos_confirmados_por_mes(st.session_state, None)
_gd_full = gasto_contable_desglosado(st.session_state, None)
meses_universo = sorted(set(_ing_full or {}) | _gd_full["meses_cubiertos"])

if not meses_universo:
    st.warning("Ninguna de las fuentes trae meses legibles todavía.")
    st.stop()

with st.sidebar:
    st.markdown("### Filtros")
    meses_sel = render_periodo_filter("resfin", meses_universo)

if not meses_sel:
    st.warning("Selecciona al menos un mes.")
    st.stop()

# ── Datos del periodo seleccionado ────────────────────────────────────────────
ingresos_mes, _ = ingresos_confirmados_por_mes(st.session_state, meses_sel)
ingresos_mes = ingresos_mes or {}
gd = gasto_contable_desglosado(st.session_state, meses_sel)

meses_con_ingreso = set(ingresos_mes)
meses_con_gasto   = gd["meses_cubiertos"]
meses_comparables = sorted(meses_con_ingreso & meses_con_gasto)
meses_fuera        = sorted((meses_con_ingreso | meses_con_gasto) - set(meses_comparables))

_fuente_gasto_label = _FUENTE_GASTO_LABEL.get(gd["fuente"], SIN_DATO)
_cap = f"Ingresos: Reporte CFDI (neto de notas, sin IVA) · Gasto: {_fuente_gasto_label}."
if meses_fuera:
    _cap += (
        " Sin una de las dos fuentes, fuera del comparable: "
        + ", ".join(label_mes(m) for m in meses_fuera) + "."
    )
st.caption(_cap)

# Las cifras de "Resultado" se acotan SIEMPRE a los meses comparables — nunca
# el gasto de un mes que el CFDI no cubre, ni el ingreso de un mes sin gasto.
gasto_op_cmp = sum(gd["por_mes"].get(m, 0.0) for m in meses_comparables)
sin_clas_cmp = sum(gd["por_mes_sin_clasificar"].get(m, 0.0) for m in meses_comparables)
total_ing_cmp = sum(ingresos_mes[m] for m in meses_comparables)

if meses_comparables:
    piso, techo, exacto = resultado_rango(total_ing_cmp, gasto_op_cmp, sin_clas_cmp)
    indicativo = (not exacto) and sin_clas_cmp > gasto_op_cmp
else:
    piso = techo = None
    exacto = False
    indicativo = False

# ── Banner: gasto sin clasificar ──────────────────────────────────────────────
if sin_clas_cmp > 0:
    b1, b2 = st.columns([5, 1])
    with b1:
        st.warning(
            f"**{fmt_money(sin_clas_cmp)} sin clasificar** en cuentas contables del "
            "periodo comparable — el Resultado se muestra como RANGO mientras eso "
            "no se resuelva. Clasifica las cuentas para que colapse en un número exacto."
        )
    with b2:
        st.markdown("<div style='padding-top:.6rem'></div>", unsafe_allow_html=True)
        if st.button("Ir al catálogo →", key="resfin_btn_catalogo", use_container_width=True):
            st.session_state["_goto"] = "pages/6_Clasificaciones.py"
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN 1 — ¿Cómo nos fue este mes?
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("## ¿Cómo nos fue este mes?")

if not meses_comparables:
    st.info(
        "Ningún mes de la selección tiene ventas confirmadas y gasto operativo "
        "a la vez — no hay nada que mostrar en esta sección."
    )
else:
    _opciones_mes = {label_mes(m): m for m in meses_comparables}
    _labels_mes   = list(_opciones_mes.keys())
    _pick_lbl = st.selectbox(
        "Mes", _labels_mes, index=len(_labels_mes) - 1, key="resfin_mes_pick",
    )
    mes_foco = _opciones_mes[_pick_lbl]

    ing_m  = ingresos_mes[mes_foco]
    gop_m  = gd["por_mes"].get(mes_foco, 0.0)
    noop_m = gd["por_mes_no_operativo"].get(mes_foco, 0.0)
    sc_m   = gd["por_mes_sin_clasificar"].get(mes_foco, 0.0)
    piso_m, techo_m, exacto_m = resultado_rango(ing_m, gop_m, sc_m)
    margen_piso_m  = piso_m / ing_m * 100 if ing_m else None
    margen_techo_m = techo_m / ing_m * 100 if ing_m else None
    indicativo_m = (not exacto_m) and sc_m > gop_m

    _idx = meses_comparables.index(mes_foco)
    _delta = None
    if _idx > 0:
        _mes_prev = meses_comparables[_idx - 1]
        _piso_prev, _, _ = resultado_rango(
            ingresos_mes[_mes_prev], gd["por_mes"].get(_mes_prev, 0.0),
            gd["por_mes_sin_clasificar"].get(_mes_prev, 0.0),
        )
        if piso_m is not None and _piso_prev is not None:
            _delta = piso_m - _piso_prev

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.markdown(_kpi("Ingresos confirmados", fmt_money(ing_m), _GREEN,
                      fuente="Reporte CFDI"), unsafe_allow_html=True)
    k2.markdown(_kpi("Gasto operativo", fmt_money(gop_m), _RED,
                      fuente=_fuente_gasto_label), unsafe_allow_html=True)
    k3.markdown(_kpi_rango("Resultado", piso_m, techo_m, exacto_m, _BLUE, indicativo_m),
                unsafe_allow_html=True)
    k4.markdown(_kpi_rango_pct("Margen %", margen_piso_m, margen_techo_m, exacto_m, _BLUE, indicativo_m),
                unsafe_allow_html=True)
    k5.markdown(_kpi("Δ Resultado vs. mes anterior",
                      fmt_money(_delta) if _delta is not None else SIN_DATO,
                      _GREEN if (_delta or 0) >= 0 else _RED), unsafe_allow_html=True)

    st.caption("Las tres cifras del mes, juntas — un total sin su pendiente al lado es un número engañoso.")
    j1, j2, j3 = st.columns(3)
    j1.markdown(_kpi("Gasto operativo", fmt_money(gop_m), _BLUE), unsafe_allow_html=True)
    j2.markdown(_kpi("No operativo", fmt_money(noop_m), _GRAY), unsafe_allow_html=True)
    j3.markdown(_kpi("Sin clasificar", fmt_money(sc_m), _AMBER if sc_m > 0 else _GRAY),
                unsafe_allow_html=True)

    with st.container(border=True):
        _cuenta_mes = {
            row["Cuenta_Nombre"]: row["Monto_MXN"]
            for _, row in gd["por_cuenta_y_mes"][gd["por_cuenta_y_mes"]["_Mes"] == mes_foco].iterrows()
        }
        st.plotly_chart(
            plot_cascada_mes(ing_m, _cuenta_mes, piso_m, techo_m, _pick_lbl, sin_clasificar=sc_m),
            use_container_width=True,
        )
        st.caption(
            "Ingresos confirmados menos el gasto del mes, cuenta por cuenta. El paso "
            "ámbar (cuando aparece) es lo que todavía no se ha clasificado."
        )

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN 2 — ¿Cómo se ve nuestro año?
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("## ¿Cómo se ve nuestro año?")

if not meses_comparables:
    st.info("No hay meses comparables en la selección para esta sección.")
else:
    _margen_piso  = piso / total_ing_cmp * 100 if total_ing_cmp else None
    _margen_techo = techo / total_ing_cmp * 100 if total_ing_cmp else None

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.markdown(_kpi("Ingresos acumulados", fmt_money(total_ing_cmp), _GREEN),
                unsafe_allow_html=True)
    k2.markdown(_kpi("Gasto operativo acumulado", fmt_money(gasto_op_cmp), _RED,
                      fuente=_fuente_gasto_label), unsafe_allow_html=True)
    k3.markdown(_kpi_rango("Resultado acumulado", piso, techo, exacto, _BLUE, indicativo),
                unsafe_allow_html=True)
    k4.markdown(_kpi_rango_pct("Margen % acumulado", _margen_piso, _margen_techo, exacto, _BLUE, indicativo),
                unsafe_allow_html=True)
    k5.markdown(_kpi("Meses comparables", f"{len(meses_comparables)} de {len(meses_sel)}", _BLUE),
                unsafe_allow_html=True)

    resultado_por_mes = {}
    for _m in meses_comparables:
        _p, _, _ = resultado_rango(
            ingresos_mes[_m], gd["por_mes"].get(_m, 0.0), gd["por_mes_sin_clasificar"].get(_m, 0.0),
        )
        resultado_por_mes[_m] = _p

    with st.container(border=True):
        st.plotly_chart(plot_cascada_anual(resultado_por_mes, piso, techo), use_container_width=True)
        st.caption(
            "Un paso por mes: su Resultado, lado conservador del rango. Cierra en el "
            "acumulado del periodo comparable."
        )

    _df_fvg = pd.DataFrame({
        "_Mes": meses_comparables,
        "Facturado_MXN": [ingresos_mes[m] for m in meses_comparables],
        "Gasto_MXN": [gd["por_mes"].get(m, 0.0) for m in meses_comparables],
    })
    with st.container(border=True):
        st.plotly_chart(
            plot_facturado_vs_gasto(_df_fvg, mostrar_valores=True, color_gasto=_RED),
            use_container_width=True,
        )
        st.caption(
            "Ingresos confirmados contra gasto operativo, mes a mes, con el margen % "
            "sobre eje secundario."
        )

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN 3 — Evolución de ingresos
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("## Evolución de ingresos")

_df_cfdi_raw = st.session_state.get("df_cfdi")
if _df_cfdi_raw is None or len(_df_cfdi_raw) == 0:
    st.info("Sube el Reporte CFDI de Ventas (en Carga de Archivos) para ver esta sección.")
else:
    _d_ing = _df_cfdi_raw[~_df_cfdi_raw["Cancelado"]].copy()
    if meses_sel:
        _d_ing = _d_ing[_d_ing["_Mes"].isin(meses_sel)]

    if len(_d_ing) == 0:
        st.info("Sin facturas ni notas de crédito vigentes en los meses seleccionados.")
    else:
        _signo = _d_ing["Tipo_Doc"].map(lambda t: 1.0 if t == "Factura" else -1.0)
        _d_ing["Ingreso_Neto_MXN"] = _d_ing["Subtotal_MXN"] * _signo

        with st.container(border=True):
            st.plotly_chart(
                plot_barras_temporales(_d_ing, "Ingreso_Neto_MXN", "Ingresos confirmados por mes", _GREEN),
                use_container_width=True,
            )
            st.caption("Facturas no canceladas menos notas de crédito no canceladas, sin IVA.")

        _tabla_ing = (
            _d_ing.groupby([_d_ing["_Mes"], "Tipo_Doc"])["Subtotal_MXN"].sum()
            .unstack(fill_value=0.0)
        )
        for _col in ("Factura", "Nota Cred"):
            if _col not in _tabla_ing.columns:
                _tabla_ing[_col] = 0.0
        _tabla_ing["Neto"] = _tabla_ing["Factura"] - _tabla_ing["Nota Cred"]
        _tabla_ing = _tabla_ing.rename(
            columns={"Factura": "Facturas", "Nota Cred": "Notas de crédito"}
        )[["Facturas", "Notas de crédito", "Neto"]].reset_index()
        _tabla_ing["Mes"] = _tabla_ing["_Mes"].apply(label_mes)
        _tabla_ing = _tabla_ing[["Mes", "Facturas", "Notas de crédito", "Neto"]]

        with st.container(border=True):
            st.dataframe(
                _tabla_ing, use_container_width=True, hide_index=True,
                column_config={
                    "Facturas":          st.column_config.NumberColumn(format="$%,.0f"),
                    "Notas de crédito":  st.column_config.NumberColumn(format="$%,.0f"),
                    "Neto":              st.column_config.NumberColumn(format="$%,.0f"),
                },
                height=min(360, 45 + 36 * len(_tabla_ing)),
            )

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN 4 — Evolución de gastos por cuenta contable
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("## Evolución de gastos por cuenta contable")

if gd["fuente"] is None or len(gd["por_cuenta_y_mes"]) == 0:
    st.info("No hay gasto operativo clasificado en el periodo seleccionado.")
else:
    st.caption(f"Fuente: {_fuente_gasto_label}. Desglose por cuenta contable, no por categoría — "
               "es el único nivel que libro y balanza pueden dar los dos.")
    with st.container(border=True):
        st.plotly_chart(
            plot_barras_temporales(gd["por_cuenta_y_mes"], "Monto_MXN", "Gasto operativo por mes", _RED),
            use_container_width=True,
        )
        st.caption("Suma del gasto operativo ya clasificado, mes a mes.")

    with st.container(border=True):
        st.plotly_chart(plot_gasto_por_cuenta_mes(gd["por_cuenta_y_mes"]), use_container_width=True)
        st.caption("Top 6 cuentas de la ventana seleccionada + Otras cuentas, apiladas por mes.")

    _matriz = (
        gd["por_cuenta_y_mes"]
        .pivot_table(index="Cuenta_Nombre", columns="_Mes", values="Monto_MXN",
                     aggfunc="sum", fill_value=0.0)
    )
    _matriz.columns = [label_mes(m) for m in _matriz.columns]
    _matriz["TOTAL"] = _matriz.sum(axis=1)
    _matriz = _matriz.sort_values("TOTAL", ascending=False).reset_index()
    with st.container(border=True):
        st.markdown("##### Gasto por cuenta × mes")
        st.dataframe(
            _matriz, use_container_width=True, hide_index=True,
            column_config={
                c: st.column_config.NumberColumn(format="$%,.0f")
                for c in _matriz.columns if c != "Cuenta_Nombre"
            },
            height=min(600, 48 + 36 * len(_matriz)),
        )

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN 5 — Resumen mensual
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
with st.container(border=True):
    st.markdown("##### Resumen mensual")

    _filas = []
    for _m in sorted(meses_sel):
        _ing_v = ingresos_mes.get(_m)
        _cubre_gasto = _m in meses_con_gasto
        _gop_v = gd["por_mes"].get(_m, 0.0) if _cubre_gasto else None
        _sc_v  = gd["por_mes_sin_clasificar"].get(_m, 0.0) if _cubre_gasto else None
        if _ing_v is not None and _gop_v is not None:
            _p, _t, _ = resultado_rango(_ing_v, _gop_v, _sc_v or 0.0)
        else:
            _p = _t = None
        _filas.append({
            "Mes": label_mes(_m),
            "Ingresos": _ing_v,
            "Gasto operativo": _gop_v,
            "Sin clasificar": _sc_v,
            "Resultado (piso)": _p,
            "Resultado (techo)": _t,
        })
    _tabla_resumen = pd.DataFrame(_filas)
    _fila_total = pd.DataFrame([{
        "Mes": "TOTAL",
        "Ingresos": total_ing_cmp if meses_comparables else None,
        "Gasto operativo": gasto_op_cmp if meses_comparables else None,
        "Sin clasificar": sin_clas_cmp if meses_comparables else None,
        "Resultado (piso)": piso,
        "Resultado (techo)": techo,
    }])
    _tabla_resumen = pd.concat([_tabla_resumen, _fila_total], ignore_index=True)

    _cols_money = ["Ingresos", "Gasto operativo", "Sin clasificar",
                   "Resultado (piso)", "Resultado (techo)"]
    _fmt = {c: (lambda v: fmt_money(v)) for c in _cols_money}
    try:
        _styled = _tabla_resumen.style.map(
            _color_resultado, subset=["Resultado (piso)", "Resultado (techo)"]
        ).format(_fmt)
    except AttributeError:
        _styled = _tabla_resumen.style.applymap(
            _color_resultado, subset=["Resultado (piso)", "Resultado (techo)"]
        ).format(_fmt)

    st.dataframe(
        _styled, use_container_width=True, hide_index=True,
        height=min(600, 52 + 36 * len(_tabla_resumen)),
    )
