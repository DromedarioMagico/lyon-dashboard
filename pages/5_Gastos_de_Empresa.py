import datetime as dt

import pandas as pd
import streamlit as st

from core.catalogos import COLOR_LYON, COLOR_GASTOS_EMPRESA, ESPANOL_MES, label_mes
from core.conciliacion import (
    conciliar_con_sae, aplicar_catalogo_cuentas, marcar_publicables,
    resumen_conciliacion, filas_para_gastos_empresa, ESTADOS,
)
from core.database import (
    init_db, get_conceptos_gastos_empresa, get_años_gastos_empresa,
    get_gastos_empresa_año, bulk_upsert_gastos_empresa, delete_concepto_año,
    log_evento, reemplazar_contabilidad, get_contabilidad, get_meta_contabilidad,
    get_cuentas_contables, reemplazar_gastos_contabilidad,
    get_gastos_empresa_publicados,
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

_MESES_COLS = [ESPANOL_MES[m] for m in range(1, 13)]
_MES_A_NUM  = {ESPANOL_MES[m]: m for m in range(1, 13)}

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
                f"que entren al costo operativo."
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


tab_ctb, tab_manual = st.tabs(
    ["🧾 Contabilidad (automático)", "✍️ Captura manual"]
)


# ══════════════════════════════════════════════════════════════════════════════
#  Contabilidad — carga, conciliación con el SAE y publicación
# ══════════════════════════════════════════════════════════════════════════════
with tab_ctb:
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



# ══════════════════════════════════════════════════════════════════════════════
#  Captura manual — para lo que Contabilidad todavía no cubre
# ══════════════════════════════════════════════════════════════════════════════
with tab_manual:
    st.caption(
        "Captura a mano los gastos que **no** pasan por el SAE y que la base de "
        "Contabilidad todavía no cubre. Se guardan de forma permanente y se suman al "
        "costo operativo en Compras y Comparativa, junto con lo publicado desde "
        "Contabilidad."
    )

    _publicados = get_gastos_empresa_publicados()
    if _publicados:
        _conceptos_pub = sorted({c for c, _ in _publicados})
        st.info(
            f"Contabilidad ya publicó **{len(_conceptos_pub)} concepto(s)**: "
            f"{', '.join(_conceptos_pub[:6])}"
            + ("…" if len(_conceptos_pub) > 6 else "")
            + ". No aparecen en esta tabla y no se editan aquí — se actualizan "
            "volviendo a publicar desde la pestaña de Contabilidad."
        )

    año_actual       = dt.datetime.now().year
    años_con_datos   = get_años_gastos_empresa()
    años_disponibles = sorted(set(años_con_datos) | {año_actual, año_actual + 1})

    col_año, _ = st.columns([1, 4])
    with col_año:
        año_sel = st.selectbox(
            "Año", años_disponibles,
            index=años_disponibles.index(año_actual) if año_actual in años_disponibles else 0,
            key="ge_año_sel",
        )

    with st.expander("➕ ¿No tienes el año que buscas? Agrégalo aquí"):
        nuevo_año = st.number_input(
            "Año a agregar", min_value=2000, max_value=2100,
            value=año_actual, step=1, key="ge_nuevo_año",
        )
        if st.button("Agregar año", key="ge_btn_nuevo_año"):
            st.session_state["ge_año_sel"] = int(nuevo_año)
            st.rerun()

    # ── Captura por monto anual (se reparte en 12 meses) ──────────────────────
    with st.expander("📅 Capturar un monto anual (se reparte en 12 meses)"):
        st.caption(
            "Ingresa el total del año para un concepto y la app lo divide entre los 12 "
            "meses. El ajuste por redondeo se coloca en diciembre. Las celdas quedan "
            "editables después en la tabla de abajo."
        )
        bc1, bc2, bc3, bc4 = st.columns([3, 2, 2, 1])
        with bc1:
            concepto_anual = st.text_input(
                "Concepto", key="ge_anual_concepto", placeholder="ej. Nómina operativa",
            )
        with bc2:
            año_anual = st.number_input(
                "Año", min_value=2000, max_value=2100, value=int(año_sel), step=1,
                key="ge_anual_año",
            )
        with bc3:
            monto_anual = st.number_input(
                "Monto anual (MXN)", min_value=0.0, step=1000.0, key="ge_anual_monto",
            )
        with bc4:
            st.markdown("<div style='padding-top:1.7rem'></div>", unsafe_allow_html=True)
            if st.button("Distribuir", key="ge_btn_anual", use_container_width=True):
                concepto_s = concepto_anual.strip()
                if not concepto_s or monto_anual <= 0:
                    st.warning("Ingresa un concepto y un monto mayor a 0.")
                else:
                    base  = int(monto_anual // 12)
                    resto = monto_anual - base * 12
                    filas = [
                        (concepto_s, f"{int(año_anual)}-{m:02d}",
                         float(base + (resto if m == 12 else 0)), "")
                        for m in range(1, 13)
                    ]
                    bulk_upsert_gastos_empresa(filas)
                    log_evento(
                        "gasto_empresa_anual",
                        f"{concepto_s} {int(año_anual)}: ${monto_anual:,.0f}",
                    )
                    st.success(
                        f"✅ ${monto_anual:,.0f} distribuido en 12 meses para "
                        f"«{concepto_s}» ({int(año_anual)})."
                    )
                    st.rerun()

    st.divider()

    # ── Grilla editable del año seleccionado ──────────────────────────────────
    st.markdown(f"### Gastos {año_sel}")
    st.caption(
        "Edita los montos directamente en la tabla. Agrega una fila para un concepto "
        "nuevo o bórrala para eliminarlo de este año. Al terminar, presiona "
        "**Guardar cambios**."
    )

    conceptos  = get_conceptos_gastos_empresa()
    datos_año  = get_gastos_empresa_año(int(año_sel))

    filas_grid = []
    for c in conceptos:
        fila = {"Concepto": c}
        for m in range(1, 13):
            fila[ESPANOL_MES[m]] = datos_año.get(c, {}).get(m, 0.0)
        filas_grid.append(fila)

    df_grid = pd.DataFrame(filas_grid, columns=["Concepto"] + _MESES_COLS)

    total_año = df_grid[_MESES_COLS].sum().sum() if len(df_grid) else 0.0
    st.metric("Total del año (captura manual)", f"${total_año:,.0f} MXN")

    edited = st.data_editor(
        df_grid,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key=f"ge_editor_{año_sel}",
        column_config={
            "Concepto": st.column_config.TextColumn(
                "Concepto", required=True, width="medium",
            ),
            **{
                mes: st.column_config.NumberColumn(
                    mes, format="$%,.0f", min_value=0.0, step=1000.0,
                )
                for mes in _MESES_COLS
            },
        },
        height=min(600, 80 + 36 * (len(df_grid) + 3)),
    )

    st.caption(
        "Nota: renombrar un concepto (editar el texto) lo trata como uno nuevo para este "
        "año — el nombre anterior se conserva en años previos. Para eliminar un concepto "
        "de este año, borra su fila."
    )

    if st.button("💾 Guardar cambios", type="primary", key=f"ge_btn_save_{año_sel}"):
        orig_conceptos   = set(df_grid["Concepto"]) if len(df_grid) else set()
        edited_conceptos = set(edited["Concepto"].astype(str).str.strip())
        edited_conceptos.discard("")

        eliminados = orig_conceptos - edited_conceptos
        for c in eliminados:
            delete_concepto_año(c, int(año_sel))
            log_evento("gasto_empresa_concepto_eliminado", f"{c} ({año_sel})")

        # Un concepto manual con el mismo nombre que uno publicado colisionaría en
        # la PK (concepto, periodo) y le arrebataría el origen a Contabilidad.
        _choques = {c for c, _ in _publicados} & edited_conceptos

        filas = []
        for _, row in edited.iterrows():
            concepto = str(row["Concepto"]).strip()
            if not concepto or concepto in _choques:
                continue
            for mes_nombre in _MESES_COLS:
                monto = float(row[mes_nombre]) if pd.notna(row[mes_nombre]) else 0.0
                periodo = f"{int(año_sel)}-{_MES_A_NUM[mes_nombre]:02d}"
                filas.append((concepto, periodo, monto, ""))

        if filas:
            bulk_upsert_gastos_empresa(filas)

        if _choques:
            st.error(
                f"No se guardó {', '.join(sorted(_choques))}: ya existe(n) como "
                f"concepto publicado desde Contabilidad. Usa otro nombre para la "
                f"captura manual."
            )

        if filas or eliminados:
            msg = f"✅ Guardado — {len(filas)} celda(s) actualizada(s)"
            if eliminados:
                msg += f", {len(eliminados)} concepto(s) eliminado(s) de {año_sel}"
            st.success(msg + ".")
            log_evento("gasto_empresa_guardado", f"{año_sel}: {len(filas)} celdas")
            st.rerun()
        elif not _choques:
            st.info("No hubo cambios que guardar.")
