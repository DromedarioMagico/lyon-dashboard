import streamlit as st
import pandas as pd

from core.catalogos import CATALOGO_CATEGORIAS, ETIQ_PENDIENTE, COLOR_LYON, COLOR_VENTAS
from core.database import (
    init_db, get_clasificaciones, upsert_clasificacion, log_evento,
    get_vendedor_clientes, upsert_vendedor_cliente,
)
from core.etl_compras import aplicar_clasificaciones
from core.etl_ventas import aplicar_vendedores
from core.navigation import render_sidebar_search, render_sidebar_status, inject_custom_css, handle_pending_nav

st.set_page_config(
    page_title="Clasificaciones — Lyon AG",
    page_icon="📂",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_db()
inject_custom_css()
handle_pending_nav()

_BLUE  = COLOR_LYON
_GREEN = COLOR_VENTAS
_CATS  = ["— seleccionar —"] + CATALOGO_CATEGORIAS

with st.sidebar:
    render_sidebar_search()
    render_sidebar_status()

st.markdown(
    f"<h1 style='color:{COLOR_LYON}'>"
    "<span class='material-symbols-outlined'>folder_open</span>Clasificaciones</h1>",
    unsafe_allow_html=True,
)

if "df_compras" not in st.session_state:
    st.warning("Carga primero el archivo de Compras para gestionar clasificaciones.")
    if st.button("Ir a Compras", use_container_width=False):
        st.switch_page("pages/1_Compras.py")
    st.stop()

# ── Datos base de proveedores ─────────────────────────────────────────────────
df_full = aplicar_clasificaciones(st.session_state.df_compras)

prov_df = (
    df_full.groupby("Proveedor", as_index=False)
           .agg(
               Gasto_Total=("Gasto_Total_MXN", "sum"),
               Facturas=("Gasto_Total_MXN", "count"),
               Categoria=("Categoria", "first"),
               Origen=("Origen", "first"),
           )
           .sort_values("Gasto_Total", ascending=False)
)

total_prov   = len(prov_df)
pend_mask    = prov_df["Categoria"] == ETIQ_PENDIENTE
n_pendientes = pend_mask.sum()
n_clasif     = total_prov - n_pendientes
gasto_total  = prov_df["Gasto_Total"].sum()
gasto_clasif = prov_df.loc[~pend_mask, "Gasto_Total"].sum()
pct_cob      = gasto_clasif / gasto_total * 100 if gasto_total else 0

# ── Outer tabs ────────────────────────────────────────────────────────────────
tab_prov, tab_vend = st.tabs(["Proveedores", "Vendedores"])


# ════════════════════════════════════════════════════════════════════════════════
#  TAB PROVEEDORES
# ════════════════════════════════════════════════════════════════════════════════
with tab_prov:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Proveedores totales",   f"{total_prov:,}")
    c2.metric("Clasificados",          f"{n_clasif:,}",     delta=f"{n_clasif/total_prov*100:.0f}%")
    c3.metric("Pendientes",            f"{n_pendientes:,}", delta=f"-{n_pendientes}", delta_color="inverse")
    c4.metric("Cobertura del gasto",   f"{pct_cob:.1f}%")

    st.divider()

    tab_pend, tab_clasif = st.tabs([
        f"⚠️ Pendientes de clasificar ({n_pendientes})",
        f"✅ Clasificados ({n_clasif})",
    ])

    # ── Pendientes ─────────────────────────────────────────────────────────────
    with tab_pend:
        if n_pendientes == 0:
            st.success("¡Todos los proveedores están clasificados!")
        else:
            pendientes = prov_df[pend_mask].copy().reset_index(drop=True)
            st.caption(
                f"{n_pendientes} proveedores representan "
                f"**${(gasto_total - gasto_clasif)/1e6:,.2f}M MXN** "
                f"({100 - pct_cob:.1f}% del gasto) aún sin categoría."
            )

            busqueda = st.text_input(
                "Buscar proveedor", placeholder="Escribe parte del nombre…", key="busq_pend"
            )
            if busqueda:
                pendientes = pendientes[
                    pendientes["Proveedor"].str.contains(busqueda, case=False, na=False)
                ]

            if len(pendientes) == 0:
                st.info("Sin resultados para esa búsqueda.")
            else:
                st.markdown(
                    f"Mostrando **{len(pendientes)}** proveedor(es). "
                    "Asigna categoría y presiona **Guardar cambios** al final."
                )

                selecciones = {}
                notas_dict  = {}

                for idx, row in pendientes.iterrows():
                    with st.container(border=True):
                        col_info, col_cat, col_nota = st.columns([3, 2, 2])
                        with col_info:
                            st.markdown(f"**{row['Proveedor']}**")
                            st.caption(
                                f"Gasto: **${row['Gasto_Total']:,.0f} MXN**  ·  "
                                f"{row['Facturas']} factura(s)"
                            )
                        with col_cat:
                            cat = st.selectbox(
                                "Categoría",
                                options=_CATS,
                                index=0,
                                key=f"cat_pend_{idx}",
                                label_visibility="collapsed",
                            )
                            selecciones[row["Proveedor"]] = cat
                        with col_nota:
                            nota = st.text_input(
                                "Notas (opcional)",
                                key=f"nota_pend_{idx}",
                                placeholder="ej: contrato anual, etc.",
                                label_visibility="collapsed",
                            )
                            notas_dict[row["Proveedor"]] = nota

                st.markdown("")
                col_btn, _ = st.columns([2, 5])
                with col_btn:
                    if st.button("💾 Guardar cambios", type="primary",
                                 use_container_width=True, key="btn_save_pend"):
                        guardados = 0
                        for prov, cat in selecciones.items():
                            if cat != "— seleccionar —":
                                upsert_clasificacion(
                                    prov, cat,
                                    notas=notas_dict.get(prov, ""),
                                    origen="usuario",
                                )
                                log_evento("clasificacion", f"{prov} → {cat}")
                                guardados += 1
                        if guardados:
                            st.success(
                                f"✅ {guardados} proveedor(es) clasificado(s). "
                                "La cobertura en Compras se actualizará automáticamente."
                            )
                            st.rerun()
                        else:
                            st.warning("No seleccionaste ninguna categoría.")

    # ── Clasificados ───────────────────────────────────────────────────────────
    with tab_clasif:
        if n_clasif == 0:
            st.info("Aún no hay proveedores clasificados.")
        else:
            clasif_df = prov_df[~pend_mask].copy().reset_index(drop=True)

            busqueda2 = st.text_input(
                "Buscar proveedor", placeholder="Escribe parte del nombre…", key="busq_clasif"
            )
            if busqueda2:
                clasif_df = clasif_df[
                    clasif_df["Proveedor"].str.contains(busqueda2, case=False, na=False)
                ]

            st.dataframe(
                clasif_df[["Proveedor", "Categoria", "Origen", "Gasto_Total", "Facturas"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Proveedor":   st.column_config.TextColumn("Proveedor"),
                    "Categoria":   st.column_config.TextColumn("Categoría"),
                    "Origen":      st.column_config.TextColumn("Origen"),
                    "Gasto_Total": st.column_config.NumberColumn("Gasto (MXN)", format="$%,.0f"),
                    "Facturas":    st.column_config.NumberColumn("Facturas",    format="%d"),
                },
                height=min(600, 45 + 36 * len(clasif_df)),
            )

            prov_lista_full = prov_df[~pend_mask]["Proveedor"].tolist()

            st.divider()
            st.markdown("**Reclasificar un proveedor**")

            if not prov_lista_full:
                st.caption("No hay proveedores clasificados aún.")
            else:
                col_sel, col_cat2, col_nota2, col_btn2 = st.columns([3, 2, 2, 1])
                with col_sel:
                    prov_sel = st.selectbox(
                        "Proveedor", prov_lista_full, key="reclass_prov",
                        label_visibility="collapsed",
                    )
                with col_cat2:
                    cat_actual = (
                        prov_df.loc[prov_df["Proveedor"] == prov_sel, "Categoria"].iloc[0]
                        if prov_sel else _CATS[0]
                    )
                    idx_actual = _CATS.index(cat_actual) if cat_actual in _CATS else 0
                    nueva_cat  = st.selectbox(
                        "Nueva categoría", _CATS, index=idx_actual,
                        key="reclass_cat", label_visibility="collapsed",
                    )
                with col_nota2:
                    nueva_nota = st.text_input(
                        "Nota", key="reclass_nota", label_visibility="collapsed",
                    )
                with col_btn2:
                    st.markdown("<div style='padding-top:4px'>", unsafe_allow_html=True)
                    if st.button("Guardar", key="btn_reclass", use_container_width=True):
                        if nueva_cat != "— seleccionar —" and prov_sel:
                            upsert_clasificacion(prov_sel, nueva_cat, notas=nueva_nota,
                                                 origen="usuario")
                            log_evento("reclasificacion", f"{prov_sel} → {nueva_cat}")
                            st.success(f"✅ {prov_sel} reclasificado como **{nueva_cat}**.")
                            st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
#  TAB VENDEDORES
# ════════════════════════════════════════════════════════════════════════════════
with tab_vend:
    if "df_ventas" not in st.session_state:
        st.warning(
            "Carga también el archivo de Ventas para gestionar asignaciones de vendedores."
        )
        if st.button("Ir a Ventas", key="btn_go_ventas"):
            st.switch_page("pages/2_Ventas.py")
    else:
        df_v          = aplicar_vendedores(st.session_state.df_ventas.copy())
        sin_vend_mask = df_v["Vendedor"] == "Sin asignar"

        clientes_sin_df = (
            df_v[sin_vend_mask]
            .groupby("Cliente_Nombre", as_index=False)
            .agg(Ventas=("Importe_MXN", "sum"), Pedidos=("Importe_MXN", "count"))
            .sort_values("Ventas", ascending=False)
        )

        asig_db        = get_vendedor_clientes()   # {cliente: vendedor} from DB
        total_clientes = df_v["Cliente_Nombre"].nunique()
        n_sin          = len(clientes_sin_df)
        n_asig         = total_clientes - n_sin
        pct_asig       = n_asig / total_clientes * 100 if total_clientes > 0 else 0
        n_en_db        = len(asig_db)

        # Summary
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Clientes totales",      f"{total_clientes:,}")
        c2.metric("Sin vendedor",          f"{n_sin:,}",
                  delta=f"-{n_sin}", delta_color="inverse")
        c3.metric("Con vendedor",          f"{n_asig:,}",
                  delta=f"{pct_asig:.0f}%")
        c4.metric("Asignados en esta app", f"{n_en_db:,}")

        st.divider()

        tab_sin, tab_asig = st.tabs([
            f"⚠️ Sin asignar ({n_sin})",
            f"✅ Asignados en app ({n_en_db})",
        ])

        # ── Sin asignar ────────────────────────────────────────────────────────
        with tab_sin:
            if n_sin == 0:
                st.success("¡Todos los clientes tienen vendedor asignado!")
            else:
                vendedores_conocidos = sorted(
                    df_v[~sin_vend_mask]["Vendedor"].dropna().unique().tolist()
                )
                opciones_vend = (
                    ["— seleccionar —"] + vendedores_conocidos + ["✏️ Escribir nombre…"]
                )

                busq_v = st.text_input(
                    "Buscar cliente",
                    placeholder="Escribe parte del nombre…",
                    key="busq_vend_sin",
                )

                filtrados = clientes_sin_df.copy()
                if busq_v:
                    filtrados = filtrados[
                        filtrados["Cliente_Nombre"].str.contains(busq_v, case=False, na=False)
                    ]

                if len(filtrados) == 0:
                    st.info("Sin resultados para esa búsqueda.")
                else:
                    st.caption(
                        f"Mostrando **{len(filtrados)}** cliente(s) sin vendedor. "
                        "Asigna un vendedor y presiona **Guardar asignaciones** al final."
                    )

                    selecciones_v = {}
                    for i, (_, row) in enumerate(filtrados.iterrows()):
                        with st.container(border=True):
                            col_info, col_vend = st.columns([4, 3])
                            with col_info:
                                st.markdown(f"**{row['Cliente_Nombre']}**")
                                st.caption(
                                    f"Ventas: **${row['Ventas']:,.0f} MXN**  ·  "
                                    f"{int(row['Pedidos'])} pedido(s)"
                                )
                            with col_vend:
                                vend_sel = st.selectbox(
                                    "Vendedor",
                                    options=opciones_vend,
                                    index=0,
                                    key=f"vend_sel_{i}",
                                    label_visibility="collapsed",
                                )
                                if vend_sel == "✏️ Escribir nombre…":
                                    vend_custom = st.text_input(
                                        "Nombre del vendedor",
                                        key=f"vend_custom_{i}",
                                        placeholder="Nombre completo…",
                                        label_visibility="collapsed",
                                    )
                                else:
                                    vend_custom = ""
                            selecciones_v[row["Cliente_Nombre"]] = {
                                "sel": vend_sel, "custom": vend_custom
                            }

                    st.markdown("")
                    col_btn, _ = st.columns([2, 5])
                    with col_btn:
                        if st.button(
                            "💾 Guardar asignaciones", type="primary",
                            use_container_width=True, key="btn_save_vend",
                        ):
                            guardados = 0
                            for cliente, vals in selecciones_v.items():
                                if vals["sel"] == "✏️ Escribir nombre…":
                                    vend_final = vals["custom"].strip()
                                else:
                                    vend_final = vals["sel"]
                                if vend_final and vend_final != "— seleccionar —":
                                    upsert_vendedor_cliente(cliente, vend_final)
                                    log_evento("asignacion_vendedor",
                                               f"{cliente} → {vend_final}")
                                    guardados += 1
                            if guardados:
                                st.success(
                                    f"✅ {guardados} cliente(s) asignado(s). "
                                    "El dashboard de Ventas se actualizará automáticamente."
                                )
                                st.rerun()
                            else:
                                st.warning("No seleccionaste ningún vendedor.")

        # ── Asignados en app ───────────────────────────────────────────────────
        with tab_asig:
            if n_en_db == 0:
                st.info("Aún no has asignado vendedores desde esta app.")
            else:
                asig_tbl = pd.DataFrame(
                    [{"Cliente": k, "Vendedor": v} for k, v in asig_db.items()]
                )
                cli_stats = (
                    df_v.groupby("Cliente_Nombre", as_index=False)
                    .agg(Ventas=("Importe_MXN", "sum"), Pedidos=("Importe_MXN", "count"))
                )
                asig_tbl = asig_tbl.merge(
                    cli_stats.rename(columns={"Cliente_Nombre": "Cliente"}),
                    on="Cliente", how="left",
                )
                asig_tbl["Ventas"]  = asig_tbl["Ventas"].fillna(0)
                asig_tbl["Pedidos"] = asig_tbl["Pedidos"].fillna(0).astype(int)
                asig_tbl = asig_tbl.sort_values("Ventas", ascending=False).reset_index(drop=True)

                busq_asig = st.text_input(
                    "Buscar cliente",
                    placeholder="Escribe parte del nombre…",
                    key="busq_asig",
                )
                disp_tbl = asig_tbl.copy()
                if busq_asig:
                    disp_tbl = disp_tbl[
                        disp_tbl["Cliente"].str.contains(busq_asig, case=False, na=False)
                    ]

                st.dataframe(
                    disp_tbl[["Cliente", "Vendedor", "Ventas", "Pedidos"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Cliente":  st.column_config.TextColumn("Cliente"),
                        "Vendedor": st.column_config.TextColumn("Vendedor"),
                        "Ventas":   st.column_config.NumberColumn("Ventas (MXN)", format="$%,.0f"),
                        "Pedidos":  st.column_config.NumberColumn("Pedidos",      format="%d"),
                    },
                    height=min(600, 45 + 36 * len(disp_tbl)),
                )

                st.divider()
                st.markdown("**Reasignar un cliente**")

                vendedores_reasig = sorted(
                    df_v[df_v["Vendedor"] != "Sin asignar"]["Vendedor"].dropna().unique().tolist()
                )
                opciones_reasig = (
                    ["— seleccionar —"] + vendedores_reasig + ["✏️ Escribir nombre…"]
                )
                all_clientes_asig = asig_tbl["Cliente"].tolist()

                col_cli, col_vv, col_btnr = st.columns([3, 3, 1])
                with col_cli:
                    cli_reasig = st.selectbox(
                        "Cliente", all_clientes_asig, key="reasig_cli",
                        label_visibility="collapsed",
                    )
                with col_vv:
                    actual_vend = asig_db.get(cli_reasig, "— seleccionar —")
                    idx_act = (opciones_reasig.index(actual_vend)
                               if actual_vend in opciones_reasig else 0)
                    nuevo_vend = st.selectbox(
                        "Nuevo vendedor", opciones_reasig, index=idx_act,
                        key="reasig_vend", label_visibility="collapsed",
                    )
                    if nuevo_vend == "✏️ Escribir nombre…":
                        nuevo_vend_custom = st.text_input(
                            "Nombre", key="reasig_custom",
                            placeholder="Nombre completo…",
                            label_visibility="collapsed",
                        )
                    else:
                        nuevo_vend_custom = ""
                with col_btnr:
                    st.markdown("<div style='padding-top:4px'>", unsafe_allow_html=True)
                    if st.button("Guardar", key="btn_reasig", use_container_width=True):
                        vend_save = (
                            nuevo_vend_custom.strip()
                            if nuevo_vend == "✏️ Escribir nombre…"
                            else nuevo_vend
                        )
                        if vend_save and vend_save != "— seleccionar —" and cli_reasig:
                            upsert_vendedor_cliente(cli_reasig, vend_save)
                            log_evento("reasignacion_vendedor",
                                       f"{cli_reasig} → {vend_save}")
                            st.success(f"✅ {cli_reasig} reasignado a **{vend_save}**.")
                            st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
