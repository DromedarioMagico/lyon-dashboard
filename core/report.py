"""Executive HTML report generator — self-contained HTML with inline Plotly.js."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from core.catalogos import (
    COLOR_LYON, COLOR_VENTAS, ETIQ_PENDIENTE,
    PALETA_CATEGORIAS, label_mes,
)
from core.etl_compras import aplicar_clasificaciones
from core.etl_ventas import aplicar_vendedores
from core.plots import (
    plot_donut_categorias,
    plot_curva_semanal_compras,
    plot_pareto_proveedores,
    plot_pendientes_clasificar,
    plot_top_facturas,
    plot_donut_clientes_ventas,
    plot_donut_resto_clientes,
    plot_curva_semanal_ventas,
    plot_pareto_clientes_ventas,
    plot_ventas_por_vendedor,
    plot_heatmap_cliente_mes,
)

_BLUE  = COLOR_LYON
_GREEN = COLOR_VENTAS
_RED   = "#C00000"
_AMBER = "#E97132"
_GRAY  = "#9E9E9E"

_COSTOS_DIRECTOS = [
    "Sustratos (Papel)", "Pre-prensa y Químicos", "Encuadernación",
    "Insumos de Producción", "Maquila",
]
_OVERHEAD = [
    "Mantenimiento y Refacciones", "Logística / Fletes", "Almacenaje y Renta",
    "Limpieza y Sanitarios", "Servicios Profesionales", "Otros / Sin clasificar",
]
_CRITICAS     = {"Sustratos (Papel)", "Mantenimiento y Refacciones", "Pre-prensa y Químicos"}
_SEMANA_ORDER = ["S1 (1–7)", "S2 (8–14)", "S3 (15–21)", "S4 (22+)"]


# ── helpers ──────────────────────────────────────────────────────────────────

def _fig_html(fig: go.Figure, include_js: bool = False) -> str:
    return fig.to_html(
        include_plotlyjs=include_js,
        full_html=False,
        config={"displayModeBar": False, "responsive": True},
    )


def _fmt_m(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v / 1e6:,.2f}M"
    if abs(v) >= 1_000:
        return f"${v / 1e3:,.0f}K"
    return f"${v:,.0f}"


def _semana(dia: int) -> str:
    if dia <= 7:  return "S1 (1–7)"
    if dia <= 14: return "S2 (8–14)"
    if dia <= 21: return "S3 (15–21)"
    return "S4 (22+)"


# ── main entry point ─────────────────────────────────────────────────────────

def generate_report_html(
    df_compras_raw: pd.DataFrame,
    df_ventas_raw: pd.DataFrame,
    meta_compras: dict | None = None,
    meta_ventas: dict | None = None,
    on_progress=None,          # callable(step: int, total: int, label: str) | None
    meses_filtrar: list | None = None,  # List[Period] from sidebar filter
) -> str:
    meta_compras = meta_compras or {}
    meta_ventas  = meta_ventas  or {}

    # ── ETL ──────────────────────────────────────────────────────────────────
    df_c = aplicar_clasificaciones(df_compras_raw)
    df_v = aplicar_vendedores(df_ventas_raw.copy())

    meses_comunes = sorted(set(df_c["_Mes"].unique()) & set(df_v["_Mes"].unique()))
    if meses_filtrar:
        _filtro_set = set(meses_filtrar)
        meses_comunes = [m for m in meses_comunes if m in _filtro_set]
    if not meses_comunes:
        return "<html><body><p>Sin datos en periodo común.</p></body></html>"

    df_cf = df_c[df_c["_Mes"].isin(meses_comunes)].copy()
    df_vf = df_v[df_v["_Mes"].isin(meses_comunes)].copy()

    periodo   = f"{label_mes(meses_comunes[0])} – {label_mes(meses_comunes[-1])}"
    fecha_gen = datetime.now().strftime("%d %b %Y  %H:%M")

    # ── Global metrics ────────────────────────────────────────────────────────
    total_ventas  = df_vf["Importe_MXN"].sum()
    total_compras = df_cf["Gasto_Total_MXN"].sum()
    gasto_total   = total_compras
    margen        = total_ventas - total_compras
    margen_pct    = margen / total_ventas * 100        if total_ventas  > 0 else 0
    ratio_cv      = total_compras / total_ventas * 100 if total_ventas  > 0 else 0
    gasto_dir     = df_cf[df_cf["Categoria"].isin(_COSTOS_DIRECTOS)]["Gasto_Total_MXN"].sum()
    gasto_ovh     = df_cf[df_cf["Categoria"].isin(_OVERHEAD)]["Gasto_Total_MXN"].sum()
    pct_dir       = gasto_dir / total_ventas * 100 if total_ventas > 0 else 0
    pct_ovh       = gasto_ovh / total_ventas * 100 if total_ventas > 0 else 0

    # Compras: coverage
    gasto_clas   = df_cf[df_cf["Categoria"] != ETIQ_PENDIENTE]["Gasto_Total_MXN"].sum()
    pct_cobertura   = gasto_clas / total_compras * 100 if total_compras > 0 else 0
    prov_pendientes = int(df_cf[df_cf["Categoria"] == ETIQ_PENDIENTE]["Proveedor"].nunique())

    # Ventas: n_clientes_80pct
    cli_rank = df_vf.groupby("Cliente_Nombre")["Importe_MXN"].sum().sort_values(ascending=False)
    if total_ventas > 0:
        cum_pct = cli_rank.cumsum() / total_ventas * 100
        n_clientes_80pct = int((cum_pct < 80).sum()) + 1
    else:
        n_clientes_80pct = 1

    # Monthly aggregation
    mes_c = (df_cf.groupby("_Mes", as_index=False)["Gasto_Total_MXN"]
                   .sum().rename(columns={"Gasto_Total_MXN": "Compras"}))
    mes_v = (df_vf.groupby("_Mes", as_index=False)["Importe_MXN"]
                   .sum().rename(columns={"Importe_MXN": "Ventas"}))
    mes_df = pd.merge(mes_v, mes_c, on="_Mes", how="outer").sort_values("_Mes").fillna(0)
    mes_df["Mes"]        = mes_df["_Mes"].apply(label_mes)
    mes_df["Margen"]     = mes_df["Ventas"] - mes_df["Compras"]
    mes_df["Margen_pct"] = mes_df.apply(
        lambda r: r["Margen"] / r["Ventas"] * 100 if r["Ventas"] > 0 else 0, axis=1
    )

    # Vendedores aggregation (shared by chart + table)
    vend = (
        df_vf[df_vf["Vendedor"] != "Sin asignar"]
        .groupby("Vendedor")
        .agg(Ventas_Brutas=("Importe_MXN", "sum"),
             Comisiones=("Comision_MXN", "sum"),
             Pedidos=("Importe_MXN", "count"))
        .reset_index()
    )
    if len(vend) > 0:
        vend["Ratio_Comision"] = vend.apply(
            lambda r: r["Comisiones"] / r["Ventas_Brutas"] * 100
                      if r["Ventas_Brutas"] > 0 else 0,
            axis=1,
        )

    # ═════════════════════════════════════════════════════════════════════════
    #  SECTION 2 — COMPRAS (plots.py functions)
    # ═════════════════════════════════════════════════════════════════════════
    fig_donut_cat   = plot_donut_categorias(df_cf, gasto_total, pct_cobertura, prov_pendientes)
    fig_curva_comp  = plot_curva_semanal_compras(df_cf)
    fig_pareto_prov = plot_pareto_proveedores(df_cf, gasto_total)
    fig_top_fact    = plot_top_facturas(df_cf)
    fig_pendientes  = plot_pendientes_clasificar(df_cf, pct_cobertura)

    # Compras por categoría — horizontal bar (inline)
    cat_tot = (df_cf.groupby("Categoria", as_index=False)["Gasto_Total_MXN"]
                    .sum().sort_values("Gasto_Total_MXN", ascending=True))
    cat_tot["Pct"]   = cat_tot["Gasto_Total_MXN"] / total_compras * 100 if total_compras > 0 else 0
    cat_tot["Color"] = cat_tot["Categoria"].apply(lambda c: PALETA_CATEGORIAS.get(c, _GRAY))
    _n_cats = len(cat_tot)
    fig_cat_bar = go.Figure(go.Bar(
        x=cat_tot["Gasto_Total_MXN"], y=cat_tot["Categoria"], orientation="h",
        marker_color=cat_tot["Color"].tolist(),
        text=cat_tot.apply(
            lambda r: f"  ${r['Gasto_Total_MXN']/1e6:,.2f}M  ({r['Pct']:.1f}%)", axis=1),
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
    ))
    fig_cat_bar.update_layout(
        title="<b>Compras por Categoría — Total Período</b>",
        template="plotly_white",
        height=max(420, 65 * _n_cats + 100),
        showlegend=False,
        xaxis=dict(tickformat="$,.0f"),
        margin=dict(t=60, b=40, l=260, r=200),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )

    # ═════════════════════════════════════════════════════════════════════════
    #  SECTION 3 — VENTAS (plots.py functions)
    # ═════════════════════════════════════════════════════════════════════════
    fig_donut_cli   = plot_donut_clientes_ventas(df_vf, total_ventas, n_clientes_80pct)
    fig_donut_resto = plot_donut_resto_clientes(df_vf, total_ventas)
    fig_curva_vent  = plot_curva_semanal_ventas(df_vf)
    fig_pareto_cli  = plot_pareto_clientes_ventas(df_vf, total_ventas)
    fig_vend_bar    = plot_ventas_por_vendedor(df_vf, total_ventas)
    fig_heatmap_cm  = plot_heatmap_cliente_mes(df_vf)

    # ═════════════════════════════════════════════════════════════════════════
    #  SECTION 5 — VENDEDORES productivity (inline)
    # ═════════════════════════════════════════════════════════════════════════
    fig_productividad = None
    if len(vend) > 0:
        vs = vend.sort_values("Ventas_Brutas", ascending=True)
        fig_productividad = go.Figure()
        fig_productividad.add_trace(go.Bar(
            x=vs["Ventas_Brutas"], y=vs["Vendedor"], name="Ventas Brutas",
            orientation="h", marker_color=_GREEN,
            hovertemplate="<b>%{y}</b><br>Ventas: $%{x:,.0f}<extra></extra>",
        ))
        fig_productividad.add_trace(go.Bar(
            x=vs["Comisiones"], y=vs["Vendedor"], name="Comisiones",
            orientation="h", marker_color=_RED, opacity=0.85,
            customdata=vs["Ratio_Comision"].values,
            hovertemplate="<b>%{y}</b><br>Comisión: $%{x:,.0f} (%{customdata:.1f}%)<extra></extra>",
        ))
        fig_productividad.update_layout(
            title="<b>Ventas Brutas vs Comisiones por Vendedor</b>",
            barmode="overlay", template="plotly_white",
            height=max(400, 90 + 65 * len(vend)),
            legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center"),
            xaxis=dict(tickformat="$,.0f"),
            margin=dict(t=85, b=40, l=180, r=40),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )

    # ═════════════════════════════════════════════════════════════════════════
    #  SECTION 4 — COMPARATIVA (inline)
    # ═════════════════════════════════════════════════════════════════════════

    # Ventas vs Compras + Margen %
    c1 = go.Figure()
    c1.add_trace(go.Bar(x=mes_df["Mes"], y=mes_df["Ventas"], name="Ventas",
                        marker_color=_GREEN,
                        hovertemplate="<b>%{x}</b><br>Ventas: $%{y:,.0f}<extra></extra>"))
    c1.add_trace(go.Bar(x=mes_df["Mes"], y=mes_df["Compras"], name="Compras",
                        marker_color=_BLUE,
                        hovertemplate="<b>%{x}</b><br>Compras: $%{y:,.0f}<extra></extra>"))
    _mp_min = min(float(mes_df["Margen_pct"].min()) - 10, -5)
    _mp_max = float(mes_df["Margen_pct"].max()) + 15
    c1.add_trace(go.Scatter(
        x=mes_df["Mes"], y=mes_df["Margen_pct"], name="Margen %", yaxis="y2",
        mode="lines+markers", line=dict(color=_AMBER, width=2.5, dash="dot"),
        marker=dict(size=8),
        hovertemplate="<b>%{x}</b><br>Margen: %{y:.1f}%<extra></extra>",
    ))
    c1.update_layout(
        title="<b>Ventas vs Compras por Mes</b>",
        barmode="group", template="plotly_white", height=460,
        legend=dict(orientation="h", y=1.14, x=0.5, xanchor="center"),
        yaxis=dict(title="MXN", tickformat="$,.0f"),
        yaxis2=dict(title="Margen %", overlaying="y", side="right",
                    ticksuffix="%", showgrid=False, range=[_mp_min, _mp_max]),
        margin=dict(t=95, b=40, l=80, r=80),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )

    # Margen bruto mensual
    bar_colors = [
        "rgba(84,130,53,0.85)" if v >= 0 else "rgba(192,0,0,0.85)"
        for v in mes_df["Margen"]
    ]
    c2 = go.Figure(go.Bar(
        x=mes_df["Mes"], y=mes_df["Margen"], marker_color=bar_colors,
        text=mes_df["Margen"].apply(_fmt_m),
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Margen: $%{y:,.0f}<extra></extra>",
    ))
    c2.add_hline(y=0, line_color="#6B7280", line_width=1)
    c2.update_layout(
        title="<b>Margen Bruto Mensual</b>",
        template="plotly_white", height=400, showlegend=False,
        yaxis=dict(tickformat="$,.0f"),
        margin=dict(t=60, b=40, l=90, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )

    # Gasto por categoría % de ventas — legend on the RIGHT to avoid tiny chart area
    cat_mes = df_cf.groupby(["_Mes", "Categoria"])["Gasto_Total_MXN"].sum().reset_index()
    cat_mes = cat_mes.merge(mes_v[["_Mes", "Ventas"]], on="_Mes", how="left")
    cat_mes["Pct"] = cat_mes.apply(
        lambda r: r["Gasto_Total_MXN"] / r["Ventas"] * 100 if r["Ventas"] > 0 else 0, axis=1
    )
    cat_mes["Mes"] = cat_mes["_Mes"].apply(label_mes)
    cats_order = (cat_mes.groupby("Categoria")["Gasto_Total_MXN"]
                          .sum().sort_values(ascending=False).index.tolist())
    c3 = go.Figure()
    for cat in cats_order:
        sub = cat_mes[cat_mes["Categoria"] == cat].sort_values("_Mes")
        c3.add_trace(go.Bar(
            x=sub["Mes"], y=sub["Pct"],
            name=cat if len(cat) <= 24 else cat[:22] + "…",
            marker_color=PALETA_CATEGORIAS.get(cat, _GRAY),
            hovertemplate=f"<b>%{{x}}</b><br>{cat}: %{{y:.1f}}% de ventas<extra></extra>",
        ))
    c3.update_layout(
        title="<b>Gasto por Categoría como % de Ventas del Mes</b>",
        barmode="stack", template="plotly_white", height=500,
        legend=dict(orientation="v", x=1.01, y=0.5, xanchor="left",
                    yanchor="middle", font=dict(size=10)),
        yaxis=dict(ticksuffix="%"),
        margin=dict(t=60, b=40, l=60, r=240),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )

    # ═════════════════════════════════════════════════════════════════════════
    #  SECTION 6 — PATRONES TEMPORALES (heatmaps)
    # ═════════════════════════════════════════════════════════════════════════
    df_cf["_sem"] = df_cf["Fecha de documento"].dt.day.apply(_semana)
    df_vf["_sem"] = df_vf["Fecha"].dt.day.apply(_semana)

    piv_c = (df_cf.pivot_table(values="Gasto_Total_MXN", index="_Mes",
                                columns="_sem", aggfunc="sum", fill_value=0).sort_index())
    piv_v = (df_vf.pivot_table(values="Importe_MXN", index="_Mes",
                                columns="_sem", aggfunc="sum", fill_value=0).sort_index())
    for piv in [piv_c, piv_v]:
        for s in _SEMANA_ORDER:
            if s not in piv.columns:
                piv[s] = 0
    piv_c = piv_c[_SEMANA_ORDER]
    piv_v = piv_v[_SEMANA_ORDER]
    piv_c.index = [label_mes(m) for m in piv_c.index]
    piv_v.index = [label_mes(m) for m in piv_v.index]
    zmax = max(
        float(piv_c.values.max()) if piv_c.size > 0 else 0,
        float(piv_v.values.max()) if piv_v.size > 0 else 0,
    ) or 1.0

    def _heatmap(piv, colorscale, title):
        txt = [[f"${v/1e3:,.0f}K" if v > 0 else "—" for v in row] for row in piv.values]
        fig = go.Figure(go.Heatmap(
            z=piv.values.tolist(), x=_SEMANA_ORDER, y=piv.index.tolist(),
            text=txt, texttemplate="%{text}", textfont=dict(size=12),
            colorscale=colorscale, zmin=0, zmax=zmax,
            hovertemplate="<b>%{y} · %{x}</b><br>$%{z:,.0f}<extra></extra>",
            showscale=True, colorbar=dict(tickformat="$,.0f", len=0.85, title="MXN"),
        ))
        fig.update_layout(
            title=f"<b>{title}</b>",
            template="plotly_white", height=max(380, 70 * len(piv) + 120),
            margin=dict(t=80, b=60, l=110, r=110),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(title="Semana del mes"),
        )
        return fig

    c7 = _heatmap(piv_c, [[0, "#EFF6FF"], [1, "#1F4E79"]],
                  "Heatmap Compras — Actividad por Semana del Mes")
    c8 = _heatmap(piv_v, [[0, "#F0FFF4"], [1, "#548235"]],
                  "Heatmap Ventas — Actividad por Semana del Mes")

    # ── Convert all figures to embedded HTML (shows progress) ────────────────
    _queue = [
        ("donut_cat",   fig_donut_cat,   "Distribución de Categorías"),
        ("curva_comp",  fig_curva_comp,  "Curva Semanal — Compras"),
        ("pareto_prov", fig_pareto_prov, "Pareto de Proveedores"),
        ("cat_bar",     fig_cat_bar,     "Compras por Categoría"),
        ("top_fact",    fig_top_fact,    "Top Facturas"),
        ("donut_cli",   fig_donut_cli,   "Distribución de Clientes"),
        ("curva_vent",  fig_curva_vent,  "Curva Semanal — Ventas"),
        ("pareto_cli",  fig_pareto_cli,  "Pareto de Clientes"),
        ("vend_bar",    fig_vend_bar,    "Ventas por Vendedor"),
        ("heatmap_cm",  fig_heatmap_cm,  "Heatmap Cliente × Mes"),
        ("c1",          c1,              "Ventas vs Compras"),
        ("c2",          c2,              "Margen Mensual"),
        ("c3",          c3,              "Gasto % Ventas"),
        ("c7",          c7,              "Heatmap Compras"),
        ("c8",          c8,              "Heatmap Ventas"),
    ]
    if fig_pendientes is not None:
        _queue.append(("pendientes",    fig_pendientes,   "Pendientes de Clasificar"))
    if fig_donut_resto is not None:
        _queue.append(("donut_resto",   fig_donut_resto,  "Desglose Resto Clientes"))
    if fig_productividad is not None:
        _queue.append(("productividad", fig_productividad, "Ventas vs Comisiones"))

    _n = len(_queue)
    _imgs: dict[str, str] = {}
    _first_chart = True
    for _i, (_key, _fig, _label) in enumerate(_queue):
        if on_progress:
            on_progress(_i + 1, _n, _label)
        _imgs[_key] = _fig_html(_fig, include_js=_first_chart)
        _first_chart = False

    def _img(key: str) -> str:
        return _imgs.get(key, "")

    # ── HTML COMPONENTS ───────────────────────────────────────────────────────

    # KPI grid
    def _kpi(label, val, color, note=""):
        note_tag = f'<div class="kpi-note">{note}</div>' if note else ""
        return (f'<div class="kpi-card">'
                f'<div class="kpi-label">{label}</div>'
                f'<div class="kpi-val" style="color:{color}">{val}</div>'
                f'{note_tag}</div>')

    m_color   = _GREEN if margen >= 0 else _RED
    mp_color  = _GREEN if margen_pct >= 25 else (_AMBER if margen_pct >= 10 else _RED)
    rcv_color = _GREEN if ratio_cv < 70 else (_AMBER if ratio_cv <= 80 else _RED)

    kpi_html = (
        '<div class="kpi-grid">'
        + _kpi("Ventas",          _fmt_m(total_ventas),  _GREEN)
        + _kpi("Compras",         _fmt_m(total_compras), _BLUE)
        + _kpi("Margen Bruto",    _fmt_m(margen),        m_color)
        + _kpi("Margen %",        f"{margen_pct:.1f}%",  mp_color)
        + _kpi("Ratio C/V",       f"{ratio_cv:.1f}%",    rcv_color, "Compras ÷ Ventas")
        + _kpi("Costo Directo %", f"{pct_dir:.1f}%",     _BLUE,     "% de ventas")
        + _kpi("Overhead %",      f"{pct_ovh:.1f}%",     _AMBER,    "% de ventas")
        + '</div>'
    )

    # Monthly summary table
    resumen = mes_df[["Mes", "Ventas", "Compras", "Margen", "Margen_pct"]].copy()
    resumen = pd.concat(
        [resumen, pd.DataFrame([{
            "Mes": "TOTAL", "Ventas": total_ventas,
            "Compras": total_compras, "Margen": margen, "Margen_pct": margen_pct,
        }])],
        ignore_index=True,
    )

    def _cell(v, col):
        if col in ("Margen", "Margen_pct") and isinstance(v, (int, float)):
            s = ("color:#C00000;font-weight:700" if v < 0
                 else ("color:#548235;font-weight:700" if v > 0 else ""))
        else:
            s = ""
        if col == "Margen_pct":
            txt = f"{v:.1f}%" if isinstance(v, (int, float)) else str(v)
        elif col in ("Ventas", "Compras", "Margen"):
            txt = f"${v:,.0f}" if isinstance(v, (int, float)) else str(v)
        else:
            txt = str(v)
        return f'<td style="{s}">{txt}</td>'

    tbl_rows = ""
    for _, row in resumen.iterrows():
        cls = 'class="total-row"' if row["Mes"] == "TOTAL" else ""
        tbl_rows += f"<tr {cls}><td>{row['Mes']}</td>"
        for col in ("Ventas", "Compras", "Margen", "Margen_pct"):
            tbl_rows += _cell(row[col], col)
        tbl_rows += "</tr>"

    monthly_table = (
        '<table class="rpt-table">'
        '<thead><tr><th>Mes</th><th>Ventas</th><th>Compras</th>'
        '<th>Margen Bruto</th><th>Margen %</th></tr></thead>'
        f'<tbody>{tbl_rows}</tbody></table>'
    )

    # Provider concentration table
    prov_rows = ""
    for cat, grp in sorted(df_cf.groupby("Categoria"),
                            key=lambda x: x[1]["Gasto_Total_MXN"].sum(), reverse=True):
        if cat == ETIQ_PENDIENTE:
            continue
        pi   = grp.groupby("Proveedor")["Gasto_Total_MXN"].sum().sort_values(ascending=False)
        ctot = pi.sum()
        p1   = float(pi.iloc[0]) / ctot * 100 if ctot > 0 else 0
        top2 = " + ".join(p[:22] + "…" if len(p) > 24 else p for p in pi.head(2).index)
        umb  = 65 if cat in _CRITICAS else 75
        if p1 < 40:    sem, sc = "🟢 Bajo",  "#548235"
        elif p1 < umb: sem, sc = "🟡 Medio", "#E97132"
        else:           sem, sc = "🔴 Alto",  "#C00000"
        ptot = ctot / total_compras * 100 if total_compras > 0 else 0
        prov_rows += (
            f"<tr><td>{cat}</td><td>${ctot/1e6:,.2f}M</td><td>{ptot:.1f}%</td>"
            f"<td>{top2}</td><td>{p1:.1f}%</td>"
            f'<td style="color:{sc};font-weight:700">{sem}</td></tr>'
        )

    prov_table = (
        '<table class="rpt-table">'
        '<thead><tr><th>Categoría</th><th>Gasto</th><th>% Total</th>'
        '<th>Top 2 Proveedores</th><th>% Top 1</th><th>Riesgo</th></tr></thead>'
        f'<tbody>{prov_rows}</tbody></table>'
    )

    # Vendedores table
    if len(vend) > 0:
        vd_rows = ""
        for i, (_, row) in enumerate(
                vend.sort_values("Ventas_Brutas", ascending=False).iterrows(), 1):
            neta = row["Ventas_Brutas"] - row["Comisiones"]
            vd_rows += (
                f"<tr><td>{i}</td><td>{row['Vendedor']}</td>"
                f"<td>${row['Ventas_Brutas']:,.0f}</td><td>${row['Comisiones']:,.0f}</td>"
                f"<td>${neta:,.0f}</td><td>{row['Ratio_Comision']:.1f}%</td>"
                f"<td>{int(row['Pedidos'])}</td></tr>"
            )
        vd_table = (
            '<table class="rpt-table">'
            '<thead><tr><th>#</th><th>Vendedor</th><th>Ventas</th><th>Comisiones</th>'
            '<th>Venta Neta</th><th>% Comisión</th><th>Pedidos</th></tr></thead>'
            f'<tbody>{vd_rows}</tbody></table>'
        )
    else:
        vd_table = '<p class="no-data">Sin vendedores asignados en el período.</p>'

    # Risk callout
    tp_gbl = df_cf.groupby("Proveedor")["Gasto_Total_MXN"].sum().sort_values(ascending=False)
    risk_box = ""
    if len(tp_gbl) > 0 and total_compras > 0:
        tp_n  = tp_gbl.index[0]
        tp_g  = float(tp_gbl.iloc[0])
        tp_pc = tp_g / total_compras * 100
        tp_pv = tp_g / total_ventas * 100 if total_ventas > 0 else 0
        risk_box = (
            f'<div class="callout warn">'
            f'⚠️ <strong>Riesgo clave:</strong> Si <strong>{tp_n}</strong> falla, '
            f'representa <strong>{tp_pc:.1f}%</strong> del gasto en compras — '
            f'equivalente a ~<strong>{tp_pv:.1f}%</strong> de las ventas del período.'
            f'</div>'
        )

    # Desfase callout
    best_r = -1.0
    best_m = best_s = "—"
    best_cv = best_vv = 0.0
    for m in set(piv_c.index) & set(piv_v.index):
        for s in _SEMANA_ORDER:
            cv = float(piv_c.loc[m, s]) if s in piv_c.columns else 0.0
            vv = float(piv_v.loc[m, s]) if s in piv_v.columns else 0.0
            if cv > 0 and vv > 0 and cv / vv > best_r:
                best_r, best_m, best_s, best_cv, best_vv = cv / vv, m, s, cv, vv

    desfase_box = ""
    if best_m != "—":
        desfase_box = (
            f'<div class="callout info">'
            f'📊 <strong>Semana con mayor desfase C/V: {best_s} de {best_m}</strong> — '
            f'Compras ${best_cv/1e3:,.0f}K · Ventas ${best_vv/1e3:,.0f}K · '
            f'Ratio C/V {best_r:.2f}'
            f'</div>'
        )

    # ── CSS ───────────────────────────────────────────────────────────────────
    css = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,Arial,sans-serif;
     background:#F3F4F6;color:#111827;font-size:14px;line-height:1.6}

.cover{background:linear-gradient(135deg,#1B4D0F 0%,#1F4E79 100%);
       min-height:100vh;display:flex;flex-direction:column;align-items:center;
       justify-content:center;text-align:center;color:#fff;padding:4rem 2rem;
       page-break-after:always}
.cover-brand{font-size:3rem;font-weight:900;letter-spacing:.22em;text-transform:uppercase}
.cover-tagline{font-size:.9rem;opacity:.7;letter-spacing:.06em;margin-top:.3rem}
.cover-divider{width:70px;height:4px;background:rgba(255,255,255,.4);
               border-radius:2px;margin:2rem auto}
.cover-title{font-size:2rem;font-weight:700;max-width:520px;margin-bottom:1.2rem}
.cover-period{font-size:1.1rem;background:rgba(255,255,255,.12);
              padding:.45rem 1.8rem;border-radius:30px;display:inline-block;
              margin-bottom:2.5rem}
.cover-meta{font-size:.8rem;opacity:.55;line-height:1.8}
.cover-filter{font-size:.75rem;background:rgba(255,255,255,.15);
              border:1px solid rgba(255,255,255,.3);border-radius:20px;
              padding:.3rem 1rem;display:inline-block;margin-bottom:1rem;
              letter-spacing:.03em;opacity:.9}

.wrap{max-width:1200px;margin:0 auto;padding:2rem 1.5rem}

.sec{background:#fff;border-radius:12px;
     box-shadow:0 1px 6px rgba(0,0,0,.07);margin-bottom:1.75rem;overflow:hidden}
.sec-head{background:#1F4E79;color:#fff;padding:.85rem 1.4rem;
          display:flex;align-items:center;gap:.6rem}
.sec-num{background:rgba(255,255,255,.18);border-radius:50%;
         width:26px;height:26px;display:flex;align-items:center;
         justify-content:center;font-size:.75rem;font-weight:800;flex-shrink:0}
.sec-head h2{margin:0;font-size:.95rem;font-weight:700;
             text-transform:uppercase;letter-spacing:.05em}
.sec-body{padding:1.4rem 1.5rem}
.sub{font-size:.68rem;font-weight:700;color:#6B7280;text-transform:uppercase;
     letter-spacing:.05em;border-left:3px solid #1F4E79;padding-left:8px;
     margin:1.4rem 0 .7rem}
.sub:first-child{margin-top:0}

.kpi-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:.65rem;margin-bottom:1rem}
@media(max-width:900px){.kpi-grid{grid-template-columns:repeat(4,1fr)}}
.kpi-card{background:#F8FAFC;border:1px solid #E1E7EC;border-radius:9px;
          padding:.8rem .9rem;text-align:center}
.kpi-label{font-size:.63rem;font-weight:700;color:#6B7280;text-transform:uppercase;
           letter-spacing:.04em;margin-bottom:.3rem}
.kpi-val{font-size:1.35rem;font-weight:800;line-height:1.1}
.kpi-note{font-size:.62rem;color:#9CA3AF;margin-top:.2rem}

.rpt-table{width:100%;border-collapse:collapse;font-size:.83rem;margin:.5rem 0}
.rpt-table thead tr{background:#1F4E79;color:#fff}
.rpt-table th{padding:.55rem .85rem;text-align:left;font-size:.72rem;
              font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.rpt-table td{padding:.48rem .85rem;border-bottom:1px solid #F3F4F6}
.rpt-table tbody tr:nth-child(even){background:#F9FAFB}
.rpt-table tbody tr:hover{background:#EFF6FF}
.rpt-table tbody tr:last-child td{border-bottom:none}
.total-row td{background:#EFF6FF!important;font-weight:700;
              border-top:2px solid #1F4E79!important}

.callout{border-radius:8px;padding:.75rem 1.1rem;margin:.9rem 0;
         font-size:.86rem;line-height:1.55}
.callout.info{background:#EFF6FF;border-left:4px solid #1F4E79;color:#1e3a5f}
.callout.warn{background:#FFF7ED;border-left:4px solid #E97132;color:#7c2d12}

.no-data{font-size:.85rem;color:#9CA3AF;font-style:italic;padding:.5rem 0}

.rpt-footer{text-align:center;color:#9CA3AF;font-size:.76rem;
            padding:1.5rem;border-top:1px solid #E5E7EB;margin-top:.5rem}

@media print{body{background:#fff}.cover{min-height:auto;padding:2.5rem}
             .sec{box-shadow:none;border:1px solid #E5E7EB}}
"""

    # ── ASSEMBLE HTML ─────────────────────────────────────────────────────────
    def _sec(num, title, body):
        return (
            f'<div class="sec">'
            f'<div class="sec-head"><div class="sec-num">{num}</div><h2>{title}</h2></div>'
            f'<div class="sec-body">{body}</div></div>'
        )

    # Section 1 — Resumen Ejecutivo
    s1 = (
        '<div class="sub">Indicadores Clave del Período</div>'
        + kpi_html
        + '<div class="sub">Resumen Mensual</div>'
        + monthly_table
    )

    # Section 2 — Compras
    s2 = (
        '<div class="sub">Distribución del Gasto por Categoría</div>'
        + _img("donut_cat")
        + '<div class="sub">Curva de Gasto Semanal</div>'
        + _img("curva_comp")
        + '<div class="sub">Top 10 Proveedores por Gasto</div>'
        + _img("pareto_prov")
        + '<div class="sub">Gasto por Categoría — Total Período</div>'
        + _img("cat_bar")
        + '<div class="sub">Top 10 Facturas Individuales</div>'
        + _img("top_fact")
        + (
            '<div class="sub">Proveedores Pendientes de Clasificar</div>'
            + _img("pendientes")
            if "pendientes" in _imgs else ""
        )
    )

    # Section 3 — Ventas
    s3 = (
        '<div class="sub">Distribución de Ventas por Cliente</div>'
        + _img("donut_cli")
        + (
            '<div class="sub">Desglose del Resto de Clientes</div>'
            + _img("donut_resto")
            if "donut_resto" in _imgs else ""
        )
        + '<div class="sub">Curva de Ventas Semanal</div>'
        + _img("curva_vent")
        + '<div class="sub">Top 10 Clientes por Volumen</div>'
        + _img("pareto_cli")
        + '<div class="sub">Ventas por Vendedor</div>'
        + _img("vend_bar")
        + '<div class="sub">Estacionalidad por Cliente — Top 15</div>'
        + _img("heatmap_cm")
    )

    # Section 4 — Comparativa
    s4 = (
        '<div class="sub">Ventas vs Compras por Mes · Margen %</div>'
        + _img("c1")
        + '<div class="sub">Margen Bruto Mensual</div>'
        + _img("c2")
        + '<div class="sub">Gasto por Categoría como % de Ventas del Mes</div>'
        + _img("c3")
        + risk_box
        + '<div class="sub">Concentración de Riesgo por Categoría</div>'
        + prov_table
    )

    # Section 5 — Vendedores
    s5 = ""
    if "productividad" in _imgs:
        s5 += (
            '<div class="sub">Ventas Brutas vs Comisiones</div>'
            + _img("productividad")
        )
    s5 += '<div class="sub">Ranking de Vendedores</div>' + vd_table

    # Section 6 — Patrones Temporales
    s6 = (
        '<div class="sub">Actividad de Compras por Semana del Mes</div>'
        + _img("c7")
        + '<div class="sub">Actividad de Ventas por Semana del Mes</div>'
        + _img("c8")
        + desfase_box
    )

    # Build cover filter badge
    if meses_filtrar:
        _mf = sorted(meses_filtrar)
        _años_fil = sorted({p.year for p in _mf})
        _fil_label = (
            f"Filtro activo: {label_mes(_mf[0])} – {label_mes(_mf[-1])}"
            f" ({', '.join(str(a) for a in _años_fil)})"
        )
        _cover_filter = f'<div class="cover-filter">🔍 {_fil_label}</div>'
    else:
        _cover_filter = ""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reporte Ejecutivo — Lyon AG · {periodo}</title>
