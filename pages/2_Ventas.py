import datetime as dt

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.catalogos import COLOR_LYON, COLOR_VENTAS, label_mes
from core.cruce_ventas import (
    cruzar_pedidos_facturas, descomponer_sin_factura, bucket_antiguedad,
    FACTURADO, SIN_FACTURA, SIN_OC,
)
from core.database import init_db
from core.etl_ventas import cargar_ventas, aplicar_vendedores
from core.navigation import render_sidebar_search, render_sidebar_status, inject_custom_css, handle_pending_nav, breadcrumb, render_periodo_filter, parse_semana_x
from core.plots import (
    plot_barras_temporales,
    plot_donut_clientes_ventas,
    plot_donut_resto_clientes,
    plot_curva_semanal_ventas,
    plot_pareto_clientes_ventas,
    plot_ventas_por_vendedor,
    plot_heatmap_cliente_mes,
    plot_embudo_facturacion,
    plot_pedido_vs_facturado,
    plot_cobranza_mix,
)

st.set_page_config(
    page_title="Ventas — Lyon AG",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_db()
inject_custom_css()
handle_pending_nav()

# ── KPI card helper ───────────────────────────────────────────────────────────
def _kpi(label, value, color):
    return f"""
    <div style="background:#fff;border:1px solid #E1E7EC;border-radius:10px;
                padding:1rem 1.25rem;box-shadow:0 1px 4px rgba(0,0,0,.05);">
      <p style="margin:0 0 4px;font-size:.72rem;font-weight:600;color:#6B7280;
                text-transform:uppercase;letter-spacing:.5px;">{label}</p>
      <p style="margin:0;font-size:1.65rem;font-weight:700;color:{color};
                line-height:1.2;">{value}</p>
    </div>"""

_BLUE  = COLOR_LYON
_GREEN = COLOR_VENTAS
_RED   = "#C00000"
_AMBER = "#E97132"
_GRAY  = "#9E9E9E"


def _marcar_base(fig, base):
    """
    Imprime la base monetaria activa (Con/Sin IVA) en la esquina de cada
    gráfica — para que ninguna captura de pantalla viaje sin decir sobre qué
    está medida. `fig` puede ser None (algunas gráficas se ocultan cuando no
    hay suficientes datos); se pasa de largo sin tronar.
    """
    if fig is None:
        return fig
    fig.add_annotation(
        text=f"Base: {base}", xref="paper", yref="paper", x=1, y=1.05,
        showarrow=False, font=dict(size=10, color="#9CA3AF"), align="right",
        xanchor="right",
    )
    return fig


# ── Vista de detalle inline ───────────────────────────────────────────────────
def _render_detalle_cliente(df_ctx, cliente):
    df = df_ctx[df_ctx["Cliente_Nombre"] == cliente].copy()
    _disp = (df["Cliente_Display"].iloc[0] if len(df) > 0 else cliente)
    _bc   = _disp if len(_disp) <= 50 else _disp[:49] + "…"
    breadcrumb([
        ("Ventas", {"clear": ["drill_cliente", "curva_semanal_ventas_chart"]}, None),
        (_bc, None, None),
    ])

    if len(df) == 0:
        st.warning(
            f"**{cliente}** no tiene pedidos en el periodo seleccionado. "
            "Ajusta el filtro de período en el sidebar para verlo."
        )
        return

    display_name  = df["Cliente_Display"].iloc[0]
    venta_total   = df["Importe_MXN"].sum()
    n_pedidos     = len(df)
    tick_prom     = df["Importe_MXN"].mean()
    tick_med      = df["Importe_MXN"].median()
    fecha_min     = df["Fecha"].min()
    fecha_max     = df["Fecha"].max()

    vend_principal = (
        df[df["Vendedor"] != "Sin asignar"]
        .groupby("Vendedor")["Importe_MXN"].sum().idxmax()
        if (df["Vendedor"] != "Sin asignar").any() else "Sin asignar"
    )

    st.markdown(f"<h2 style='margin-bottom:6px'>{display_name}</h2>", unsafe_allow_html=True)
    if display_name != cliente:
        st.caption(cliente)
    st.markdown("<div style='margin-top:1rem'></div>", unsafe_allow_html=True)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.markdown(_kpi("Venta Total",    f"${venta_total/1e6:,.2f}M",                     _GREEN), unsafe_allow_html=True)
    k2.markdown(_kpi("Pedidos",        f"{n_pedidos:,}",                                 _BLUE),  unsafe_allow_html=True)
    k3.markdown(_kpi("Ticket Prom.",   f"${tick_prom:,.0f}",                             _GREEN), unsafe_allow_html=True)
    k4.markdown(_kpi("Ticket Med.",    f"${tick_med:,.0f}",                              _GREEN), unsafe_allow_html=True)
    k5.markdown(_kpi("Vendedor Ppal.", vend_principal,                                   _BLUE),  unsafe_allow_html=True)

    st.divider()

    # Ventas mensuales (agregación anual automática si el periodo es largo)
    with st.container(border=True):
        st.plotly_chart(
            _marcar_base(plot_barras_temporales(
                df, "Importe_MXN", f"Ventas Mensuales — {display_name}", COLOR_VENTAS
            ), vta_base),
            use_container_width=True,
        )

    # Desglose por vendedor (solo si hay más de uno)
    if df["Vendedor"].nunique() > 1:
        with st.container(border=True):
            vv = (df.groupby("Vendedor")
                    .agg(Ventas=("Importe_MXN", "sum"), Pedidos=("Importe_MXN", "count"))
                    .sort_values("Ventas", ascending=False).reset_index())
            fig2 = px.bar(
                vv, x="Vendedor", y="Ventas",
                title="<b>Ventas por Vendedor</b>",
                color_discrete_sequence=[COLOR_LYON], text="Ventas",
            )
            fig2.update_traces(
                texttemplate="$%{text:,.0f}", textposition="outside",
                customdata=vv["Pedidos"],
                hovertemplate="<b>%{x}</b><br>Ventas: $%{y:,.0f}<br>Pedidos: %{customdata}<extra></extra>",
            )
            fig2.update_layout(
                template="plotly_white", height=360, showlegend=False,
                xaxis_title="", yaxis_title="Ventas (MXN)",
                margin=dict(t=80, b=40, l=60, r=40),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            fig2.update_yaxes(tickformat=",.0f", tickprefix="$")
            st.plotly_chart(_marcar_base(fig2, vta_base), use_container_width=True)

    # Tabla completa de pedidos
    with st.container(border=True):
        st.markdown("##### Todos los Pedidos")
        tbl = df[["Clave", "Fecha", "Vendedor", "Importe_MXN", "Estatus"]].copy()
        tbl["Fecha"] = tbl["Fecha"].dt.strftime("%d-%b-%Y")
        tbl = tbl.sort_values("Importe_MXN", ascending=False).reset_index(drop=True)
        tbl.index = tbl.index + 1
        st.dataframe(
            tbl, use_container_width=True, hide_index=False,
            column_config={
                "Clave":       st.column_config.TextColumn("Clave"),
                "Fecha":       st.column_config.TextColumn("Fecha"),
                "Vendedor":    st.column_config.TextColumn("Vendedor"),
                "Importe_MXN": st.column_config.NumberColumn("Importe (MXN)", format="$%,.2f"),
                "Estatus":     st.column_config.TextColumn("Estatus"),
            },
            height=min(600, 48 + 36 * len(tbl)),
        )

    # ── El ciclo de este cliente (condicional al reporte CFDI) ────────────────
    if _pedidos_cx is not None:
        _meses_ctx_c = set(df["_Mes"].unique())
        _ped_cli = _pedidos_cx[
            (_pedidos_cx["Cliente_Nombre"] == cliente) & (_pedidos_cx["_Mes"].isin(_meses_ctx_c))
        ]
        if len(_ped_cli):
            with st.container(border=True):
                st.markdown("##### Línea de tiempo: pedido → factura")
                st.caption("Sin IVA — del cruce contra el reporte CFDI.")
                _tbl_cli = _ped_cli[
                    ["Clave", "Fecha", "Subtotal_MXN", "Estado_Cruce",
                     "Facturado_MXN", "Dias_Ciclo", "Su pedido"]
                ].sort_values("Fecha", ascending=False).rename(columns={
                    "Subtotal_MXN": "Pedido sin IVA", "Facturado_MXN": "Facturado sin IVA",
                    "Dias_Ciclo": "Ciclo (días)", "Su pedido": "OC",
                })
                st.dataframe(
                    _tbl_cli, use_container_width=True, hide_index=True,
                    column_config={
                        "Fecha": st.column_config.DateColumn(format="DD-MMM-YYYY"),
                        "Pedido sin IVA": st.column_config.NumberColumn(format="$%,.0f"),
                        "Facturado sin IVA": st.column_config.NumberColumn(format="$%,.0f"),
                        "Ciclo (días)": st.column_config.NumberColumn(format="%.0f"),
                    },
                    height=min(420, 45 + 36 * min(len(_tbl_cli), 10)),
                )

        _notas_cli = _df_cfdi_raw[
            (_df_cfdi_raw["Tipo_Doc"] == "Nota Cred") & (~_df_cfdi_raw["Cancelado"]) &
            (_df_cfdi_raw["Cliente_Nombre"] == cliente) &
            (_df_cfdi_raw["_Mes"].isin(_meses_ctx_c))
        ] if _df_cfdi_raw is not None else None
        if _notas_cli is not None and len(_notas_cli):
            with st.container(border=True):
                st.markdown("##### Notas de crédito de este cliente")
                st.dataframe(
                    _notas_cli[["Fecha", "Folio", "Subtotal_MXN"]]
                    .rename(columns={"Subtotal_MXN": "Monto sin IVA"})
                    .sort_values("Fecha", ascending=False),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Fecha": st.column_config.DateColumn(format="DD-MMM-YYYY"),
                        "Monto sin IVA": st.column_config.NumberColumn(format="$%,.0f"),
                    },
                )


# ── Vista de detalle por vendedor ────────────────────────────────────────────
def _render_detalle_vendedor(df_ctx, vendedor):
    _bc_v = vendedor if len(vendedor) <= 50 else vendedor[:49] + "…"
    breadcrumb([
        ("Ventas", {"clear": ["drill_vendedor", "curva_semanal_ventas_chart"]}, None),
        (_bc_v, None, None),
    ])

    df = df_ctx[df_ctx["Vendedor"] == vendedor].copy()
    if len(df) == 0:
        st.warning(
            f"**{vendedor}** no tiene pedidos en el periodo seleccionado. "
            "Ajusta el filtro de período en el sidebar para verlo."
        )
        return

    # ── Métricas individuales ──────────────────────────────────────────────────
    venta_total   = df["Importe_MXN"].sum()
    n_pedidos     = len(df)
    tick_prom     = df["Importe_MXN"].mean()
    comisiones    = df["Comision_MXN"].sum()
    clientes_uniq = df["Cliente_Nombre"].nunique()
    comis_pp      = comisiones / n_pedidos if n_pedidos > 0 else 0
    tasa_cumpl    = (df["Estatus"] == "Remitido").mean() * 100
    top_cli_monto = df.groupby("Cliente_Nombre")["Importe_MXN"].sum().max() if venta_total > 0 else 0
    concentracion = top_cli_monto / venta_total * 100 if venta_total > 0 else 0

    st.markdown(f"<h2 style='margin-bottom:6px'>Vendedor: {vendedor}</h2>",
                unsafe_allow_html=True)
    st.markdown("<div style='margin-top:1rem'></div>", unsafe_allow_html=True)

    # Fila 1 — volumen
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_kpi("Venta Total",    f"${venta_total/1e6:,.2f}M", _GREEN), unsafe_allow_html=True)
    k2.markdown(_kpi("Pedidos",        f"{n_pedidos:,}",             _BLUE),  unsafe_allow_html=True)
    k3.markdown(_kpi("Ticket Prom.",   f"${tick_prom:,.0f}",         _GREEN), unsafe_allow_html=True)
    k4.markdown(_kpi("Comisiones",     f"${comisiones:,.0f}",        _GREEN), unsafe_allow_html=True)

    st.markdown("<div style='margin-top:.75rem'></div>", unsafe_allow_html=True)

    # Fila 2 — calidad
    k5, k6, k7, k8 = st.columns(4)
    k5.markdown(_kpi("Comisión / Pedido",  f"${comis_pp:,.0f}",      _GREEN), unsafe_allow_html=True)
    k6.markdown(_kpi("Clientes Únicos",    f"{clientes_uniq:,}",      _BLUE),  unsafe_allow_html=True)
    k7.markdown(_kpi("Concentración",      f"{concentracion:.1f}%",   _BLUE),  unsafe_allow_html=True)
    k8.markdown(_kpi("Tasa Cumplimiento",  f"{tasa_cumpl:.1f}%",      _BLUE),  unsafe_allow_html=True)

    # Fila 3 — el ciclo (condicional al reporte CFDI)
    if _pedidos_cx is not None:
        _meses_ctx = set(df["_Mes"].unique())
        _ped_vend = _pedidos_cx[
            (_pedidos_cx["Vendedor"] == vendedor) & (_pedidos_cx["_Mes"].isin(_meses_ctx))
        ]
        _ped_con_oc = _ped_vend[_ped_vend["Estado_Cruce"] != SIN_OC]
        _pedido_oc_total = float(_ped_con_oc["Subtotal_MXN"].sum())
        _facturado_oc_total = float(_ped_con_oc["Facturado_MXN"].sum())
        _pct_convertido = (
            _facturado_oc_total / _pedido_oc_total * 100 if _pedido_oc_total > 0 else None
        )
        _dias_vend = _ped_vend.loc[_ped_vend["Estado_Cruce"] == FACTURADO, "Dias_Ciclo"].dropna()
        _ciclo_vend = float(_dias_vend.median()) if len(_dias_vend) else None
        _remitido_vend, _ = descomponer_sin_factura(_ped_vend)
        _remitido_vend_mxn = float(_remitido_vend["Subtotal_MXN"].sum())

        st.markdown("<div style='margin-top:.75rem'></div>", unsafe_allow_html=True)
        k9, k10, k11 = st.columns(3)
        k9.markdown(_kpi(
            "% pedido → factura",
            f"{_pct_convertido:.0f}%" if _pct_convertido is not None else "—",
            _GREEN if (_pct_convertido or 0) >= 80 else _AMBER,
        ), unsafe_allow_html=True)
        k10.markdown(_kpi(
            "Ciclo mediano",
            f"{_ciclo_vend:.0f} días" if _ciclo_vend is not None else "—",
            _BLUE,
        ), unsafe_allow_html=True)
        k11.markdown(_kpi(
            "Remitido sin facturar",
            f"${_remitido_vend_mxn/1e6:,.2f}M" if _remitido_vend_mxn > 0 else "$0",
            _GREEN if _remitido_vend_mxn == 0 else _AMBER,
        ), unsafe_allow_html=True)
        st.caption(
            "Del cruce contra el reporte CFDI, sin IVA. Solo pedidos con OC "
            "entran al % de conversión — los que no traen OC no se pueden "
            "amarrar documento a documento."
        )

    st.divider()

    # ── Ventas mensuales (agregación anual automática si el periodo es largo) ──
    with st.container(border=True):
        st.plotly_chart(
            _marcar_base(plot_barras_temporales(
                df, "Importe_MXN", f"Ventas Mensuales — {vendedor}", COLOR_VENTAS
            ), vta_base),
            use_container_width=True,
        )

    # ── Top clientes de este vendedor ──────────────────────────────────────────
    n2d = (df.drop_duplicates("Cliente_Nombre")
             .set_index("Cliente_Nombre")["Cliente_Display"].to_dict())
    top_cli = (df.groupby("Cliente_Nombre", as_index=False)["Importe_MXN"].sum()
                 .sort_values("Importe_MXN", ascending=False).head(10))
    top_cli["Display"] = top_cli["Cliente_Nombre"].apply(lambda c: n2d.get(c, c))
    pct_top = top_cli["Importe_MXN"].sum() / venta_total * 100

    with st.container(border=True):
        fig3 = px.bar(
            top_cli.sort_values("Importe_MXN", ascending=True),
            x="Importe_MXN", y="Display", orientation="h",
            title=(f"<b>Top 10 Clientes — {vendedor}</b>"
                   f"<br><sup>Concentran el {pct_top:.1f}% de sus ventas</sup>"),
            color_discrete_sequence=[COLOR_LYON], text="Importe_MXN",
        )
        fig3.update_traces(
            texttemplate="$%{text:,.0f}", textposition="outside",
            customdata=top_cli.sort_values("Importe_MXN", ascending=True)["Cliente_Nombre"].values,
            hovertemplate="<b>%{customdata}</b><br>$%{x:,.0f} MXN<extra></extra>",
        )
        fig3.update_layout(
            template="plotly_white", height=460, showlegend=False,
            xaxis_title="Ventas (MXN)", yaxis_title="",
            margin=dict(t=100, b=60, l=200, r=130),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        fig3.update_xaxes(tickformat=",.0f", tickprefix="$")
        st.plotly_chart(_marcar_base(fig3, vta_base), use_container_width=True)

    # ── Tabla completa de pedidos ──────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("##### Todos los Pedidos")
        tbl = df[["Clave", "Fecha", "Cliente_Nombre", "Importe_MXN", "Estatus"]].copy()
        tbl["Fecha"] = tbl["Fecha"].dt.strftime("%d-%b-%Y")
        tbl = tbl.sort_values("Importe_MXN", ascending=False).reset_index(drop=True)
        tbl.index = tbl.index + 1
        st.dataframe(
            tbl, use_container_width=True, hide_index=False,
            column_config={
                "Clave":          st.column_config.TextColumn("Clave"),
                "Fecha":          st.column_config.TextColumn("Fecha"),
                "Cliente_Nombre": st.column_config.TextColumn("Cliente"),
                "Importe_MXN":    st.column_config.NumberColumn("Importe (MXN)", format="$%,.2f"),
                "Estatus":        st.column_config.TextColumn("Estatus"),
            },
            height=min(600, 48 + 36 * len(tbl)),
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  COMPARATIVA CON EL EQUIPO
    # ══════════════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("#### ⚔️ Comparativa con el equipo")

    real_df = df_ctx[df_ctx["Vendedor"] != "Sin asignar"]
    team = (real_df.groupby("Vendedor")
            .agg(
                Ventas=("Importe_MXN", "sum"),
                Pedidos=("Importe_MXN", "count"),
                Ticket=("Importe_MXN", "mean"),
                Clientes=("Cliente_Nombre", "nunique"),
                Comisiones=("Comision_MXN", "sum"),
            ).reset_index())

    rem_pct = (real_df.assign(_r=real_df["Estatus"] == "Remitido")
               .groupby("Vendedor")["_r"].mean() * 100)
    team = team.set_index("Vendedor")
    team["Cumplimiento"] = rem_pct
    team["Comision_pp"]  = team["Comisiones"] / team["Pedidos"]
    team = team.reset_index()
    n_team = len(team)

    if n_team < 2 or vendedor not in team["Vendedor"].values:
        st.info("No hay suficientes vendedores para comparar.")
    else:
        # ── Medallas de ranking ────────────────────────────────────────────────
        def _rank(col, asc=False):
            return team.sort_values(col, ascending=asc)["Vendedor"].tolist().index(vendedor) + 1

        def _medal(r):
            return {1: "🥇", 2: "🥈", 3: "🥉"}.get(r, f"#{r}")

        ranks = {
            "Ventas":       _rank("Ventas"),
            "Ticket":       _rank("Ticket"),
            "Clientes":     _rank("Clientes"),
            "Cumplimiento": _rank("Cumplimiento"),
            "Comisión/Ped": _rank("Comision_pp"),
        }

        cols_r = st.columns(len(ranks))
        for col_w, (label, r) in zip(cols_r, ranks.items()):
            col_w.markdown(
                f"<div style='text-align:center;background:#fff;border:1px solid #E1E7EC;"
                f"border-radius:10px;padding:.75rem .5rem;box-shadow:0 1px 4px rgba(0,0,0,.05)'>"
                f"<p style='margin:0 0 2px;font-size:.68rem;font-weight:600;color:#6B7280;"
                f"text-transform:uppercase;letter-spacing:.5px'>{label}</p>"
                f"<p style='margin:0;font-size:1.8rem;line-height:1.1'>{_medal(r)}</p>"
                f"<p style='margin:0;font-size:.78rem;color:#6B7280'>de {n_team}</p>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<div style='margin-top:1.25rem'></div>", unsafe_allow_html=True)

        # ── Radar chart ────────────────────────────────────────────────────────
        dims      = ["Ventas", "Ticket", "Clientes", "Cumplimiento", "Comision_pp"]
        dim_lbl   = ["Ventas", "Ticket Prom.", "Clientes", "Cumplimiento %", "Comisión/Ped."]

        # Normaliza cada dimensión → 0–100 (mejor del equipo = 100)
        t = team.copy()
        for d in dims:
            mx = t[d].max()
            t[f"{d}_n"] = t[d] / mx * 100 if mx > 0 else 0.0

        vrow = t[t["Vendedor"] == vendedor].iloc[0]
        vvals = [vrow[f"{d}_n"] for d in dims]
        avals = [t[f"{d}_n"].mean() for d in dims]

        # Cierra el polígono
        vc = vvals + [vvals[0]]
        ac = avals + [avals[0]]
        lc = dim_lbl + [dim_lbl[0]]

        fig_r = go.Figure()
        fig_r.add_trace(go.Scatterpolar(
            r=vc, theta=lc, fill="toself", name=vendedor,
            line=dict(color=COLOR_VENTAS, width=2.5),
            fillcolor="rgba(84,130,53,0.22)",
        ))
        fig_r.add_trace(go.Scatterpolar(
            r=ac, theta=lc, fill="toself", name="Promedio equipo",
            line=dict(color=COLOR_LYON, width=2, dash="dash"),
            fillcolor="rgba(31,78,121,0.08)",
        ))
        fig_r.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True, range=[0, 100],
                    tickfont=dict(size=9), ticksuffix="%",
                    gridcolor="#E5E7EB",
                ),
                angularaxis=dict(tickfont=dict(size=11)),
                bgcolor="rgba(0,0,0,0)",
            ),
            template="plotly_white",
            height=460,
            margin=dict(t=60, b=80, l=80, r=80),
            legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center",
                        font=dict(size=12)),
            paper_bgcolor="rgba(0,0,0,0)",
        )

        with st.container(border=True):
            st.caption("100 = mejor del equipo en esa dimensión · Verde = este vendedor · Azul punteado = promedio")
            st.plotly_chart(_marcar_base(fig_r, vta_base), use_container_width=True)

        # ── Tabla scoreboard completa ──────────────────────────────────────────
        with st.container(border=True):
            st.markdown("##### Scoreboard del equipo")
            sb = team[["Vendedor", "Ventas", "Ticket", "Clientes",
                        "Cumplimiento", "Comision_pp"]].sort_values(
                "Ventas", ascending=False).reset_index(drop=True)
            sb.index = sb.index + 1
            st.dataframe(
                sb, use_container_width=True, hide_index=False,
                column_config={
                    "Vendedor":    st.column_config.TextColumn("Vendedor"),
                    "Ventas":      st.column_config.NumberColumn("Ventas",          format="$%,.0f"),
                    "Ticket":      st.column_config.NumberColumn("Ticket Prom.",    format="$%,.0f"),
                    "Clientes":    st.column_config.NumberColumn("Clientes",        format="%d"),
                    "Cumplimiento":st.column_config.NumberColumn("Cumplimiento %",  format="%.1f%%"),
                    "Comision_pp": st.column_config.NumberColumn("Comisión / Ped.", format="$%,.0f"),
                },
                height=min(400, 48 + 36 * len(sb)),
            )


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    render_sidebar_search()
    render_sidebar_status()

