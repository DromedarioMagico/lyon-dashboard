import datetime as dt

import pandas as pd
import streamlit as st

from core.catalogos import COLOR_LYON, COLOR_GASTOS_EMPRESA, label_mes
from core.conciliacion import (
    contabilidad_de_sesion, resumen_conciliacion, gasto_empresa_por_concepto,
    gasto_empresa_por_periodo, ESTADOS,
)
from core.database import init_db, log_evento
from core.etl_contabilidad import cargar_contabilidad
from core.navigation import (
    render_sidebar_search, render_sidebar_status, inject_custom_css, handle_pending_nav,
)
from core.plots import (
    plot_conciliacion_sae, plot_gasto_fuera_sae, plot_barras_gastos_empresa,
)

st.set_page_config(
    page_title="Gastos de Empresa — Lyon AG",
    page_icon="💼",
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
    "<span class='material-symbols-outlined'>payments</span>Gastos de Empresa</h1>",
    unsafe_allow_html=True,
)

_GRAY  = "#9E9E9E"
_AMBER = "#E97132"
_GREEN = "#548235"


def _kpi(label, value, color, desc=None):
    """Tarjeta KPI — misma gramática visual que Compras y Facturación."""
    tip = (
        f"<div style='font-size:.7rem;color:#6B7280;margin-top:.25rem'>{desc}</div>"
        if desc else ""
    )
    return (
        "<div style='border:1px solid #E5E7EB;border-radius:8px;padding:.7rem .9rem;"
        "background:#fff;height:100%'>"
        f"<div style='font-size:.75rem;color:#6B7280'>{label}</div>"
        f"<div style='font-size:1.5rem;font-weight:700;color:{color}'>{value}</div>"
        f"{tip}</div>"
    )


