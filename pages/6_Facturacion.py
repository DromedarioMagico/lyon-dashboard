import datetime as dt

import streamlit as st

from core.catalogos import COLOR_LYON
from core.database import init_db
from core.etl_facturacion import cargar_facturacion
from core.navigation import (
    render_sidebar_search, render_sidebar_status, inject_custom_css,
    handle_pending_nav, render_periodo_filter,
)
from core.plots import (
    plot_embudo_facturacion, plot_facturacion_segmento, plot_fugas_cliente,
    plot_aging_remisiones, plot_pedido_vs_facturado,
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
    "El tramo **pedido → factura**. Continuación del embudo de Ventas: qué se "
    "facturó, qué quedó pendiente y dónde se fugó valor entre el pedido y el "
    "documento."
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
    "**Regla de lectura:** Ventas muestra **pedidos con IVA**; esta página muestra "
    "**facturas sin IVA**. Son dos etapas distintas, no dos versiones del mismo número. "
    "El embudo lleva los pedidos a base sin IVA para que sea comparable."
)

# Datos del SAE (si Ventas está cargado) — para el embudo y el cruce por cliente
tiene_ventas = "df_ventas" in st.session_state
df_ventas    = st.session_state.get("df_ventas")

facturado_periodo = float(df_fact["Subtotal_MXN"].sum())
pendiente_periodo = float(df_rem["Subtotal_MXN"].sum())

pedidos_periodo = None
if tiene_ventas and periodo is not None:
    _pv = df_ventas[df_ventas["_Mes"] == periodo]
    if len(_pv):
        pedidos_periodo = float(_pv["Subtotal_MXN"].sum())


# ════════════════════════════════════════════════════════════════════════════════
#  1 — Embudo del periodo
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("### Embudo del periodo")
st.caption(
    "Del pedido al documento fiscal. La conversión pedido → factura es un KPI que "
    "hoy no existe: mide cuánto de lo vendido efectivamente se facturó en el mes."
)

k1, k2, k3 = st.columns(3)
with k1:
    if pedidos_periodo is not None:
        st.markdown(_kpi("Pedidos SAE (sin IVA)", f"${pedidos_periodo/1e6:,.2f}M", COLOR_LYON,
                         desc="Subtotal de pedidos del SAE en el mes del archivo. Base "
                              "sin IVA para comparar contra facturación."),
                    unsafe_allow_html=True)
    else:
        st.markdown(_kpi("Pedidos SAE (sin IVA)", "— sin Ventas —", "#9E9E9E",
                         desc="Carga el archivo de Ventas (Pedidos SAE) para ver esta cifra "
                              "y la conversión pedido → factura."),
                    unsafe_allow_html=True)
with k2:
    st.markdown(_kpi("Facturado (sin IVA)", f"${facturado_periodo/1e6:,.2f}M", _GREEN,
                     desc="Suma del subtotal de las facturas del mes. Coincide al peso con "
                          "la columna del mes en la hoja HISTORICO."),
                unsafe_allow_html=True)
with k3:
    st.markdown(_kpi("Pendiente por facturar", f"${pendiente_periodo/1e6:,.2f}M", _AMBER,
                     desc="Remisiones entregadas y aún sin factura (hoja "
                          "REMISIONES PTES FACTURAR), subtotal sin IVA."),
                unsafe_allow_html=True)

with st.container(border=True):
    st.plotly_chart(
        plot_embudo_facturacion(pedidos_periodo, facturado_periodo, pendiente_periodo),
        use_container_width=True,
    )
    if pedidos_periodo is not None:
        conv = facturado_periodo / pedidos_periodo * 100 if pedidos_periodo else 0
        st.caption(
            f"Conversión pedido → factura del periodo: **{conv:.1f}%**. "
            f"Brecha (pedido no facturado en el mes): "
            f"**${(pedidos_periodo - facturado_periodo)/1e6:,.2f}M**."
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
#  5 — Cliente: pedido vs facturado
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("### Cliente: pedido vs facturado")
st.caption(
    "Cruce por **código numérico de cliente** — la llave que sí coincide entre "
    "facturación y el SAE (18 = DELMAN, 270 = GD BAJIO, 287 = PENGUIN…). "
    "La brecha por cliente es pedido no facturado en el periodo."
)

with st.container(border=True):
    fact_cli = (
        df_fact.groupby("Cliente_Codigo", as_index=False)
               .agg(Facturado_MXN=("Subtotal_MXN", "sum"),
                    Cliente=("Cliente_Display", "first"))
    )

    if tiene_ventas and periodo is not None and "Cliente_Codigo" in df_ventas.columns:
        ped_cli = (
            df_ventas[df_ventas["_Mes"] == periodo]
            .groupby("Cliente_Codigo", as_index=False)
            .agg(Pedido_MXN=("Subtotal_MXN", "sum"),
                 Cliente_SAE=("Cliente_Display", "first"))
        )
        cross = fact_cli.merge(ped_cli, on="Cliente_Codigo", how="outer")
        cross["Cliente"] = cross["Cliente"].fillna(cross["Cliente_SAE"]).fillna(
            cross["Cliente_Codigo"].astype("string")
        )
        cross["Facturado_MXN"] = cross["Facturado_MXN"].fillna(0.0)
        cross["Pedido_MXN"]    = cross["Pedido_MXN"].fillna(0.0)
        cross["Brecha_MXN"]    = cross["Pedido_MXN"] - cross["Facturado_MXN"]
        cross = cross.sort_values("Pedido_MXN", ascending=False)

        st.plotly_chart(
            plot_pedido_vs_facturado(cross[["Cliente", "Pedido_MXN", "Facturado_MXN"]]),
            use_container_width=True,
        )
        tabla_cross = cross[[
            "Cliente_Codigo", "Cliente", "Pedido_MXN", "Facturado_MXN", "Brecha_MXN",
        ]].rename(columns={
            "Cliente_Codigo": "Código", "Pedido_MXN": "Pedido (sin IVA)",
            "Facturado_MXN": "Facturado (sin IVA)", "Brecha_MXN": "Brecha",
        })
        st.dataframe(
            tabla_cross, use_container_width=True, hide_index=True,
            column_config={
                "Pedido (sin IVA)":    st.column_config.NumberColumn(format="$%,.0f"),
                "Facturado (sin IVA)": st.column_config.NumberColumn(format="$%,.0f"),
                "Brecha":              st.column_config.NumberColumn(format="$%,.0f"),
            },
        )
    else:
        st.warning(
            "Carga el archivo de **Ventas** (Pedidos SAE) para cruzar pedido vs "
            "facturado por cliente. Mientras tanto, sólo se muestra lo facturado:"
        )
        st.dataframe(
            fact_cli[["Cliente_Codigo", "Cliente", "Facturado_MXN"]].rename(columns={
                "Cliente_Codigo": "Código", "Facturado_MXN": "Facturado (sin IVA)",
            }).sort_values("Facturado (sin IVA)", ascending=False),
            use_container_width=True, hide_index=True,
            column_config={
                "Facturado (sin IVA)": st.column_config.NumberColumn(format="$%,.0f"),
            },
        )


# ── Reset ─────────────────────────────────────────────────────────────────────
st.divider()
if st.button("🗑 Cargar otro archivo de facturación"):
    for k in ("df_facturacion", "df_facturacion_meta"):
        st.session_state.pop(k, None)
    st.rerun()
