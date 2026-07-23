import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from core.catalogos import (
    COLOR_LYON, COLOR_VENTAS, PALETA_CATEGORIAS, ETIQ_PENDIENTE,
    CATALOGO_CATEGORIAS, label_mes,
)
from core.database import init_db
from core.etl_compras import aplicar_clasificaciones
from core.etl_ventas import aplicar_vendedores
from core.navigation import (
    render_sidebar_search, render_sidebar_status,
    inject_custom_css, handle_pending_nav, render_periodo_filter,
)

st.set_page_config(
    page_title="Comparativa — Lyon AG",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_db()
inject_custom_css()
handle_pending_nav()

_BLUE  = COLOR_LYON
_GREEN = COLOR_VENTAS
_RED   = "#C00000"
_AMBER = "#E97132"
_GRAY  = "#9E9E9E"

COSTOS_DIRECTOS = [
    "Sustratos (Papel)", "Pre-prensa y Químicos", "Encuadernación",
    "Insumos de Producción", "Maquila",
]
OVERHEAD = [
    "Mantenimiento y Refacciones", "Logística / Fletes", "Almacenaje y Renta",
    "Limpieza y Sanitarios", "Servicios Profesionales", "Otros / Sin clasificar",
]


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


def _risk_card(titulo, pct, nombre_top, total_entidades, detalle_filas):
    color  = _GREEN if pct < 40 else (_AMBER if pct < 60 else _RED)
    estado = "Riesgo bajo" if pct < 40 else ("Riesgo medio" if pct < 60 else "Riesgo alto")
    rows_html = "".join(
        f"<div style='display:flex;justify-content:space-between;"
        f"font-size:.75rem;margin:2px 0'>"
        f"<span style='color:#374151'>{n}</span>"
        f"<span style='color:{color};font-weight:600'>{p:.1f}%</span></div>"
        for n, p in detalle_filas
    )
    return f"""
    <div style="background:#fff;border:1px solid #E1E7EC;border-radius:10px;
                padding:1.1rem 1.25rem;box-shadow:0 1px 4px rgba(0,0,0,.05);">
      <p style="margin:0 0 6px;font-size:.72rem;font-weight:700;color:#6B7280;
                text-transform:uppercase;letter-spacing:.5px">{titulo}</p>
      <p style="margin:0;font-size:2.4rem;font-weight:800;color:{color};
                line-height:1.1">{pct:.1f}%</p>
      <span style="background:{color};color:#fff;padding:2px 10px;border-radius:10px;
                   font-size:.72rem;font-weight:700">{estado}</span>
      <p style="margin:8px 0 4px;font-size:.72rem;color:#9CA3AF">
        Mayor concentración: <b style='color:#374151'>{nombre_top}</b>
        &nbsp;·&nbsp; {total_entidades} total</p>
      <div style="margin-top:4px">{rows_html}</div>
    </div>"""


def _semana_mes(dia):
    if dia <= 7:  return "S1 (1–7)"
    if dia <= 14: return "S2 (8–14)"
    if dia <= 21: return "S3 (15–21)"
    return "S4 (22+)"


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    render_sidebar_search()
    render_sidebar_status()

st.markdown(
    f"<h1 style='color:{COLOR_LYON}'>"
    "<span class='material-symbols-outlined'>compare_arrows</span>Comparativa Compras vs Ventas</h1>",
    unsafe_allow_html=True,
)

compras_ok = "df_compras" in st.session_state
ventas_ok  = "df_ventas"  in st.session_state

if not compras_ok or not ventas_ok:
    st.warning("Para ver la Comparativa necesitas haber cargado ambos archivos.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Ir a Compras", use_container_width=True):
            st.switch_page("pages/1_Compras.py")
    with c2:
        if st.button("Ir a Ventas", use_container_width=True):
            st.switch_page("pages/2_Ventas.py")
    st.stop()

# ── Datos completos ───────────────────────────────────────────────────────────
df_c = aplicar_clasificaciones(st.session_state.df_compras)
df_v = aplicar_vendedores(st.session_state.df_ventas.copy())

meses_c       = set(df_c["_Mes"].unique())
meses_v       = set(df_v["_Mes"].unique())
meses_comunes = sorted(meses_c & meses_v)

if not meses_comunes:
    st.warning(
        "Los archivos no tienen meses en común. "
        "Carga archivos del mismo periodo para ver la comparativa."
    )
    st.stop()

# ── Caption ───────────────────────────────────────────────────────────────────
meta_c = st.session_state.get("df_compras_meta", {})
meta_v = st.session_state.get("df_ventas_meta",  {})
st.caption(
    f"Compras: **{meta_c.get('archivo','Compras')}**  ·  "
    f"Ventas: **{meta_v.get('archivo','Ventas')}**  ·  "
    f"Periodo común: **{label_mes(meses_comunes[0])} – {label_mes(meses_comunes[-1])}**"
    + (f"  ·  ⚠️ {len(meses_c - meses_v)} mes(es) solo en Compras, "
       f"{len(meses_v - meses_c)} solo en Ventas"
       if meses_c != meses_v else "")
)


# ── Filtros sidebar ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filtros")
    meses_sel = render_periodo_filter("cmn", meses_comunes)

if not meses_sel:
    st.warning("Selecciona al menos un mes.")
    st.stop()

df_cf = df_c[df_c["_Mes"].isin(meses_sel)].copy()
df_vf = df_v[df_v["_Mes"].isin(meses_sel)].copy()

# ── Métricas base ─────────────────────────────────────────────────────────────
total_ventas  = df_vf["Importe_MXN"].sum()
total_compras = df_cf["Gasto_Total_MXN"].sum()
margen        = total_ventas - total_compras
margen_pct    = margen / total_ventas * 100        if total_ventas  > 0 else 0
ratio_costo   = total_compras / total_ventas * 100 if total_ventas  > 0 else 0

gasto_directo  = df_cf[df_cf["Categoria"].isin(COSTOS_DIRECTOS)]["Gasto_Total_MXN"].sum()
gasto_overhead = df_cf[df_cf["Categoria"].isin(OVERHEAD)]["Gasto_Total_MXN"].sum()
pct_directo    = gasto_directo  / total_ventas * 100 if total_ventas > 0 else 0
pct_overhead   = gasto_overhead / total_ventas * 100 if total_ventas > 0 else 0

margen_color = _GREEN if margen >= 0 else _RED

# ── Tablas mensuales base ─────────────────────────────────────────────────────
mes_c_df = (df_cf.groupby("_Mes", as_index=False)["Gasto_Total_MXN"]
                  .sum().rename(columns={"Gasto_Total_MXN": "Compras"}))
mes_v_df = (df_vf.groupby("_Mes", as_index=False)["Importe_MXN"]
                  .sum().rename(columns={"Importe_MXN": "Ventas"}))
mes_df = (pd.merge(mes_v_df, mes_c_df, on="_Mes", how="outer")
            .sort_values("_Mes").fillna(0))
mes_df["Mes"]        = mes_df["_Mes"].apply(label_mes)
mes_df["Margen"]     = mes_df["Ventas"] - mes_df["Compras"]
mes_df["Margen_pct"] = mes_df.apply(
    lambda r: r["Margen"] / r["Ventas"] * 100 if r["Ventas"] > 0 else 0, axis=1
)

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN 1 — KPIs GLOBALES
# ══════════════════════════════════════════════════════════════════════════════
k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
k1.markdown(_kpi("Ventas",       f"${total_ventas/1e6:,.2f}M",  _GREEN),       unsafe_allow_html=True)
k2.markdown(_kpi("Compras",      f"${total_compras/1e6:,.2f}M", _BLUE),        unsafe_allow_html=True)
k3.markdown(_kpi("Margen Bruto", f"${margen/1e6:,.2f}M",        margen_color), unsafe_allow_html=True)
k4.markdown(_kpi("Margen %",     f"{margen_pct:.1f}%",          margen_color), unsafe_allow_html=True)
k5.markdown(
    _kpi("Ratio C/V", f"{ratio_costo:.1f}%", _AMBER,
         desc="<b>Compras ÷ Ventas × 100</b><br>"
              "Por cada $100 de ventas, cuánto se gastó en compras.<br>"
              "<b>Target:</b> &lt; 80 % — si supera 100 %, la empresa compró más de lo que vendió en el periodo."),
    unsafe_allow_html=True,
)
k6.markdown(
    _kpi("Costo Directo %", f"{pct_directo:.1f}%", _BLUE,
         desc="<b>Costos directos ÷ Ventas × 100</b><br>"
              "Porcentaje de las ventas destinado a materiales y producción directa.<br>"
              "<b>Incluye:</b> Sustratos, Pre-prensa y Químicos, Encuadernación, Insumos de Producción, Maquila."),
    unsafe_allow_html=True,
)
k7.markdown(
    _kpi("Overhead %", f"{pct_overhead:.1f}%", _AMBER,
         desc="<b>Costos overhead ÷ Ventas × 100</b><br>"
              "Porcentaje de las ventas destinado a gastos operativos no productivos.<br>"
              "<b>Incluye:</b> Mantenimiento, Logística / Fletes, Almacenaje y Renta, Limpieza, Servicios Profesionales, Otros."),
    unsafe_allow_html=True,
)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN 2 — CONCENTRACIÓN DE RIESGO
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### Concentración de Riesgo")

# ── Proveedores: por categoría ────────────────────────────────────────────────
cat_spend = (df_cf.groupby("Categoria")["Gasto_Total_MXN"]
                   .sum().sort_values(ascending=False))
n_cats    = len(cat_spend)
top1_cat  = cat_spend.index[0] if n_cats > 0 else "—"
pct_top1  = cat_spend.iloc[0] / total_compras * 100 if (n_cats > 0 and total_compras > 0) else 0

# ── Tabla resumen: concentración por categoría ───────────────────────────────
_CRITICAS_CMP = {"Sustratos (Papel)", "Mantenimiento y Refacciones", "Pre-prensa y Químicos"}

cat_tbl_rows = []
for cat, cat_group in df_cf.groupby("Categoria"):
    if cat == ETIQ_PENDIENTE:
        continue
    prov_in_cat = (cat_group.groupby("Proveedor")["Gasto_Total_MXN"]
                             .sum().sort_values(ascending=False))
    n_prov_cat  = len(prov_in_cat)
    cat_tot     = prov_in_cat.sum()
    top1_pct    = float(prov_in_cat.iloc[0]) / cat_tot * 100 if cat_tot > 0 else 0
    top2        = prov_in_cat.head(min(2, n_prov_cat))
    top2_pct    = top2.sum() / cat_tot * 100 if cat_tot > 0 else 0
    top2_names  = " + ".join(
        p[:22] + "…" if len(p) > 24 else p for p in top2.index
    )
    umbral      = 65 if cat in _CRITICAS_CMP else 75
    semaforo    = ("🟢 Bajo" if top1_pct < 40
                   else ("🟡 Medio" if top1_pct < umbral else "🔴 Alto"))
    cat_tbl_rows.append({
        "Categoría":          cat,
        "Gasto total":        cat_tot,
        "% del gasto total":  cat_tot / total_compras * 100 if total_compras > 0 else 0,
        "Proveedores dominantes": top2_names if n_prov_cat > 1 else top2_names + " (único)",
        "% acumulado":        top2_pct,
        "Riesgo":             semaforo,
    })

cat_tbl_rows.sort(key=lambda r: r["Gasto total"], reverse=True)

with st.container(border=True):
    st.markdown("##### Concentración por Categoría de Gasto")
    st.caption(
        "Muestra los 2 proveedores que más concentran el gasto dentro de cada categoría "
        "y el nivel de riesgo de dependencia. "
        "Umbrales: 🔴 > 65% en categorías críticas (Sustratos, Pre-prensa, Mantenimiento) "
        "· 🔴 > 75% en el resto."
    )
    cat_tbl_df = pd.DataFrame(cat_tbl_rows)
    st.dataframe(
        cat_tbl_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Categoría":              st.column_config.TextColumn("Categoría"),
            "Gasto total":            st.column_config.NumberColumn("Gasto total",    format="$%,.0f"),
            "% del gasto total":      st.column_config.NumberColumn("% del total",    format="%.1f%%"),
            "Proveedores dominantes": st.column_config.TextColumn("Top 2 proveedores"),
            "% acumulado":            st.column_config.NumberColumn("% acumulado",    format="%.1f%%"),
            "Riesgo":                 st.column_config.TextColumn("Riesgo"),
        },
        height=min(600, 52 + 36 * len(cat_tbl_df)),
    )