st.markdown(
    f"<h1 style='color:{COLOR_VENTAS}'>"
    "<span class='material-symbols-outlined'>bar_chart</span>Ventas</h1>",
    unsafe_allow_html=True,
)

# ── Upload ────────────────────────────────────────────────────────────────────
if "df_ventas" not in st.session_state:
    st.markdown("Sube el archivo SAE de pedidos para ver el dashboard.")
    uploaded = st.file_uploader(
        "Archivo SAE de Ventas",
        type=["xlsx", "xlsm", "xls"],
        label_visibility="collapsed",
    )
    if uploaded:
        with st.spinner("Procesando archivo…"):
            try:
                df, warns = cargar_ventas(uploaded)
                st.session_state.df_ventas = df
                st.session_state.df_ventas_meta = {
                    "archivo":     uploaded.name,
                    "uploaded_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "total_rows":  len(df),
                }
                for w in warns:
                    st.warning(w)
                st.success(f"✅ {len(df):,} pedidos cargados.")
                st.rerun()
            except ValueError as e:
                st.error(f"Error al procesar el archivo:\n\n{e}")
    st.stop()

# ──────────────────────────────────────────────────────────────────────────────
#  Drill-down de semana — Ventas
# ──────────────────────────────────────────────────────────────────────────────
def _render_detalle_semana_ventas(df_full, df, semana_str):
    """Week-level drill-down for ventas: clients, sellers, and orders for a specific week."""
    # ── Parsear fechas (también para el label del breadcrumb) ────────────────
    week_label = parse_semana_x(semana_str)
    if week_label is not None:
        week_start = week_label - pd.Timedelta(days=6)
        week_end   = week_label
        _bc_label  = f"{week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}"
    else:
        week_start = week_end = None
        _bc_label  = str(semana_str)

    breadcrumb([
        ("Ventas", {"clear": ["drill_semana_v", "curva_semanal_ventas_chart", "vta_semana_pick", "sem_v_pareto_chart", "sem_v_vendedor_chart", "sem_v_pedidos_table"]}, None),
        (_bc_label, None, None),
    ])

    if week_label is None:
        st.error("No se pudo interpretar la semana. Haz clic nuevamente en la gráfica.")
        return

    df_semana = df[
        (df["Fecha"].dt.normalize() >= week_start) &
        (df["Fecha"].dt.normalize() <= week_end)
    ].copy()

    if len(df_semana) == 0:
        st.warning(
            f"No hay pedidos para la semana del "
            f"{week_start.strftime('%d %b')} al {week_end.strftime('%d %b %Y')} "
            "en el periodo filtrado."
        )
        return

    # ── Header ───────────────────────────────────────────────────────────────
    venta_sem    = df_semana["Importe_MXN"].sum()
    n_pedidos    = len(df_semana)
    n_clientes   = df_semana["Cliente_Nombre"].nunique()
    n_vendedores = df_semana[df_semana["Vendedor"] != "Sin asignar"]["Vendedor"].nunique()

    st.markdown(
        f"<h2 style='margin-bottom:4px'>"
        f"Semana del {week_start.strftime('%d %b')} al {week_end.strftime('%d %b %Y')}"
        f"</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='margin:0 0 1rem;color:#6B7280;font-size:.85rem'>"
        f"{n_pedidos} pedidos &nbsp;·&nbsp; {n_clientes} clientes "
        f"&nbsp;·&nbsp; {n_vendedores} vendedores</p>",
        unsafe_allow_html=True,
    )

    # ── KPIs ─────────────────────────────────────────────────────────────────
    prior_start = week_start - pd.Timedelta(weeks=1)
    prior_end   = week_end   - pd.Timedelta(weeks=1)
    df_prior    = df[
        (df["Fecha"].dt.normalize() >= prior_start) &
        (df["Fecha"].dt.normalize() <= prior_end)
    ]
    venta_prior = df_prior["Importe_MXN"].sum() if len(df_prior) > 0 else None

    var_str   = "—"
    var_color = _BLUE
    if venta_prior is not None and venta_prior > 0:
        var_pct   = (venta_sem - venta_prior) / venta_prior * 100
        sign      = "+" if var_pct >= 0 else ""
        var_str   = f"{sign}{var_pct:.1f}%"
        var_color = _GREEN if var_pct >= 0 else "#C00000"

    cli_shares_sem = (df_semana.groupby("Cliente_Nombre")["Importe_MXN"]
                               .sum().sort_values(ascending=False))
    top_cli_pct   = float(cli_shares_sem.iloc[0]) / venta_sem * 100 if (len(cli_shares_sem) > 0 and venta_sem > 0) else 0
    top_cli_color = _GREEN if top_cli_pct < 40 else ("#E97132" if top_cli_pct < 60 else "#C00000")

    completado_mxn = df_semana[df_semana["Estatus"] == "Remitido"]["Importe_MXN"].sum()
    pct_completado = completado_mxn / venta_sem * 100 if venta_sem > 0 else 0
    compl_color    = _GREEN if pct_completado >= 90 else ("#E97132" if pct_completado >= 70 else "#C00000")
    compl_str      = f"{pct_completado:.0f}% (${completado_mxn/1e6:,.2f}M)"

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_kpi("Venta Semana",        f"${venta_sem/1e6:,.2f}M",       _GREEN),       unsafe_allow_html=True)
    k2.markdown(_kpi("vs. Semana Anterior", var_str,                          var_color),    unsafe_allow_html=True)
    k3.markdown(_kpi("Cliente Top",         f"{top_cli_pct:.0f}% del total",  top_cli_color), unsafe_allow_html=True)
    k4.markdown(_kpi("Remitido",            compl_str,                        compl_color),  unsafe_allow_html=True)

    st.divider()

    # ── Sección 1: Pareto de Clientes ─────────────────────────────────────────
    st.markdown("### Pareto de Clientes")
    st.caption("¿Qué clientes concentraron el 80 % de las ventas esta semana? Haz clic en una barra para ver el detalle del cliente.")

    nombre_a_display = (
        df_semana.drop_duplicates("Cliente_Nombre")
                 .set_index("Cliente_Nombre")["Cliente_Display"]
                 .to_dict()
    )

    pareto_v = cli_shares_sem.reset_index()
    pareto_v.columns = ["Cliente_Nombre", "Venta"]
    pareto_v["Pct"]      = pareto_v["Venta"] / venta_sem * 100
    pareto_v["Pct_Acum"] = pareto_v["Pct"].cumsum()
    pareto_v["Display"]  = pareto_v["Cliente_Nombre"].apply(lambda c: nombre_a_display.get(c, c))
    pareto_v["DispDisp"] = pareto_v["Display"].apply(lambda d: d[:34] + "…" if len(d) > 36 else d)

    n_to_80_v = int((pareto_v["Pct_Acum"] >= 80).idxmax()) + 1 if (pareto_v["Pct_Acum"] >= 80).any() else len(pareto_v)

    with st.container(border=True):
        fig_pareto_v = go.Figure()
        fig_pareto_v.add_trace(go.Bar(
            x=pareto_v["Venta"].iloc[::-1],
            y=pareto_v["DispDisp"].iloc[::-1],
            orientation="h",
            marker=dict(color=_GREEN, line=dict(color="white", width=1), opacity=0.85),
            text=[f"  ${v/1e6:,.2f}M  ({p:.1f}%)"
                  for v, p in zip(pareto_v["Venta"].iloc[::-1], pareto_v["Pct"].iloc[::-1])],
            textposition="outside",
            customdata=pareto_v["Cliente_Nombre"].iloc[::-1].values,
            hovertemplate="<b>%{y}</b><br>$%{x:,.0f} MXN<extra></extra>",
            name="Ventas",
        ))
        h_pareto_v = max(280, 44 * len(pareto_v) + 100)
        fig_pareto_v.update_layout(
            title=(
                "<b>Pareto de Clientes — Desglose de la Semana</b>"
                f"<br><sup>{n_to_80_v} cliente(s) concentran el 80 % de las ventas</sup>"
            ),
            template="plotly_white", height=h_pareto_v, showlegend=False,
            xaxis=dict(tickformat="$,.0f", title="Ventas (MXN)"),
            yaxis_title="",
            margin=dict(t=80, b=40, l=20, r=200),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        pareto_v_event = st.plotly_chart(
            _marcar_base(fig_pareto_v, vta_base), use_container_width=True,
            on_select="rerun", key="sem_v_pareto_chart",
        )
        if pareto_v_event and pareto_v_event.selection and pareto_v_event.selection.points:
            pt  = pareto_v_event.selection.points[0]
            cd  = pt.get("customdata", None) if isinstance(pt, dict) else getattr(pt, "customdata", None)
            if cd and isinstance(cd, str):
                cli_full = cd
            else:
                clicked_y = pt.get("y", "") if isinstance(pt, dict) else getattr(pt, "y", "")
                disp_to_full = {row["DispDisp"]: row["Cliente_Nombre"] for _, row in pareto_v.iterrows()}
                cli_full = disp_to_full.get(clicked_y, clicked_y)
            if cli_full:
                st.session_state["drill_cliente"] = cli_full
                for _k in ("drill_semana_v", "curva_semanal_ventas_chart",
                           "sem_v_pareto_chart", "sem_v_vendedor_chart", "sem_v_pedidos_table"):
                    st.session_state.pop(_k, None)
                st.toast(f"Cargando cliente **{cli_full[:40]}**…", icon="⏳")
                st.rerun()

    st.divider()

    # ── Sección 2: Desglose por Vendedor ──────────────────────────────────────
    st.markdown("### Desglose por Vendedor")
    st.caption("Contribución de cada vendedor en la semana. Haz clic en una barra para ver el detalle.")

    vend_shares = (
        df_semana[df_semana["Vendedor"] != "Sin asignar"]
        .groupby("Vendedor")["Importe_MXN"].sum().sort_values(ascending=False)
    )

    if len(vend_shares) > 0:
        pareto_vend = vend_shares.reset_index()
        pareto_vend.columns = ["Vendedor", "Venta"]
        pareto_vend["Pct"]      = pareto_vend["Venta"] / venta_sem * 100
        pareto_vend["VendDisp"] = pareto_vend["Vendedor"].apply(lambda v: v[:34] + "…" if len(v) > 36 else v)

        with st.container(border=True):
            fig_vend = go.Figure()
            fig_vend.add_trace(go.Bar(
                x=pareto_vend["Venta"].iloc[::-1],
                y=pareto_vend["VendDisp"].iloc[::-1],
                orientation="h",
                marker=dict(color=_BLUE, line=dict(color="white", width=1), opacity=0.85),
                text=[f"  ${v/1e6:,.2f}M  ({p:.1f}%)"
                      for v, p in zip(pareto_vend["Venta"].iloc[::-1], pareto_vend["Pct"].iloc[::-1])],
                textposition="outside",
                customdata=pareto_vend["Vendedor"].iloc[::-1].values,
                hovertemplate="<b>%{customdata}</b><br>$%{x:,.0f} MXN<extra></extra>",
                name="Ventas",
            ))
            h_vend = max(200, 44 * len(pareto_vend) + 80)
            fig_vend.update_layout(
                title="<b>Ventas por Vendedor — Semana</b>",
                template="plotly_white", height=h_vend, showlegend=False,
                xaxis=dict(tickformat="$,.0f", title="Ventas (MXN)"),
                yaxis_title="",
                margin=dict(t=60, b=40, l=20, r=200),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            vend_event = st.plotly_chart(
                _marcar_base(fig_vend, vta_base), use_container_width=True,
                on_select="rerun", key="sem_v_vendedor_chart",
            )
            if vend_event and vend_event.selection and vend_event.selection.points:
                pt  = vend_event.selection.points[0]
                cd  = pt.get("customdata", None) if isinstance(pt, dict) else getattr(pt, "customdata", None)
                if cd and isinstance(cd, str):
                    vend_full = cd
                else:
                    clicked_y = pt.get("y", "") if isinstance(pt, dict) else getattr(pt, "y", "")
                    disp_to_full_v = {row["VendDisp"]: row["Vendedor"] for _, row in pareto_vend.iterrows()}
                    vend_full = disp_to_full_v.get(clicked_y, clicked_y)
                if vend_full:
                    st.session_state["drill_vendedor"] = vend_full
                    for _k in ("drill_semana_v", "curva_semanal_ventas_chart",
                               "sem_v_pareto_chart", "sem_v_vendedor_chart", "sem_v_pedidos_table"):
                        st.session_state.pop(_k, None)
                    st.toast(f"Cargando vendedor **{vend_full[:40]}**…", icon="⏳")
                    st.rerun()
    else:
        st.info("No hay pedidos con vendedor asignado esta semana.")

    st.divider()

    # ── Tabla de Pedidos ──────────────────────────────────────────────────────
    st.markdown("### Detalle de Pedidos")
    st.caption("Todos los pedidos de la semana. Selecciona una fila para navegar al cliente o vendedor.")

    tbl_sem_v = df_semana[["Fecha", "Cliente_Display", "Vendedor", "Clave", "Importe_MXN", "Estatus"]].copy()
    tbl_sem_v["% Semana"]    = tbl_sem_v["Importe_MXN"] / venta_sem * 100
    tbl_sem_v["Fecha_str"]   = tbl_sem_v["Fecha"].dt.strftime("%d-%b-%Y")
    tbl_sem_v["_cli_nombre"] = df_semana["Cliente_Nombre"].values
    tbl_sem_v = tbl_sem_v.sort_values("Importe_MXN", ascending=False).reset_index(drop=True)

    tbl_display_v = tbl_sem_v[["Fecha_str", "Cliente_Display", "Vendedor", "Clave", "Importe_MXN", "% Semana"]].copy()

    tbl_v_event = st.dataframe(
        tbl_display_v,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="sem_v_pedidos_table",
        column_config={
            "Fecha_str":       st.column_config.TextColumn("Fecha"),
            "Cliente_Display": st.column_config.TextColumn("Cliente"),
            "Vendedor":        st.column_config.TextColumn("Vendedor"),
            "Clave":           st.column_config.TextColumn("Pedido"),
            "Importe_MXN":     st.column_config.NumberColumn("Importe (MXN)", format="$%,.2f"),
            "% Semana":        st.column_config.NumberColumn("% Semana",      format="%.1f%%"),
        },
        height=min(600, 48 + 36 * len(tbl_display_v)),
    )

    if tbl_v_event.selection and tbl_v_event.selection.rows:
        sel_idx  = tbl_v_event.selection.rows[0]
        sel_cli  = tbl_sem_v.iloc[sel_idx]["_cli_nombre"]
        sel_vend = tbl_sem_v.iloc[sel_idx]["Vendedor"]
        disp_c   = tbl_sem_v.iloc[sel_idx]["Cliente_Display"]

        nav_c1, nav_c2, _ = st.columns([2, 2, 4])
        with nav_c1:
            disp_c_short = disp_c[:28] + ("…" if len(disp_c) > 28 else "")
            if st.button(f"Ver cliente: {disp_c_short} →", key="btn_semv_to_cli", type="primary"):
                st.session_state["drill_cliente"] = sel_cli
                for _k in ("drill_semana_v", "curva_semanal_ventas_chart",
                           "sem_v_pareto_chart", "sem_v_vendedor_chart", "sem_v_pedidos_table"):
                    st.session_state.pop(_k, None)
                st.rerun()
        if sel_vend != "Sin asignar":
            with nav_c2:
                disp_v_short = sel_vend[:28] + ("…" if len(sel_vend) > 28 else "")
                if st.button(f"Ver vendedor: {disp_v_short} →", key="btn_semv_to_vend", type="secondary"):
                    st.session_state["drill_vendedor"] = sel_vend
                    for _k in ("drill_semana_v", "curva_semanal_ventas_chart",
                               "sem_v_pareto_chart", "sem_v_vendedor_chart", "sem_v_pedidos_table"):
                        st.session_state.pop(_k, None)
                    st.rerun()


# ── Dashboard ─────────────────────────────────────────────────────────────────
meta = st.session_state.df_ventas_meta
st.caption(
    f"Archivo: **{meta['archivo']}**  ·  "
    f"{meta['total_rows']:,} pedidos  ·  "
    f"Cargado: {meta['uploaded_at']}"
)

df_full = aplicar_vendedores(st.session_state.df_ventas.copy())

# ── Sidebar filters (antes de los drill-downs para que los detalles respeten
#    el período seleccionado) ────────────────────────────────────────────────
meses_disponibles = sorted(df_full["_Mes"].unique())

with st.sidebar:
    st.markdown("### Filtros")
    meses_sel = render_periodo_filter("vta", meses_disponibles)

    st.markdown("### Base monetaria")
    vta_base = st.radio(
        "¿Cómo medir los montos de esta página?",
        ["Con IVA", "Sin IVA"], index=0, key="vta_base",
        help="El SAE captura ambos. «Sin IVA» es la base comparable contra "
             "Facturación y el reporte CFDI de Contabilidad — úsala para el "
             "cruce pedido↔factura.",
    )

    st.markdown("---")
    if st.button("🗑 Borrar datos y volver a subir", use_container_width=True):
        for key in ("df_ventas", "df_ventas_meta"):
            st.session_state.pop(key, None)
        st.rerun()

# El SAE trae ambas bases (Importe_MXN con IVA, Subtotal_MXN sin). Se alias
# UNA sola vez, aquí: todo lo que ya existía en esta página sigue leyendo
# "Importe_MXN" sin cambiar una línea, y automáticamente respeta el switch —
# incluidos los tres drill-downs, que reciben `df_full`/`_ctx_v` ya aliasado.
if vta_base == "Sin IVA":
    df_full = df_full.assign(Importe_MXN=df_full["Subtotal_MXN"])

st.caption(f"📐 Midiendo **{vta_base}** — cámbialo en el sidebar.")

_ctx_v = df_full[df_full["_Mes"].isin(meses_sel)] if meses_sel else df_full

# ── Cruce pedido ↔ factura ──────────────────────────────────────────────────
# Se calcula sobre df_full (no _ctx_v): "Fuera de rango" debe reflejar lo que
# el CFDI en verdad cubre, no lo que el usuario tiene filtrado en este momento.
# El monto de estos bloques SIEMPRE es sin IVA — es la base que usa el CFDI y
# Facturación, y mezclarla con el switch de arriba confundiría más de lo que
# ayudaría. Cada bloque lo deja explícito en su caption.
_df_cfdi_raw = st.session_state.get("df_cfdi")
if _df_cfdi_raw is not None:
    _facturas_vigentes = _df_cfdi_raw[
        (_df_cfdi_raw["Tipo_Doc"] == "Factura") & (~_df_cfdi_raw["Cancelado"])
    ]
    _pedidos_cx, _facturas_cx, _resumen_cx = cruzar_pedidos_facturas(df_full, _facturas_vigentes)
else:
    _pedidos_cx = _facturas_cx = _resumen_cx = None

# ── Modo drill-down (respetan el filtro de período vía _ctx_v) ────────────────
if st.session_state.get("drill_cliente"):
    _render_detalle_cliente(_ctx_v, st.session_state["drill_cliente"])
    st.stop()

if st.session_state.get("drill_vendedor"):
    _render_detalle_vendedor(_ctx_v, st.session_state["drill_vendedor"])
    st.stop()

if st.session_state.get("drill_semana_v"):
    _render_detalle_semana_ventas(df_full, _ctx_v, st.session_state["drill_semana_v"])
    st.stop()

if not meses_sel:
    st.warning("Selecciona al menos un mes.")
    st.stop()

df = _ctx_v.copy()

if len(df) == 0:
    st.warning("No hay datos para los meses seleccionados.")
    st.stop()

# ── KPIs ──────────────────────────────────────────────────────────────────────
venta_total      = df["Importe_MXN"].sum()
total_pedidos    = len(df)
ticket_promedio  = df["Importe_MXN"].mean()
ticket_mediano   = df["Importe_MXN"].median()
clientes_unicos  = df["Cliente_Nombre"].nunique()
vendedores_act   = df[df["Vendedor"] != "Sin asignar"]["Vendedor"].nunique()

ventas_ranking = df.groupby("Cliente_Nombre")["Importe_MXN"].sum().sort_values(ascending=False)
acum_pct = ventas_ranking.cumsum() / venta_total * 100
n_clientes_80pct = int((acum_pct <= 80).sum()) + 1 if len(acum_pct) > 0 else 0

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.markdown(_kpi("Venta Total",      f"${venta_total/1e6:,.2f}M",   _GREEN), unsafe_allow_html=True)
k2.markdown(_kpi("Pedidos",          f"{total_pedidos:,}",           _BLUE),  unsafe_allow_html=True)
k3.markdown(_kpi("Ticket Promedio",  f"${ticket_promedio:,.0f}",     _GREEN), unsafe_allow_html=True)
k4.markdown(_kpi("Ticket Mediano",   f"${ticket_mediano:,.0f}",      _GREEN), unsafe_allow_html=True)
k5.markdown(_kpi("Clientes Únicos",  f"{clientes_unicos:,}",         _BLUE),  unsafe_allow_html=True)
k6.markdown(_kpi("Vendedores Act.",  f"{vendedores_act:,}",          _BLUE),  unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  EL CICLO: DEL PEDIDO A LA FACTURA (condicional al reporte CFDI)
# ══════════════════════════════════════════════════════════════════════════════
# Todo este tramo se calcula al vuelo desde core/cruce_ventas.py y siempre en
# base SIN IVA — es la comparable contra Facturación y el CFDI, y no depende
# del switch de arriba (mezclar bases aquí confundiría más de lo que ayuda).
if _pedidos_cx is None:
    st.info(
        "Sube el reporte CFDI de Ventas de Contabilidad (en **Gastos de Empresa**) "
        "para ver el ciclo completo: qué pedidos ya se facturaron, cuáles siguen "
        "pendientes y cuánto tardan."
    )
else:
    _pedidos_periodo = _pedidos_cx[_pedidos_cx["_Mes"].isin(meses_sel)] if meses_sel else _pedidos_cx

    # El embudo compara pedido vs facturado SOLO entre pedidos con OC: un
    # pedido sin OC nunca puede tener Facturado_MXN > 0 (no hay documento con
    # el que amarrarlo), así que mezclarlo aquí hundiría la conversión % de
    # forma artificial. Se tratan aparte, más abajo.
    _pedidos_con_oc = _pedidos_periodo[_pedidos_periodo["Estado_Cruce"] != SIN_OC]
    _ped_total  = float(_pedidos_con_oc["Subtotal_MXN"].sum())
    _fact_total = float(_pedidos_con_oc["Facturado_MXN"].sum())
    _sin_fact_total = float(
        _pedidos_periodo.loc[_pedidos_periodo["Estado_Cruce"] == SIN_FACTURA, "Subtotal_MXN"].sum()
    )
    _remitido_sf, _emitido_sf = descomponer_sin_factura(_pedidos_periodo)
    _dias_validos = _pedidos_periodo.loc[
        _pedidos_periodo["Estado_Cruce"] == FACTURADO, "Dias_Ciclo"
    ].dropna()
    _ciclo_mediano = float(_dias_validos.median()) if len(_dias_validos) else None

    # ── A. Embudo del pedido a la factura ───────────────────────────────────────
    st.markdown("### El ciclo: del pedido a la factura")
    st.caption(
        "Cruce documento a documento por la orden de compra del cliente — el "
        "SAE y el CFDI capturan la misma OC por separado. Base **siempre sin "
        "IVA**. No incluye pedidos sin OC (se tratan aparte, más abajo): para "
        "esos no hay forma de amarrar un documento con otro."
    )
    ea, eb, ec, ed = st.columns(4)
    ea.markdown(_kpi("Pedido (sin IVA)", f"${_ped_total/1e6:,.2f}M", _BLUE), unsafe_allow_html=True)
    eb.markdown(_kpi("Facturado (sin IVA)", f"${_fact_total/1e6:,.2f}M", _GREEN), unsafe_allow_html=True)
    ec.markdown(_kpi("Sin factura (con OC)", f"${_sin_fact_total/1e6:,.2f}M", _AMBER), unsafe_allow_html=True)
    ed.markdown(_kpi(
        "Ciclo mediano",
        f"{_ciclo_mediano:.0f} días" if _ciclo_mediano is not None else "—",
        _BLUE,
    ), unsafe_allow_html=True)

    with st.container(border=True):
        st.plotly_chart(
            plot_embudo_facturacion(_ped_total, _fact_total, _sin_fact_total),
            use_container_width=True,
        )

    # ── B. Pedidos remitidos sin factura — la lista de dinero ───────────────────
    st.markdown("#### Pedidos remitidos sin factura")
    st.caption(
        "Lo entregado (Remitido) que no aparece amarrado a ninguna factura. Es "
        "el único bucket accionable: un pedido *Emitido* todavía no se remite, "
        "así que es normal que no tenga factura."
    )
    if len(_remitido_sf) == 0:
        st.success("Todo lo remitido con OC en el periodo ya tiene factura amarrada.")
    else:
        _rem = _remitido_sf.copy()
        _hoy = _pedidos_periodo["Fecha"].max()
        _rem["Días"] = (_hoy - _rem["Fecha"]).dt.days.clip(lower=0)
        _rem["Antigüedad"] = _rem["Días"].apply(bucket_antiguedad)
        with st.container(border=True):
            _resumen_edad = (
                _rem.groupby("Antigüedad")["Subtotal_MXN"].agg(["size", "sum"])
                .reindex(["0-30 días", "31-60 días", "61-90 días", "90+ días"])
                .fillna(0)
            )
            _cols_edad = st.columns(4)
            for _col, (_bucket, _row) in zip(_cols_edad, _resumen_edad.iterrows()):
                _color = _GREEN if _bucket == "0-30 días" else (
                    _AMBER if _bucket in ("31-60 días", "61-90 días") else _RED
                )
                _col.markdown(_kpi(
                    _bucket, f"${_row['sum']/1e6:,.2f}M ({int(_row['size'])})", _color,
                ), unsafe_allow_html=True)

            _tabla_rem = _rem[
                ["Clave", "Fecha", "Cliente_Display", "Vendedor", "Subtotal_MXN", "Su pedido", "Días"]
            ].sort_values("Subtotal_MXN", ascending=False).rename(
                columns={"Cliente_Display": "Cliente", "Subtotal_MXN": "Monto sin IVA",
                         "Su pedido": "OC"}
            )
            st.dataframe(
                _tabla_rem, use_container_width=True, hide_index=True,
                column_config={
                    "Fecha": st.column_config.DateColumn(format="DD-MMM-YYYY"),
                    "Monto sin IVA": st.column_config.NumberColumn(format="$%,.0f"),
                },
                height=min(480, 45 + 36 * min(len(_tabla_rem), 12)),
            )
    if len(_emitido_sf):
        st.caption(
            f"Además, **{len(_emitido_sf)}** pedido(s) por "
            f"**${_emitido_sf['Subtotal_MXN'].sum()/1e6:,.2f}M** siguen en estatus "
            f"*Emitido* — aún no se remiten, es normal que no tengan factura."
        )

    _sin_oc_periodo = _pedidos_periodo[_pedidos_periodo["Estado_Cruce"] == SIN_OC]
    if len(_sin_oc_periodo):
        st.caption(
            f"📎 **{len(_sin_oc_periodo)}** pedido(s) por "
            f"**${_sin_oc_periodo['Subtotal_MXN'].sum()/1e6:,.2f}M** no traen número "
            f"de OC — hay clientes que no lo emiten. No es una alerta; se comparan "
            f"por cliente y mes en el bloque de abajo, no documento a documento."
        )

    # ── C. Cliente: pedido vs facturado ──────────────────────────────────────────
    st.markdown("#### Cliente: pedido vs facturado")
    st.caption(
        "Por cliente: lo pedido contra lo facturado. Para los clientes sin OC, "
        "se usa el total facturado del cliente en el periodo (cliente × mes) en "
        "vez del cruce documento a documento."
    )
    _por_cliente_ped = _pedidos_periodo.groupby("Cliente_Display")["Subtotal_MXN"].sum()
    _fact_periodo_cli = (
        _facturas_vigentes[_facturas_vigentes["_Mes"].isin(meses_sel)]
        if meses_sel else _facturas_vigentes
    )
    _por_cliente_fact = _fact_periodo_cli.groupby("Cliente_Display")["Subtotal_MXN"].sum()
    _cross_cli = pd.DataFrame({
        "Cliente": _por_cliente_ped.index,
        "Pedido_MXN": _por_cliente_ped.values,
    })
    _cross_cli["Facturado_MXN"] = _cross_cli["Cliente"].map(_por_cliente_fact).fillna(0.0)

    with st.container(border=True):
        st.plotly_chart(plot_pedido_vs_facturado(_cross_cli), use_container_width=True)

    # ── D. Ciclo pedido → factura ─────────────────────────────────────────────
    if len(_dias_validos) > 0:
        st.markdown("#### Ciclo pedido → factura")
        st.caption(
            f"Cuánto tarda un pedido en convertirse en factura. Mediana "
            f"**{_ciclo_mediano:.0f} días** sobre {len(_dias_validos)} pedido(s) "
            f"facturado(s) con OC."
        )
        with st.container(border=True):
            _fig_ciclo = px.histogram(
                _dias_validos, nbins=30, color_discrete_sequence=[_BLUE],
            )
            _fig_ciclo.update_layout(
                title="<b>Distribución del ciclo pedido → factura</b>",
                template="plotly_white", height=340, showlegend=False,
                xaxis_title="Días", yaxis_title="Pedidos",
                margin=dict(t=60, b=40, l=60, r=40),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(_fig_ciclo, use_container_width=True)

        _fact_ok = _pedidos_periodo[_pedidos_periodo["Estado_Cruce"] == FACTURADO].dropna(
            subset=["Dias_Ciclo"]
        )
        _cc1, _cc2 = st.columns(2)
        with _cc1:
            st.markdown("##### Mediana por vendedor")
            _por_vend_ciclo = (
                _fact_ok[_fact_ok["Vendedor"] != "Sin asignar"]
                .groupby("Vendedor")["Dias_Ciclo"].median()
                .sort_values().reset_index()
            )
            st.dataframe(
                _por_vend_ciclo, use_container_width=True, hide_index=True,
                column_config={"Dias_Ciclo": st.column_config.NumberColumn("Días (mediana)", format="%.0f")},
                height=min(320, 45 + 36 * len(_por_vend_ciclo)),
            )
        with _cc2:
            st.markdown("##### Mediana por cliente")
            _por_cli_ciclo = (
                _fact_ok.groupby("Cliente_Display")["Dias_Ciclo"].median()
                .sort_values().reset_index()
            )
            st.dataframe(
                _por_cli_ciclo, use_container_width=True, hide_index=True,
                column_config={"Dias_Ciclo": st.column_config.NumberColumn("Días (mediana)", format="%.0f")},
                height=min(320, 45 + 36 * len(_por_cli_ciclo)),
            )

    # ── E. Después de la factura: notas de crédito y forma de cobro ────────────
    st.markdown("#### Después de la factura")
    st.caption(
        "Lo que pasa una vez facturado: devoluciones/descuentos y si el cobro "
        "es de contado o a crédito. Del reporte CFDI, año completo."
    )
    _notas_periodo = _df_cfdi_raw[
        (_df_cfdi_raw["Tipo_Doc"] == "Nota Cred") & (~_df_cfdi_raw["Cancelado"])
    ]
    if meses_sel:
        _notas_periodo = _notas_periodo[_notas_periodo["_Mes"].isin(meses_sel)]

    _nc1, _nc2 = st.columns(2)
    with _nc1:
        st.markdown("##### Notas de crédito por cliente")
        if len(_notas_periodo) == 0:
            st.success("Sin notas de crédito vigentes en el periodo.")
        else:
            _nc_por_cli = (
                _notas_periodo.groupby("Cliente_Display")["Subtotal_MXN"].agg(["size", "sum"])
                .sort_values("sum", ascending=False).reset_index()
                .rename(columns={"Cliente_Display": "Cliente", "size": "N", "sum": "Monto sin IVA"})
            )
            _fact_por_cli_periodo = _fact_periodo_cli.groupby("Cliente_Display")["Subtotal_MXN"].sum()
            _nc_por_cli["% de lo facturado"] = _nc_por_cli.apply(
                lambda r: r["Monto sin IVA"] / _fact_por_cli_periodo.get(r["Cliente"], 0) * 100
                if _fact_por_cli_periodo.get(r["Cliente"], 0) else 0.0,
                axis=1,
            )
            st.dataframe(
                _nc_por_cli, use_container_width=True, hide_index=True,
                column_config={
                    "Monto sin IVA": st.column_config.NumberColumn(format="$%,.0f"),
                    "% de lo facturado": st.column_config.NumberColumn(format="%.1f%%"),
                },
                height=min(360, 45 + 36 * len(_nc_por_cli)),
            )
    with _nc2:
        st.markdown("##### Cómo se cobra")
        st.plotly_chart(plot_cobranza_mix(_facturas_vigentes), use_container_width=True)

st.divider()

# ── Gráficas ──────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.plotly_chart(
        _marcar_base(plot_donut_clientes_ventas(df, venta_total, n_clientes_80pct), vta_base),
        use_container_width=True,
    )

fig_resto = _marcar_base(plot_donut_resto_clientes(df, venta_total), vta_base)
if fig_resto is not None:
    with st.container(border=True):
        st.plotly_chart(fig_resto, use_container_width=True)

with st.container(border=True):
    sem_v_event = st.plotly_chart(
        _marcar_base(plot_curva_semanal_ventas(df), vta_base),
        use_container_width=True,
        on_select="rerun",
        selection_mode="points",
        key="curva_semanal_ventas_chart",
    )
    st.caption("Haz **un solo clic** (no doble) sobre un punto de la curva para ver el desglose de esa semana.")

    # Reliable fallback: pick the week from a selector.
    _semanas_disp_v = (
        df.set_index("Fecha").resample("W-MON")["Importe_MXN"].sum()
    )
    _semanas_disp_v = _semanas_disp_v[_semanas_disp_v > 0].index
    if len(_semanas_disp_v) > 0:
        _opts_v = {
            f"{(w - pd.Timedelta(days=6)).strftime('%d %b')} – {w.strftime('%d %b %Y')}": w
            for w in _semanas_disp_v
        }
        _pick_v = st.selectbox(
            "…o selecciona la semana:", ["—"] + list(_opts_v.keys()),
            key="vta_semana_pick",
        )
        if _pick_v != "—":
            st.session_state["drill_semana_v"] = str(_opts_v[_pick_v])
            st.session_state.pop("curva_semanal_ventas_chart", None)
            st.rerun()

    if sem_v_event and sem_v_event.selection and sem_v_event.selection.points:
        pt        = sem_v_event.selection.points[0]
        clicked_x = pt.get("x", "") if isinstance(pt, dict) else getattr(pt, "x", "")
        _wk = parse_semana_x(clicked_x) if clicked_x else None
        if _wk is not None:
            # Ignore clicks on empty valley weeks (markers sit at y=0)
            _ws   = _wk - pd.Timedelta(days=6)
            _dias = df["Fecha"].dt.normalize()
            if ((_dias >= _ws) & (_dias <= _wk)).any():
                st.session_state["drill_semana_v"] = str(_wk)
                st.session_state.pop("curva_semanal_ventas_chart", None)
                st.toast("Cargando detalle de la semana…", icon="⏳")
                st.rerun()
            else:
                st.toast("Esa semana no tiene pedidos.", icon="⚠️")

with st.container(border=True):
    st.plotly_chart(
        _marcar_base(plot_pareto_clientes_ventas(df, venta_total), vta_base),
        use_container_width=True,
    )

# Resto de clientes
ranking = df.groupby("Cliente_Nombre")["Importe_MXN"].sum().sort_values(ascending=False)
n2d = (df.drop_duplicates("Cliente_Nombre")
         .set_index("Cliente_Nombre")["Cliente_Display"].to_dict())
resto_clientes = ranking.iloc[10:]
if len(resto_clientes) > 0:
    with st.container(border=True):
        st.markdown(f"##### Resto de Clientes (posiciones 11 – {len(ranking)})")
        st.caption(
            f"{len(resto_clientes)} clientes  ·  "
            f"${resto_clientes.sum()/1e6:,.2f}M MXN  ·  "
            f"{resto_clientes.sum()/venta_total*100:.1f}% del revenue"
        )
        resto_df = resto_clientes.reset_index()
        resto_df.columns = ["Cliente_Nombre", "Importe_MXN"]
        resto_df["Cliente_Display"] = resto_df["Cliente_Nombre"].apply(lambda c: n2d.get(c, c))
        resto_df["Pct"] = resto_df["Importe_MXN"] / venta_total * 100
        resto_df.index = range(11, 11 + len(resto_df))
        st.dataframe(
            resto_df[["Cliente_Display", "Importe_MXN", "Pct"]],
            use_container_width=True, hide_index=False,
            column_config={
                "Cliente_Display": st.column_config.TextColumn("Cliente"),
                "Importe_MXN":     st.column_config.NumberColumn("Ventas (MXN)", format="$%,.2f"),
                "Pct":             st.column_config.NumberColumn("% Revenue",    format="%.2f%%"),
            },
            height=min(400, 40 + 35 * len(resto_df)),
        )

with st.container(border=True):
    st.plotly_chart(
        _marcar_base(plot_ventas_por_vendedor(df, venta_total), vta_base),
        use_container_width=True,
    )

# ══════════════════════════════════════════════════════════════════════════════
#  PRODUCTIVIDAD DE VENDEDORES
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("### Productividad de Vendedores")

_vend_df = (
    df[df["Vendedor"] != "Sin asignar"]
    .groupby("Vendedor")
    .agg(
        Ventas_Brutas=("Importe_MXN",  "sum"),
        Comisiones   =("Comision_MXN", "sum"),
        Pedidos      =("Importe_MXN",  "count"),
    ).reset_index()
)

if len(_vend_df) > 0:
    _vend_df["Venta_Neta"]     = _vend_df["Ventas_Brutas"] - _vend_df["Comisiones"]
    _vend_df["Ratio_Comision"] = _vend_df.apply(
        lambda r: r["Comisiones"] / r["Ventas_Brutas"] * 100
                  if r["Ventas_Brutas"] > 0 else 0,
        axis=1,
    )

    # ── El ciclo por vendedor (condicional al reporte CFDI) ─────────────────
    _cols_ciclo = ["Vendedor", "Ventas_Brutas", "Comisiones",
                   "Venta_Neta", "Ratio_Comision", "Pedidos"]
    _cfg_ciclo = {}
    if _pedidos_cx is not None:
        _ped_periodo_v = _pedidos_cx[_pedidos_cx["_Mes"].isin(meses_sel)] if meses_sel else _pedidos_cx
        _con_oc_v = _ped_periodo_v[_ped_periodo_v["Estado_Cruce"] != SIN_OC]
        _por_vend = _con_oc_v.groupby("Vendedor").agg(
            _ped_oc=("Subtotal_MXN", "sum"), _fact_oc=("Facturado_MXN", "sum"),
        )
        _pct_vend = (_por_vend["_fact_oc"] / _por_vend["_ped_oc"] * 100).where(_por_vend["_ped_oc"] > 0)
        _ciclo_vend_s = (
            _ped_periodo_v[_ped_periodo_v["Estado_Cruce"] == FACTURADO]
            .groupby("Vendedor")["Dias_Ciclo"].median()
        )
        _remitido_por_vend, _ = descomponer_sin_factura(_ped_periodo_v)
        _remitido_vend_s = _remitido_por_vend.groupby("Vendedor")["Subtotal_MXN"].sum()

        _vend_df["% Pedido→Factura"] = _vend_df["Vendedor"].map(_pct_vend)
        _vend_df["Ciclo (días)"]     = _vend_df["Vendedor"].map(_ciclo_vend_s)
        _vend_df["Remitido s/factura"] = _vend_df["Vendedor"].map(_remitido_vend_s).fillna(0.0)

        _cols_ciclo += ["% Pedido→Factura", "Ciclo (días)", "Remitido s/factura"]
        _cfg_ciclo = {
            "% Pedido→Factura":   st.column_config.NumberColumn(format="%.0f%%"),
            "Ciclo (días)":       st.column_config.NumberColumn(format="%.0f"),
            "Remitido s/factura": st.column_config.NumberColumn(format="$%,.0f"),
        }

    _vend_df = _vend_df.sort_values("Ventas_Brutas", ascending=False).reset_index(drop=True)
    _vend_df.index = _vend_df.index + 1

    _col_vl, _col_vr = st.columns([2, 3])

    with _col_vl:
        with st.container(border=True):
            st.markdown("##### Ranking de vendedores")
            st.caption(
                "Venta Neta = Ventas Brutas − Comisiones"
                + ("  ·  el ciclo es sin IVA, del cruce contra el CFDI" if _pedidos_cx is not None else "")
            )
            st.dataframe(
                _vend_df[_cols_ciclo],
                use_container_width=True,
                hide_index=False,
                column_config={
                    "Vendedor":       st.column_config.TextColumn("Vendedor"),
                    "Ventas_Brutas":  st.column_config.NumberColumn("Ventas",      format="$%,.0f"),
                    "Comisiones":     st.column_config.NumberColumn("Comisiones",  format="$%,.0f"),
                    "Venta_Neta":     st.column_config.NumberColumn("Venta Neta",  format="$%,.0f"),
                    "Ratio_Comision": st.column_config.NumberColumn("% Comisión",  format="%.1f%%"),
                    "Pedidos":        st.column_config.NumberColumn("Pedidos",      format="%d"),
                    **_cfg_ciclo,
                },
                height=min(500, 52 + 36 * len(_vend_df)),
            )

    with _col_vr:
        with st.container(border=True):
            _vend_sort = _vend_df.sort_values("Ventas_Brutas", ascending=True)
            _fig_vp = go.Figure()
            _fig_vp.add_trace(go.Bar(
                x=_vend_sort["Ventas_Brutas"], y=_vend_sort["Vendedor"],
                name="Ventas Brutas", orientation="h",
                marker_color=_GREEN,
                hovertemplate="<b>%{y}</b><br>Ventas: $%{x:,.0f}<extra></extra>",
            ))
            _fig_vp.add_trace(go.Bar(
                x=_vend_sort["Comisiones"], y=_vend_sort["Vendedor"],
                name="Comisiones", orientation="h",
                marker_color=_RED, opacity=0.85,
                customdata=_vend_sort["Ratio_Comision"].values,
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Comisión: $%{x:,.0f} (%{customdata:.1f}%)<extra></extra>"
                ),
            ))
            _fig_vp.update_layout(
                title="<b>Ventas Brutas vs Comisiones</b>",
                barmode="overlay", template="plotly_white",
                height=max(280, 60 + 50 * len(_vend_df)),
                legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
                xaxis=dict(tickformat="$,.0f", title=""),
                yaxis_title="",
                margin=dict(t=70, b=40, l=140, r=40),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(_marcar_base(_fig_vp, vta_base), use_container_width=True)
else:
    st.info("No hay pedidos con vendedor asignado en el periodo seleccionado.")

with st.container(border=True):
    st.plotly_chart(
        _marcar_base(plot_heatmap_cliente_mes(df), vta_base),
        use_container_width=True,
    )

# Top 10 pedidos
with st.container(border=True):
    st.markdown("##### Top 10 Pedidos Individuales por Monto")
    st.caption("Identifica contratos grandes y entregas excepcionales")

    top_cols = ["Clave", "Fecha", "Cliente_Nombre", "Vendedor", "Importe_MXN", "Estatus"]
    top = df.nlargest(10, "Importe_MXN")[top_cols].copy().reset_index(drop=True)
    top["Fecha"] = top["Fecha"].dt.strftime("%d-%b-%Y")
    top.index = top.index + 1

    st.dataframe(
        top, use_container_width=True, hide_index=False,
        column_config={
            "Clave":          st.column_config.TextColumn("Clave"),
            "Fecha":          st.column_config.TextColumn("Fecha"),
            "Cliente_Nombre": st.column_config.TextColumn("Cliente"),
            "Vendedor":       st.column_config.TextColumn("Vendedor"),
            "Importe_MXN":    st.column_config.NumberColumn("Importe (MXN)", format="$%,.2f"),
            "Estatus":        st.column_config.TextColumn("Estatus"),
        },
        height=410,
    )

# ── Drill-down ────────────────────────────────────────────────────────────────
st.divider()
st.markdown("#### Drill-down — Detalle de cliente")

all_clientes = (
    df_full.groupby("Cliente_Nombre")["Importe_MXN"]
           .sum().sort_values(ascending=False).index.tolist()
)

dd_busq = st.text_input(
    "Buscar cliente",
    placeholder="Escribe parte del nombre para filtrar…",
    key="dd_busq_cliente",
    label_visibility="collapsed",
)
filtered_clientes = (
    [c for c in all_clientes if dd_busq.upper() in c.upper()]
    if dd_busq else all_clientes
)

if filtered_clientes:
    dd_c1, dd_c2 = st.columns([4, 1])
    with dd_c1:
        cliente_sel = st.selectbox(
            "", filtered_clientes, key="dd_cliente", label_visibility="collapsed"
        )
    with dd_c2:
        if st.button("Ver detalle →", key="btn_dd_cliente",
                     use_container_width=True, type="primary"):
            st.session_state["drill_cliente"] = cliente_sel
            st.session_state.pop("curva_semanal_ventas_chart", None)
            st.rerun()
else:
    st.caption("Sin resultados para esa búsqueda.")

st.markdown("#### Drill-down — Detalle de vendedor")

all_vendedores = (
    df_full.groupby("Vendedor")["Importe_MXN"]
           .sum().sort_values(ascending=False).index.tolist()
)

dd_busq_v = st.text_input(
    "Buscar vendedor",
    placeholder="Escribe parte del nombre para filtrar…",
    key="dd_busq_vendedor",
    label_visibility="collapsed",
)
filtered_vendedores = (
    [v for v in all_vendedores if dd_busq_v.upper() in v.upper()]
    if dd_busq_v else all_vendedores
)

if filtered_vendedores:
    dd_v1, dd_v2 = st.columns([4, 1])
    with dd_v1:
        vendedor_sel = st.selectbox(
            "", filtered_vendedores, key="dd_vendedor", label_visibility="collapsed"
        )
    with dd_v2:
        if st.button("Ver detalle →", key="btn_dd_vendedor",
                     use_container_width=True, type="primary"):
            st.session_state["drill_vendedor"] = vendedor_sel
            st.session_state.pop("curva_semanal_ventas_chart", None)
            st.rerun()
else:
    st.caption("Sin resultados para esa búsqueda.")
