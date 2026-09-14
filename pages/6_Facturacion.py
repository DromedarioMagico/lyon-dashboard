import datetime as dt

import pandas as pd
import streamlit as st

from core.catalogos import COLOR_LYON, COLOR_GASTOS_EMPRESA
from core.conciliacion import (
    contabilidad_de_sesion, resumen_conciliacion, NAT_GASTO,
)
from core.database import init_db
from core.etl_facturacion import cargar_facturacion
from core.navigation import (
    render_sidebar_search, render_sidebar_status, inject_custom_css,
    handle_pending_nav, render_periodo_filter,
)
from core.plots import (
    plot_facturacion_segmento, plot_fugas_cliente, plot_aging_remisiones,
    plot_waterfall_margen, plot_facturado_vs_gasto,
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


# ── _kpi local (copiado, mismo patrón que el resto de páginas) ────────────────
def _kpi(label, value, color, desc=None):
    info = ""
    if desc:
        info = (
            f"<details style='display:inline-block;margin-left:5px;vertical-align:middle;'>"
            f"<summary style='cursor:pointer;color:#9CA3AF;font-size:.78rem;"
            f"list-style:none;outline:none;user-select:none;'>ⓘ</summary>"
            f"<div style='margin-top:6px;padding:8px 10px;background:#F9FAFB;"
            f"border:1px solid #E5E7EB;border-radius:6px;font-size:.75rem;"
            f"color:#374151;font-weight:400;text-transform:none;letter-spacing:0;"
            f"line-height:1.5;white-space:normal;'>{desc}</div></details>"
        )
    return f"""
    <div style="background:#fff;border:1px solid #E1E7EC;border-radius:10px;
                padding:1rem 1.25rem;box-shadow:0 1px 4px rgba(0,0,0,.05);">
      <p style="margin:0 0 4px;font-size:.72rem;font-weight:600;color:#6B7280;
                text-transform:uppercase;letter-spacing:.5px;">{label}{info}</p>
      <p style="margin:0;font-size:1.65rem;font-weight:700;color:{color};
                line-height:1.2;">{value}</p>
    </div>"""


_GREEN = "#548235"
_AMBER = "#E97132"
_RED   = "#C00000"
_GRAY  = "#9E9E9E"


# ── Upload ────────────────────────────────────────────────────────────────────
if "df_facturacion" not in st.session_state:
    st.markdown(
        "Sube **`Facturación <MES> 2026 - LYON.xlsx`** (el archivo que ya genera "
        "Contabilidad, sin modificar)."
    )
    up = st.file_uploader(
        "Archivo de facturación", type=["xlsx", "xlsm"], label_visibility="collapsed",
    )
    if up:
        with st.spinner("Procesando archivo…"):
            try:
                data, warns = cargar_facturacion(up)
                st.session_state.df_facturacion = data
                st.session_state.df_facturacion_meta = {
                    "archivo":     up.name,
                    "uploaded_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "periodo":     str(data["periodo"]) if data["periodo"] else "—",
                }
                for w in warns:
                    st.warning(w)
                st.success(
                    f"✅ {len(data['facturas'])} facturas cargadas · "
                    f"periodo {data['periodo']}."
                )
                st.rerun()
            except ValueError as e:
                st.error(f"Error al procesar el archivo:\n\n{e}")
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

# ── Gasto contable del mismo periodo ──────────────────────────────────────────
# Solo cuentas marcadas como gasto operativo: los movimientos de balance
# (anticipos) inflarían el costo y distorsionarían el margen.
_conc = contabilidad_de_sesion()

gasto_periodo    = 0.0
gasto_por_cuenta = {}
res_ctb          = None
if _conc is not None:
    res_ctb = resumen_conciliacion(_conc)
    _op = _conc[_conc["Naturaleza"] == NAT_GASTO]
    if periodo is not None:
        _op = _op[_op["_Mes"] == periodo]
    gasto_periodo = float(_op["Monto_MXN"].sum())
    gasto_por_cuenta = (
        _op.groupby("Cuenta_Nombre")["Monto_MXN"].sum()
        .sort_values(ascending=False).to_dict()
    )

margen     = facturado_periodo - gasto_periodo
margen_pct = margen / facturado_periodo * 100 if facturado_periodo else 0.0


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
    if gasto_periodo > 0:
        st.markdown(_kpi("Gasto contable", f"${gasto_periodo/1e6:,.2f}M",
                         COLOR_GASTOS_EMPRESA,
                         desc="Movimientos del libro contable de este mes en cuentas "
                              "marcadas como gasto operativo. Los anticipos y "
                              "movimientos de balance no cuentan."),
                    unsafe_allow_html=True)
    else:
        st.markdown(_kpi("Gasto contable", "— sin contabilidad —", _GRAY,
                         desc="Sube la base de Contabilidad en Gastos de Empresa y "
                              "clasifica las cuentas para ver el margen del periodo."),
                    unsafe_allow_html=True)
with k3:
    st.markdown(_kpi("Margen del periodo",
                     f"${margen/1e6:,.2f}M" if gasto_periodo > 0 else "—",
                     _GREEN if margen >= 0 else _RED,
                     desc="Facturado menos gasto contable del mismo mes."),
                unsafe_allow_html=True)
with k4:
    st.markdown(_kpi("Margen %",
                     f"{margen_pct:.1f}%" if gasto_periodo > 0 else "—",
                     _GREEN if margen >= 0 else _RED,
                     desc="Margen sobre facturación. Es el número que dice si el mes "
                          "se sostiene solo."),
                unsafe_allow_html=True)

if res_ctb and res_ctb["n_cuentas_sin_clasificar"]:
    st.warning(
        f"**{res_ctb['n_cuentas_sin_clasificar']} cuenta(s) contable(s) sin clasificar** "
        f"(${res_ctb['sin_clasificar']/1e6:,.2f}M en el libro completo) todavía no "
        f"cuentan como gasto, así que el margen de arriba está incompleto. "
        f"Clasifícalas en **Clasificaciones → Cuentas contables**."
    )

with st.container(border=True):
    if gasto_periodo > 0:
        st.plotly_chart(
            plot_waterfall_margen(facturado_periodo, gasto_por_cuenta, margen),
            use_container_width=True,
        )
        st.caption(
            f"De **${facturado_periodo/1e6:,.2f}M** facturados quedan "
            f"**${margen/1e6:,.2f}M** ({margen_pct:.1f}%) después del gasto que "
            f"reportó Contabilidad para {meta['periodo']}."
        )
    else:
        st.info(
            "Sube la base de Contabilidad en **Gastos de Empresa** y clasifica las "
            "cuentas para ver aquí de dónde se va el ingreso del mes."
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
    "Cada cuenta contable como porcentaje de lo que se facturó en el mes. Convierte "
    "el gasto en una medida comparable entre meses buenos y malos: $2M de "
    "mantenimiento pesa distinto en un mes de $9M que en uno de $6M."
)

with st.container(border=True):
    if gasto_periodo > 0:
        peso = pd.DataFrame(
            [
                {
                    "Cuenta": nombre,
                    "Monto": monto,
                    "% de lo facturado": (
                        monto / facturado_periodo * 100 if facturado_periodo else 0.0
                    ),
                }
                for nombre, monto in gasto_por_cuenta.items()
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
            f"**{gasto_periodo/facturado_periodo*100:.1f}%** de lo facturado."
            if facturado_periodo else ""
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


# ── Reset ─────────────────────────────────────────────────────────────────────
st.divider()
if st.button("🗑 Cargar otro archivo de facturación"):
    for k in ("df_facturacion", "df_facturacion_meta"):
        st.session_state.pop(k, None)
    st.rerun()