# ── Concentración de clientes: top 3 ─────────────────────────────────────────
cli_rank     = (df_vf.groupby("Cliente_Nombre")["Importe_MXN"]
                      .sum().sort_values(ascending=False))
n_cli        = len(cli_rank)
top3_cli     = cli_rank.head(3)
pct_top3_cli = top3_cli.sum() / total_ventas * 100 if total_ventas > 0 else 0
color_cli    = _GREEN if pct_top3_cli < 40 else (_AMBER if pct_top3_cli < 60 else _RED)

cli_pct_rows = [
    (n[:28] + "…" if len(n) > 30 else n, v / total_ventas * 100)
    for n, v in top3_cli.items()
    if total_ventas > 0
]
top1_cli_name = top3_cli.index[0] if n_cli > 0 else "—"

with st.container(border=True):
    st.markdown("##### Concentración de Clientes")
    r1, r2 = st.columns([1, 1])
    with r1:
        st.markdown(
            _risk_card(
                "Concentración Top 3 Clientes",
                pct_top3_cli, top1_cli_name, n_cli, cli_pct_rows,
            ),
            unsafe_allow_html=True,
        )
    with r2:
        donut_labels_c = list(top3_cli.index) + ["Resto"]
        donut_values_c = list(top3_cli.values) + [max(0.0, total_ventas - top3_cli.sum())]
        donut_colors_c = [color_cli, color_cli, color_cli, "#E5E7EB"]
        fig_dc = go.Figure(go.Pie(
            labels=donut_labels_c, values=donut_values_c,
            hole=0.52, marker_colors=donut_colors_c,
            textinfo="percent", textfont_size=13,
            hovertemplate="<b>%{label}</b><br>$%{value:,.0f}  ·  %{percent}<extra></extra>",
        ))
        fig_dc.update_layout(
            showlegend=False, height=340,
            margin=dict(t=10, b=10, l=10, r=10),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_dc, use_container_width=True)

