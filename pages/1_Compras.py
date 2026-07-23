import datetime as dt

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.catalogos import (
    CATALOGO_CATEGORIAS, ETIQ_PENDIENTE,
    COLOR_LYON, COLOR_VENTAS, PALETA_CATEGORIAS, label_mes,
)
from core.database import init_db
from core.etl_compras import cargar_compras, aplicar_clasificaciones
from core.navigation import render_sidebar_search, render_sidebar_status, inject_custom_css, handle_pending_nav, breadcrumb, render_periodo_filter
from core.plots import (
    plot_donut_categorias,
    plot_curva_semanal_compras,
    plot_pareto_proveedores,
    plot_pendientes_clasificar,
)

st.set_page_config(
    page_title="Compras — Lyon AG",
    page_icon="📋",
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

# Categorías críticas donde la concentración es más peligrosa
_CRITICAS = {"Sustratos (Papel)", "Mantenimiento y Refacciones", "Pre-prensa y Químicos"}
# Paleta para slices de proveedores dentro de un donut
_PROV_PALETTE   = ["#1F4E79", "#2E75B6", "#4472C4", "#5B9BD5", "#9DC3E6", "#BDD7EE"]
_COMMODITY_CATS = {"Sustratos (Papel)", "Pre-prensa y Químicos", "Insumos de Producción"}


def _kpi(label, value, color):
    return f"""
    <div style="background:#fff;border:1px solid #E1E7EC;border-radius:10px;
                padding:1rem 1.25rem;box-shadow:0 1px 4px rgba(0,0,0,.05);">
      <p style="margin:0 0 4px;font-size:.72rem;font-weight:600;color:#6B7280;
                text-transform:uppercase;letter-spacing:.5px;">{label}</p>
      <p style="margin:0;font-size:1.65rem;font-weight:700;color:{color};
                line-height:1.2;">{value}</p>
    </div>"""


# ──────────────────────────────────────────────────────────────────────────────
#  Scorecard helpers para el drill-down intra-categoría
# ──────────────────────────────────────────────────────────────────────────────

def _compute_scorecard(df_ctx, proveedor_sel):
    """
    df_ctx: filtrado solo por meses (sin filtro de categoría) para comparación justa.
    Devuelve (metrics, cat_agg, monthly_all).
    """
    cat_sel = (df_ctx[df_ctx["Proveedor"] == proveedor_sel]["Categoria"]
               .mode().iloc[0] if len(df_ctx[df_ctx["Proveedor"] == proveedor_sel]) > 0
               else ETIQ_PENDIENTE)

    df_cat  = df_ctx[df_ctx["Categoria"] == cat_sel].copy()
    df_prov = df_cat[df_cat["Proveedor"] == proveedor_sel].copy()

    cat_agg = (
        df_cat.groupby("Proveedor")
        .agg(
            gasto_total   =("Gasto_Total_MXN", "sum"),
            n_facturas    =("Gasto_Total_MXN", "count"),
            meses_activos =("_Mes", "nunique"),
            avg_ticket    =("Gasto_Total_MXN", "mean"),
        )
        .reset_index()
        .sort_values("gasto_total", ascending=False)
        .reset_index(drop=True)
    )
    cat_total = cat_agg["gasto_total"].sum()
    cat_agg["pct_share"]  = cat_agg["gasto_total"] / cat_total if cat_total > 0 else 0
    cat_agg["rank_gasto"] = range(1, len(cat_agg) + 1)
    cat_agg["es_sel"]     = cat_agg["Proveedor"] == proveedor_sel

    if len(cat_agg[cat_agg["Proveedor"] == proveedor_sel]) == 0:
        return None, cat_agg, None

    row = cat_agg[cat_agg["Proveedor"] == proveedor_sel].iloc[0]

    meses_totales = df_ctx["_Mes"].nunique()
    monthly_prov  = df_prov.groupby("_Mes")["Gasto_Total_MXN"].sum().sort_index()

    trend_pct = None
    if len(monthly_prov) >= 2:
        last      = float(monthly_prov.iloc[-1])
        prior_avg = float(monthly_prov.iloc[:-1].mean())
        trend_pct = (last - prior_avg) / prior_avg * 100 if prior_avg > 0 else None

    cv = None
    if len(monthly_prov) >= 3:
        cv = (float(monthly_prov.std()) / float(monthly_prov.mean()) * 100
              if monthly_prov.mean() > 0 else None)

    monthly_all = (
        df_cat.groupby(["_Mes", "Proveedor"])["Gasto_Total_MXN"]
        .sum().reset_index()
    )

    metrics = {
        "cat_sel"       : cat_sel,
        "share"         : float(row["pct_share"]),
        "rank_share"    : int(row["rank_gasto"]),
        "n_provs"       : len(cat_agg),
        "n_facturas"    : int(row["n_facturas"]),
        "meses_activos" : int(row["meses_activos"]),
        "meses_totales" : meses_totales,
        "avg_ticket"    : float(row["avg_ticket"]),
        "cat_med_ticket": float(cat_agg["avg_ticket"].median()),
        "trend_pct"     : trend_pct,
        "cv"            : cv,
        "gasto_total"   : float(row["gasto_total"]),
        "cat_total"     : float(cat_total),
    }
    return metrics, cat_agg, monthly_all


def _risk_alerts(metrics):
    """Devuelve lista de (severity, markdown_message)."""
    alerts = []
    cat      = metrics["cat_sel"]
    share    = metrics["share"]
    trend    = metrics["trend_pct"]
    cv       = metrics["cv"]
    umbral   = 0.65 if cat in _CRITICAS else 0.75

    if share > umbral:
        alerts.append(("error",
            f"Concentra el **{share*100:.1f}%** del gasto en **{cat}**. "
            f"Riesgo de dependencia operativa alta."))

    if metrics["meses_activos"] == 1 and share > 0.20:
        alerts.append(("warning",
            f"Activo **solo un mes** y representa el {share*100:.1f}% del gasto "
            f"de la categoría. Confirmar si es compra puntual o nuevo proveedor recurrente."))

    if metrics["n_facturas"] == 1:
        alerts.append(("warning",
            "**Una sola factura** en el periodo. "
            "Verificar si fue una compra de emergencia o extraordinaria."))

    if trend is not None and trend > 100:
        alerts.append(("warning",
            f"Gasto del último mes **+{trend:.0f}%** vs. promedio previo. "
            "Revisar si fue una compra extraordinaria."))

    if trend is not None and trend < -70:
        alerts.append(("warning",
            f"Gasto del último mes cayó **{abs(trend):.0f}%** vs. promedio. "
            "Verificar disponibilidad del proveedor."))

    if cv is not None and cv > 80:
        alerts.append(("info",
            f"Patrón de compra muy irregular (Variabilidad = {cv:.0f}%). "
            "Oportunidad para negociar contrato con volumen comprometido."))

    if metrics["cat_med_ticket"] > 0 and metrics["avg_ticket"] > 3 * metrics["cat_med_ticket"]:
        alerts.append(("info",
            f"Ticket promedio **{metrics['avg_ticket']/metrics['cat_med_ticket']:.1f}×** "
            "la mediana de su categoría. Revisar si incluye servicios agrupados."))

    return alerts


def _render_intra_cat(df_ctx, proveedor, cat_sel):
    """Sección completa de comparativa intra-categoría dentro del drill-down."""
    if cat_sel == ETIQ_PENDIENTE:
        st.info("Clasifica este proveedor para ver su contexto dentro de una categoría.")
        return

    metrics, cat_agg, monthly_all = _compute_scorecard(df_ctx, proveedor)

    if metrics is None:
        st.info("Sin datos en el periodo seleccionado para comparar dentro de la categoría.")
        return

    if metrics["n_provs"] < 2:
        st.info(f"Es el único proveedor clasificado en **{cat_sel}** en el periodo. "
                "Agrega más facturas para ver comparativas.")
        return

    # ── Banners de riesgo ─────────────────────────────────────────────────────
    alerts = _risk_alerts(metrics)
    for sev, msg in alerts[:3]:
        if sev == "error":
            st.error(msg)
        elif sev == "warning":
            st.warning(msg)
        else:
            st.info(msg)
    if len(alerts) > 3:
        with st.expander(f"Ver {len(alerts) - 3} señal(es) más"):
            for sev, msg in alerts[3:]:
                if sev == "error":
                    st.error(msg)
                elif sev == "warning":
                    st.warning(msg)
                else:
                    st.info(msg)

    # ── 4 KPIs contextuales ───────────────────────────────────────────────────
    ticket_ratio = (metrics["avg_ticket"] / metrics["cat_med_ticket"]
                    if metrics["cat_med_ticket"] > 0 else None)
    ticket_ratio_str = (f"{ticket_ratio:.1f}× mediana cat."
                        if ticket_ratio is not None else "—")

    share_color = (_GREEN if metrics["share"] < 0.40
                   else (_AMBER if metrics["share"] < 0.65 else _RED))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Participación en categoría",
        f"{metrics['share']*100:.1f}%",
        f"#{metrics['rank_share']} de {metrics['n_provs']} proveedores",
        delta_color="off",
        help=f"Del gasto total de {cat_sel} en el periodo, este proveedor representa el {metrics['share']*100:.1f}%.",
    )
    c2.metric(
        "Facturas emitidas",
        f"{metrics['n_facturas']:,}",
        help="Número de facturas/registros en el periodo seleccionado.",
    )
    c3.metric(
        "Meses activo",
        f"{metrics['meses_activos']} / {metrics['meses_totales']}",
        help="Meses con al menos una factura, sobre el total de meses en el periodo.",
    )
    c4.metric(
        "Ticket promedio",
        f"${metrics['avg_ticket']:,.0f}",
        ticket_ratio_str,
        delta_color="off",
        help="Gasto total dividido entre número de facturas.",
    )

    st.markdown("")

    # ── Ranking de gasto en la categoría ─────────────────────────────────────
    with st.container(border=True):
        cat_agg_sorted = cat_agg.sort_values("gasto_total", ascending=True)
        colors = [_RED if e else _BLUE for e in cat_agg_sorted["es_sel"]]
        fig_rank = go.Figure(go.Bar(
            x=cat_agg_sorted["gasto_total"],
            y=cat_agg_sorted["Proveedor"],
            orientation="h",
            marker_color=colors,
            text=cat_agg_sorted.apply(
                lambda r: f"  ${r['gasto_total']/1e6:,.2f}M  ({r['pct_share']*100:.1f}%)", axis=1
            ),
            textposition="outside",
            customdata=cat_agg_sorted[["pct_share", "n_facturas"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "$%{x:,.0f}  ·  %{customdata[0]:.1%} del gasto<br>"
                "%{customdata[1]:.0f} facturas<extra></extra>"
            ),
        ))
        h_rank = max(300, 50 * len(cat_agg) + 80)
        fig_rank.update_layout(
            title=f"<b>Ranking de Gasto — {cat_sel}</b>"
                  " · <span style='color:#C00000'>■</span> proveedor seleccionado"
                  " · <span style='color:#1F4E79'>■</span> otros proveedores",
            template="plotly_white", height=h_rank, showlegend=False,
            xaxis=dict(tickformat="$,.0f", title="Gasto (MXN)"),
            yaxis_title="",
            margin=dict(t=70, b=40, l=200, r=180),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_rank, use_container_width=True)

    # ── Evolución mensual + Volatilidad (solo con >= 3 meses) ─────────────────
    if metrics["meses_totales"] >= 3:
        # Trend — ancho completo
        with st.container(border=True):
            fig_trend = go.Figure()
            n_peers = 0
            for prov_name, grp in monthly_all.groupby("Proveedor"):
                grp_sorted = grp.sort_values("_Mes")
                x_vals = [label_mes(m) for m in grp_sorted["_Mes"]]
                y_vals = grp_sorted["Gasto_Total_MXN"].tolist()
                is_sel = prov_name == proveedor
                fig_trend.add_trace(go.Scatter(
                    x=x_vals, y=y_vals,
                    name=prov_name[:22] + ("…" if len(prov_name) > 22 else ""),
                    mode="lines+markers" if is_sel else "lines",
                    line=dict(color=_RED if is_sel else "#D1D5DB",
                              width=3   if is_sel else 1),
                    marker=dict(size=8 if is_sel else 4,
                                color=_RED if is_sel else "#D1D5DB"),
                    hovertemplate=(
                        f"<b>{prov_name[:30]}</b><br>"
                        "$%{y:,.0f}<extra></extra>"
                    ),
                    showlegend=is_sel,
                ))
                if not is_sel:
                    n_peers += 1

            fig_trend.update_layout(
                title="<b>Evolución Mensual del Gasto</b>"
                      f" · Gris = {n_peers} proveedor(es) de la misma categoría",
                template="plotly_white", height=360,
                legend=dict(orientation="h", y=1.08, x=0, xanchor="left"),
                xaxis_title="", yaxis=dict(tickformat="$,.0f", title="MXN"),
                margin=dict(t=70, b=40, l=70, r=20),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_trend, use_container_width=True)

        # Volatility — ancho completo
        with st.container(border=True):
            cv_data = []
            for prov_name, grp in monthly_all.groupby("Proveedor"):
                ms = grp.groupby("_Mes")["Gasto_Total_MXN"].sum()
                if len(ms) >= 2 and ms.mean() > 0:
                    cv_val = ms.std() / ms.mean() * 100
                    cv_data.append({
                        "Proveedor": prov_name,
                        "CV": cv_val,
                        "es_sel": prov_name == proveedor,
                    })

            if cv_data:
                cv_df = (pd.DataFrame(cv_data)
                           .sort_values("CV", ascending=True))
                n_cv   = len(cv_df)
                h_cv   = max(380, 52 * n_cv + 100)
                cv_colors = [_RED if e else _BLUE for e in cv_df["es_sel"]]
                fig_cv = go.Figure(go.Bar(
                    x=cv_df["CV"],
                    y=cv_df["Proveedor"],
                    orientation="h",
                    marker_color=cv_colors,
                    text=cv_df["CV"].apply(lambda v: f"  {v:.0f}%"),
                    textposition="outside",
                    hovertemplate="<b>%{y}</b><br>Variabilidad: %{x:.1f}%<extra></extra>",
                ))
                fig_cv.add_vline(
                    x=50, line_color=_AMBER, line_dash="dot", line_width=1.5,
                    annotation_text="50% — umbral de irregularidad",
                    annotation_position="top right",
                )
                fig_cv.update_layout(
                    title=(
                        "<b>Variabilidad del Gasto por Proveedor</b><br>"
                        "<span style='font-size:12px;color:#6B7280'>"
                        "Coeficiente de variación mensual (%) — "
                        "mayor % = patrón de compra más irregular. "
                        "<span style='color:#C00000'>■</span> proveedor seleccionado"
                        "</span>"
                    ),
                    template="plotly_white", height=h_cv, showlegend=False,
                    xaxis=dict(
                        ticksuffix="%", title="Variabilidad (%)",
                        range=[0, max(130, cv_df["CV"].max() * 1.25)],
                    ),
                    yaxis_title="",
                    margin=dict(t=90, b=50, l=220, r=80),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_cv, use_container_width=True)
            else:
                st.info("Datos insuficientes para calcular variabilidad.")
    else:
        st.caption(
            f"*Tendencia y variabilidad requieren 3+ meses. Periodo actual: "
            f"{metrics['meses_totales']} mes(es).*"
        )


# ──────────────────────────────────────────────────────────────────────────────
#  Drill-down de semana (desglose de gasto de una semana específica)
# ──────────────────────────────────────────────────────────────────────────────
def _render_detalle_semana(df_full, df_ctx, semana_str):
    """Week-level drill-down: who spent what, in which categories, which invoices."""
    # ── Parsear fechas (también para el label del breadcrumb) ────────────────
    try:
        week_label = pd.Timestamp(str(semana_str)).normalize()
        week_start = week_label - pd.Timedelta(days=6)
        week_end   = week_label
        _bc_label  = f"{week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}"
    except Exception:
        week_label = week_start = week_end = None
        _bc_label  = str(semana_str)

    breadcrumb([
        ("Compras", {"clear": ["drill_semana", "curva_semanal_chart", "sem_pareto_chart", "sem_heatmap_chart", "sem_facturas_table"]}, None),
        (_bc_label, None, None),
    ])

    if week_label is None:
        st.error("No se pudo interpretar la semana seleccionada. Haz clic nuevamente en la gráfica.")
        return

    df_semana = df_ctx[
        (df_ctx["Fecha de documento"].dt.normalize() >= week_start) &
        (df_ctx["Fecha de documento"].dt.normalize() <= week_end)
    ].copy()

    if len(df_semana) == 0:
        st.warning(
            f"No hay facturas para la semana del "
            f"{week_start.strftime('%d %b')} al {week_end.strftime('%d %b %Y')} "
            "en el periodo filtrado. Verifica los filtros del sidebar."
        )
        return

    # ── Header ───────────────────────────────────────────────────────────────
    gasto_sem  = df_semana["Gasto_Total_MXN"].sum()
    n_facturas = len(df_semana)
    n_provs    = df_semana["Proveedor"].nunique()
    n_cats     = df_semana[df_semana["Categoria"] != ETIQ_PENDIENTE]["Categoria"].nunique()

    st.markdown(
        f"<h2 style='margin-bottom:4px'>"
        f"Semana del {week_start.strftime('%d %b')} al {week_end.strftime('%d %b %Y')}"
        f"</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='margin:0 0 1rem;color:#6B7280;font-size:.85rem'>"
        f"{n_facturas} facturas &nbsp;·&nbsp; {n_provs} proveedores "
        f"&nbsp;·&nbsp; {n_cats} categorías</p>",
        unsafe_allow_html=True,
    )

    # ── KPIs ─────────────────────────────────────────────────────────────────
    prior_start = week_start - pd.Timedelta(weeks=1)
    prior_end   = week_end   - pd.Timedelta(weeks=1)
    df_prior    = df_ctx[
        (df_ctx["Fecha de documento"].dt.normalize() >= prior_start) &
        (df_ctx["Fecha de documento"].dt.normalize() <= prior_end)
    ]
    gasto_prior = df_prior["Gasto_Total_MXN"].sum() if len(df_prior) > 0 else None

    var_str   = "—"
    var_color = _BLUE
    if gasto_prior is not None and gasto_prior > 0:
        var_pct   = (gasto_sem - gasto_prior) / gasto_prior * 100
        sign      = "+" if var_pct >= 0 else ""
        var_str   = f"{sign}{var_pct:.1f}%"
        var_color = _GREEN if var_pct <= 0 else (_AMBER if var_pct <= 30 else _RED)

    prov_shares_sem = (df_semana.groupby("Proveedor")["Gasto_Total_MXN"]
                                .sum().sort_values(ascending=False))
    top_prov_amt    = float(prov_shares_sem.iloc[0]) if len(prov_shares_sem) > 0 else 0
    top_prov_pct    = top_prov_amt / gasto_sem * 100 if gasto_sem > 0 else 0
    top_prov_color  = _GREEN if top_prov_pct < 40 else (_AMBER if top_prov_pct < 60 else _RED)

    gasto_sin_cat = df_semana[df_semana["Categoria"] == ETIQ_PENDIENTE]["Gasto_Total_MXN"].sum()
    pct_sin_cat   = gasto_sin_cat / gasto_sem * 100 if gasto_sem > 0 else 0
    sin_cat_color = _GREEN if gasto_sin_cat == 0 else (_AMBER if pct_sin_cat < 15 else _RED)
    sin_cat_str   = "Todo clasificado" if gasto_sin_cat == 0 else f"${gasto_sin_cat/1e6:,.2f}M ({pct_sin_cat:.0f}%)"

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_kpi("Gasto Semana",        f"${gasto_sem/1e6:,.2f}M",        _BLUE),          unsafe_allow_html=True)
    k2.markdown(_kpi("vs. Semana Anterior", var_str,                           var_color),      unsafe_allow_html=True)
    k3.markdown(_kpi("Proveedor Top",       f"{top_prov_pct:.0f}% del gasto",  top_prov_color), unsafe_allow_html=True)
    k4.markdown(_kpi("Sin clasificar",      sin_cat_str,                       sin_cat_color),  unsafe_allow_html=True)

    st.divider()

    # ── Sección 1: Pareto de Proveedores ─────────────────────────────────────
    st.markdown("### Pareto de Proveedores")
    st.caption("¿Qué proveedores concentraron el 80 % del gasto esta semana? Haz clic en una barra para ver el detalle del proveedor.")

    pareto = prov_shares_sem.reset_index()
    pareto.columns = ["Proveedor", "Gasto"]
    pareto["Pct"]      = pareto["Gasto"] / gasto_sem * 100
    pareto["Pct_Acum"] = pareto["Pct"].cumsum()
    pareto["Prov_Disp"] = pareto["Proveedor"].apply(lambda p: p[:34] + "…" if len(p) > 36 else p)

    def _prov_color_sem(prov):
        rows = df_semana[df_semana["Proveedor"] == prov]
        if len(rows) == 0:
            return _GRAY
        cat = rows["Categoria"].mode().iloc[0]
        return PALETA_CATEGORIAS.get(cat, _GRAY)

    bar_colors = [_prov_color_sem(p) for p in pareto["Proveedor"].iloc[::-1]]

    n_to_80 = int((pareto["Pct_Acum"] >= 80).idxmax()) + 1 if (pareto["Pct_Acum"] >= 80).any() else len(pareto)

    with st.container(border=True):
        fig_pareto = go.Figure()
        fig_pareto.add_trace(go.Bar(
            x=pareto["Gasto"].iloc[::-1],
            y=pareto["Prov_Disp"].iloc[::-1],
            orientation="h",
            marker=dict(color=bar_colors, line=dict(color="white", width=1)),
            text=[f"  ${g/1e6:,.2f}M  ({pc:.1f}%)"
                  for g, pc in zip(pareto["Gasto"].iloc[::-1], pareto["Pct"].iloc[::-1])],
            textposition="outside",
            customdata=pareto["Proveedor"].iloc[::-1].values,
            hovertemplate="<b>%{customdata}</b><br>$%{x:,.0f} MXN<extra></extra>",
            name="Gasto",
        ))
        h_pareto = max(280, 44 * len(pareto) + 100)
        fig_pareto.update_layout(
            title=(
                "<b>Pareto de Proveedores — Desglose de la Semana</b>"
                f"<br><sup>{n_to_80} proveedor(es) concentran el 80 % del gasto</sup>"
            ),
            template="plotly_white", height=h_pareto, showlegend=False,
            xaxis=dict(tickformat="$,.0f", title="Gasto (MXN)"),
            yaxis_title="",
            margin=dict(t=80, b=40, l=20, r=200),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        pareto_event = st.plotly_chart(
            fig_pareto, use_container_width=True,
            on_select="rerun", key="sem_pareto_chart",
        )
        if pareto_event and pareto_event.selection and pareto_event.selection.points:
            pt = pareto_event.selection.points[0]
            cd = pt.get("customdata", None) if isinstance(pt, dict) else getattr(pt, "customdata", None)
            if cd and isinstance(cd, str) and cd:
                prov_full = cd
            else:
                clicked_y = pt.get("y", "") if isinstance(pt, dict) else getattr(pt, "y", "")
                disp_to_full = {row["Prov_Disp"]: row["Proveedor"] for _, row in pareto.iterrows()}
                prov_full = disp_to_full.get(clicked_y, clicked_y)
            if prov_full:
                st.session_state["drill_proveedor"] = prov_full
                for _k in ("drill_semana", "drill_categoria", "curva_semanal_chart", "sem_pareto_chart", "sem_heatmap_chart", "sem_facturas_table"):
                    st.session_state.pop(_k, None)
                st.toast(f"Cargando proveedor **{prov_full[:40]}**…", icon="⏳")
                st.rerun()

    st.divider()

    # ── Sección 2: Heatmap Proveedor × Categoría ─────────────────────────────
    st.markdown("### Mapa Proveedor × Categoría")
    st.caption(
        "Color = gasto MXN. Celdas vacías = sin compras en esa combinación. "
        "Haz clic en una celda para ver el detalle del proveedor."
    )

    cats_en_sem  = [c for c in CATALOGO_CATEGORIAS
                    if c in df_semana["Categoria"].values and c != ETIQ_PENDIENTE]
    provs_en_sem = prov_shares_sem.index.tolist()
    df_sem_cls   = df_semana[df_semana["Categoria"] != ETIQ_PENDIENTE]

    if cats_en_sem and len(df_sem_cls) > 0:
        pivot_heat = (
            df_sem_cls
            .groupby(["Proveedor", "Categoria"])["Gasto_Total_MXN"]
            .sum()
            .reset_index()
            .pivot_table(
                index="Proveedor", columns="Categoria",
                values="Gasto_Total_MXN", aggfunc="sum", fill_value=0,
            )
        )
        pivot_heat = pivot_heat.reindex(
            [p for p in provs_en_sem if p in pivot_heat.index]
        ).fillna(0)
        pivot_heat = pivot_heat.reindex(
            columns=[c for c in cats_en_sem if c in pivot_heat.columns],
        ).fillna(0)

        prov_labels_heat = [p[:28] + "…" if len(p) > 30 else p for p in pivot_heat.index]

        h_heat = max(280, 44 * len(pivot_heat) + 120)
        with st.container(border=True):
            fig_heat = go.Figure(data=go.Heatmap(
                z=pivot_heat.values,
                x=list(pivot_heat.columns),
                y=prov_labels_heat,
                customdata=[[p] * len(pivot_heat.columns) for p in pivot_heat.index],
                colorscale=[
                    [0.0,   "#FFFFFF"],
                    [0.001, "#EFF6FF"],
                    [0.15,  "#BFDBFE"],
                    [0.5,   "#3B82F6"],
                    [1.0,   "#1F4E79"],
                ],
                hovertemplate="<b>%{y}</b> × <b>%{x}</b><br>$%{z:,.0f} MXN<extra></extra>",
                colorbar=dict(title=dict(text="MXN", font=dict(size=11)),
                              tickformat="$,.0f", thickness=14),
                xgap=2, ygap=2,
            ))
            fig_heat.update_layout(
                title="<b>Heatmap Proveedor × Categoría</b>",
                template="plotly_white", height=h_heat,
                margin=dict(t=60, b=80, l=200, r=80),
                xaxis=dict(side="top", tickfont=dict(size=10), tickangle=-30),
                yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
                paper_bgcolor="rgba(0,0,0,0)",
            )
            heat_event = st.plotly_chart(
                fig_heat, use_container_width=True,
                on_select="rerun", key="sem_heatmap_chart",
            )
            if heat_event and heat_event.selection and heat_event.selection.points:
                pt = heat_event.selection.points[0]
                # customdata[i] = [full_prov_name, full_prov_name, ...] → first element
                cd_heat = pt.get("customdata", None) if isinstance(pt, dict) else getattr(pt, "customdata", None)
                if cd_heat and isinstance(cd_heat, (list, tuple)):
                    prov_heat = cd_heat[0]
                elif cd_heat and isinstance(cd_heat, str):
                    prov_heat = cd_heat
                else:
                    clicked_y_heat = pt.get("y", "") if isinstance(pt, dict) else getattr(pt, "y", "")
                    disp_to_full_heat = {(p[:28] + "…" if len(p) > 30 else p): p for p in pivot_heat.index}
                    prov_heat = disp_to_full_heat.get(clicked_y_heat, clicked_y_heat)
                if prov_heat:
                    st.session_state["drill_proveedor"] = prov_heat
                    for _k in ("drill_semana", "drill_categoria", "curva_semanal_chart", "sem_pareto_chart", "sem_heatmap_chart", "sem_facturas_table"):
                        st.session_state.pop(_k, None)
                    st.toast(f"Cargando proveedor **{prov_heat[:40]}**…", icon="⏳")
                    st.rerun()
    else:
        st.info("Se requieren facturas con categoría asignada para mostrar el mapa.")

    st.divider()

    # ── Tabla de Facturas ─────────────────────────────────────────────────────
    st.markdown("### Detalle de Facturas")
    st.caption("Todas las facturas de la semana ordenadas por gasto. Selecciona una fila para navegar al proveedor o categoría.")

    tbl_sem = df_semana[[
        "Fecha de documento", "Proveedor", "Categoria",
        "Referencia factura", "Gasto_Total_MXN",
    ]].copy()
    tbl_sem["% Semana"] = tbl_sem["Gasto_Total_MXN"] / gasto_sem * 100
    tbl_sem["Fecha"]    = tbl_sem["Fecha de documento"].dt.strftime("%d-%b-%Y")
    tbl_sem = tbl_sem.sort_values("Gasto_Total_MXN", ascending=False).reset_index(drop=True)

    tbl_display_sem = tbl_sem[[
        "Fecha", "Proveedor", "Categoria",
        "Referencia factura", "Gasto_Total_MXN", "% Semana",
    ]].copy()

    tbl_sem_event = st.dataframe(
        tbl_display_sem,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="sem_facturas_table",
        column_config={
            "Fecha":              st.column_config.TextColumn("Fecha"),
            "Proveedor":          st.column_config.TextColumn("Proveedor"),
            "Categoria":          st.column_config.TextColumn("Categoría"),
            "Referencia factura": st.column_config.TextColumn("Referencia"),
            "Gasto_Total_MXN":    st.column_config.NumberColumn("Gasto (MXN)", format="$%,.2f"),
            "% Semana":           st.column_config.NumberColumn("% Semana",    format="%.1f%%"),
        },
        height=min(600, 48 + 36 * len(tbl_display_sem)),
    )

    if tbl_sem_event.selection and tbl_sem_event.selection.rows:
        sel_idx  = tbl_sem_event.selection.rows[0]
        sel_prov = tbl_display_sem.iloc[sel_idx]["Proveedor"]
        sel_cat  = tbl_display_sem.iloc[sel_idx]["Categoria"]

        nav_c1, nav_c2, _ = st.columns([2, 2, 4])
        with nav_c1:
            disp_p = sel_prov[:28] + ("…" if len(sel_prov) > 28 else "")
            if st.button(f"Ver proveedor: {disp_p} →", key="btn_sem_to_prov", type="primary"):
                st.session_state["drill_proveedor"] = sel_prov
                for _k in ("drill_semana", "drill_categoria", "curva_semanal_chart", "sem_pareto_chart", "sem_heatmap_chart", "sem_facturas_table"):
                    st.session_state.pop(_k, None)
                st.toast(f"Cargando proveedor **{sel_prov[:40]}**…", icon="⏳")
                st.rerun()
        if sel_cat != ETIQ_PENDIENTE:
            with nav_c2:
                if st.button(f"Ver categoría: {sel_cat[:20]} →", key="btn_sem_to_cat", type="secondary"):
                    st.session_state["drill_categoria"] = sel_cat
                    for _k in ("drill_semana", "curva_semanal_chart", "sem_pareto_chart", "sem_heatmap_chart", "sem_facturas_table"):
                        st.session_state.pop(_k, None)
                    st.toast(f"Cargando categoría **{sel_cat}**…", icon="⏳")
                    st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
#  Drill-down de categoría (nivel intermedio: overview → categoría → proveedor)
# ──────────────────────────────────────────────────────────────────────────────
def _render_detalle_categoria(df_full, df_ctx, categoria):
    """Mid-level view: all providers within a category, with trend + concentration charts."""
    breadcrumb([
        ("Compras", {"clear": ["drill_categoria", "donut_cat_chart", "curva_semanal_chart"]}, None),
        (categoria, None, None),
    ])

    df_cat = df_ctx[df_ctx["Categoria"] == categoria].copy()
    if len(df_cat) == 0:
        st.error(f"No hay datos para **{categoria}** en el periodo seleccionado.")
        return

    # ── Header ────────────────────────────────────────────────────────────────
    cat_color  = PALETA_CATEGORIAS.get(categoria, _GRAY)
    gasto_cat  = df_cat["Gasto_Total_MXN"].sum()
    gasto_all  = df_ctx["Gasto_Total_MXN"].sum()
    pct_total  = gasto_cat / gasto_all * 100 if gasto_all > 0 else 0
    fecha_min  = df_cat["Fecha de documento"].min()
    fecha_max  = df_cat["Fecha de documento"].max()
    n_provs    = df_cat["Proveedor"].nunique()
    n_facturas = len(df_cat)

    st.markdown(
        f"<span style='background:{cat_color};color:white;padding:4px 16px;"
        f"border-radius:14px;font-size:.84rem;font-weight:700'>{categoria}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='margin:6px 0 0;color:#6B7280;font-size:.85rem'>"
        f"${gasto_cat/1e6:,.2f}M &nbsp;·&nbsp; {pct_total:.1f}% del gasto total "
        f"&nbsp;·&nbsp; {fecha_min.strftime('%b %Y')} – {fecha_max.strftime('%b %Y')}</p>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='margin:1rem 0'></div>", unsafe_allow_html=True)

    # ── KPIs ──────────────────────────────────────────────────────────────────
    prov_shares = (df_cat.groupby("Proveedor")["Gasto_Total_MXN"]
                         .sum().sort_values(ascending=False))
    top_pct     = float(prov_shares.iloc[0] / prov_shares.sum() * 100) if len(prov_shares) > 0 else 0

    monthly_cat = df_cat.groupby("_Mes")["Gasto_Total_MXN"].sum().sort_index()
    var_pct = None
    if len(monthly_cat) >= 2:
        last      = float(monthly_cat.iloc[-1])
        prior_avg = float(monthly_cat.iloc[:-1].mean())
        var_pct   = (last - prior_avg) / prior_avg * 100 if prior_avg > 0 else None

    var_str   = "—"
    var_color = _BLUE
    if var_pct is not None:
        sign      = "+" if var_pct >= 0 else ""
        var_str   = f"{sign}{var_pct:.1f}%"
        var_color = _GREEN if var_pct <= 0 else (_AMBER if var_pct <= 15 else _RED)

    conc_color  = _GREEN if top_pct < 40 else (_AMBER if top_pct < 60 else _RED)
    provs_color = _AMBER if n_provs == 1 else (_GREEN if n_provs <= 5 else _BLUE)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.markdown(_kpi("Gasto Categoría",       f"${gasto_cat/1e6:,.2f}M",  _BLUE),       unsafe_allow_html=True)
    k2.markdown(_kpi("Variación últ. mes",    var_str,                     var_color),   unsafe_allow_html=True)
    k3.markdown(_kpi("Proveedores activos",   f"{n_provs}",                provs_color), unsafe_allow_html=True)
    k4.markdown(_kpi("Concentración (top 1)", f"{top_pct:.1f}%",           conc_color),  unsafe_allow_html=True)
    k5.markdown(_kpi("Facturas en período",   f"{n_facturas:,}",           _BLUE),       unsafe_allow_html=True)

    st.divider()

    # ── Sección 1: Stacked area mensual por proveedor ─────────────────────────
    st.markdown("### Evolución Mensual por Proveedor")
    st.caption("Composición mensual del gasto — identifica qué proveedor mueve la aguja cada mes.")

    top5_provs   = prov_shares.head(5).index.tolist()
    top5_display = {p: (p[:28] + "…" if len(p) > 30 else p) for p in top5_provs}

    monthly_prov = (
        df_cat.groupby(["_Mes", "Proveedor"])["Gasto_Total_MXN"]
        .sum().reset_index()
    )
    monthly_prov["Grp"] = monthly_prov["Proveedor"].apply(
        lambda p: top5_display.get(p, p) if p in top5_provs else "Otros"
    )
    monthly_grp = (
        monthly_prov.groupby(["_Mes", "Grp"])["Gasto_Total_MXN"]
        .sum().reset_index()
    )

    all_mes  = sorted(df_cat["_Mes"].unique())
    x_labels = [label_mes(m) for m in all_mes]

    grp_order = [top5_display[p] for p in top5_provs
                 if top5_display[p] in monthly_grp["Grp"].values]
    if "Otros" in monthly_grp["Grp"].values:
        grp_order.append("Otros")

    area_colors = _PROV_PALETTE[:5] + ["#BDBDBD"]

    with st.container(border=True):
        fig_area = go.Figure()
        for idx, grp in enumerate(grp_order):
            grp_data = monthly_grp[monthly_grp["Grp"] == grp].set_index("_Mes")
            y_vals = [
                float(grp_data.loc[m, "Gasto_Total_MXN"]) if m in grp_data.index else 0.0
                for m in all_mes
            ]
            color = area_colors[idx % len(area_colors)]
            fig_area.add_trace(go.Scatter(
                x=x_labels, y=y_vals,
                name=grp,
                stackgroup="one",
                mode="lines",
                line=dict(width=0.8, color=color),
                fillcolor=color,
                opacity=0.82,
                hovertemplate=f"<b>{grp}</b><br>%{{x}}: $%{{y:,.0f}} MXN<extra></extra>",
            ))
        fig_area.update_layout(
            title="<b>Gasto Mensual Acumulado por Proveedor</b>",
            template="plotly_white", height=380,
            legend=dict(orientation="h", y=-0.22, x=0, xanchor="left", font=dict(size=10)),
            xaxis_title="", yaxis=dict(tickformat="$,.0f", title="MXN"),
            margin=dict(t=60, b=90, l=80, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_area, use_container_width=True)

    st.divider()

    # ── Sección 2: Mapa de proveedores (scatter) ──────────────────────────────
    st.markdown("### Mapa de Proveedores")
    st.caption(
        "Eje X = participación en la categoría · Eje Y = número de facturas · "
        "Tamaño de burbuja = ticket promedio. "
        "Haz clic en una burbuja para ver el detalle del proveedor."
    )

    sc_agg = (
        df_cat.groupby("Proveedor")
        .agg(gasto=("Gasto_Total_MXN", "sum"),
             facturas=("Gasto_Total_MXN", "count"),
             ticket_prom=("Gasto_Total_MXN", "mean"))
        .reset_index()
    )
    sc_agg["share_pct"] = sc_agg["gasto"] / sc_agg["gasto"].sum() * 100

    t_min, t_max = sc_agg["ticket_prom"].min(), sc_agg["ticket_prom"].max()
    sc_agg["bubble_sz"] = (
        12 + 48 * (sc_agg["ticket_prom"] - t_min) / (t_max - t_min)
        if t_max > t_min else pd.Series([30.0] * len(sc_agg))
    )
    sc_agg["label_disp"] = sc_agg["Proveedor"].apply(
        lambda p: p[:22] + "…" if len(p) > 24 else p
    )

    med_share = float(sc_agg["share_pct"].median())
    med_fact  = float(sc_agg["facturas"].median())

    with st.container(border=True):
        fig_sc = go.Figure()
        for _, row in sc_agg.iterrows():
            fig_sc.add_trace(go.Scatter(
                x=[row["share_pct"]], y=[row["facturas"]],
                mode="markers+text",
                name=row["label_disp"],
                text=[row["label_disp"]],
                textposition="top center",
                textfont=dict(size=9, color="#374151"),
                marker=dict(
                    size=row["bubble_sz"],
                    color=PALETA_CATEGORIAS.get(categoria, _BLUE),
                    opacity=0.72,
                    line=dict(color="white", width=1.5),
                ),
                customdata=[[row["Proveedor"], row["gasto"], row["ticket_prom"]]],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Share: %{x:.1f}%<br>"
                    "Facturas: %{y}<br>"
                    "Ticket prom.: $%{customdata[2]:,.0f}<br>"
                    "Gasto total: $%{customdata[1]:,.0f}<extra></extra>"
                ),
                showlegend=False,
            ))

        x_max_sc = sc_agg["share_pct"].max() * 1.18
        y_max_sc = sc_agg["facturas"].max()   * 1.28

        fig_sc.add_vline(x=med_share, line_dash="dot", line_color="#CBD5E1", line_width=1)
        fig_sc.add_hline(y=med_fact,  line_dash="dot", line_color="#CBD5E1", line_width=1)

        for label_q, qx, qy in [
            ("Dominante",   x_max_sc * 0.82, y_max_sc * 0.93),
            ("Estratégico", x_max_sc * 0.82, y_max_sc * 0.07),
            ("Rutinario",   x_max_sc * 0.05, y_max_sc * 0.93),
            ("Marginal",    x_max_sc * 0.05, y_max_sc * 0.07),
        ]:
            fig_sc.add_annotation(
                x=qx, y=qy, text=f"<i>{label_q}</i>",
                showarrow=False, font=dict(size=9, color="#9CA3AF"),
            )

        fig_sc.update_layout(
            title="<b>Mapa de Proveedores — Participación vs. Frecuencia</b>",
            template="plotly_white", height=420,
            xaxis=dict(title="Participación en categoría (%)", ticksuffix="%",
                       range=[0, x_max_sc]),
            yaxis=dict(title="Número de facturas", range=[0, y_max_sc]),
            margin=dict(t=70, b=60, l=70, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )

        sc_event = st.plotly_chart(
            fig_sc, use_container_width=True,
            on_select="rerun", key="cat_scatter",
        )
        if sc_event and sc_event.selection and sc_event.selection.points:
            pt = sc_event.selection.points[0]
            cd = pt.get("customdata", [None]) if isinstance(pt, dict) else getattr(pt, "customdata", [None])
            if cd and cd[0]:
                st.session_state["drill_proveedor"] = cd[0]
                del st.session_state["drill_categoria"]
                st.rerun()

    st.divider()

    # ── Sección 3: Cascada MoM ────────────────────────────────────────────────
    st.markdown("### Variación Mes a Mes")
    st.caption("Cada barra muestra el cambio vs. el mes anterior — identifica los meses que explican el alza o baja total.")

    if len(monthly_cat) >= 2:
        mc6      = monthly_cat.tail(6)
        mc6_vals = mc6.tolist()
        mc6_x    = [label_mes(m) for m in mc6.index]

        measures = ["absolute"] + ["relative"] * (len(mc6_vals) - 1)
        y_wf     = [mc6_vals[0]] + [mc6_vals[i] - mc6_vals[i - 1]
                                     for i in range(1, len(mc6_vals))]
        texts_wf = [f"${mc6_vals[0]/1e6:,.2f}M"] + [
            f"{'+'if d >= 0 else ''}${d/1e6:,.2f}M" for d in y_wf[1:]
        ]

        with st.container(border=True):
            fig_wf = go.Figure(go.Waterfall(
                x=mc6_x, y=y_wf,
                measure=measures,
                text=texts_wf,
                textposition="outside",
                connector=dict(line=dict(color="#E5E7EB", width=1)),
                increasing=dict(marker=dict(color=_RED)),
                decreasing=dict(marker=dict(color=_GREEN)),
                totals=dict(marker=dict(color=_BLUE)),
                hovertemplate="<b>%{x}</b><br>Δ: $%{y:,.0f} MXN<extra></extra>",
            ))
            fig_wf.update_layout(
                title="<b>Cascada de Gasto Mensual</b>"
                      "<br><sup>Rojo = alza vs. mes anterior · Verde = baja · Azul = punto de partida</sup>",
                template="plotly_white", height=380, showlegend=False,
                yaxis=dict(tickformat="$,.0f", title="MXN"),
                xaxis_title="",
                margin=dict(t=80, b=60, l=80, r=40),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_wf, use_container_width=True)
    else:
        st.caption("*Se requieren al menos 2 meses para mostrar la cascada.*")

    # ── Sección 4: Proxy de precio (solo categorías de insumos) ──────────────
    if categoria in _COMMODITY_CATS and len(prov_shares) >= 2:
        st.divider()
        st.markdown("### Tendencia de Ticket Promedio")
        st.caption(
            "Ticket promedio mensual por proveedor — "
            "un alza sostenida puede indicar inflación de insumos, no mayor volumen de compra."
        )
        top3_provs    = prov_shares.head(3).index.tolist()
        tick_monthly  = (
            df_cat[df_cat["Proveedor"].isin(top3_provs)]
            .groupby(["_Mes", "Proveedor"])["Gasto_Total_MXN"]
            .agg(["sum", "count"]).reset_index()
        )
        tick_monthly.columns = ["_Mes", "Proveedor", "gasto", "n"]
        tick_monthly["ticket"] = tick_monthly["gasto"] / tick_monthly["n"]

        with st.container(border=True):
            fig_tick = go.Figure()
            for idx_t, prov in enumerate(top3_provs):
                pdata = tick_monthly[tick_monthly["Proveedor"] == prov].sort_values("_Mes")
                if len(pdata) < 2:
                    continue
                fig_tick.add_trace(go.Scatter(
                    x=[label_mes(m) for m in pdata["_Mes"]],
                    y=pdata["ticket"].tolist(),
                    name=(prov[:28] + "…" if len(prov) > 30 else prov),
                    mode="lines+markers",
                    line=dict(color=_PROV_PALETTE[idx_t % len(_PROV_PALETTE)], width=2),
                    marker=dict(size=7),
                    hovertemplate="<b>%{fullData.name}</b><br>%{x}: $%{y:,.0f}/factura<extra></extra>",
                ))
            fig_tick.update_layout(
                title="<b>Ticket Promedio Mensual — Top 3 Proveedores</b>",
                template="plotly_white", height=340,
                legend=dict(orientation="h", y=1.08, x=0),
                yaxis=dict(tickformat="$,.0f", title="MXN / factura"),
                xaxis_title="",
                margin=dict(t=80, b=50, l=80, r=20),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_tick, use_container_width=True)

    # ── Tabla resumen de proveedores ──────────────────────────────────────────
    st.divider()
    st.markdown("### Detalle por Proveedor")
    st.caption("Selecciona una fila y usa el botón para navegar al detalle completo del proveedor.")

    tbl_agg = (
        df_cat.groupby("Proveedor")
        .agg(
            gasto=("Gasto_Total_MXN", "sum"),
            facturas=("Gasto_Total_MXN", "count"),
            ticket_prom=("Gasto_Total_MXN", "mean"),
            fecha_min=("Fecha de documento", "min"),
            fecha_max=("Fecha de documento", "max"),
        )
        .reset_index()
        .sort_values("gasto", ascending=False)
        .reset_index(drop=True)
    )
    tbl_agg["pct_cat"] = tbl_agg["gasto"] / tbl_agg["gasto"].sum() * 100
    tbl_agg["Período"]  = tbl_agg.apply(
        lambda r: f"{r['fecha_min'].strftime('%b %Y')} – {r['fecha_max'].strftime('%b %Y')}", axis=1
    )

    def _trend_str(prov):
        pdata = (df_cat[df_cat["Proveedor"] == prov]
                 .groupby("_Mes")["Gasto_Total_MXN"].sum().sort_index())
        if len(pdata) < 2:
            return "—"
        last_v = float(pdata.iloc[-1])
        window = pdata.iloc[-4:-1] if len(pdata) >= 4 else pdata.iloc[:-1]
        prior  = float(window.mean())
        if prior <= 0:
            return "—"
        delta = (last_v - prior) / prior * 100
        return f"+{delta:.0f}%" if delta > 0 else f"{delta:.0f}%"

    tbl_agg["Tendencia"] = tbl_agg["Proveedor"].apply(_trend_str)

    tbl_display = tbl_agg[["Proveedor", "gasto", "pct_cat", "facturas",
                             "ticket_prom", "Período", "Tendencia"]].copy()

    tbl_event = st.dataframe(
        tbl_display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="cat_detail_table",
        column_config={
            "Proveedor":   st.column_config.TextColumn("Proveedor"),
            "gasto":       st.column_config.NumberColumn("Gasto (MXN)", format="$%,.0f"),
            "pct_cat":     st.column_config.NumberColumn("% Categoría", format="%.1f%%"),
            "facturas":    st.column_config.NumberColumn("Facturas"),
            "ticket_prom": st.column_config.NumberColumn("Ticket Prom.", format="$%,.0f"),
            "Período":     st.column_config.TextColumn("Período"),
            "Tendencia":   st.column_config.TextColumn("Tendencia (3m)"),
        },
        height=min(600, 48 + 36 * len(tbl_display)),
    )

    if tbl_event.selection and tbl_event.selection.rows:
        sel_idx  = tbl_event.selection.rows[0]
        sel_prov = tbl_display.iloc[sel_idx]["Proveedor"]
        col_nav, _ = st.columns([3, 5])
        with col_nav:
            disp = sel_prov[:32] + ("…" if len(sel_prov) > 32 else "")
            if st.button(f"Ver detalle: {disp} →",
                         key="btn_cat_to_prov", type="primary"):
                st.session_state["drill_proveedor"] = sel_prov
                del st.session_state["drill_categoria"]
                st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
#  Vista de detalle inline (drill-down completo)
# ──────────────────────────────────────────────────────────────────────────────
def _render_detalle_proveedor(df_full, df_ctx, proveedor):
    _prov_bc = proveedor if len(proveedor) <= 50 else proveedor[:49] + "…"
    breadcrumb([
        ("Compras", {"clear": ["drill_proveedor", "curva_semanal_chart"]}, None),
        (_prov_bc, None, None),
    ])

    df = df_full[df_full["Proveedor"] == proveedor].copy()
    if len(df) == 0:
        st.error(f"No se encontraron facturas para **{proveedor}**.")
        return

    categoria   = df["Categoria"].iloc[0]
    gasto_total = df["Gasto_Total_MXN"].sum()
    n_facturas  = len(df)
    tick_prom   = df["Gasto_Total_MXN"].mean()
    tick_med    = df["Gasto_Total_MXN"].median()
    fecha_min   = df["Fecha de documento"].min()
    fecha_max   = df["Fecha de documento"].max()
    badge_bg    = PALETA_CATEGORIAS.get(categoria, _GRAY)

    st.markdown(f"<h2 style='margin-bottom:6px'>{proveedor}</h2>", unsafe_allow_html=True)
    st.markdown(
        f"<span style='background:{badge_bg};color:white;padding:3px 12px;"
        f"border-radius:12px;font-size:.82rem;font-weight:600'>{categoria}</span>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='margin-top:1rem'></div>", unsafe_allow_html=True)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.markdown(_kpi("Gasto Total",  f"${gasto_total/1e6:,.2f}M",                   _GREEN), unsafe_allow_html=True)
    k2.markdown(_kpi("Facturas",     f"{n_facturas:,}",                              _BLUE),  unsafe_allow_html=True)
    k3.markdown(_kpi("Ticket Prom.", f"${tick_prom:,.0f}",                           _GREEN), unsafe_allow_html=True)
    k4.markdown(_kpi("Ticket Med.",  f"${tick_med:,.0f}",                            _GREEN), unsafe_allow_html=True)
    k5.markdown(_kpi("Periodo",
        f"{fecha_min.strftime('%b %Y')} – {fecha_max.strftime('%b %Y')}",           _BLUE),  unsafe_allow_html=True)

    # ── Contexto en su categoría ──────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### Contexto en su categoría — {categoria}")
    st.caption(
        "Comparativa con los demás proveedores de la misma categoría "
        "en el periodo actualmente filtrado."
    )
    _render_intra_cat(df_ctx, proveedor, categoria)

    # ── Gasto mensual (historial completo) ────────────────────────────────────
    st.divider()
    df_mes = (df.groupby("_Mes", as_index=False)["Gasto_Total_MXN"]
                .sum().sort_values("_Mes"))
    df_mes["Mes"] = df_mes["_Mes"].apply(label_mes)

    with st.container(border=True):
        fig = px.bar(
            df_mes, x="Mes", y="Gasto_Total_MXN",
            title=f"<b>Gasto Mensual — {proveedor}</b> (historial completo)",
            color_discrete_sequence=[COLOR_LYON], text="Gasto_Total_MXN",
        )
        fig.update_traces(
            texttemplate="$%{text:,.0f}", textposition="outside",
            hovertemplate="<b>%{x}</b><br>$%{y:,.0f} MXN<extra></extra>",
        )
        fig.update_layout(
            template="plotly_white", height=380, showlegend=False,
            xaxis_title="", yaxis_title="Gasto (MXN)",
            margin=dict(t=80, b=40, l=60, r=40),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        fig.update_yaxes(tickformat=",.0f", tickprefix="$")
        st.plotly_chart(fig, use_container_width=True)

    # ── Todas las facturas ────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("##### Todas las Facturas")
        tbl = df[["Fecha de documento", "Referencia factura", "Gasto_Total_MXN"]].copy()
        tbl["Fecha de documento"] = tbl["Fecha de documento"].dt.strftime("%d-%b-%Y")
        tbl = tbl.sort_values("Gasto_Total_MXN", ascending=False).reset_index(drop=True)
        tbl.index = tbl.index + 1
        st.dataframe(
            tbl, use_container_width=True, hide_index=False,
            column_config={
                "Fecha de documento": st.column_config.TextColumn("Fecha"),
                "Referencia factura": st.column_config.TextColumn("Referencia"),
                "Gasto_Total_MXN":    st.column_config.NumberColumn("Gasto (MXN)", format="$%,.2f"),
            },
            height=min(600, 48 + 36 * len(tbl)),
        )


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    render_sidebar_search()
    render_sidebar_status()

st.markdown(
    f"<h1 style='color:{COLOR_LYON}'>"
    "<span class='material-symbols-outlined'>receipt_long</span>Compras</h1>",
    unsafe_allow_html=True,
)

# ── Upload ────────────────────────────────────────────────────────────────────
if "df_compras" not in st.session_state:
    st.markdown("Sube el archivo SAE de compras para ver el dashboard.")
    uploaded = st.file_uploader(
        "Archivo SAE de Compras",
        type=["xlsx", "xlsm", "xls"],
        label_visibility="collapsed",
    )
    if uploaded:
        with st.spinner("Procesando archivo…"):
            try:
                df_raw, warns = cargar_compras(uploaded)
                st.session_state.df_compras = df_raw
                st.session_state.df_compras_meta = {
                    "archivo":     uploaded.name,
                    "uploaded_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "total_rows":  len(df_raw),
                }
                for w in warns:
                    st.warning(w)
                st.success(f"✅ {len(df_raw):,} facturas cargadas.")
                st.rerun()
            except ValueError as e:
                st.error(f"Error al procesar el archivo:\n\n{e}")
    st.stop()

# ── Dashboard ─────────────────────────────────────────────────────────────────

meta = st.session_state.df_compras_meta
st.caption(
    f"Archivo: **{meta['archivo']}**  ·  "
    f"{meta['total_rows']:,} facturas  ·  "
    f"Cargado: {meta['uploaded_at']}"
)

df_full = aplicar_clasificaciones(st.session_state.df_compras)

# ── Sidebar filters ───────────────────────────────────────────────────────────
meses_disponibles = sorted(df_full["_Mes"].unique())
cats_opciones     = [ETIQ_PENDIENTE] + CATALOGO_CATEGORIAS

with st.sidebar:
    st.markdown("### Filtros")
    meses_sel = render_periodo_filter("cmp", meses_disponibles)

    st.markdown("**Categorías**")
    cats_sel = []
    for cat in cats_opciones:
        if st.checkbox(cat, value=True, key=f"cmp_cat_{cat}"):
            cats_sel.append(cat)

    st.markdown("---")
    if st.button("🗑 Borrar datos y volver a subir", use_container_width=True):
        for key in ("df_compras", "df_compras_meta"):
            st.session_state.pop(key, None)
        st.rerun()

# ── Modo drill-down (antes del guard de meses vacíos para no bloquear vistas activas) ──
_drill_ctx = df_full[df_full["_Mes"].isin(meses_sel)].copy() if meses_sel else df_full
if st.session_state.get("drill_proveedor"):
    _render_detalle_proveedor(df_full, _drill_ctx, st.session_state["drill_proveedor"])
    st.stop()
if st.session_state.get("drill_categoria"):
    _render_detalle_categoria(df_full, _drill_ctx, st.session_state["drill_categoria"])
    st.stop()
if st.session_state.get("drill_semana"):
    _render_detalle_semana(df_full, _drill_ctx, st.session_state["drill_semana"])
    st.stop()

if not meses_sel:
    st.warning("Selecciona al menos un mes.")
    st.stop()

# df_ctx: filtrado solo por meses (para comparativas intra-categoría)
df_ctx = _drill_ctx  # already computed; meses_sel is non-empty at this point
# df: filtrado por meses Y categorías (para el dashboard principal)
df = df_ctx[df_ctx["Categoria"].isin(cats_sel)].copy()

if len(df) == 0:
    st.warning("No hay datos para los filtros seleccionados.")
    st.stop()

# ── KPIs ──────────────────────────────────────────────────────────────────────
gasto_total     = df["Gasto_Total_MXN"].sum()
total_facturas  = len(df)
ticket_promedio = df["Gasto_Total_MXN"].mean()
ticket_mediano  = df["Gasto_Total_MXN"].median()
prov_unicos     = df["Proveedor"].nunique()

mask_clasificado  = df["Categoria"] != ETIQ_PENDIENTE
gasto_clasificado = df.loc[mask_clasificado, "Gasto_Total_MXN"].sum()
pct_cobertura     = gasto_clasificado / gasto_total * 100 if gasto_total else 0
prov_pendientes   = df.loc[~mask_clasificado, "Proveedor"].nunique()

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.markdown(_kpi("Gasto Total",      f"${gasto_total/1e6:,.2f}M", _GREEN), unsafe_allow_html=True)
k2.markdown(_kpi("Facturas",         f"{total_facturas:,}",        _BLUE),  unsafe_allow_html=True)
k3.markdown(_kpi("Ticket Promedio",  f"${ticket_promedio:,.0f}",   _GREEN), unsafe_allow_html=True)
k4.markdown(_kpi("Ticket Mediano",   f"${ticket_mediano:,.0f}",    _GREEN), unsafe_allow_html=True)
k5.markdown(_kpi("Proveedores",      f"{prov_unicos:,}",           _BLUE),  unsafe_allow_html=True)
k6.markdown(_kpi("Cobertura Categ.", f"{pct_cobertura:.1f}%",      _BLUE),  unsafe_allow_html=True)

st.divider()

# ── Gráficas ──────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.plotly_chart(
        plot_donut_categorias(df, gasto_total, pct_cobertura, prov_pendientes),
        use_container_width=True,
    )

    # Clickable pills — nav mechanism
    cats_presentes = [c for c in CATALOGO_CATEGORIAS if c in df["Categoria"].values]
    if cats_presentes:
        st.caption("Selecciona una categoría para ver el análisis detallado:")
        PILLS_PER_ROW = 4
        for row_start in range(0, len(cats_presentes), PILLS_PER_ROW):
            chunk     = cats_presentes[row_start:row_start + PILLS_PER_ROW]
            pill_cols = st.columns(len(chunk))
            for j, cat in enumerate(chunk):
                with pill_cols[j]:
                    if st.button(cat, key=f"pill_cat_{cat}", use_container_width=True):
                        st.session_state["drill_categoria"] = cat
                        st.rerun()

with st.container(border=True):
    sem_event = st.plotly_chart(
        plot_curva_semanal_compras(df),
        use_container_width=True,
        on_select="rerun",
        key="curva_semanal_chart",
    )
    st.caption("Haz clic en cualquier punto de la curva para ver el desglose detallado de esa semana.")
    if sem_event and sem_event.selection and sem_event.selection.points:
        pt        = sem_event.selection.points[0]
        clicked_x = pt.get("x", "") if isinstance(pt, dict) else getattr(pt, "x", "")
        if clicked_x:
            st.session_state["drill_semana"] = str(clicked_x)
            st.session_state.pop("curva_semanal_chart", None)
            st.toast("Cargando detalle de la semana…", icon="⏳")
            st.rerun()

with st.container(border=True):
    st.plotly_chart(plot_pareto_proveedores(df, gasto_total), use_container_width=True)

fig_pend = plot_pendientes_clasificar(df, pct_cobertura)
if fig_pend is not None:
    with st.container(border=True):
        st.plotly_chart(fig_pend, use_container_width=True)

# ── Compras por Categoría — ANCHO COMPLETO ───────────────────────────────────
st.divider()
st.markdown("### Compras por Categoría")
_cat_df = (df.groupby("Categoria", as_index=False)["Gasto_Total_MXN"]
              .sum().sort_values("Gasto_Total_MXN", ascending=True))
_cat_df["_Pct"]   = _cat_df["Gasto_Total_MXN"] / gasto_total * 100 if gasto_total > 0 else 0
_cat_df["_Color"] = _cat_df["Categoria"].apply(lambda c: PALETA_CATEGORIAS.get(c, _GRAY))

with st.container(border=True):
    _n_bars     = len(_cat_df)
    _bar_height = max(420, 65 * _n_bars + 100)
    _fig_cat = go.Figure(go.Bar(
        x=_cat_df["Gasto_Total_MXN"],
        y=_cat_df["Categoria"],
        orientation="h",
        marker_color=_cat_df["_Color"].tolist(),
        text=_cat_df.apply(
            lambda r: f"  ${r['Gasto_Total_MXN']/1e6:,.2f}M  ({r['_Pct']:.1f}%)", axis=1
        ),
        textposition="outside",
        customdata=_cat_df[["Categoria", "_Pct"]].values,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "$%{x:,.0f}  ·  %{customdata[1]:.1f}% del gasto<extra></extra>"
        ),
    ))
    _fig_cat.update_layout(
        title="<b>Compras por Categoría — Total Periodo</b>",
        template="plotly_white", height=_bar_height, showlegend=False,
        xaxis=dict(tickformat="$,.0f", title="Gasto (MXN)"),
        yaxis_title="",
        margin=dict(t=60, b=40, l=240, r=180),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(_fig_cat, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
#  DONUTS DE CONCENTRACIÓN POR CATEGORÍA
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("### Concentración de Proveedores por Categoría")
st.caption(
    "Una categoría dominada por 1–2 proveedores representa un riesgo operativo: "
    "si ese proveedor falla, la operación se detiene. "
    "Se muestran solo categorías con 2 o más proveedores activos en el periodo."
)

cats_resumen = (
    df_ctx[df_ctx["Categoria"] != ETIQ_PENDIENTE]
    .groupby("Categoria")
    .agg(gasto=("Gasto_Total_MXN", "sum"), n_prov=("Proveedor", "nunique"))
    .reset_index()
    .query("n_prov >= 2 and gasto > 0")
    .sort_values("gasto", ascending=False)
)

if len(cats_resumen) == 0:
    st.info(
        "Clasifica proveedores para ver la concentración por categoría. "
        "Cada categoría necesita al menos 2 proveedores."
    )
else:
    COLS_PER_ROW = 3
    for row_start in range(0, len(cats_resumen), COLS_PER_ROW):
        chunk   = cats_resumen.iloc[row_start:row_start + COLS_PER_ROW]
        n_chunk = len(chunk)
        cols    = st.columns(n_chunk)

        for col_idx, (_, cat_row) in enumerate(chunk.iterrows()):
            cat        = cat_row["Categoria"]
            df_cat_sub = df_ctx[df_ctx["Categoria"] == cat]
            prov_rank  = (df_cat_sub.groupby("Proveedor")["Gasto_Total_MXN"]
                                    .sum().sort_values(ascending=False))

            top4   = prov_rank.head(4)
            resto  = prov_rank.iloc[4:].sum()
            total_cat = prov_rank.sum()

            labels = [p[:24] + "…" if len(p) > 26 else p for p in top4.index]
            values = list(top4.values)
            if resto > 0:
                labels.append("Otros")
                values.append(resto)

            pct_top1 = float(top4.iloc[0]) / total_cat * 100 if total_cat > 0 else 0
            umbral   = 65 if cat in _CRITICAS else 75
            color_badge  = _GREEN if pct_top1 < 40 else (_AMBER if pct_top1 < umbral else _RED)
            estado_badge = ("Baja concentración" if pct_top1 < 40
                            else ("Concentración media" if pct_top1 < umbral
                                  else "Alta concentración"))

            slice_colors = _PROV_PALETTE[:len(top4)] + (["#BDBDBD"] if resto > 0 else [])
            cat_color    = PALETA_CATEGORIAS.get(cat, _GRAY)

            with cols[col_idx]:
                with st.container(border=True):
                    st.markdown(
                        f"<div style='margin-bottom:4px'>"
                        f"<span style='background:{cat_color};color:#fff;padding:2px 9px;"
                        f"border-radius:10px;font-size:.70rem;font-weight:700'>{cat}</span>"
                        f"&nbsp;"
                        f"<span style='background:{color_badge};color:#fff;padding:2px 9px;"
                        f"border-radius:10px;font-size:.68rem'>{estado_badge}</span>"
                        f"</div>"
                        f"<p style='margin:2px 0 0;font-size:.73rem;color:#6B7280'>"
                        f"${total_cat/1e6:,.2f}M · {cat_row['n_prov']:.0f} proveedores"
                        f"</p>",
                        unsafe_allow_html=True,
                    )
                    fig_cat = go.Figure(go.Pie(
                        labels=labels, values=values,
                        hole=0.48,
                        marker=dict(colors=slice_colors,
                                    line=dict(color="#fff", width=2)),
                        textinfo="percent", textfont_size=11,
                        sort=False,
                        hovertemplate=(
                            "<b>%{label}</b><br>"
                            "$%{value:,.0f}  ·  %{percent}<extra></extra>"
                        ),
                    ))
                    fig_cat.update_layout(
                        showlegend=True,
                        legend=dict(
                            orientation="v", x=1.0, y=0.5, xanchor="left",
                            font=dict(size=9), itemwidth=30,
                        ),
                        height=330,
                        margin=dict(t=12, b=12, l=12, r=140),
                        paper_bgcolor="rgba(0,0,0,0)",
                    )
                    st.plotly_chart(fig_cat, use_container_width=True)

# ── Top 10 Facturas ───────────────────────────────────────────────────────────
st.divider()
with st.container(border=True):
    st.markdown("##### Top 10 Facturas Individuales por Monto")
    st.caption("Identifica inyecciones fuertes de capital (CapEx) y compras masivas")

    top_cols = ["Proveedor", "Fecha de documento", "Referencia factura",
                "Gasto_Total_MXN", "Categoria"]
    top = df.nlargest(10, "Gasto_Total_MXN")[top_cols].copy().reset_index(drop=True)
    top["Fecha de documento"] = top["Fecha de documento"].dt.strftime("%d-%b-%Y")
    top.index = top.index + 1

    st.dataframe(
        top, use_container_width=True, hide_index=False,
        column_config={
            "Proveedor":          st.column_config.TextColumn("Proveedor"),
            "Fecha de documento": st.column_config.TextColumn("Fecha"),
            "Referencia factura": st.column_config.TextColumn("Referencia"),
            "Gasto_Total_MXN":    st.column_config.NumberColumn("Gasto (MXN)", format="$%,.2f"),
            "Categoria":          st.column_config.TextColumn("Categoría"),
        },
        height=410,
    )

# ── Drill-down selector ───────────────────────────────────────────────────────
st.divider()
st.markdown("#### Drill-down — Detalle de proveedor")

all_provs = (
    df_full.groupby("Proveedor")["Gasto_Total_MXN"]
           .sum().sort_values(ascending=False).index.tolist()
)

dd_busq = st.text_input(
    "Buscar proveedor",
    placeholder="Escribe parte del nombre para filtrar…",
    key="dd_busq_prov",
    label_visibility="collapsed",
)
filtered_provs = (
    [p for p in all_provs if dd_busq.upper() in p.upper()]
    if dd_busq else all_provs
)

if filtered_provs:
    dd_c1, dd_c2 = st.columns([4, 1])
    with dd_c1:
        prov_sel = st.selectbox(
            "", filtered_provs, key="dd_prov", label_visibility="collapsed"
        )
    with dd_c2:
        if st.button("Ver detalle →", key="btn_dd_prov",
                     use_container_width=True, type="primary"):
            st.session_state["drill_proveedor"] = prov_sel
            st.session_state.pop("drill_categoria", None)
            st.rerun()
else:
    st.caption("Sin resultados para esa búsqueda.")
