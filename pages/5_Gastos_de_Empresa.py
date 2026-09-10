import datetime as dt

import pandas as pd
import streamlit as st

from core.catalogos import COLOR_LYON, COLOR_GASTOS_EMPRESA, label_mes
from core.conciliacion import (
    conciliar_con_sae, aplicar_catalogo_cuentas, marcar_publicables,
    resumen_conciliacion, filas_para_gastos_empresa, ESTADOS,
)
from core.database import (
    init_db, log_evento, reemplazar_contabilidad, get_contabilidad,
    get_meta_contabilidad, get_cuentas_contables, reemplazar_gastos_contabilidad,
    get_gastos_empresa_publicados, get_gastos_manuales, delete_gastos_manuales,
)
from core.etl_contabilidad import cargar_contabilidad, filas_para_bd, df_desde_bd
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


def _render_conciliacion(df_ctb, meta_bd):
    """
    Conciliación del libro contable contra el SAE + publicación a Gastos de Empresa.

    Va en una función y no inline en la pestaña porque el caso "sin libro cargado"
    necesita cortar solo este bloque: `st.stop()` mataría también la pestaña de
    captura manual, ya que Streamlit ejecuta el script completo, no una pestaña.
    """
    df_compras = st.session_state.get("df_compras")
    cuentas    = get_cuentas_contables()

    df_conc = marcar_publicables(
        aplicar_catalogo_cuentas(conciliar_con_sae(df_ctb, df_compras), cuentas)
    )
    res = resumen_conciliacion(df_conc)

    _meta_sesion = st.session_state.get("df_contabilidad_meta")
    _origen = (
        f"{_meta_sesion['archivo']} · cargado {_meta_sesion['uploaded_at']}"
        if _meta_sesion else f"última carga: {meta_bd['ultima_carga'] or '—'}"
    )
    _p0, _p1 = meta_bd["periodos"]
    st.caption(
        f"**{res['n_movimientos']:,}** movimientos · **{res['n_cuentas']}** cuentas · "
        f"periodos {_p0} → {_p1} · {_origen}"
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

    # ── Publicación a Gastos de Empresa ───────────────────────────────────────
    st.divider()
    st.markdown("#### Publicar a Gastos de Empresa")
    st.caption(
        "Solo entra lo que está **fuera del SAE** y cuya cuenta marcaste como **gasto "
        "operativo**. Lo que quedó «Por revisar» no se publica: ahí el dato no alcanza "
        "para afirmar que el gasto no pasó por compras, y publicarlo duplicaría lo que "
        "Compras ya muestra."
    )

    filas_pub = filas_para_gastos_empresa(df_conc)
    ya_pub    = get_gastos_empresa_publicados()

    if not filas_pub:
        st.info(
            "No hay nada que publicar todavía. "
            + (
                "Clasifica las cuentas en el catálogo para que su gasto cuente."
                if res["n_cuentas_sin_clasificar"]
                else "Ningún movimiento quedó fuera del SAE con una cuenta de gasto."
            )
        )
        if ya_pub:
            st.warning(
                f"Hay {len(ya_pub)} concepto-mes publicado(s) de una corrida anterior "
                f"por ${sum(ya_pub.values())/1e6:,.2f}M. Al publicar de nuevo se "
                f"reemplazan por completo."
            )
    else:
        prev = pd.DataFrame(
            filas_pub, columns=["Concepto", "Periodo", "Monto", "Notas"]
        )
        total_pub = float(prev["Monto"].sum())
        st.dataframe(
            prev[["Concepto", "Periodo", "Monto"]],
            use_container_width=True, hide_index=True,
            column_config={
                "Monto": st.column_config.NumberColumn("Monto", format="$%,.2f"),
            },
            height=min(400, 45 + 36 * min(len(prev), 9)),
        )
        st.caption(
            f"**{len(prev)}** concepto-mes · **${total_pub/1e6:,.2f}M** entrarían como "
            f"Gasto de Empresa. Republicar reemplaza por completo lo publicado antes; "
            f"la captura manual no se toca."
        )
        if st.button("💾 Publicar a Gastos de Empresa", type="primary",
                     key="ctb_btn_publicar"):
            n = reemplazar_gastos_contabilidad(filas_pub)
            log_evento(
                "contabilidad_publicacion",
                f"{n} concepto-mes, ${total_pub:,.0f}",
            )
            st.success(
                f"✅ {n} concepto-mes publicado(s) por ${total_pub/1e6:,.2f}M. "
                f"Ya se reflejan en Compras, Comparativa y Facturación."
            )
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  Carga del libro contable, conciliación con el SAE y publicación
# ══════════════════════════════════════════════════════════════════════════════
st.caption(
    "Sube la base consolidada que te manda Contabilidad. La app cruza cada "
    "movimiento contra las compras del SAE y separa lo que **ya pasó por el "
    "proceso de compras** de lo que **no** — eso último es el Gasto de Empresa, "
    "sin captura manual. A diferencia del SAE, esta base **sí se guarda**: cada "
    "carga reemplaza por completo a la anterior."
)

meta_bd = get_meta_contabilidad()

with st.expander(
    "📥 Cargar / actualizar la base de contabilidad",
    expanded=(meta_bd["n_movimientos"] == 0),
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
        "Reemplazar base de contabilidad", type="primary", key="ctb_btn_cargar"
    ):
        with st.spinner("Procesando la base de contabilidad…"):
            try:
                df_new, warns = cargar_contabilidad(up)
                n = reemplazar_contabilidad(filas_para_bd(df_new))
                log_evento(
                    "contabilidad_carga",
                    f"{up.name}: {n} movimientos, "
                    f"${df_new['Monto_MXN'].sum():,.0f}",
                )
                st.session_state["df_contabilidad_meta"] = {
                    "archivo":     up.name,
                    "uploaded_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                for w in warns:
                    st.warning(w)
                st.success(f"✅ {n:,} movimientos cargados.")
                st.rerun()
            except ValueError as e:
                st.error(f"Error al procesar el archivo:\n\n{e}")

df_ctb = df_desde_bd(get_contabilidad())

if len(df_ctb) == 0:
    st.info(
        "Todavía no hay base de contabilidad cargada. Súbela arriba para ver la "
        "conciliación contra el SAE."
    )
else:
    _render_conciliacion(df_ctb, meta_bd)


# ── Residuos de la captura manual, que ya no existe ───────────────────────────
# Estas filas dejaron de sumar al costo operativo al quitarse la pantalla. Se
# muestran en vez de borrarse solas: un monto que dejó de contar sin que nadie
# lo vea es peor que uno de más, y borrar datos del usuario no se hace en
# silencio.
_manuales = get_gastos_manuales()
if _manuales:
    st.divider()
    _tot_man = sum(m for _, _, m in _manuales)
    with st.expander(
        f"⚠️ Quedan {len(_manuales)} registro(s) de la captura manual "
        f"(${_tot_man/1e6:,.2f}M) — ya no cuentan",
    ):
        st.caption(
            "La captura manual se eliminó: el libro de Contabilidad es ahora la "
            "única fuente del gasto que no pasa por el SAE. Estos registros **ya "
            "no suman** al costo operativo ni al margen en ninguna pantalla. "
            "Se conservan por si quieres consultarlos antes de borrarlos."
        )
        st.dataframe(
            pd.DataFrame(_manuales, columns=["Concepto", "Periodo", "Monto"]),
            use_container_width=True, hide_index=True,
            column_config={
                "Monto": st.column_config.NumberColumn("Monto", format="$%,.2f"),
            },
            height=min(340, 45 + 36 * min(len(_manuales), 8)),
        )
        if st.button("🗑 Borrar definitivamente", key="ge_btn_borrar_manual"):
            n = delete_gastos_manuales()
            log_evento("gastos_manuales_borrados", f"{n} registros, ${_tot_man:,.0f}")
            st.success(f"✅ {n} registro(s) borrado(s).")
            st.rerun()