# ── Risk narrative callout ────────────────────────────────────────────────────
_tp_gbl = df_cf.groupby("Proveedor")["Gasto_Total_MXN"].sum().sort_values(ascending=False)
if len(_tp_gbl) > 0 and total_compras > 0:
    _tp_name  = _tp_gbl.index[0]
    _tp_gasto = float(_tp_gbl.iloc[0])
    _pct_comp = _tp_gasto / total_compras * 100
    _pct_vtas = _tp_gasto / total_ventas * 100 if total_ventas > 0 else 0
    st.info(
        f"⚠️ **Riesgo clave:** Si **{_tp_name}** falla, representa "
        f"**{_pct_comp:.1f}%** del gasto total en compras — "
        f"equivalente a ~**{_pct_vtas:.1f}%** de las ventas del período."
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN 3 — EVOLUCIÓN TEMPORAL
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### Evolución Temporal")

# ── Chart: Ventas vs Compras mensual ─────────────────────────────────────────
with st.container(border=True):
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=mes_df["Mes"], y=mes_df["Ventas"], name="Ventas",
        marker_color=_GREEN,
        hovertemplate="<b>%{x}</b><br>Ventas: $%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=mes_df["Mes"], y=mes_df["Compras"], name="Compras",
        marker_color=_BLUE,
        hovertemplate="<b>%{x}</b><br>Compras: $%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=mes_df["Mes"], y=mes_df["Margen_pct"],
        name="Margen %", yaxis="y2", mode="lines+markers",
        line=dict(color=_AMBER, width=2.5, dash="dot"),
        marker=dict(size=7),
        hovertemplate="<b>%{x}</b><br>Margen: %{y:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        title="<b>Ventas vs Compras por Mes</b> · línea naranja = Margen %",
        barmode="group", template="plotly_white", height=420,
        legend=dict(orientation="h", y=1.09, x=0.5, xanchor="center"),
        xaxis_title="",
        yaxis=dict(title="MXN", tickformat="$,.0f"),
        yaxis2=dict(
            title="Margen %", overlaying="y", side="right",
            ticksuffix="%", showgrid=False,
            range=[min(mes_df["Margen_pct"].min() - 5, 0),
                   mes_df["Margen_pct"].max() + 10],
        ),
        margin=dict(t=80, b=40, l=80, r=80),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Chart: Margen bruto mensual ───────────────────────────────────────────────
with st.container(border=True):
    bar_colors = [
        "rgba(84,130,53,0.85)" if v >= 0 else "rgba(192,0,0,0.85)"
        for v in mes_df["Margen"]
    ]
    fig2 = go.Figure(go.Bar(
        x=mes_df["Mes"], y=mes_df["Margen"],
        marker_color=bar_colors,
        text=mes_df["Margen"].apply(lambda v: f"${v/1e6:,.2f}M"),
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Margen: $%{y:,.0f} MXN<extra></extra>",
    ))
    fig2.add_hline(y=0, line_color="#6B7280", line_width=1)
    fig2.update_layout(
        title="<b>Margen Bruto Mensual</b> (Ventas − Compras) · verde = positivo · rojo = negativo",
        template="plotly_white", height=340, showlegend=False,
        xaxis_title="", yaxis=dict(tickformat="$,.0f", title="MXN"),
        margin=dict(t=60, b=40, l=80, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN 4 — COSTOS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### Costos")

# ── Chart: Gasto por categoría como % de ventas del mes ──────────────────────
cat_mes_df = (df_cf.groupby(["_Mes", "Categoria"])["Gasto_Total_MXN"]
                    .sum().reset_index())
cat_mes_df = cat_mes_df.merge(mes_v_df[["_Mes", "Ventas"]], on="_Mes", how="left")
cat_mes_df["Pct_Ventas"] = cat_mes_df.apply(
    lambda r: r["Gasto_Total_MXN"] / r["Ventas"] * 100 if r["Ventas"] > 0 else 0, axis=1
)
mes_order = [label_mes(m) for m in sorted(meses_sel)]
cat_mes_df["Mes"] = pd.Categorical(
    cat_mes_df["_Mes"].apply(label_mes), categories=mes_order, ordered=True
)
cat_mes_df = cat_mes_df.sort_values("Mes")

cats_presentes = (cat_mes_df.groupby("Categoria")["Gasto_Total_MXN"]
                             .sum().sort_values(ascending=False).index.tolist())

with st.container(border=True):
    fig5 = go.Figure()
    for cat in cats_presentes:
        sub = cat_mes_df[cat_mes_df["Categoria"] == cat]
        fig5.add_trace(go.Bar(
            x=sub["Mes"].astype(str), y=sub["Pct_Ventas"],
            name=cat if len(cat) <= 22 else cat[:20] + "…",
            marker_color=PALETA_CATEGORIAS.get(cat, _GRAY),
            hovertemplate=(
                f"<b>%{{x}}</b><br>{cat}<br>"
                "$%{customdata:,.0f} · %{y:.1f}% de ventas<extra></extra>"
            ),
            customdata=sub["Gasto_Total_MXN"].values,
        ))
    fig5.update_layout(
        title="<b>Gasto por Categoría como % de Ventas del Mes</b>",
        barmode="stack", template="plotly_white", height=420,
        legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center",
                    font=dict(size=10)),
        xaxis_title="", yaxis=dict(ticksuffix="%", title="% sobre Ventas"),
        margin=dict(t=60, b=150, l=60, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig5, use_container_width=True)

# ── Desvío de Categoría vs Promedio ──────────────────────────────────────────
with st.container(border=True):
    st.markdown("##### Desvío de Categoría vs Promedio del Período")
    st.caption(
        "Evolución mensual del gasto de cada categoría como % de las ventas. "
        "⬆ = por encima de su promedio móvil de 3 meses — señal de presión creciente sobre el margen."
    )
    _spark_rows = []
    for _cat in cats_presentes:
        _sub = cat_mes_df[cat_mes_df["Categoria"] == _cat].sort_values("_Mes")
        _vals = _sub["Pct_Ventas"].tolist()
        if not _vals:
            continue
        _last   = _vals[-1]
        _avg_p  = sum(_vals) / len(_vals)
        _roll3  = float(_sub["Pct_Ventas"].rolling(3, min_periods=1).mean().iloc[-1])
        _tipo   = "Costo Directo" if _cat in COSTOS_DIRECTOS else "Overhead"
        _estado = "⬆ Sobre promedio" if _last > _roll3 else "— En línea"
        _spark_rows.append({
            "Categoría":            _cat,
            "Tipo":                 _tipo,
            "Tendencia (% Ventas)": _vals,
            "Último mes %":         _last,
            "Prom. período %":      _avg_p,
            "Estado":               _estado,
        })
    if _spark_rows:
        _spark_df = pd.DataFrame(_spark_rows)
        st.dataframe(
            _spark_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Categoría":            st.column_config.TextColumn("Categoría",      width="medium"),
                "Tipo":                 st.column_config.TextColumn("Tipo",            width="small"),
                "Tendencia (% Ventas)": st.column_config.LineChartColumn(
                                            "Tendencia (% de Ventas)", y_min=0,
                                        ),
                "Último mes %":         st.column_config.NumberColumn("Último mes",    format="%.1f%%"),
                "Prom. período %":      st.column_config.NumberColumn("Prom. período", format="%.1f%%"),
                "Estado":               st.column_config.TextColumn("Estado"),
            },
            height=min(600, 52 + 40 * len(_spark_df)),
        )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN 6 — PATRONES TEMPORALES
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### Patrones Temporales")

semana_order = ["S1 (1–7)", "S2 (8–14)", "S3 (15–21)", "S4 (22+)"]

df_cf["semana"] = df_cf["Fecha de documento"].dt.day.apply(_semana_mes)
df_vf["semana"] = df_vf["Fecha"].dt.day.apply(_semana_mes)

pivot_c = (df_cf.pivot_table(values="Gasto_Total_MXN", index="_Mes",
                              columns="semana", aggfunc="sum", fill_value=0)
                .sort_index())
pivot_v = (df_vf.pivot_table(values="Importe_MXN", index="_Mes",
                              columns="semana", aggfunc="sum", fill_value=0)
                .sort_index())
for piv in [pivot_c, pivot_v]:
    for s in semana_order:
        if s not in piv.columns:
            piv[s] = 0
pivot_c = pivot_c[semana_order]
pivot_v = pivot_v[semana_order]
pivot_c.index = [label_mes(m) for m in pivot_c.index]
pivot_v.index = [label_mes(m) for m in pivot_v.index]

# Shared scale so both heatmaps are visually comparable
_z_max_shared = max(
    float(pivot_c.values.max()) if pivot_c.size > 0 else 0,
    float(pivot_v.values.max()) if pivot_v.size > 0 else 0,
) or 1.0

# ── Heatmap Compras — ANCHO COMPLETO ─────────────────────────────────────────
with st.container(border=True):
    z_c    = pivot_c.values.tolist()
    txt_c  = [[f"${v/1e3:,.0f}K" if v > 0 else "—" for v in row] for row in pivot_c.values]
    h_c    = max(320, 75 * len(pivot_c) + 120)
    fig_hc = go.Figure(go.Heatmap(
        z=z_c,
        x=semana_order,
        y=pivot_c.index.tolist(),
        text=txt_c,
        texttemplate="%{text}",
        textfont=dict(size=13),
        colorscale=[[0, "#EFF6FF"], [1, "#1F4E79"]],
        zmin=0, zmax=_z_max_shared,
        hovertemplate="<b>%{y} · %{x}</b><br>$%{z:,.0f}<extra></extra>",
        showscale=True,
        colorbar=dict(tickformat="$,.0f", len=0.8, title="MXN"),
    ))
    fig_hc.update_layout(
        title=(
            "<b>Heatmap Compras — Actividad por Semana del Mes</b><br>"
            "<span style='font-size:12px;color:#6B7280'>"
            "Tonos más oscuros = mayor gasto registrado en esa semana</span>"
        ),
        template="plotly_white",
        height=h_c,
        margin=dict(t=100, b=60, l=110, r=100),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(title="Semana del mes", side="bottom"),
        yaxis_title="",
    )
    st.plotly_chart(fig_hc, use_container_width=True)

# ── Heatmap Ventas — ANCHO COMPLETO ──────────────────────────────────────────
with st.container(border=True):
    z_v    = pivot_v.values.tolist()
    txt_v  = [[f"${v/1e3:,.0f}K" if v > 0 else "—" for v in row] for row in pivot_v.values]
    h_v    = max(320, 75 * len(pivot_v) + 120)
    fig_hv = go.Figure(go.Heatmap(
        z=z_v,
        x=semana_order,
        y=pivot_v.index.tolist(),
        text=txt_v,
        texttemplate="%{text}",
        textfont=dict(size=13),
        colorscale=[[0, "#F0FFF4"], [1, "#548235"]],
        zmin=0, zmax=_z_max_shared,
        hovertemplate="<b>%{y} · %{x}</b><br>$%{z:,.0f}<extra></extra>",
        showscale=True,
        colorbar=dict(tickformat="$,.0f", len=0.8, title="MXN"),
    ))
    fig_hv.update_layout(
        title=(
            "<b>Heatmap Ventas — Actividad por Semana del Mes</b><br>"
            "<span style='font-size:12px;color:#6B7280'>"
            "Tonos más oscuros = mayor venta registrada en esa semana</span>"
        ),
        template="plotly_white",
        height=h_v,
        margin=dict(t=100, b=60, l=110, r=100),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(title="Semana del mes", side="bottom"),
        yaxis_title="",
    )
    st.plotly_chart(fig_hv, use_container_width=True)

# ── Desfase callout ───────────────────────────────────────────────────────────
_best_ratio = -1.0
_best_mes = _best_sem = "—"
_best_c_val = _best_v_val = 0.0
for _m in set(pivot_c.index) & set(pivot_v.index):
    for _s in semana_order:
        _cv = float(pivot_c.loc[_m, _s]) if _s in pivot_c.columns else 0.0
        _vv = float(pivot_v.loc[_m, _s]) if _s in pivot_v.columns else 0.0
        if _cv > 0 and _vv > 0:
            _r = _cv / _vv
            if _r > _best_ratio:
                _best_ratio, _best_mes, _best_sem = _r, _m, _s
                _best_c_val, _best_v_val = _cv, _vv

if _best_mes != "—":
    st.info(
        f"📊 **Semana con mayor desfase C/V: {_best_sem} de {_best_mes}** — "
        f"Compras ${_best_c_val/1e3:,.0f}K · Ventas ${_best_v_val/1e3:,.0f}K · "
        f"Ratio C/V {_best_ratio:.2f}"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  TABLA RESUMEN MENSUAL — negativos en rojo
# ══════════════════════════════════════════════════════════════════════════════
with st.container(border=True):
    st.markdown("##### Resumen mensual")

    resumen = mes_df[["Mes", "Ventas", "Compras", "Margen", "Margen_pct"]].copy().reset_index(drop=True)
    totales = pd.DataFrame([{
        "Mes": "TOTAL", "Ventas": total_ventas, "Compras": total_compras,
        "Margen": margen, "Margen_pct": margen_pct,
    }])
    resumen_full = pd.concat([resumen, totales], ignore_index=True)

    def _color_margen(v):
        if isinstance(v, (int, float)):
            if v < 0:
                return "color: #C00000; font-weight: 700"
            if v > 0:
                return "color: #548235; font-weight: 700"
        return ""

    fmt = {
        "Ventas":     lambda v: f"${v:,.0f}" if isinstance(v, (int, float)) else str(v),
        "Compras":    lambda v: f"${v:,.0f}" if isinstance(v, (int, float)) else str(v),
        "Margen":     lambda v: f"${v:,.0f}" if isinstance(v, (int, float)) else str(v),
        "Margen_pct": lambda v: f"{v:.1f}%"  if isinstance(v, (int, float)) else str(v),
    }

    try:
        styled = resumen_full.style.map(_color_margen, subset=["Margen", "Margen_pct"]).format(fmt)
    except AttributeError:
        styled = resumen_full.style.applymap(_color_margen, subset=["Margen", "Margen_pct"]).format(fmt)

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=min(600, 52 + 36 * len(resumen_full)),
    )
