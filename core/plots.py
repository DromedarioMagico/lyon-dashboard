"""
Plotly figure generators — ported from the standalone Colab scripts.
Each function receives a DataFrame (already filtered) + parameters
and returns a go.Figure ready for st.plotly_chart().
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from core.catalogos import (
    PALETA_CATEGORIAS, ETIQ_PENDIENTE, PALETA_PRINCIPAL, label_mes,
    COLOR_LYON, COLOR_VENTAS, COLOR_GASTOS_EMPRESA,
)

_RED   = "#C00000"
_GREEN = "#548235"
_AMBER = "#E97132"

_TOP_N_PROVEEDORES    = 10
_TOP_N_FACTURAS       = 10
_TOP_N_SIN_CLASIFICAR = 15


# ══════════════════════════════════════════════════════════════════════════════
#  COMPRAS — 1: Donut de categorías
# ══════════════════════════════════════════════════════════════════════════════
def plot_donut_categorias(df, gasto_total, pct_cobertura, prov_pendientes):
    gasto_cat = (
        df.groupby("Categoria", as_index=False)["Gasto_Total_MXN"].sum()
          .sort_values("Gasto_Total_MXN", ascending=False)
    )
    subtit = (
        f"Cobertura clasificada: <b>{pct_cobertura:.1f}%</b>  ·  "
        f"{prov_pendientes} proveedor(es) aún pendientes"
    )
    fig = px.pie(
        gasto_cat, names="Categoria", values="Gasto_Total_MXN",
        hole=0.58, color="Categoria", color_discrete_map=PALETA_CATEGORIAS,
        title=f"<b>Distribución del Gasto por Categoría</b><br><sup>{subtit}</sup>",
    )
    # Labels go INSIDE the slices (no leader-line spaghetti); Plotly auto-hides
    # the ones that don't fit, so tiny slices stay clean. Names live in the
    # legend; full detail on hover. Scales cleanly to many categories.
    fig.update_traces(
        textposition="inside",
        textinfo="percent",
        texttemplate="%{percent:.1%}",
        insidetextorientation="horizontal",
        sort=False,
        marker=dict(line=dict(color="white", width=1.5)),
        hovertemplate=(
            "<b>%{label}</b><br>Gasto: $%{value:,.0f} MXN<br>"
            "Participación: %{percent}<extra></extra>"
        ),
    )
    fig.update_layout(
        template="plotly_white",
        annotations=[dict(
            text=(
                f"<b>${gasto_total/1e6:,.1f}M</b><br>"
                f"<span style='font-size:12px'>MXN total</span>"
            ),
            x=0.5, y=0.5, font=dict(size=18), showarrow=False,
        )],
        height=560,
        margin=dict(t=120, b=40, l=40, r=220),
        legend=dict(
            orientation="v", yanchor="middle", y=0.5, x=1.02,
            font=dict(size=11), itemclick=False, itemdoubleclick=False,
        ),
        uniformtext=dict(minsize=11, mode="hide"),
        paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig


def plot_barras_categorias(df, gasto_total, pct_cobertura, prov_pendientes):
    """Horizontal bar of spend by category — readable with many categories.

    Sorted by spend (largest on top). Same signature as plot_donut_categorias
    so it can be swapped in-place.
    """
    gasto_cat = (
        df.groupby("Categoria", as_index=False)["Gasto_Total_MXN"].sum()
          .sort_values("Gasto_Total_MXN", ascending=True)
    )
    total = gasto_cat["Gasto_Total_MXN"].sum()
    gasto_cat["Pct"]   = gasto_cat["Gasto_Total_MXN"] / total * 100 if total else 0
    gasto_cat["Color"] = gasto_cat["Categoria"].apply(
        lambda c: PALETA_CATEGORIAS.get(c, "#9E9E9E")
    )
    subtit = (
        f"Cobertura clasificada: <b>{pct_cobertura:.1f}%</b>  ·  "
        f"{prov_pendientes} proveedor(es) aún pendientes  ·  "
        f"Total: <b>${gasto_total/1e6:,.1f}M MXN</b>"
    )
    n = len(gasto_cat)
    fig = go.Figure(go.Bar(
        x=gasto_cat["Gasto_Total_MXN"], y=gasto_cat["Categoria"], orientation="h",
        marker_color=gasto_cat["Color"].tolist(),
        text=gasto_cat.apply(
            lambda r: f"  ${r['Gasto_Total_MXN']/1e6:,.2f}M  ({r['Pct']:.1f}%)", axis=1
        ),
        textposition="outside",
        cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>Gasto: $%{x:,.0f} MXN<extra></extra>",
    ))
    fig.update_layout(
        title=f"<b>Distribución del Gasto por Categoría</b><br><sup>{subtit}</sup>",
        template="plotly_white",
        height=max(420, 46 * n + 130),
        showlegend=False,
        xaxis=dict(tickformat="$,.0f", title="Gasto (MXN)"),
        yaxis=dict(title=""),
        margin=dict(t=90, b=40, l=240, r=150),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    )
    return fig


# Monochromatic purple family anchored on COLOR_GASTOS_EMPRESA — keeps every
# Gastos de Empresa visual (KPI accents, donut, bars, waterfall) visually
# distinct from the real-purchase category palette used elsewhere.
_PALETA_GASTOS_EMPRESA = [
    "#7030A0", "#9754C4", "#5A2380", "#B383D6", "#421A5C", "#C9A6E8",
]


def _trunc(s, n=22):
    return s if len(s) <= n else s[:n - 1] + "…"


def plot_dona_gastos_empresa(ge_por_concepto, total):
    """
    Donut of Gastos de Empresa spend by concepto — composition view for the
    interactive Compras page. `ge_por_concepto`: {concepto: monto}.
    """
    conceptos = list(ge_por_concepto.keys())
    montos    = list(ge_por_concepto.values())
    colors    = [_PALETA_GASTOS_EMPRESA[i % len(_PALETA_GASTOS_EMPRESA)]
                 for i in range(len(conceptos))]

    fig = go.Figure(go.Pie(
        labels=conceptos, values=montos, hole=0.55,
        marker=dict(colors=colors, line=dict(color="white", width=1.5)),
        textposition="inside", textinfo="percent",
        texttemplate="%{percent:.1%}",
        sort=True,
        hovertemplate="<b>%{label}</b><br>$%{value:,.0f} MXN<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        title="<b>Gastos de Empresa — Composición</b>",
        template="plotly_white",
        height=560,
        annotations=[dict(
            text=f"<b>${total/1e6:,.1f}M</b><br><span style='font-size:13px'>MXN total</span>",
            x=0.5, y=0.5, font=dict(size=19), showarrow=False,
        )],
        legend=dict(orientation="v", yanchor="middle", y=0.5, font=dict(size=13)),
        margin=dict(t=70, b=30, l=30, r=30),
        uniformtext=dict(minsize=11, mode="hide"),
        paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig


def plot_barras_gastos_empresa(ge_por_concepto, total):
    """
    Horizontal bar of Gastos de Empresa by concepto — mirrors the visual
    grammar of plot_barras_categorias (value + % label outside each bar).
    Used in the static HTML report, where a scannable bar list reads better
    on paper/PDF than a hover-dependent donut.
    """
    items     = sorted(ge_por_concepto.items(), key=lambda kv: kv[1])
    conceptos = [k for k, _ in items]
    montos    = [v for _, v in items]
    colors    = [_PALETA_GASTOS_EMPRESA[i % len(_PALETA_GASTOS_EMPRESA)]
                 for i in range(len(conceptos))]
    pcts      = [m / total * 100 if total else 0 for m in montos]

    n = len(conceptos)
    fig = go.Figure(go.Bar(
        x=montos, y=conceptos, orientation="h",
        marker_color=colors,
        text=[f"  ${m/1e6:,.2f}M  ({p:.1f}%)" for m, p in zip(montos, pcts)],
        textposition="outside",
        cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>Gasto: $%{x:,.0f} MXN<extra></extra>",
    ))
    fig.update_layout(
        title=(
            "<b>Gastos de Empresa por Concepto</b>"
            f"<br><sup>Total del período: <b>${total/1e6:,.1f}M MXN</b></sup>"
        ),
        template="plotly_white",
        height=max(300, 55 * n + 130),
        showlegend=False,
        xaxis=dict(tickformat="$,.0f", title="Monto (MXN)"),
        yaxis=dict(title=""),
        margin=dict(t=80, b=40, l=220, r=140),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    )
    return fig


def plot_waterfall_margen(margen_bruto, ge_por_concepto, margen_operativo, top_n=5):
    """
    Waterfall bridge: Margen Bruto → (− Gastos de Empresa por concepto, top N
    + 'Otros conceptos') → Margen Operativo. Makes the P&L impact of Gastos
    de Empresa explicit instead of a bolted-on info box. Used in both the
    Resultados Financieros page and the HTML report.
    """
    items = sorted(ge_por_concepto.items(), key=lambda kv: kv[1], reverse=True)
    top   = items[:top_n]
    resto = sum(v for _, v in items[top_n:])

    labels = ["Margen Bruto"] + [_trunc(k) for k, _ in top]
    deltas = [-v for _, v in top]
    if resto > 0:
        labels.append("Otros conceptos")
        deltas.append(-resto)
    labels.append("Margen Operativo")

    values   = [margen_bruto] + deltas + [0]  # last 0 is a placeholder — ignored for measure="total"
    measures = ["absolute"] + ["relative"] * len(deltas) + ["total"]
    texts    = (
        [f"${margen_bruto/1e6:,.2f}M"]
        + [f"-${abs(d)/1e6:,.2f}M" for d in deltas]
        + [f"${margen_operativo/1e6:,.2f}M"]
    )

    fig = go.Figure(go.Waterfall(
        x=labels, y=values,
        measure=measures,
        text=texts,
        textposition="outside",
        connector=dict(line=dict(color="#E5E7EB", width=1)),
        increasing=dict(marker=dict(color=_GREEN)),
        decreasing=dict(marker=dict(color=COLOR_GASTOS_EMPRESA)),
        totals=dict(marker=dict(color=COLOR_LYON)),
        hovertemplate="<b>%{x}</b><br>$%{y:,.0f} MXN<extra></extra>",
    ))
    fig.update_layout(
        title=(
            "<b>De Margen Bruto a Margen Operativo</b>"
            "<br><sup>Impacto de los Gastos de Empresa (nómina y otros) en el margen</sup>"
        ),
        template="plotly_white", height=420, showlegend=False,
        yaxis=dict(tickformat="$,.0f", title="MXN"),
        xaxis_title="",
        margin=dict(t=90, b=60, l=80, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_barras_temporales(df, value_col, titulo, color, umbral_meses=24):
    """
    Bar chart of `value_col` over time for a drill-down detail view.

    Monthly by default, but auto-aggregates by YEAR when the selected period
    spans more than `umbral_meses` months, so a long history (e.g. loading the
    full historical file) doesn't crush the axis into unreadable bars.

    `df` must contain a `_Mes` (pandas Period[M]) column.
    """
    n_meses = df["_Mes"].nunique()
    anual = n_meses > umbral_meses
    if anual:
        agg = (df.assign(_k=df["_Mes"].apply(lambda p: p.year))
                 .groupby("_k", as_index=False)[value_col].sum()
                 .sort_values("_k"))
        agg["X"] = agg["_k"].astype(str)
    else:
        agg = (df.groupby("_Mes", as_index=False)[value_col].sum()
                 .sort_values("_Mes"))
        agg["X"] = agg["_Mes"].apply(label_mes)

    titulo_full = f"<b>{titulo}</b>"
    if anual:
        titulo_full += (
            f"<br><sup>Agregado por año — {n_meses} meses en el periodo "
            f"seleccionado</sup>"
        )

    fig = px.bar(
        agg, x="X", y=value_col, text=value_col,
        color_discrete_sequence=[color],
    )
    fig.update_traces(
        texttemplate="$%{text:,.0f}", textposition="outside",
        hovertemplate="<b>%{x}</b><br>$%{y:,.0f} MXN<extra></extra>",
    )
    fig.update_layout(
        title=titulo_full,
        template="plotly_white", height=380, showlegend=False,
        xaxis_title="", yaxis_title="MXN",
        margin=dict(t=80, b=40, l=60, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(tickformat=",.0f", tickprefix="$")
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  COMPRAS — 2: Curva de gasto semanal
# ══════════════════════════════════════════════════════════════════════════════
def plot_curva_semanal_compras(df):
    df_sem = (
        df.set_index("Fecha de documento")
          .resample("W-MON")["Gasto_Total_MXN"]
          .sum()
          .reset_index()
    )
    promedio_sem = df_sem["Gasto_Total_MXN"].mean()
    pico_idx = df_sem["Gasto_Total_MXN"].idxmax()
    pico_x   = df_sem.loc[pico_idx, "Fecha de documento"]
    pico_y   = df_sem.loc[pico_idx, "Gasto_Total_MXN"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_sem["Fecha de documento"], y=df_sem["Gasto_Total_MXN"],
        mode="lines+markers", fill="tozeroy",
        line=dict(color="#1F4E79", width=2.5),
        fillcolor="rgba(31, 78, 121, 0.18)",
        marker=dict(size=11, color="#1F4E79"),
        hovertemplate="Semana del %{x|%d-%b-%Y}<br>Gasto: $%{y:,.0f} MXN<extra></extra>",
    ))
    fig.add_hline(
        y=promedio_sem, line_dash="dash", line_color="#C00000",
        annotation_text=f"Promedio semanal: ${promedio_sem:,.0f}",
        annotation_position="top right", annotation_font_color="#C00000",
    )
    fig.add_annotation(
        x=pico_x, y=pico_y,
        text=f"<b>PICO</b><br>${pico_y/1e6:.2f}M",
        showarrow=True, arrowhead=2, arrowcolor="#C00000",
        font=dict(color="#C00000", size=11), yshift=12,
    )
    fig.update_layout(
        title=(
            "<b>Curva de Gasto Semanal — Detección de Picos</b>"
            "<br><sup>Agrupación dinámica L–D; se ajusta automáticamente a meses futuros</sup>"
        ),
        xaxis_title="Semana", yaxis_title="Gasto (MXN)",
        template="plotly_white", height=480, showlegend=False,
        margin=dict(t=100, b=60, l=70, r=40),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    )
    fig.update_yaxes(tickformat=",.0f", tickprefix="$")
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  COMPRAS — 3: Pareto Top N proveedores
# ══════════════════════════════════════════════════════════════════════════════
def plot_pareto_proveedores(df, gasto_total, top_n=_TOP_N_PROVEEDORES):
    prov_to_cat = df.groupby("Proveedor")["Categoria"].first().to_dict()
    top_prov = (
        df.groupby("Proveedor", as_index=False)["Gasto_Total_MXN"].sum()
          .sort_values("Gasto_Total_MXN", ascending=False)
          .head(top_n)
    )
    top_prov["Categoria"] = top_prov["Proveedor"].map(prov_to_cat)
    top_prov["Proveedor_Display"] = top_prov["Proveedor"].apply(
        lambda x: x if len(x) <= 38 else x[:35] + "…"
    )
    top_prov["Pct_Acumulado"] = top_prov["Gasto_Total_MXN"].cumsum() / gasto_total * 100
    pct_top = top_prov["Pct_Acumulado"].iloc[-1]

    fig = px.bar(
        top_prov.sort_values("Gasto_Total_MXN", ascending=True),
        x="Gasto_Total_MXN", y="Proveedor_Display", orientation="h",
        color="Categoria", color_discrete_map=PALETA_CATEGORIAS,
        text="Gasto_Total_MXN",
        title=(
            f"<b>Pareto — Top {top_n} Proveedores por Gasto (MXN)</b>"
            f"<br><sup>El top {top_n} concentra el <b>{pct_top:.1f}%</b> "
            f"del gasto total del periodo</sup>"
        ),
    )
    fig.update_traces(
        texttemplate="$%{text:,.0f}", textposition="outside",
        hovertemplate="<b>%{y}</b><br>Gasto: $%{x:,.0f} MXN<extra></extra>",
    )
    fig.update_layout(
        template="plotly_white", xaxis_title="Gasto (MXN)", yaxis_title="",
        height=560, legend_title="Categoría",
        margin=dict(t=110, b=60, l=20, r=120),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    )
    fig.update_xaxes(tickformat=",.0f", tickprefix="$")
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  COMPRAS — 4: Top pendientes de clasificar
# ══════════════════════════════════════════════════════════════════════════════
def plot_pendientes_clasificar(df, pct_cobertura, top_n=_TOP_N_SIN_CLASIFICAR):
    pend = (
        df[df["Categoria"] == ETIQ_PENDIENTE]
          .groupby("Proveedor", as_index=False)["Gasto_Total_MXN"].sum()
          .sort_values("Gasto_Total_MXN", ascending=False)
          .head(top_n)
    )
    if len(pend) == 0:
        return None

    pend["Proveedor_Display"] = pend["Proveedor"].apply(
        lambda x: x if len(x) <= 40 else x[:37] + "…"
    )
    fig = px.bar(
        pend.sort_values("Gasto_Total_MXN", ascending=True),
        x="Gasto_Total_MXN", y="Proveedor_Display", orientation="h",
        text="Gasto_Total_MXN",
        title=(
            f"<b>Top {top_n} Proveedores Pendientes de Clasificar</b>"
            f"<br><sup>Clasifícalos para subir la cobertura desde el "
            f"{pct_cobertura:.1f}% actual</sup>"
        ),
        color_discrete_sequence=["#9E9E9E"],
    )
    fig.update_traces(
        texttemplate="$%{text:,.0f}", textposition="outside",
        hovertemplate="<b>%{y}</b><br>Gasto: $%{x:,.0f} MXN<extra></extra>",
    )
    fig.update_layout(
        template="plotly_white", xaxis_title="Gasto (MXN)", yaxis_title="",
        height=560, showlegend=False,
        margin=dict(t=110, b=60, l=20, r=120),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    )
    fig.update_xaxes(tickformat=",.0f", tickprefix="$", showgrid=True,
                     gridcolor="#E5E7EB", gridwidth=1)
    fig.update_yaxes(showgrid=True, gridcolor="#E5E7EB", gridwidth=1)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  VENTAS — helpers internos
# ══════════════════════════════════════════════════════════════════════════════
_PALETA_CLIENTES = PALETA_PRINCIPAL + ["#5B9BD5", "#ED7D31"]
_COLOR_RESTO     = "#9FA8DA"
_COLOR_SIN_VEND  = "#9E9E9E"
_TOP_N_CLIENTES  = 10
_TOP_N_HEATMAP   = 15
_TOP_N_PEDIDOS_V = 10


def _ventas_ranking(df):
    return (df.groupby("Cliente_Nombre")["Importe_MXN"]
              .sum().sort_values(ascending=False))


def _color_cliente_map(ranking_index):
    return {c: _PALETA_CLIENTES[i % len(_PALETA_CLIENTES)]
            for i, c in enumerate(ranking_index)}


def _name_to_display(df):
    return (df.drop_duplicates("Cliente_Nombre")
              .set_index("Cliente_Nombre")["Cliente_Display"].to_dict())


# ══════════════════════════════════════════════════════════════════════════════
#  VENTAS — 1: Donut top N clientes + "Resto"
# ══════════════════════════════════════════════════════════════════════════════
def plot_donut_clientes_ventas(df, venta_total, n_clientes_80pct, top_n=_TOP_N_CLIENTES):
    n2d         = _name_to_display(df)
    ranking     = _ventas_ranking(df)
    color_map   = _color_cliente_map(ranking.index)

    top_full    = ranking.head(top_n)
    resto_total = ranking.iloc[top_n:].sum()
    resto_count = max(0, len(ranking) - top_n)
    resto_label = f"Resto ({resto_count} clientes)"

    labels = [n2d.get(c, c) for c in top_full.index] + [resto_label]
    values = list(top_full.values) + [resto_total]
    colors = [color_map[c] for c in top_full.index] + [_COLOR_RESTO]

    legend_labels = [
        f"{lab} — ${v/1e6:,.2f}M ({v/venta_total*100:.1f}%)"
        for lab, v in zip(labels, values)
    ]
    hover_names = list(top_full.index) + [resto_label]

    fig = go.Figure(data=[go.Pie(
        labels=legend_labels, values=values,
        hole=0.55,
        marker=dict(colors=colors, line=dict(color="white", width=2)),
        text=hover_names,
        textinfo="percent", textposition="inside",
        insidetextorientation="radial",
        insidetextfont=dict(color="white", size=12, family="Arial Black"),
        hovertemplate="<b>%{text}</b><br>Ventas: $%{value:,.0f} MXN<br>"
                      "Participación: %{percent}<extra></extra>",
        sort=False, direction="clockwise",
    )])
    fig.update_traces(domain=dict(x=[0.0, 0.40], y=[0.0, 1.0]))
    fig.update_layout(
        title=(f"<b>Distribución de Ventas por Cliente</b>"
               f"<br><sup>Top {top_n} clientes vs el resto  ·  "
               f"<b>{n_clientes_80pct} clientes</b> concentran el 80% del revenue</sup>"),
        template="plotly_white",
        annotations=[dict(
            text=(f"<b>${venta_total/1e6:,.1f}M</b><br>"
                  f"<span style='font-size:12px'>MXN total</span>"),
            x=0.18, y=0.5, font=dict(size=20), showarrow=False,
        )],
        height=580,
        margin=dict(t=110, b=40, l=20, r=20),
        legend=dict(orientation="v", yanchor="middle", y=0.5,
                    xanchor="left", x=0.45, font=dict(size=11)),
        paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  VENTAS — 2: Donut desglose del "Resto" (clientes N+1 en adelante)
# ══════════════════════════════════════════════════════════════════════════════
def plot_donut_resto_clientes(df, venta_total, top_n=_TOP_N_CLIENTES):
    n2d       = _name_to_display(df)
    ranking   = _ventas_ranking(df)
    color_map = _color_cliente_map(ranking.index)

    resto_clientes = ranking.iloc[top_n:]
    if len(resto_clientes) == 0:
        return None

    resto_total = resto_clientes.sum()
    labels  = [n2d.get(c, c) for c in resto_clientes.index]
    values  = list(resto_clientes.values)
    colors  = [color_map[c] for c in resto_clientes.index]

    legend_labels = [
        f"{lab} — ${v/1e3:,.0f}K ({v/resto_total*100:.1f}%)"
        for lab, v in zip(labels, values)
    ]

    fig = go.Figure(data=[go.Pie(
        labels=legend_labels, values=values,
        hole=0.50,
        marker=dict(colors=colors, line=dict(color="white", width=1.5)),
        text=list(resto_clientes.index),
        textinfo="percent", textposition="inside",
        insidetextorientation="auto",
        insidetextfont=dict(color="white", size=11, family="Arial Black"),
        hovertemplate="<b>%{text}</b><br>Ventas: $%{value:,.0f} MXN<br>"
                      "Participación del resto: %{percent}<extra></extra>",
        sort=False,
    )])
    fig.update_traces(domain=dict(x=[0.0, 0.40], y=[0.0, 1.0]))
    fig.update_layout(
        title=(f"<b>Desglose del 'Resto' — {len(resto_clientes)} Clientes fuera del Top {top_n}</b>"
               f"<br><sup>Total agregado: <b>${resto_total/1e6:,.2f}M MXN</b>  ·  "
               f"{resto_total/venta_total*100:.1f}% del revenue total</sup>"),
        template="plotly_white",
        annotations=[dict(
            text=(f"<b>${resto_total/1e6:,.2f}M</b><br>"
                  f"<span style='font-size:11px'>resto</span>"),
            x=0.18, y=0.5, font=dict(size=16), showarrow=False,
        )],
        height=520,
        margin=dict(t=110, b=40, l=20, r=20),
        legend=dict(orientation="v", yanchor="middle", y=0.5,
                    xanchor="left", x=0.45, font=dict(size=10)),
        paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  VENTAS — 3: Curva de ventas semanal con pico estrella
# ══════════════════════════════════════════════════════════════════════════════
def plot_curva_semanal_ventas(df):
    df_sem = (
        df.set_index("Fecha").resample("W-MON")["Importe_MXN"]
          .sum().reset_index()
    )
    promedio_sem = df_sem["Importe_MXN"].mean()
    pico_idx = df_sem["Importe_MXN"].idxmax()
    pico_x   = df_sem.loc[pico_idx, "Fecha"]
    pico_y   = df_sem.loc[pico_idx, "Importe_MXN"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_sem["Fecha"], y=df_sem["Importe_MXN"],
        mode="lines+markers", fill="tozeroy",
        line=dict(color="#548235", width=2.8),
        fillcolor="rgba(84, 130, 53, 0.18)",
        marker=dict(size=11, color="#548235", line=dict(color="white", width=1.5)),
        hovertemplate="Semana del %{x|%d-%b-%Y}<br>Ventas: $%{y:,.0f} MXN<extra></extra>",
        name="Ventas",
    ))
    fig.add_hline(
        y=promedio_sem, line_dash="dash", line_color="#1F4E79", line_width=1.5,
        annotation_text=f"Promedio semanal: ${promedio_sem:,.0f}",
        annotation_position="top left", annotation_font_color="#1F4E79",
        annotation_font_size=11,
    )
    # Halo del pico
    fig.add_trace(go.Scatter(
        x=[pico_x], y=[pico_y], mode="markers",
        marker=dict(size=32, color="rgba(192,0,0,0.15)",
                    line=dict(color="rgba(192,0,0,0.4)", width=2)),
        hoverinfo="skip", showlegend=False,
    ))
    # Estrella del pico
    fig.add_trace(go.Scatter(
        x=[pico_x], y=[pico_y],
        mode="markers+text",
        marker=dict(size=18, color="#C00000", symbol="star",
                    line=dict(color="white", width=2)),
        text=[f"<b>PICO ${pico_y/1e6:.2f}M</b>"],
        textposition="top center",
        textfont=dict(color="#C00000", size=13, family="Arial Black"),
        hovertemplate=f"<b>PICO</b><br>Semana del %{{x|%d-%b-%Y}}<br>"
                      f"Ventas: ${pico_y:,.0f} MXN<extra></extra>",
        showlegend=False,
    ))
    fig.update_layout(
        title=("<b>Curva de Ventas Semanal — Detección de Picos</b>"
               "<br><sup>Agrupación dinámica de lunes a domingo</sup>"),
        xaxis_title="Semana", yaxis_title="Ventas (MXN)",
        template="plotly_white", height=480, showlegend=False,
        margin=dict(t=100, b=60, l=80, r=40),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    )
    fig.update_yaxes(tickformat=",.0f", tickprefix="$")
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  VENTAS — 4: Pareto Top 10 clientes
# ══════════════════════════════════════════════════════════════════════════════
def plot_pareto_clientes_ventas(df, venta_total, top_n=_TOP_N_CLIENTES):
    n2d     = _name_to_display(df)
    ranking = _ventas_ranking(df)
    color_map = _color_cliente_map(ranking.index)

    top = ranking.head(top_n).reset_index()
    top.columns = ["Cliente_Full", "Ventas"]
    top["Cliente_Display"] = top["Cliente_Full"].apply(lambda c: n2d.get(c, c))
    top["Pct_Acumulado"]   = top["Ventas"].cumsum() / venta_total * 100
    pct_top = top["Pct_Acumulado"].iloc[-1]
    colors  = [color_map[c] for c in top["Cliente_Full"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=top["Ventas"].iloc[::-1],
        y=top["Cliente_Display"].iloc[::-1],
        orientation="h",
        marker=dict(color=colors[::-1], line=dict(color="white", width=1)),
        text=[f"${v/1e6:,.2f}M" for v in top["Ventas"].iloc[::-1]],
        textposition="outside",
        textfont=dict(size=11, color="#1F4E79"),
        customdata=top["Cliente_Full"].iloc[::-1].values,
        hovertemplate="<b>%{customdata}</b><br>Ventas: $%{x:,.0f} MXN<extra></extra>",
    ))
    fig.update_layout(
        title=(f"<b>Pareto — Top {top_n} Clientes por Volumen de Ventas (MXN)</b>"
               f"<br><sup>El top {top_n} concentra el <b>{pct_top:.1f}%</b> "
               f"del revenue del periodo</sup>"),
        xaxis_title="Ventas (MXN)", yaxis_title="",
        template="plotly_white", height=540, showlegend=False,
        margin=dict(t=110, b=60, l=200, r=140),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    )
    fig.update_xaxes(tickformat=",.0f", tickprefix="$")
    fig.update_yaxes(tickfont=dict(size=11))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  VENTAS — 5: Ventas por vendedor
# ══════════════════════════════════════════════════════════════════════════════
def plot_ventas_por_vendedor(df, venta_total, unidad="pedidos", comisiones_por_vendedor=None):
    """
    `unidad`: la palabra para el conteo en cada barra ("pedidos" o "facturas")
    — el conteo de documentos es el mismo, solo cambia cómo se llama según la
    base que se esté midiendo.

    `comisiones_por_vendedor`: dict {vendedor: monto}, opcional. Cuando la
    base son ventas confirmadas, el CFDI no trae comisiones — se pasa el total
    real tomado de los pedidos en vez de agregar una columna `Comision_MXN`
    que esa base no tiene. `None` (default) conserva el comportamiento
    original: agregar `Comision_MXN` del propio `df`.
    """
    vv = (df.groupby("Vendedor")
            .agg(Ventas=("Importe_MXN", "sum"),
                 Pedidos=("Importe_MXN", "count"))
            .sort_values("Ventas", ascending=False)
            .reset_index())
    if comisiones_por_vendedor is not None:
        vv["Comisiones"] = vv["Vendedor"].map(comisiones_por_vendedor).fillna(0.0)
    else:
        _com = df.groupby("Vendedor")["Comision_MXN"].sum()
        vv["Comisiones"] = vv["Vendedor"].map(_com).fillna(0.0)

    paleta_vend = ["#1F4E79", "#C00000", "#E97132", "#7030A0",
                   "#548235", "#2E75B6", "#BF8F00", "#A02B93"]
    colors = []
    idx_c = 0
    for v in vv["Vendedor"]:
        if v == "Sin asignar":
            colors.append(_COLOR_SIN_VEND)
        else:
            colors.append(paleta_vend[idx_c % len(paleta_vend)])
            idx_c += 1

    sin_vend_row = vv[vv["Vendedor"] == "Sin asignar"]
    gasto_sin  = sin_vend_row["Ventas"].sum()
    pct_sin    = gasto_sin / venta_total * 100 if venta_total else 0

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=vv["Ventas"].iloc[::-1],
        y=vv["Vendedor"].iloc[::-1],
        orientation="h",
        marker=dict(color=colors[::-1], line=dict(color="white", width=1)),
        text=[f"${v/1e6:,.2f}M  ·  {p} {unidad}"
              for v, p in zip(vv["Ventas"].iloc[::-1], vv["Pedidos"].iloc[::-1])],
        textposition="outside",
        textfont=dict(size=11, color="#1F4E79"),
        customdata=vv[["Pedidos", "Comisiones"]].iloc[::-1].values,
        hovertemplate="<b>%{y}</b><br>Ventas: $%{x:,.0f} MXN<br>"
                      "Pedidos: %{customdata[0]}<br>"
                      "Comisiones: $%{customdata[1]:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=(f"<b>Ventas por Vendedor</b>"
               f"<br><sup>El segmento gris ({pct_sin:.1f}% · "
               f"${gasto_sin/1e6:,.2f}M) son pedidos sin vendedor asignado</sup>"),
        xaxis_title="Ventas (MXN)", yaxis_title="",
        template="plotly_white", height=440, showlegend=False,
        margin=dict(t=110, b=60, l=170, r=240),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    )
    fig.update_xaxes(tickformat=",.0f", tickprefix="$")
    fig.update_yaxes(tickfont=dict(size=11))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  VENTAS — 6: Heatmap cliente × mes
# ══════════════════════════════════════════════════════════════════════════════
def plot_heatmap_cliente_mes(df, top_n=_TOP_N_HEATMAP):
    ranking        = _ventas_ranking(df)
    top_clientes   = ranking.head(top_n).index.tolist()
    n2d            = _name_to_display(df)

    pivot = (df[df["Cliente_Nombre"].isin(top_clientes)]
               .pivot_table(index="Cliente_Nombre", columns="_Mes",
                            values="Importe_MXN", aggfunc="sum", fill_value=0))
    pivot = pivot.reindex(top_clientes)

    col_labels = [label_mes(c) for c in pivot.columns]
    row_labels = [n2d.get(c, c) for c in pivot.index]

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=col_labels,
        y=row_labels,
        colorscale=[
            [0.0,   "#FFFFFF"], [0.001, "#F0F4F8"],
            [0.15,  "#A6C8E0"], [0.5,   "#5B9BD5"],
            [1.0,   "#1F4E79"],
        ],
        hovertemplate="<b>%{y}</b><br>Mes: %{x}<br>"
                      "Ventas: $%{z:,.0f} MXN<extra></extra>",
        colorbar=dict(
            title=dict(text="MXN", font=dict(size=11)),
            tickformat=",.0f", tickprefix="$", thickness=15,
        ),
        xgap=2, ygap=2,
    ))
    fig.update_layout(
        title=(f"<b>Estacionalidad por Cliente — Top {top_n}</b>"
               f"<br><sup>Detecta picos puntuales vs facturación recurrente</sup>"),
        template="plotly_white",
        height=max(420, 70 + 28 * len(pivot)),
        margin=dict(t=100, b=60, l=200, r=80),
        xaxis=dict(side="top", tickfont=dict(size=11)),
        yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
        paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  VENTAS — 7: Tendencia mensual de un cliente vs el resto (drill-down)
# ══════════════════════════════════════════════════════════════════════════════
def plot_tendencia_cliente(df, cliente, display_name):
    """
    Tendencia mensual de UN cliente contra el promedio mensual por cliente del
    resto de la cartera — reemplaza la barra "Ventas Mensuales" del drill-down
    cuando lo que se quiere ver es si el cliente crece o decrece y cómo se
    compara, no solo su nivel absoluto mes a mes.

    `df`: el periodo completo (TODOS los clientes, no solo el filtrado a
    `cliente`), con columnas `_Mes`, `Cliente_Nombre`, `Importe_MXN`. El
    contraste usa el PROMEDIO por cliente del resto, no la suma de todos los
    demás juntos — sumar dejaría al cliente individual invisible contra
    docenas de clientes acumulados.
    """
    if df is None or len(df) == 0:
        return _figura_vacia("Sin datos para calcular la tendencia.")

    meses = sorted(df["_Mes"].unique())
    cli   = df[df["Cliente_Nombre"] == cliente]
    resto = df[df["Cliente_Nombre"] != cliente]

    serie_cli = cli.groupby("_Mes")["Importe_MXN"].sum().reindex(meses, fill_value=0.0)
    n_resto   = resto["Cliente_Nombre"].nunique()
    serie_resto = (
        resto.groupby("_Mes")["Importe_MXN"].sum().reindex(meses, fill_value=0.0) / n_resto
        if n_resto else pd.Series(0.0, index=meses)
    )

    x = [label_mes(m) for m in meses]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=serie_cli.values, mode="lines+markers", name=display_name,
        line=dict(color=COLOR_VENTAS, width=3),
        marker=dict(size=9, color=COLOR_VENTAS),
        hovertemplate=f"<b>{display_name}</b><br>%{{x}}: $%{{y:,.0f}} MXN<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=x, y=serie_resto.values, mode="lines+markers", name="Promedio del resto",
        line=dict(color="#9E9E9E", width=2, dash="dash"),
        marker=dict(size=7, color="#9E9E9E"),
        hovertemplate="<b>Promedio por cliente (resto)</b><br>"
                      "%{x}: $%{y:,.0f} MXN<extra></extra>",
    ))
    fig.update_layout(
        title=(f"<b>Tendencia mensual — {display_name}</b>"
               f"<br><sup>Contra el promedio mensual por cliente del resto de "
               f"la cartera ({n_resto} cliente(s))</sup>"),
        template="plotly_white", height=400,
        xaxis_title="", yaxis_title="MXN",
        legend=dict(orientation="h", y=-0.15, x=0.1),
        margin=dict(t=90, b=60, l=60, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(tickformat=",.0f", tickprefix="$")
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  COMPRAS — 5: Tabla Top N facturas individuales
# ══════════════════════════════════════════════════════════════════════════════
def plot_top_facturas(df, top_n=_TOP_N_FACTURAS):
    cols = ["Proveedor", "Fecha de documento", "Referencia factura",
            "Gasto_Total_MXN", "Categoria"]
    top = df.nlargest(top_n, "Gasto_Total_MXN")[cols].copy().reset_index(drop=True)
    top["Fecha de documento"] = top["Fecha de documento"].dt.strftime("%d-%b-%Y")
    top["Gasto_fmt"] = top["Gasto_Total_MXN"].apply(lambda x: f"${x:,.2f}")
    top.index = top.index + 1

    fig = go.Figure(data=[go.Table(
        columnwidth=[30, 220, 80, 110, 130, 180],
        header=dict(
            values=["<b>#</b>", "<b>Proveedor</b>", "<b>Fecha</b>",
                    "<b>Referencia</b>", "<b>Gasto (MXN)</b>", "<b>Categoría</b>"],
            fill_color="#1F4E79", font=dict(color="white", size=12),
            align="left", height=34,
        ),
        cells=dict(
            values=[
                list(top.index),
                top["Proveedor"],
                top["Fecha de documento"],
                top["Referencia factura"],
                top["Gasto_fmt"],
                top["Categoria"],
            ],
            fill_color=[
                ["#F4F7FA" if r % 2 == 0 else "#FFFFFF" for r in range(len(top))]
                for _ in range(6)
            ],
            align="left", font=dict(color="#1f2933", size=11), height=28,
        ),
    )])
    fig.update_layout(
        title=(
            f"<b>Top {top_n} Facturas Individuales por Monto</b>"
            "<br><sup>Identifica inyecciones fuertes de capital (CapEx) y compras masivas</sup>"
        ),
        height=460, margin=dict(t=90, b=20, l=10, r=10),
        paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  FACTURACIÓN — el tramo pedido → factura (pages/5_Facturacion.py)
# ══════════════════════════════════════════════════════════════════════════════

_SEGMENTOS_ORDEN = [
    "VENTA PRIVADA", "VENTA FILIAL", "VENTA PRIVADA/GOBIERNO",
    "VENTA GOBIERNO (CONALITEG)", "VENTA VARIOS (RENTA)",
]
_FMT_S = "$.2s"   # eje monetario compacto: $9.4M, $500k


def _figura_vacia(mensaje):
    fig = go.Figure()
    fig.add_annotation(text=mensaje, showarrow=False,
                       font=dict(size=13, color="#6B7280"), x=0.5, y=0.5)
    fig.update_layout(
        template="plotly_white", height=260,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(t=30, b=20, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_embudo_facturacion(pedidos, facturado, pendiente):
    """
    Embudo del periodo pedido → factura, como waterfall.

    `pedidos` = Pedidos SAE llevados a base sin IVA (o None si Ventas no está
    cargado — entonces se muestra solo Facturado + Pendiente por facturar).
    """
    if pedidos and pedidos > 0:
        gap = pedidos - facturado
        # Un cliente puede reusar la misma OC en más de un pedido, o
        # consolidar varias OC viejas en un pedido nuevo. cruce_ventas.py
        # cuenta a propósito el monto facturado completo en cada pedido que
        # comparte esa OC ("el dinero es real, solo la fecha es ambigua"),
        # así que sumado a nivel periodo el Facturado puede rebasar ligeramente
        # al Pedido. Cuando pasa, no es "sin facturar" negativo: es ese ajuste.
        if gap >= 0:
            label_gap = "Sin facturar"
            text_gap  = f"-${gap/1e6:,.2f}M"
        else:
            label_gap = "Ajuste<br>(OC compartida)"
            text_gap  = f"+${abs(gap)/1e6:,.2f}M"
        labels   = ["Pedidos SAE<br>(sin IVA)", label_gap, "Facturado"]
        values   = [pedidos, -gap, 0]
        measures = ["absolute", "relative", "total"]
        texts    = [f"${pedidos/1e6:,.2f}M", text_gap, f"${facturado/1e6:,.2f}M"]
        conv     = facturado / pedidos * 100 if pedidos else 0
        sub      = f"Conversión pedido → factura: <b>{conv:.1f}%</b> · base sin IVA"
    else:
        labels   = ["Facturado", "Pendiente<br>por facturar"]
        values   = [facturado, pendiente]
        measures = ["absolute", "relative"]
        texts    = [f"${facturado/1e6:,.2f}M", f"+${pendiente/1e6:,.2f}M"]
        sub      = "Carga Ventas (Pedidos SAE) para ver la conversión pedido → factura"

    fig = go.Figure(go.Waterfall(
        x=labels, y=values, measure=measures, text=texts, textposition="outside",
        connector=dict(line=dict(color="#E5E7EB", width=1)),
        increasing=dict(marker=dict(color=COLOR_VENTAS)),
        decreasing=dict(marker=dict(color=_AMBER)),
        totals=dict(marker=dict(color=COLOR_LYON)),
        hovertemplate="<b>%{x}</b><br>$%{y:,.0f} MXN<extra></extra>",
    ))
    fig.update_layout(
        title=f"<b>Embudo del periodo — pedido → factura</b><br><sup>{sub}</sup>",
        template="plotly_white", height=380, showlegend=False,
        yaxis=dict(tickformat=_FMT_S, title="MXN"), xaxis_title="",
        margin=dict(t=85, b=40, l=75, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_facturacion_segmento(df_hist, meses_sel=None):
    """
    Facturación por segmento — barras apiladas por mes del año (desde HISTORICO,
    importes sin IVA). CONALITEG puede ser negativo en un mes sólo de
    penalizaciones → `barmode="relative"` lo apila bajo el cero.
    `df_hist` cols: Segmento, _Mes, Subtotal_MXN.
    """
    if df_hist is None or df_hist.empty:
        return _figura_vacia("Sin datos en la hoja HISTORICO")

    d = df_hist.copy()
    if meses_sel:
        d = d[d["_Mes"].isin(meses_sel)]
    d = d[d["Subtotal_MXN"] != 0]
    if d.empty:
        return _figura_vacia("Sin facturación en los meses seleccionados")

    meses = sorted(d["_Mes"].unique())
    x = [label_mes(m) for m in meses]

    fig = go.Figure()
    for i, seg in enumerate(_SEGMENTOS_ORDEN):
        sub = d[d["Segmento"] == seg].set_index("_Mes")
        y = [float(sub.loc[m, "Subtotal_MXN"]) if m in sub.index else 0.0 for m in meses]
        if not any(v != 0 for v in y):
            continue
        fig.add_trace(go.Bar(
            x=x, y=y, name=seg.replace("VENTA ", "").title(),
            marker=dict(color=PALETA_PRINCIPAL[i % len(PALETA_PRINCIPAL)],
                        line=dict(color="white", width=1)),
            hovertemplate=f"<b>{seg}</b><br>%{{x}}: $%{{y:,.0f}} MXN<extra></extra>",
        ))

    fig.update_layout(
        title=("<b>Facturación por segmento</b><br><sup>Importes sin IVA · "
               "CONALITEG puede quedar negativo (mes sólo con penalizaciones)</sup>"),
        barmode="relative", template="plotly_white", height=440,
        legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=11)),
        yaxis=dict(tickformat=_FMT_S, title="MXN"), xaxis_title="",
        margin=dict(t=80, b=95, l=75, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_fugas_cliente(df_dev):
    """
    Penalizaciones y descuentos por cliente (sin IVA). CONALITEG a tasa 0 %
    se resalta en el subtítulo. `df_dev` cols: Cliente_Display, Tipo,
    Subtotal_MXN, Tasa_Cero.
    """
    if df_dev is None or df_dev.empty:
        return _figura_vacia("Sin devoluciones ni descuentos en el periodo")

    d = (df_dev.groupby(["Cliente_Display", "Tipo"], as_index=False)["Subtotal_MXN"]
             .sum())
    orden_cli = (d.groupby("Cliente_Display")["Subtotal_MXN"].sum()
                  .sort_values().index.tolist())

    fig = go.Figure()
    for tipo, color in [("Penalizacion", _RED), ("Descuento", _AMBER)]:
        sub = d[d["Tipo"] == tipo]
        if sub.empty:
            continue
        sub = sub.set_index("Cliente_Display").reindex(orden_cli).dropna(subset=["Subtotal_MXN"])
        fig.add_trace(go.Bar(
            x=sub["Subtotal_MXN"], y=sub.index, orientation="h",
            name=tipo, marker_color=color,
            hovertemplate=f"<b>%{{y}}</b><br>{tipo}: $%{{x:,.0f}} MXN<extra></extra>",
        ))

    total  = df_dev["Subtotal_MXN"].sum()
    conali = df_dev.loc[df_dev["Tasa_Cero"], "Subtotal_MXN"].sum()
    fig.update_layout(
        title=(f"<b>Fugas del periodo — penalizaciones y descuentos</b><br><sup>"
               f"Total ${total/1e6:,.2f}M · de los cuales ${conali/1e6:,.2f}M son "
               f"CONALITEG a tasa 0 %</sup>"),
        barmode="stack", template="plotly_white",
        height=max(300, 44 * len(orden_cli) + 140),
        legend=dict(orientation="h", y=-0.22, x=0),
        xaxis=dict(tickformat=_FMT_S, title="MXN"), yaxis=dict(title=""),
        margin=dict(t=90, b=70, l=190, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_aging_remisiones(df_rem):
    """
    Pendiente por facturar por antigüedad, separando lo que cae fuera del mes
    del archivo. `df_rem` cols: Antiguedad_Dias, Subtotal_MXN, Fuera_De_Mes,
    Revisar.
    """
    if df_rem is None or df_rem.empty:
        return _figura_vacia("Sin remisiones pendientes")

    def _bucket(x):
        if x <= 30:  return "0–30 días"
        if x <= 60:  return "31–60 días"
        if x <= 90:  return "61–90 días"
        return "90+ días"

    d = df_rem.copy()
    d["Bucket"] = d["Antiguedad_Dias"].apply(_bucket)
    orden  = ["0–30 días", "31–60 días", "61–90 días", "90+ días"]
    normal = d[~d["Fuera_De_Mes"]].groupby("Bucket")["Subtotal_MXN"].sum()
    fuera  = d[d["Fuera_De_Mes"]].groupby("Bucket")["Subtotal_MXN"].sum()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=orden, y=[float(normal.get(b, 0.0)) for b in orden],
        name="En regla", marker_color=COLOR_LYON,
        hovertemplate="<b>%{x}</b><br>$%{y:,.0f} MXN<extra></extra>",
    ))
    if bool(d["Fuera_De_Mes"].any()):
        fig.add_trace(go.Bar(
            x=orden, y=[float(fuera.get(b, 0.0)) for b in orden],
            name="Fecha fuera del mes", marker_color=_AMBER,
            hovertemplate="<b>%{x}</b><br>$%{y:,.0f} MXN (fuera de mes)<extra></extra>",
        ))

    n_fuera = int(df_rem["Fuera_De_Mes"].sum())
    n_rev   = int(df_rem["Revisar"].sum())
    partes  = []
    if n_fuera: partes.append(f"{n_fuera} con fecha fuera del mes")
    if n_rev:   partes.append(f"{n_rev} marcada(s) *** REVISAR ***")
    sub = " · ".join(partes) if partes else "Todas dentro del mes del archivo"

    fig.update_layout(
        title=(f"<b>Pendiente por facturar — {len(df_rem)} remisiones, "
               f"${df_rem['Subtotal_MXN'].sum()/1e6:,.2f}M sin IVA</b>"
               f"<br><sup>{sub}</sup>"),
        barmode="stack", template="plotly_white", height=380,
        legend=dict(orientation="h", y=-0.16, x=0),
        yaxis=dict(tickformat=_FMT_S, title="MXN"), xaxis=dict(title="Antigüedad"),
        margin=dict(t=85, b=70, l=75, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_pedido_vs_facturado(df_cross):
    """
    Pedido SAE (sin IVA) vs Facturado (sin IVA) por cliente, base para la
    tabla cruzada del bloque 5. `df_cross` cols: Cliente, Pedido_MXN,
    Facturado_MXN.
    """
    if df_cross is None or df_cross.empty:
        return _figura_vacia("Carga Ventas para cruzar pedido vs facturado")

    d = df_cross.sort_values("Facturado_MXN")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=d["Pedido_MXN"], y=d["Cliente"], orientation="h",
        name="Pedido SAE (sin IVA)", marker_color=COLOR_LYON,
        hovertemplate="<b>%{y}</b><br>Pedido: $%{x:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=d["Facturado_MXN"], y=d["Cliente"], orientation="h",
        name="Facturado (sin IVA)", marker_color=COLOR_VENTAS,
        hovertemplate="<b>%{y}</b><br>Facturado: $%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title=("<b>Pedido vs facturado por cliente</b><br><sup>"
               "Base sin IVA · la brecha es pedido no facturado en el periodo</sup>"),
        barmode="group", template="plotly_white",
        height=max(340, 40 * len(d) + 140),
        legend=dict(orientation="h", y=-0.18, x=0),
        xaxis=dict(tickformat=_FMT_S, title="MXN"), yaxis=dict(title=""),
        margin=dict(t=80, b=70, l=190, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  CONTABILIDAD — conciliación con el SAE
# ══════════════════════════════════════════════════════════════════════════════
_COLOR_EN_SAE      = COLOR_LYON
_COLOR_FUERA_SAE   = COLOR_GASTOS_EMPRESA
_COLOR_POR_REVISAR = _AMBER
_COLOR_MES_SIN_SAE = "#9E9E9E"


def plot_conciliacion_sae(resumen):
    """
    Cobertura del proceso de compras: de todo lo que reportó Contabilidad, qué
    parte pasó por el SAE y qué parte no.

    `resumen` es el dict de `conciliacion.resumen_conciliacion()`. Barra apilada
    horizontal única — el punto es la proporción, no comparar categorías entre sí,
    y así la cifra de cobertura se lee de un vistazo.
    """
    tramos = [
        ("En SAE",       resumen.get("en_sae", 0.0),       _COLOR_EN_SAE),
        ("Fuera de SAE", resumen.get("fuera_de_sae", 0.0), _COLOR_FUERA_SAE),
        ("Por revisar",  resumen.get("por_revisar", 0.0),  _COLOR_POR_REVISAR),
        ("Mes sin SAE",  resumen.get("mes_sin_sae", 0.0),  _COLOR_MES_SIN_SAE),
        ("Sin comparar", resumen.get("sin_comparar", 0.0), _COLOR_MES_SIN_SAE),
    ]
    tramos = [t for t in tramos if t[1] > 0]
    if not tramos:
        return _figura_vacia("Sin movimientos contables para el período.")

    total = sum(v for _, v, _ in tramos)
    fig = go.Figure()
    for nombre, valor, color in tramos:
        pct = valor / total * 100 if total else 0
        fig.add_trace(go.Bar(
            x=[valor], y=["Gasto contable"], orientation="h",
            name=nombre, marker_color=color,
            # Etiqueta dentro solo si el tramo da espacio; si no, estorba.
            text=[f"{pct:.0f}%" if pct >= 6 else ""],
            textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white", size=13),
            hovertemplate=f"<b>{nombre}</b><br>$%{{x:,.0f}} MXN ({pct:.1f}%)<extra></extra>",
        ))

    en_sae   = resumen.get("en_sae", 0.0)
    cobertura = en_sae / total * 100 if total else 0
    fig.update_layout(
        title=(
            "<b>¿Cuánto del gasto pasa por el proceso de compras?</b><br><sup>"
            f"Cobertura del SAE: <b>{cobertura:.1f}%</b> de "
            f"${total/1e6:,.1f}M reportados por Contabilidad</sup>"
        ),
        barmode="stack", template="plotly_white", height=250,
        legend=dict(orientation="h", y=-0.35, x=0),
        xaxis=dict(tickformat=_FMT_S, title="MXN"),
        yaxis=dict(title="", showticklabels=False),
        margin=dict(t=85, b=70, l=30, r=30),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_cobertura_sae_pie(resumen):
    """
    Pie binario: de todo lo que reportó Contabilidad, qué parte pasó por el
    proceso de compras y qué parte no. Solo dos rebanadas a propósito — la
    barra apilada de 5 tramos (`plot_conciliacion_sae`, arriba) ya vive en
    Cuadre Contable para la auditoría; aquí el punto es una pregunta simple de
    sí/no. Lo que no se puede concluir (Por revisar / Mes sin SAE / Sin
    comparar) NO tiene rebanada propia — mezclarlo aquí ya se probó confuso —
    pero tampoco desaparece: la página lo reporta aparte, como texto con su
    monto, junto a este pie.

    `resumen` es el dict de `conciliacion.resumen_conciliacion()`.
    """
    en_sae = resumen.get("en_sae", 0.0)
    fuera_sae = resumen.get("fuera_de_sae", 0.0)
    total_concluyente = en_sae + fuera_sae
    if total_concluyente <= 0:
        return _figura_vacia("Sin movimientos concluyentes para comparar contra el SAE.")

    fig = go.Figure(go.Pie(
        labels=["Sí, en el SAE", "Fuera del SAE"],
        values=[en_sae, fuera_sae], hole=0.55,
        marker=dict(colors=[_COLOR_EN_SAE, _COLOR_FUERA_SAE], line=dict(color="white", width=1.5)),
        textposition="inside", textinfo="percent",
        texttemplate="%{percent:.1%}",
        sort=False,
        hovertemplate="<b>%{label}</b><br>$%{value:,.0f} MXN<br>%{percent}<extra></extra>",
    ))
    cobertura = en_sae / total_concluyente * 100 if total_concluyente else 0
    fig.update_layout(
        title="<b>¿El gasto del libro pasó por Compras?</b>",
        template="plotly_white",
        height=380,
        annotations=[dict(
            text=f"<b>{cobertura:.0f}%</b><br><span style='font-size:12px'>en el SAE</span>",
            x=0.5, y=0.5, font=dict(size=19), showarrow=False,
        )],
        legend=dict(orientation="h", y=-0.12, x=0.15, font=dict(size=13)),
        margin=dict(t=60, b=40, l=30, r=30),
        uniformtext=dict(minsize=11, mode="hide"),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_gasto_fuera_sae(df, top_n=15):
    """
    Proveedores a los que se les paga sin que pase por el SAE, de mayor a menor.

    `df` = movimientos ya conciliados (necesita Proveedor, Monto_MXN, Estado_SAE).
    Es la lista de a quién se le paga fuera del proceso de compras — la que
    Dirección necesita para saber dónde no hay orden de compra de por medio.
    """
    if df is None or len(df) == 0 or "Estado_SAE" not in df.columns:
        return _figura_vacia("Carga la base de contabilidad para ver este análisis.")

    fuera = df[df["Estado_SAE"] == "Fuera de SAE"]
    if len(fuera) == 0:
        return _figura_vacia(
            "Todo el gasto contable del período cruza con el SAE."
        )

    g = (
        fuera.groupby("Proveedor", as_index=False)["Monto_MXN"].sum()
        .sort_values("Monto_MXN", ascending=False)
        .head(top_n)
        .sort_values("Monto_MXN")          # ascendente: la barra mayor arriba
    )
    total_fuera = float(fuera["Monto_MXN"].sum())
    mostrado    = float(g["Monto_MXN"].sum())

    fig = go.Figure(go.Bar(
        x=g["Monto_MXN"], y=[_trunc(p, 30) for p in g["Proveedor"]],
        orientation="h", marker_color=COLOR_GASTOS_EMPRESA,
        text=[f"  ${m/1e6:,.2f}M" for m in g["Monto_MXN"]],
        textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>$%{x:,.0f} MXN<extra></extra>",
    ))
    sub = (
        f"Top {len(g)} de ${total_fuera/1e6:,.1f}M sin orden de compra"
        + (f" · {mostrado/total_fuera*100:.0f}% del total mostrado"
           if total_fuera else "")
    )
    fig.update_layout(
        title=f"<b>Gasto fuera del proceso de compras</b><br><sup>{sub}</sup>",
        template="plotly_white", height=max(320, 32 * len(g) + 140),
        showlegend=False,
        xaxis=dict(tickformat=_FMT_S, title="MXN"), yaxis=dict(title=""),
        margin=dict(t=85, b=45, l=230, r=110),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_facturado_vs_gasto(df_mes, mostrar_valores=False, color_gasto=None):
    """
    Ingreso facturado contra gasto reportado por Contabilidad, mes a mes, con el
    margen en porcentaje sobre eje secundario.

    `df_mes` necesita: _Mes (Period[M]), Facturado_MXN, Gasto_MXN.

    `mostrar_valores=True` agrega el monto de cada barra como texto visible
    (por defecto apagado: Facturación solo quiere la línea de margen % como
    texto, igual que siempre). `color_gasto` sobreescribe el morado de Gastos
    de Empresa — Resultados Financieros lo pinta rojo, como todo gasto en esa
    página; por defecto se queda `COLOR_GASTOS_EMPRESA` tal cual.
    """
    if df_mes is None or len(df_mes) == 0:
        return _figura_vacia("Sin meses comparables entre facturación y contabilidad.")

    d = df_mes.sort_values("_Mes").copy()
    etiquetas = [label_mes(m) for m in d["_Mes"]]
    margen    = d["Facturado_MXN"] - d["Gasto_MXN"]
    margen_pct = [
        (m / f * 100) if f else 0.0
        for m, f in zip(margen, d["Facturado_MXN"])
    ]
    color_gasto = color_gasto or COLOR_GASTOS_EMPRESA
    _bar_kwargs = (
        dict(text=d["Facturado_MXN"], texttemplate="$%{text:,.2s}", textposition="outside")
        if mostrar_valores else {}
    )

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=etiquetas, y=d["Facturado_MXN"], name="Facturado (sin IVA)",
        marker_color=COLOR_VENTAS,
        hovertemplate="<b>%{x}</b><br>Facturado: $%{y:,.0f}<extra></extra>",
        **_bar_kwargs,
    ))
    fig.add_trace(go.Bar(
        x=etiquetas, y=d["Gasto_MXN"], name="Gasto contable",
        marker_color=color_gasto,
        hovertemplate="<b>%{x}</b><br>Gasto: $%{y:,.0f}<extra></extra>",
        **({**_bar_kwargs, "text": d["Gasto_MXN"]} if mostrar_valores else {}),
    ))
    fig.add_trace(go.Scatter(
        x=etiquetas, y=margen_pct, name="Margen %", yaxis="y2",
        mode="lines+markers+text",
        line=dict(color=COLOR_LYON, width=2),
        marker=dict(size=7),
        text=[f"{p:.0f}%" for p in margen_pct],
        textposition="top center",
        textfont=dict(size=11, color=COLOR_LYON),
        hovertemplate="<b>%{x}</b><br>Margen: %{y:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        title=("<b>Facturado vs gasto reportado por contabilidad</b><br><sup>"
               "Ingreso sin IVA contra el gasto del mismo mes · la línea es el "
               "margen sobre facturación</sup>"),
        barmode="group", template="plotly_white", height=430,
        legend=dict(orientation="h", y=-0.18, x=0),
        xaxis=dict(title=""),
        yaxis=dict(tickformat=_FMT_S, title="MXN"),
        yaxis2=dict(overlaying="y", side="right", ticksuffix="%",
                    title="Margen", showgrid=False, zeroline=False),
        margin=dict(t=90, b=70, l=75, r=70),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  CONTABILIDAD — mezcla de cobro
# ══════════════════════════════════════════════════════════════════════════════
def plot_cobranza_mix(df_cfdi):
    """
    Cómo se cobra la facturación del año: a crédito (PPD) contra de contado
    (PUE), por mes. Una mezcla mayoritaria de PPD es una señal de flujo de
    efectivo que hoy no aparece en ningún otro lado de la app.
    """
    if df_cfdi is None or len(df_cfdi) == 0:
        return _figura_vacia("Sin facturación CFDI cargada para este análisis.")

    d = df_cfdi[
        df_cfdi["Tipo_Doc"].str.upper().str.startswith("FACTURA")
        & ~df_cfdi["Cancelado"]
    ].copy()
    if len(d) == 0:
        return _figura_vacia("Sin facturas vigentes para este análisis.")

    d["_metodo"] = d["Metodo_Pago"].replace("", "Sin especificar")
    g = (
        d.groupby([d["_Mes"].astype(str), "_metodo"])["Importe_MXN"]
        .sum().unstack(fill_value=0.0)
    )
    etiquetas = [label_mes(pd.Period(m, "M")) for m in g.index]
    colores = {"PPD": _AMBER, "PUE": _GREEN, "Sin especificar": "#9E9E9E"}

    fig = go.Figure()
    for metodo in g.columns:
        fig.add_trace(go.Bar(
            x=etiquetas, y=g[metodo], name=metodo,
            marker_color=colores.get(metodo, COLOR_LYON),
            hovertemplate=f"<b>%{{x}}</b><br>{metodo}: $%{{y:,.0f}}<extra></extra>",
        ))

    total = float(g.to_numpy().sum())
    ppd_pct = float(g["PPD"].sum()) / total * 100 if total and "PPD" in g.columns else 0.0

    fig.update_layout(
        title=(
            "<b>Cómo se cobra la facturación</b><br><sup>"
            f"PPD (a crédito) es el {ppd_pct:.0f}% del importe facturado</sup>"
        ),
        barmode="stack", template="plotly_white", height=380,
        legend=dict(orientation="h", y=-0.18, x=0),
        xaxis=dict(title=""), yaxis=dict(tickformat=_FMT_S, title="MXN"),
        margin=dict(t=85, b=60, l=70, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  RESULTADOS FINANCIEROS — la página del chairman
# ══════════════════════════════════════════════════════════════════════════════
def plot_cascada_mes(ingresos, gasto_por_cuenta, piso, techo, etiqueta_mes,
                     sin_clasificar=0.0, top_n=6):
    """
    Cascada del mes: Ingresos confirmados → top-N cuentas de gasto (pasos
    rojos) → "Otras cuentas" si sobra → "Sin clasificar" (ámbar, solo si > 0)
    → Resultado.

    El paso ámbar hace el rango piso/techo visible en la propia gráfica: la
    barra justo ANTES de él es el *techo* (mejor caso, como si lo pendiente no
    fuera gasto) y la cascada aterriza en el *piso* (peor caso, como si todo
    lo pendiente sí lo fuera) — el rango deja de ser una nota al pie.

    `go.Waterfall` solo pinta 3 colores (increasing/decreasing/totals), no uno
    por barra, así que esta cascada se arma a mano con `go.Bar` + `base`
    (la técnica estándar de "floating bars" para un waterfall con colores por
    paso) — mismo lenguaje visual que `plot_waterfall_margen`, un trace más
    flexible por la necesidad real de un cuarto color.

    `gasto_por_cuenta`: {Cuenta_Nombre: monto} del mes, ya filtrado a
    Naturaleza == Gasto operativo — nunca incluye lo sin clasificar, eso
    entra aparte por `sin_clasificar`.
    """
    if ingresos is None or piso is None or techo is None:
        return _figura_vacia("No hay suficientes fuentes para la cascada de este mes.")

    items = sorted(
        ((k, v) for k, v in gasto_por_cuenta.items() if v > 0),
        key=lambda kv: kv[1], reverse=True,
    )
    top   = items[:top_n]
    resto = sum(v for _, v in items[top_n:])

    pasos = [("Ingresos", ingresos, "total")]
    pasos += [(_trunc(k), -v, "gasto") for k, v in top]
    if resto > 0:
        pasos.append(("Otras cuentas", -resto, "gasto"))
    if sin_clasificar > 0:
        pasos.append(("Sin clasificar", -sin_clasificar, "sinclas"))
    pasos.append(("Resultado", None, "total"))

    labels, bases, alturas, colores, textos = [], [], [], [], []
    acumulado = 0.0
    for i, (nombre, delta, tipo) in enumerate(pasos):
        if i == 0:
            base, altura, acumulado = 0.0, ingresos, ingresos
            color, texto = _GREEN, f"${ingresos/1e6:,.2f}M"
        elif tipo == "total":
            base, altura = min(0.0, acumulado), abs(acumulado)
            color, texto = COLOR_LYON, f"${acumulado/1e6:,.2f}M"
        else:
            nuevo = acumulado + delta
            base, altura = min(acumulado, nuevo), abs(delta)
            acumulado = nuevo
            color = _AMBER if tipo == "sinclas" else _RED
            texto = f"-${abs(delta)/1e6:,.2f}M"
        labels.append(nombre); bases.append(base); alturas.append(altura)
        colores.append(color); textos.append(texto)

    fig = go.Figure(go.Bar(
        x=labels, y=alturas, base=bases,
        marker=dict(color=colores, line=dict(color="white", width=1)),
        text=textos, textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
    ))
    # Líneas punteadas de continuidad entre barras, mismo estilo que el
    # connector de `plot_waterfall_margen` — sin ellas, las barras flotantes
    # no se leen como cascada.
    for i in range(len(labels) - 1):
        y_conector = bases[i] + alturas[i] if colores[i] != _RED and colores[i] != _AMBER else bases[i]
        fig.add_shape(
            type="line", x0=i + 0.4, x1=i + 1 - 0.4, y0=y_conector, y1=y_conector,
            line=dict(color="#E5E7EB", width=1, dash="dot"),
        )

    subt = f"Techo ${techo/1e6:,.2f}M · Piso ${piso/1e6:,.2f}M" if piso != techo else f"${techo/1e6:,.2f}M"
    fig.update_layout(
        title=(f"<b>Cómo nos fue en {etiqueta_mes}</b><br><sup>{subt}</sup>"),
        template="plotly_white", height=440, showlegend=False,
        yaxis=dict(tickformat="$,.0f", title="MXN"),
        xaxis_title="",
        margin=dict(t=90, b=60, l=60, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_cascada_anual(resultado_por_mes, total_piso, total_techo):
    """
    Cascada del año: un paso por mes (su Resultado, lado piso del rango — el
    caso conservador), cerrando en el acumulado del periodo. Verde si el mes
    suma al acumulado, rojo si resta — gratis con `go.Waterfall`, que sí
    alcanza aquí porque solo hacen falta los 3 colores de siempre.

    `resultado_por_mes`: {pd.Period: float}, ya sobre meses comparables
    (ingreso y gasto a la vez) — nunca mezcla un mes sin la otra fuente.
    """
    if not resultado_por_mes:
        return _figura_vacia("No hay meses comparables para la cascada del año.")

    meses  = sorted(resultado_por_mes)
    deltas = [resultado_por_mes[m] for m in meses]
    labels = [label_mes(m) for m in meses] + ["Total"]

    values   = deltas + [0]
    measures = ["relative"] * len(deltas) + ["total"]
    textos   = (
        [f"{'+' if d >= 0 else ''}${d/1e6:,.2f}M" for d in deltas]
        + [f"${total_piso/1e6:,.2f}M"]
    )

    fig = go.Figure(go.Waterfall(
        x=labels, y=values, measure=measures,
        text=textos, textposition="outside", cliponaxis=False,
        connector=dict(line=dict(color="#E5E7EB", width=1)),
        increasing=dict(marker=dict(color=_GREEN)),
        decreasing=dict(marker=dict(color=_RED)),
        totals=dict(marker=dict(color=COLOR_LYON)),
        hovertemplate="<b>%{x}</b><br>$%{y:,.0f} MXN<extra></extra>",
    ))
    subt = (
        f"Acumulado: ${total_piso/1e6:,.2f}M – ${total_techo/1e6:,.2f}M"
        if total_piso != total_techo else f"Acumulado: ${total_techo/1e6:,.2f}M"
    )
    fig.update_layout(
        title=(f"<b>Cómo se ve el año</b><br><sup>{subt}</sup>"),
        template="plotly_white", height=420, showlegend=False,
        yaxis=dict(tickformat="$,.0f", title="MXN"),
        xaxis_title="",
        margin=dict(t=90, b=60, l=80, r=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_gasto_por_cuenta_mes(df_cuenta_mes, top_n=6):
    """
    Evolución del gasto operativo por cuenta contable, mes a mes — barras
    apiladas, top-N cuentas (por su total en la ventana) + "Otras cuentas" en
    gris, `barmode="relative"` para tolerar algún mes con ajuste negativo.

    `df_cuenta_mes`: DataFrame[Cuenta, Cuenta_Nombre, _Mes, Monto_MXN] — la
    forma exacta que regresa `core.fuentes.gasto_contable_desglosado()["por_cuenta_y_mes"]`.
    """
    if df_cuenta_mes is None or len(df_cuenta_mes) == 0:
        return _figura_vacia("Sin gasto operativo clasificado en el periodo.")

    d = df_cuenta_mes[df_cuenta_mes["Monto_MXN"] != 0].copy()
    if len(d) == 0:
        return _figura_vacia("Sin gasto operativo clasificado en el periodo.")

    ranking = (d.groupby("Cuenta_Nombre")["Monto_MXN"].sum()
                 .sort_values(ascending=False))
    top_cuentas = ranking.head(top_n).index.tolist()

    meses = sorted(d["_Mes"].unique())
    x = [label_mes(m) for m in meses]

    fig = go.Figure()
    for i, cta in enumerate(top_cuentas):
        sub = d[d["Cuenta_Nombre"] == cta].set_index("_Mes")
        y = [float(sub.loc[m, "Monto_MXN"]) if m in sub.index else 0.0 for m in meses]
        fig.add_trace(go.Bar(
            x=x, y=y, name=_trunc(cta, 28),
            marker=dict(color=PALETA_PRINCIPAL[i % len(PALETA_PRINCIPAL)],
                        line=dict(color="white", width=1)),
            hovertemplate=f"<b>{cta}</b><br>%{{x}}: $%{{y:,.0f}} MXN<extra></extra>",
        ))

    otras = d[~d["Cuenta_Nombre"].isin(top_cuentas)]
    if len(otras):
        sub = otras.groupby("_Mes")["Monto_MXN"].sum()
        y = [float(sub.get(m, 0.0)) for m in meses]
        if any(v != 0 for v in y):
            fig.add_trace(go.Bar(
                x=x, y=y, name="Otras cuentas",
                marker=dict(color="#9E9E9E", line=dict(color="white", width=1)),
                hovertemplate="<b>Otras cuentas</b><br>%{x}: $%{y:,.0f} MXN<extra></extra>",
            ))

    fig.update_layout(
        title=(
            f"<b>Gasto operativo por cuenta contable</b>"
            f"<br><sup>Top {min(top_n, len(ranking))} cuentas de la ventana + Otras</sup>"
        ),
        barmode="relative", template="plotly_white", height=460,
        legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=10)),
        yaxis=dict(tickformat=_FMT_S, title="MXN"), xaxis_title="",
        margin=dict(t=80, b=110, l=75, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig
