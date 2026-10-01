import pandas as pd
import streamlit as st

from core.catalogos import COLOR_LYON, COLOR_GASTOS_EMPRESA
from core.conciliacion import (
    contabilidad_de_sesion, resumen_conciliacion, NAT_GASTO,
)
from core.database import init_db
from core.fuentes import (
    kpi_card as _kpi, fmt_money, fmt_pct, gasto_operativo_contable,
)
from core.navigation import (
    render_sidebar_search, render_sidebar_status, inject_custom_css,
    handle_pending_nav, render_periodo_filter,
)
from core.plots import (
    plot_facturacion_segmento, plot_fugas_cliente, plot_aging_remisiones,
    plot_waterfall_margen, plot_facturado_vs_gasto,
    plot_pareto_clientes_ventas, plot_barras_temporales, plot_cobranza_mix,
)

st.set_page_config(
    page_title="Facturación — Lyon AG",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_db()
inject_custom_css()
handle_pending_nav()

with st.sidebar:
    render_sidebar_search()
    render_sidebar_status()

st.markdown(
    f"<h1 style='color:{COLOR_LYON}'>"
    "<span class='material-symbols-outlined'>request_quote</span>Facturación</h1>",
    unsafe_allow_html=True,
)
st.caption(
    "El resultado real del mes: qué se facturó, cuánto costó según Contabilidad, "
    "dónde se fugó valor en devoluciones y descuentos, y qué falta por facturar."
)


_GREEN = "#548235"
_AMBER = "#E97132"
_RED   = "#C00000"
_GRAY  = "#9E9E9E"


# ── Gate: sin Facturación no hay nada que mostrar aquí ────────────────────────
if "df_facturacion" not in st.session_state:
    st.info(
        "Todavía no has cargado ningún archivo mensual de Facturación en esta "
        "sesión. Súbelo en **Carga de Archivos** (puedes subir varios meses de "
        "un jalón)."
    )
    if st.button("Ir a Carga de Archivos", type="primary"):
        st.switch_page("app.py")
    st.stop()


# ── Dashboard ─────────────────────────────────────────────────────────────────
fac  = st.session_state.df_facturacion
meta = st.session_state.df_facturacion_meta

df_fact = fac["facturas"]
df_hist = fac["historico"]
df_dev  = fac["dev_desc"]
df_rem  = fac["remisiones"]
df_res  = fac["resumen"]
periodo = fac["periodo"]

st.caption(
    f"Archivo: **{meta['archivo']}**  ·  periodo **{meta['periodo']}**  ·  "
    f"cargado {meta['uploaded_at']}"
)
st.info(
    "**Regla de lectura:** esta página muestra **facturas sin IVA** (ingreso real "
    "del mes) contra el **gasto que reportó Contabilidad** para ese mismo mes. No "
    "habla de pedidos: el pedido es una etapa anterior y vive en Ventas."
)

facturado_periodo = float(df_fact["Subtotal_MXN"].sum())
pendiente_periodo = float(df_rem["Subtotal_MXN"].sum())

# ── Gasto operativo contable del mismo periodo ────────────────────────────────
# Esta es una de las DOS medidas de "gasto" que trae la app (ver core/fuentes.py):
# todo el gasto operativo del periodo, venga del libro o, si el libro no cubre
# el mes completo, de la balanza — nunca se mezclan las dos fuentes dentro de
# la misma cifra, y se declara de dónde salió.
_conc   = contabilidad_de_sesion()
res_ctb = resumen_conciliacion(_conc) if _conc is not None else None

_meses_periodo = [periodo] if periodo is not None else None
gasto_operativo_ctb, _fuente_gasto = gasto_operativo_contable(
    st.session_state, _meses_periodo,
)

# El desglose por categoría (para el waterfall y la tabla de "peso") solo existe
# cuando la cifra viene del libro — la balanza no trae detalle de proveedor ni
# categoría, solo el total por cuenta mayor.
gasto_por_categoria = {}
if _fuente_gasto == "libro" and _conc is not None:
    _op = _conc[_conc["Naturaleza"] == NAT_GASTO]
    if periodo is not None:
        _op = _op[_op["_Mes"] == periodo]
    # Por Categoría, no por cuenta: es el bucket que el usuario arma a propósito
    # ("Nómina" agrupa una o varias cuentas) — agrupar por cuenta individual
    # dejaría esa clasificación sin reflejo en la gráfica.
    gasto_por_categoria = (
        _op.groupby("Categoria")["Monto_MXN"].sum()
        .sort_values(ascending=False).to_dict()
    )

margen = (
    facturado_periodo - gasto_operativo_ctb
    if gasto_operativo_ctb is not None else None
)
margen_pct = (
    (margen / facturado_periodo * 100 if facturado_periodo else 0.0)
    if margen is not None else None
)


# ════════════════════════════════════════════════════════════════════════════════
#  1 — Facturado vs gasto reportado por contabilidad
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("### Resultado del periodo")
st.caption(
    "Lo que realmente se facturó contra lo que realmente costó, según Contabilidad. "
    "Es la fotografía del mes: cuánto entró, cuánto salió y qué quedó."
)

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(_kpi("Facturado (sin IVA)", f"${facturado_periodo/1e6:,.2f}M", _GREEN,
                     desc="Suma del subtotal de las facturas del mes. Coincide al peso con "
                          "la columna del mes en la hoja HISTORICO."),
                unsafe_allow_html=True)
with k2:
    st.markdown(_kpi(
        "Gasto operativo contable", fmt_money(gasto_operativo_ctb),
        COLOR_GASTOS_EMPRESA if gasto_operativo_ctb is not None else _GRAY,
        desc="Todo el gasto operativo que reportó Contabilidad para este mes. "
             "Sale del libro de movimientos cuando lo cubre completo; si no, de "
             "la balanza completa del mes — nunca se mezclan las dos fuentes "
             "dentro de la misma cifra.",
        fuente=f"Fuente: {_fuente_gasto}" if _fuente_gasto else "Sin contabilidad cargada",
    ), unsafe_allow_html=True)
with k3:
    st.markdown(_kpi(
        "Margen del periodo", fmt_money(margen),
        _GREEN if (margen or 0) >= 0 else _RED,
        desc="Facturado menos gasto operativo contable del mismo mes.",
    ), unsafe_allow_html=True)
with k4:
    st.markdown(_kpi(
        "Margen %", fmt_pct(margen_pct),
        _GREEN if (margen or 0) >= 0 else _RED,
        desc="Margen sobre facturación. Es el número que dice si el mes "
             "se sostiene solo.",
    ), unsafe_allow_html=True)

if res_ctb and res_ctb["n_cuentas_sin_clasificar"]:
    st.warning(
        f"**{res_ctb['n_cuentas_sin_clasificar']} cuenta(s) contable(s) sin clasificar** "
        f"(${res_ctb['sin_clasificar']/1e6:,.2f}M en el libro completo) todavía no "
        f"cuentan como gasto, así que el margen de arriba está incompleto. "
        f"Clasifícalas en **Clasificaciones → Cuentas contables**."
    )

with st.container(border=True):
    if gasto_por_categoria:
        st.plotly_chart(
            plot_waterfall_margen(facturado_periodo, gasto_por_categoria, margen),
            use_container_width=True,
        )
        # Los "$" van escapados a propósito: con dos signos de peso sin escapar
        # en el mismo bloque de markdown, Streamlit los toma como delimitadores
        # de LaTeX y renderiza como fórmula todo lo que hay entre ellos —
        # incluidos los **negritas** y los espacios (bug real, visto en
        # producción: "9.42M**facturadosquedan**3.08M" en cursiva de fórmula).
        st.caption(
            f"De **\\${facturado_periodo/1e6:,.2f}M** facturados quedan "
            f"**\\${margen/1e6:,.2f}M** ({margen_pct:.1f}%) después del gasto que "
            f"reportó Contabilidad para {meta['periodo']}."
        )
    elif gasto_operativo_ctb is not None:
        st.info(
            f"El gasto operativo contable de este mes viene de la balanza "
            f"({fmt_money(gasto_operativo_ctb)}), que no trae detalle por "
            f"categoría — solo el libro de movimientos lo tiene."
        )
    else:
        st.info(
            "Sube la base de Contabilidad en **Carga de Archivos** y clasifica las "
            "cuentas en **Clasificaciones** para ver aquí de dónde se va el ingreso "
            "del mes."
        )


# ════════════════════════════════════════════════════════════════════════════════
#  2 — Facturación por segmento
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("### Facturación por segmento")
st.caption(
    "PRIVADA / FILIAL / GOBIERNO — una lente que la app no tiene. DELMAN, por "
    "ejemplo, hoy está enterrado como un cliente más dentro de Ventas y es todo FILIAL."
)

meses_hist = sorted(df_hist["_Mes"].unique()) if not df_hist.empty else []
with st.sidebar:
    st.markdown("### Filtro de segmento (bloque 2)")
    meses_sel = render_periodo_filter("fac", meses_hist)

with st.container(border=True):
    st.plotly_chart(
        plot_facturacion_segmento(df_hist, meses_sel or None),
        use_container_width=True,
    )
    if not df_hist.empty:
        _d = df_hist[df_hist["_Mes"].isin(meses_sel)] if meses_sel else df_hist
        resumen_seg = (
            _d.groupby("Segmento_Corto", as_index=False)["Subtotal_MXN"].sum()
              .sort_values("Subtotal_MXN", ascending=False)
              .rename(columns={"Segmento_Corto": "Segmento", "Subtotal_MXN": "Facturado sin IVA"})
        )
        st.dataframe(
            resumen_seg, use_container_width=True, hide_index=True,
            column_config={
                "Facturado sin IVA": st.column_config.NumberColumn(format="$%,.0f"),
            },
        )


# ════════════════════════════════════════════════════════════════════════════════
#  3 — Fugas: penalizaciones y descuentos
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("### Fugas del periodo")
st.caption(
    "Penalizaciones y descuentos: ocurren después del pedido y antes de la factura. "
    "Ni el SAE ni el análisis de absorción los registran. CONALITEG va a tasa 0 %."
)

with st.container(border=True):
    st.plotly_chart(plot_fugas_cliente(df_dev), use_container_width=True)
    if not df_dev.empty:
        tabla_dev = (
            df_dev[["Cliente_Display", "Tipo", "Subtotal_MXN", "Tasa_Cero"]]
            .rename(columns={
                "Cliente_Display": "Cliente", "Subtotal_MXN": "Monto sin IVA",
                "Tasa_Cero": "Tasa 0 %",
            })
            .sort_values("Monto sin IVA", ascending=False)
        )
        st.dataframe(
            tabla_dev, use_container_width=True, hide_index=True,
            column_config={"Monto sin IVA": st.column_config.NumberColumn(format="$%,.0f")},
        )

# El archivo mensual manual solo ve las fugas del mes cargado. Si además hay un
# reporte CFDI de Notas de Crédito, se agrega la vista del año completo — con
# algo que el archivo manual no trae: el estatus de cancelación.
_df_cfdi = st.session_state.get("df_cfdi")
if _df_cfdi is not None:
    _notas = _df_cfdi[_df_cfdi["Tipo_Doc"] == "Nota Cred"]
    if len(_notas):
        with st.container(border=True):
            st.markdown("#### Notas de crédito — año completo")
            _canceladas = _notas[_notas["Cancelado"]]
            st.caption(
                f"**{len(_notas)}** nota(s) de crédito en el año, de las cuales "
                f"**{len(_canceladas)}** están **canceladas** y no deberían restar "
                f"al neto — el archivo mensual manual no distingue esto."
            )
            _tabla_nc = (
                _notas[["Fecha", "Cliente_Display", "Subtotal_MXN", "Cancelado"]]
                .sort_values("Subtotal_MXN", ascending=False)
                .rename(columns={
                    "Cliente_Display": "Cliente", "Subtotal_MXN": "Monto sin IVA",
                })
            )
            st.dataframe(
                _tabla_nc, use_container_width=True, hide_index=True,
                column_config={
                    "Monto sin IVA": st.column_config.NumberColumn(format="$%,.0f"),
                    "Fecha": st.column_config.DateColumn(format="DD-MMM-YYYY"),
                },
            )
            _vig = float(_notas.loc[~_notas["Cancelado"], "Subtotal_MXN"].sum())
            _can = float(_canceladas["Subtotal_MXN"].sum())
            st.caption(
                f"Vigentes: **${_vig/1e6:,.2f}M** · Canceladas (no restan): "
                f"**${_can/1e6:,.2f}M**"
            )


# ════════════════════════════════════════════════════════════════════════════════
#  4 — Pendiente por facturar (aging + anomalías)
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("### Pendiente por facturar")
st.caption(
    "Remisiones entregadas sin factura, por antigüedad. Se marca lo que cae fuera "
    "del mes del archivo (fechas adelantadas o rezagadas) y lo etiquetado *** REVISAR ***."
)

with st.container(border=True):
    st.plotly_chart(plot_aging_remisiones(df_rem), use_container_width=True)
    _flag = df_rem[df_rem["Fuera_De_Mes"] | df_rem["Revisar"]]
    if len(_flag):
        st.markdown("**Remisiones a revisar**")
        tabla_flag = _flag.assign(
            Fecha=_flag["Fecha"].dt.strftime("%d-%b-%Y"),
            Marca=_flag.apply(
                lambda r: " · ".join(
                    ([f"fuera de mes ({r['_Mes']})"] if r["Fuera_De_Mes"] else [])
                    + (["*** REVISAR ***"] if r["Revisar"] else [])
                ), axis=1,
            ),
        )[["Fecha", "Remision", "Cliente_Display", "Subtotal_MXN", "Marca"]].rename(
            columns={"Remision": "Remisión", "Cliente_Display": "Cliente",
                     "Subtotal_MXN": "Monto sin IVA"}
        )
        st.dataframe(
            tabla_flag, use_container_width=True, hide_index=True,
            column_config={"Monto sin IVA": st.column_config.NumberColumn(format="$%,.0f")},
        )


# ════════════════════════════════════════════════════════════════════════════════
#  5 — Peso del gasto contable sobre la facturación
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("### Peso del gasto contable sobre la facturación")
st.caption(
    "Cada categoría de gasto (agrupando sus cuentas contables) como porcentaje de "
    "lo que se facturó en el mes. Convierte el gasto en una medida comparable "
    "entre meses buenos y malos: \\$2M de mantenimiento pesa distinto en un mes de "
    "\\$9M que en uno de \\$6M."
)

with st.container(border=True):
    if gasto_por_categoria:
        peso = pd.DataFrame(
            [
                {
                    "Categoría": nombre,
                    "Monto": monto,
                    "% de lo facturado": (
                        monto / facturado_periodo * 100 if facturado_periodo else 0.0
                    ),
                }
                for nombre, monto in gasto_por_categoria.items()
            ]
        )
        st.dataframe(
            peso, use_container_width=True, hide_index=True,
            column_config={
                "Monto": st.column_config.NumberColumn(format="$%,.0f"),
                "% de lo facturado": st.column_config.NumberColumn(format="%.1f%%"),
            },
            height=min(480, 45 + 36 * min(len(peso), 11)),
        )
        st.caption(
            f"El gasto contable del mes equivale al "
            f"**{gasto_operativo_ctb/facturado_periodo*100:.1f}%** de lo facturado."
            if facturado_periodo else ""
        )
    elif gasto_operativo_ctb is not None:
        st.info(
            "El gasto de este mes viene de la balanza, que no trae detalle por "
            "categoría para desglosar este peso."
        )
    else:
        st.info(
            "Sin base de Contabilidad cargada no hay gasto que comparar contra la "
            "facturación."
        )

# ── Evolución mes a mes: ingreso vs gasto ────────────────────────────────────
if _conc is not None and len(df_hist) > 0:
    _gasto_mes = (
        _conc[_conc["Naturaleza"] == NAT_GASTO]
        .groupby("_Mes")["Monto_MXN"].sum().rename("Gasto_MXN")
    )
    _fact_mes = df_hist.groupby("_Mes")["Subtotal_MXN"].sum().rename("Facturado_MXN")
    comp = pd.concat([_fact_mes, _gasto_mes], axis=1).dropna().reset_index()

    if len(comp) > 1:
        with st.container(border=True):
            st.caption(
                "Los meses donde hay tanto facturación como gasto contable clasificado. "
                "La línea de margen es la que hay que ver: un mes puede facturar más y "
                "dejar menos."
            )
            st.plotly_chart(plot_facturado_vs_gasto(comp), use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════════
#  6 — El año facturado (reporte CFDI de Contabilidad — condicional)
# ════════════════════════════════════════════════════════════════════════════════
# A diferencia de los bloques 1-5 (que vienen del archivo mensual hecho a mano y
# solo ven un mes a la vez), esto sale del reporte CFDI del SAT que se sube en
# Carga de Archivos: cubre el año completo y sabe qué se canceló.
if _df_cfdi is not None:
    st.divider()
    st.markdown("### El año facturado")
    st.caption(
        "Del reporte CFDI que te manda Contabilidad — cubre el año completo, no "
        "solo el mes cargado arriba, y distingue lo que se **canceló**."
    )

    _facturas_anio = _df_cfdi[_df_cfdi["Tipo_Doc"] == "Factura"]
    _canc_anio     = _facturas_anio[_facturas_anio["Cancelado"]]
    _notas_anio    = _df_cfdi[_df_cfdi["Tipo_Doc"] == "Nota Cred"]
    _notas_vig     = _notas_anio[~_notas_anio["Cancelado"]]

    _emitido = float(_facturas_anio["Subtotal_MXN"].sum())
    _cancel  = float(_canc_anio["Subtotal_MXN"].sum())
    _nc_vig  = float(_notas_vig["Subtotal_MXN"].sum())
    _real    = _emitido - _cancel - _nc_vig

    _meta_cfdi = st.session_state.get("df_cfdi_meta", {})
    st.caption(
        f"**{len(_facturas_anio):,}** factura(s) · periodo {_meta_cfdi.get('periodos', '—')} "
        f"· {_meta_cfdi.get('archivo', '—')}"
    )

    a1, a2, a3, a4 = st.columns(4)
    a1.markdown(_kpi(
        "Facturado emitido", f"${_emitido/1e6:,.2f}M", COLOR_LYON,
        desc="Todo lo timbrado en el año, sin IVA — incluye lo cancelado.",
    ), unsafe_allow_html=True)
    a2.markdown(_kpi(
        "Cancelado", f"${_cancel/1e6:,.2f}M", _RED,
        desc=f"{len(_canc_anio)} de {len(_facturas_anio)} facturas se cancelaron.",
    ), unsafe_allow_html=True)
    a3.markdown(_kpi(
        "Notas de crédito", f"${_nc_vig/1e6:,.2f}M", _AMBER,
        desc="Devoluciones y descuentos del año, vigentes (sin las canceladas).",
    ), unsafe_allow_html=True)
    a4.markdown(_kpi(
        "Facturado real", f"${_real/1e6:,.2f}M", _GREEN,
        desc="Emitido menos cancelado menos notas de crédito vigentes — el "
             "neto real del año.",
    ), unsafe_allow_html=True)

    _vigentes_anio = _facturas_anio[~_facturas_anio["Cancelado"]]

    with st.container(border=True):
        st.plotly_chart(
            plot_barras_temporales(
                _vigentes_anio, "Subtotal_MXN",
                "Facturación por mes — año completo", _GREEN,
            ),
            use_container_width=True,
        )

    with st.container(border=True):
        st.caption(
            "Top clientes del año por lo facturado (vigente, sin cancelaciones)."
        )
        # Se reutiliza el Pareto de Ventas tal cual: solo se alias Subtotal_MXN
        # (sin IVA, consistente con el resto de esta página) al nombre de
        # columna que la función ya espera.
        _d_pareto = _vigentes_anio.assign(Importe_MXN=_vigentes_anio["Subtotal_MXN"])
        st.plotly_chart(
            plot_pareto_clientes_ventas(
                _d_pareto, float(_d_pareto["Importe_MXN"].sum()), top_n=10,
            ),
            use_container_width=True,
        )

    # ── Cómo se cobra ──────────────────────────────────────────────────────────
    st.markdown("#### Cómo se cobra")
    st.caption(
        "PPD = a crédito (pago en parcialidades o diferido); PUE = de contado. "
        "Una mezcla mayoritaria de PPD es una señal de flujo de efectivo que hoy "
        "no aparece en ningún otro lado de la app."
    )
    with st.container(border=True):
        st.plotly_chart(plot_cobranza_mix(_df_cfdi), use_container_width=True)