def _render_conciliacion(df_conc):
    """Conciliación del libro contable de la sesión contra las compras del SAE."""
    df_compras = st.session_state.get("df_compras")
    res        = resumen_conciliacion(df_conc)

    _meta = st.session_state.get("df_contabilidad_meta", {})
    st.caption(
        f"**{res['n_movimientos']:,}** movimientos · **{res['n_cuentas']}** cuentas · "
        f"periodos {_meta.get('periodos', '—')} · {_meta.get('archivo', '—')} "
        f"(cargado {_meta.get('uploaded_at', '—')})"
    )

    if df_compras is None:
        st.warning(
            "**Compras no está cargado**, así que no se puede saber qué movimientos ya "
            "pasaron por el SAE. Todo aparece como «Sin comparar» y nada se publica "
            "automáticamente. Carga el archivo de Compras para la conciliación real."
        )

    # ── Banner de cuentas sin clasificar ──────────────────────────────────────
    if res["n_cuentas_sin_clasificar"]:
        b1, b2 = st.columns([5, 1])
        with b1:
            st.warning(
                f"**{res['n_cuentas_sin_clasificar']} cuenta(s) contable(s) sin "
                f"clasificar** — ${res['sin_clasificar']/1e6:,.2f}M del libro todavía "
                f"**no cuentan como gasto**. Nómbralas y márcalas en el catálogo para "
                f"que entren al costo operativo.\n\n"
                f"Si ya las marcaste y sigue apareciendo este aviso: los cambios de la "
                f"tabla del catálogo **no se guardan solos**, hay que presionar "
                f"«Guardar catálogo de cuentas». El propio catálogo te dice cuántas "
                f"están guardadas en la base."
            )
        with b2:
            st.markdown("<div style='padding-top:.6rem'></div>", unsafe_allow_html=True)
            if st.button("Ir al catálogo →", key="ctb_btn_catalogo",
                         use_container_width=True):
                st.session_state["_goto"] = "pages/4_Clasificaciones.py"
                st.rerun()

    # ── KPIs ──────────────────────────────────────────────────────────────────
    st.markdown("#### Conciliación contra el SAE")
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_kpi(
        "Gasto contable total", f"${res['total']/1e6:,.2f}M", COLOR_LYON,
        "Todo lo que reportó Contabilidad en el libro cargado",
    ), unsafe_allow_html=True)
    k2.markdown(_kpi(
        "Ya está en el SAE", f"${res['en_sae']/1e6:,.2f}M", _GREEN,
        "Mismo proveedor y mismo mes — ya lo cuenta Compras",
    ), unsafe_allow_html=True)
    k3.markdown(_kpi(
        "Fuera del SAE", f"${res['fuera_de_sae']/1e6:,.2f}M", COLOR_GASTOS_EMPRESA,
        "Proveedor que nunca aparece en Compras — esto es Gasto de Empresa",
    ), unsafe_allow_html=True)
    k4.markdown(_kpi(
        "Por revisar", f"${(res['por_revisar'] + res['mes_sin_sae'])/1e6:,.2f}M", _AMBER,
        "Proveedor del SAE pero en otro mes, o meses que el archivo de Compras no cubre",
    ), unsafe_allow_html=True)

    st.markdown("#### Clasificación de las cuentas")
    c1, c2, c3 = st.columns(3)
    c1.markdown(_kpi(
        "Gasto operativo", f"${res['gasto_operativo']/1e6:,.2f}M", COLOR_LYON,
        "Cuentas que marcaste como gasto del periodo",
    ), unsafe_allow_html=True)
    c2.markdown(_kpi(
        "No operativo", f"${res['no_operativo']/1e6:,.2f}M", _GRAY,
        "Anticipos y movimientos de balance — no tocan el margen",
    ), unsafe_allow_html=True)
    c3.markdown(_kpi(
        "Sin clasificar", f"${res['sin_clasificar']/1e6:,.2f}M", _AMBER,
        "Todavía no cuentan para nada. Clasifícalas en el catálogo",
    ), unsafe_allow_html=True)

    with st.container(border=True):
        st.plotly_chart(plot_conciliacion_sae(res), use_container_width=True)

    with st.container(border=True):
        st.caption(
            "A quién se le paga sin que pase por una orden de compra. No todo es un "
            "problema —la nómina nunca va a pasar por el SAE— pero un proveedor de "
            "insumos en esta lista sí lo es."
        )
        st.plotly_chart(plot_gasto_fuera_sae(df_conc), use_container_width=True)

    # ── Desglose por cuenta ───────────────────────────────────────────────────
    with st.container(border=True):
        st.caption(
            "El libro contable agrupado por cuenta, con el nombre que le pusiste en "
            "el catálogo."
        )
        _por_cuenta = (
            df_conc.groupby("Cuenta_Nombre")["Monto_MXN"].sum()
            .sort_values(ascending=False).to_dict()
        )
        st.plotly_chart(
            plot_barras_gastos_empresa(_por_cuenta, res["total"]),
            use_container_width=True,
        )

    # ── Detalle de movimientos ────────────────────────────────────────────────
    st.markdown("#### Detalle de movimientos")
    f1, f2, f3 = st.columns([2, 2, 3])
    with f1:
        estados_pres = [e for e in ESTADOS if (df_conc["Estado_SAE"] == e).any()]
        est_sel = st.multiselect(
            "Estado", estados_pres, key="ctb_f_estado",
        )
    with f2:
        cta_sel = st.multiselect(
            "Cuenta", sorted(df_conc["Cuenta_Nombre"].unique()), key="ctb_f_cuenta",
        )
    with f3:
        busq = st.text_input(
            "Buscar proveedor o descripción", key="ctb_f_busq",
            placeholder="ej. nómina, flete, Tresguerras…",
        )

    tabla = df_conc.copy()
    if est_sel:
        tabla = tabla[tabla["Estado_SAE"].isin(est_sel)]
    if cta_sel:
        tabla = tabla[tabla["Cuenta_Nombre"].isin(cta_sel)]
    if busq:
        _m = (
            tabla["Proveedor"].str.contains(busq, case=False, na=False)
            | tabla["Descripcion"].str.contains(busq, case=False, na=False)
        )
        tabla = tabla[_m]

    st.caption(
        f"{len(tabla):,} movimiento(s) · ${tabla['Monto_MXN'].sum()/1e6:,.2f}M en pantalla"
    )
    _vista = tabla.sort_values("Monto_MXN", ascending=False).head(500).copy()
    _vista["Mes"] = [label_mes(m) for m in _vista["_Mes"]]
    st.dataframe(
        _vista[["Mes", "Cuenta", "Cuenta_Nombre", "Proveedor", "Monto_MXN",
                "Estado_SAE", "Naturaleza", "Descripcion"]],
        use_container_width=True, hide_index=True,
        column_config={
            "Cuenta_Nombre": st.column_config.TextColumn("Nombre de cuenta"),
            "Monto_MXN":     st.column_config.NumberColumn("Monto", format="$%,.2f"),
            "Estado_SAE":    st.column_config.TextColumn("Estado"),
            "Descripcion":   st.column_config.TextColumn("Descripción", width="large"),
        },
        height=min(520, 45 + 36 * min(len(_vista), 12)),
    )
    if len(tabla) > 500:
        st.caption("Se muestran los 500 movimientos de mayor monto. Usa los filtros.")

    # ── Lo que cuenta como Gasto de Empresa ───────────────────────────────────
    st.divider()
    st.markdown("#### Lo que entra como Gasto de Empresa")
    st.caption(
        "Solo entra lo que está **fuera del SAE** y cuya cuenta marcaste como **gasto "
        "operativo**. Lo que quedó «Por revisar» no entra: ahí el dato no alcanza "
        "para afirmar que el gasto no pasó por compras, y contarlo duplicaría lo que "
        "Compras ya muestra. Se calcula al vuelo — no hay nada que publicar ni "
        "guardar, y cambiar el catálogo se refleja de inmediato."
    )

    _por_concepto = gasto_empresa_por_concepto(df_conc)
    if not _por_concepto:
        st.info(
            "Todavía no hay nada que cuente como Gasto de Empresa. "
            + (
                "Clasifica las cuentas en el catálogo para que su gasto cuente."
                if res["n_cuentas_sin_clasificar"]
                else "Ningún movimiento quedó fuera del SAE con una cuenta de gasto."
            )
        )
    else:
        _por_periodo = gasto_empresa_por_periodo(df_conc)
        prev = pd.DataFrame(
            sorted(_por_concepto.items(), key=lambda kv: -kv[1]),
            columns=["Concepto", "Monto"],
        )
        total_ge = float(prev["Monto"].sum())
        st.dataframe(
            prev, use_container_width=True, hide_index=True,
            column_config={
                "Monto": st.column_config.NumberColumn("Monto", format="$%,.2f"),
            },
            height=min(400, 45 + 36 * min(len(prev), 9)),
        )
        st.caption(
            f"**${total_ge/1e6:,.2f}M** en **{len(prev)}** concepto(s), repartidos en "
            f"**{len(_por_periodo)}** mes(es). Ya se refleja en Compras, Comparativa "
            f"y Facturación mientras el libro siga cargado en esta sesión."
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Carga del libro contable y conciliación con el SAE
# ══════════════════════════════════════════════════════════════════════════════
st.caption(
    "Sube la base consolidada que te manda Contabilidad. La app cruza cada "
    "movimiento contra las compras del SAE y separa lo que **ya pasó por el "
    "proceso de compras** de lo que **no** — eso último es el Gasto de Empresa. "
    "Igual que el SAE, **este archivo no se guarda**: vive solo en esta sesión y "
    "hay que volver a subirlo la próxima vez. Lo único que se guarda son tus "
    "decisiones del catálogo de cuentas."
)

_ya_cargada = "df_contabilidad" in st.session_state

with st.expander(
    "📥 Cargar la base de contabilidad", expanded=not _ya_cargada,
):
    up = st.file_uploader(
        "Base de contabilidad (.xlsx)",
        type=["xlsx", "xlsm"],
        key="ctb_uploader",
        label_visibility="collapsed",
    )
    st.caption(
        "Se esperan las columnas `MES`, `CUENTA CONTABLE`, `PROVEEDOR`, `MONTO` "
        "y `DESCRIPCIÓN`. El mes puede venir como «abril-26»."
    )
    if up is not None and st.button(
        "Cargar base de contabilidad", type="primary", key="ctb_btn_cargar"
    ):
        with st.spinner("Procesando la base de contabilidad…"):
            try:
                df_new, warns = cargar_contabilidad(up)
                st.session_state["df_contabilidad"] = df_new
                st.session_state["df_contabilidad_meta"] = {
                    "archivo":     up.name,
                    "uploaded_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "periodos":    (
                        f"{df_new['_Mes'].min()} → {df_new['_Mes'].max()}"
                    ),
                }
                log_evento(
                    "contabilidad_carga",
                    f"{up.name}: {len(df_new)} movimientos, "
                    f"${df_new['Monto_MXN'].sum():,.0f}",
                )
                for w in warns:
                    st.warning(w)
                st.success(f"✅ {len(df_new):,} movimientos cargados.")
                st.rerun()
            except ValueError as e:
                st.error(f"Error al procesar el archivo:\n\n{e}")

df_conc = contabilidad_de_sesion()

if df_conc is None:
    st.info(
        "Todavía no hay base de contabilidad cargada en esta sesión. Súbela arriba "
        "para ver la conciliación contra el SAE."
    )
else:
    _render_conciliacion(df_conc)

    st.divider()
    if st.button("🗑 Quitar la base de contabilidad de esta sesión"):
        for k in ("df_contabilidad", "df_contabilidad_meta"):
            st.session_state.pop(k, None)
        st.rerun()
