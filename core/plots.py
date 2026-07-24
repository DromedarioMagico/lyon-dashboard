"""
Plotly figure generators — ported from the standalone Colab scripts.
Each function receives a DataFrame (already filtered) + parameters
and returns a go.Figure ready for st.plotly_chart().
"""
import plotly.express as px
import plotly.graph_objects as go

from core.catalogos import PALETA_CATEGORIAS, ETIQ_PENDIENTE, PALETA_PRINCIPAL, label_mes

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
def plot_ventas_por_vendedor(df, venta_total):
    vv = (df.groupby("Vendedor")
            .agg(Ventas=("Importe_MXN", "sum"),
                 Pedidos=("Importe_MXN", "count"),
                 Comisiones=("Comision_MXN", "sum"))
            .sort_values("Ventas", ascending=False)
            .reset_index())

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
        text=[f"${v/1e6:,.2f}M  ·  {p} pedidos"
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