<style>{css}</style>
</head>
<body>

<div class="cover">
  <div class="cover-brand">LYON AG</div>
  <div class="cover-tagline">Planta QUMA · Reporte de Compra-Venta</div>
  <div class="cover-divider"></div>
  <div class="cover-title">Reporte Ejecutivo<br>Compras vs Ventas</div>
  <div class="cover-period">📅 {periodo}</div>
  {_cover_filter}
  <div class="cover-meta">
    Compras: {meta_compras.get('archivo', 'datos de compras')}<br>
    Ventas: {meta_ventas.get('archivo', 'datos de ventas')}<br>
    Generado el {fecha_gen}
  </div>
</div>

<div class="wrap">
  {_sec(1, "Resumen Ejecutivo", s1)}
  {_sec(2, "Análisis de Compras", s2)}
  {_sec(3, "Análisis de Ventas", s3)}
  {_sec(4, "Comparativa Compras vs Ventas", s4)}
  {_sec(5, "Productividad de Vendedores", s5)}
  {_sec(6, "Patrones Temporales", s6)}
</div>

<div class="rpt-footer">
  LYON AG — Reporte Ejecutivo · Período: {periodo}{" · " + _fil_label if meses_filtrar else ""} · Generado: {fecha_gen} · Confidencial
</div>

</body>
</html>"""

    return html
