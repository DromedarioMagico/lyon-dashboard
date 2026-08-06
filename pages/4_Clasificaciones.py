import streamlit as st
import pandas as pd

from core.catalogos import CATALOGO_CATEGORIAS, ETIQ_PENDIENTE, COLOR_LYON, COLOR_VENTAS
from core.database import (
    init_db, get_clasificaciones, upsert_clasificacion, delete_clasificacion,
    log_evento, get_vendedor_clientes, upsert_vendedor_cliente,
    delete_vendedor_cliente, bulk_upsert_clasificaciones,
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
               Ultima_Factura=("Fecha de documento", "max"),
           )
           .sort_values("Gasto_Total", ascending=False)
)

# ── Split 2020+ vs histórico (según la fecha de la última factura) ─────────────
_CORTE_HIST = pd.Timestamp("2020-01-01")
_rec_mask   = prov_df["Ultima_Factura"] >= _CORTE_HIST
prov_rec    = prov_df[_rec_mask].copy()
prov_hist   = prov_df[~_rec_mask].copy()

# KPIs y contadores se calculan SOLO sobre proveedores 2020+
total_prov   = len(prov_rec)
pend_mask    = prov_rec["Categoria"] == ETIQ_PENDIENTE
n_pendientes = int(pend_mask.sum())
n_clasif     = total_prov - n_pendientes
gasto_total  = prov_rec["Gasto_Total"].sum()
gasto_clasif = prov_rec.loc[~pend_mask, "Gasto_Total"].sum()
pct_cob      = gasto_clasif / gasto_total * 100 if gasto_total else 0
n_hist       = len(prov_hist)

def _render_tabla_editable(base_df, prefijo):
    """
    Excel-like editable provider table: filter by category/name, Top-N selector,
    inline category editing (dropdown), and save (upsert / delete-to-pending).
    `prefijo` namespaces widget keys so several instances don't collide.
    `base_df` must include: Proveedor, Categoria, Gasto_Total, Facturas, Origen,
    Ultima_Factura.
    """
    opciones_cat = [ETIQ_PENDIENTE] + CATALOGO_CATEGORIAS

    fc1, fc2, fc3 = st.columns([3, 3, 2])
    with fc1:
        cats_filtro = st.multiselect(
            "Filtrar por categoría", options=opciones_cat, default=[],
            placeholder="Todas las categorías", key=f"{prefijo}_cat_filter",
        )
    with fc2:
        busqueda = st.text_input(
            "Buscar proveedor", placeholder="Escribe parte del nombre…",
            key=f"{prefijo}_busq",
        )
    with fc3:
        top_sel = st.selectbox(
            "Mostrar",
            ["Top 50", "Top 100", "Top 200", "Todas (lista completa)"],
            key=f"{prefijo}_topn",
        )

    tabla = base_df.copy()
    if cats_filtro:
        tabla = tabla[tabla["Categoria"].isin(cats_filtro)]
    if busqueda:
        tabla = tabla[tabla["Proveedor"].str.contains(busqueda, case=False, na=False)]
    tabla = tabla.sort_values("Gasto_Total", ascending=False).reset_index(drop=True)
    _limite = {"Top 50": 50, "Top 100": 100, "Top 200": 200}.get(top_sel, len(tabla))
    tabla = tabla.head(_limite).reset_index(drop=True)

    if len(tabla) == 0:
        st.info("Sin proveedores para ese filtro.")
        return

    st.caption(
        f"Mostrando **{len(tabla)}** proveedor(es) · "
        f"Gasto en pantalla: **${tabla['Gasto_Total'].sum()/1e6:,.2f}M MXN**"
    )

    tabla["Ultima"] = tabla["Ultima_Factura"].dt.strftime("%b %Y")
    edit_df = tabla[["Proveedor", "Categoria", "Gasto_Total",
                     "Facturas", "Ultima", "Origen"]].copy()

    _editor_key = f"{prefijo}_editor_{top_sel}_{busqueda}_{'-'.join(sorted(cats_filtro))}"

    edited = st.data_editor(
        edit_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key=_editor_key,
        column_config={
            "Proveedor":   st.column_config.TextColumn("Proveedor", disabled=True),
            "Categoria":   st.column_config.SelectboxColumn(
                "Categoría", options=opciones_cat, required=True, width="medium",
            ),
            "Gasto_Total": st.column_config.NumberColumn(
                "Gasto (MXN)", format="$%,.0f", disabled=True,
            ),
            "Facturas":    st.column_config.NumberColumn(
                "Facturas", format="%d", disabled=True,
            ),
            "Ultima":      st.column_config.TextColumn("Última factura", disabled=True),
            "Origen":      st.column_config.TextColumn("Origen", disabled=True),
        },
        height=min(650, 45 + 36 * len(edit_df)),
    )

    if st.button("💾 Guardar cambios", type="primary", key=f"{prefijo}_save"):
        cambios = 0
        for i in range(len(edit_df)):
            prov    = edit_df.iloc[i]["Proveedor"]
            cat_old = edit_df.iloc[i]["Categoria"]
            cat_new = edited.iloc[i]["Categoria"]
            if cat_new == cat_old:
                continue
            if cat_new == ETIQ_PENDIENTE:
                delete_clasificacion(prov)
                log_evento("desclasificacion", f"{prov} → Pendiente")
            else:
                upsert_clasificacion(prov, cat_new, origen="usuario")
                log_evento("reclasificacion", f"{prov} → {cat_new}")
            cambios += 1

        if cambios:
            st.session_state.pop(_editor_key, None)
            st.success(f"✅ {cambios} cambio(s) guardado(s).")
            st.rerun()
        else:
            st.info("No hubo cambios que guardar.")


def _render_asignacion(clientes_df, opciones_vend, prefijo, mostrar_ultimo=False):
    """
    Per-client vendor assignment UI (search + one card per client + save-all).
    `prefijo` namespaces widget keys. When `mostrar_ultimo` is True, each card
    shows the client's last-order month (useful for historical clients).
    `clientes_df` must include: Cliente_Nombre, Ventas, Pedidos, Ultimo_Pedido.
    """
    busq = st.text_input(
        "Buscar cliente", placeholder="Escribe parte del nombre…", key=f"{prefijo}_busq",
    )
    filtrados = clientes_df.copy()
    if busq:
        filtrados = filtrados[
            filtrados["Cliente_Nombre"].str.contains(busq, case=False, na=False)
        ]

    if len(filtrados) == 0:
        st.info("Sin resultados para esa búsqueda.")
        return

    st.caption(
        f"Mostrando **{len(filtrados)}** cliente(s). "
        "Asigna un vendedor y presiona **Guardar asignaciones** al final."
    )

    selecciones_v = {}
    for i, (_, row) in enumerate(filtrados.iterrows()):
        with st.container(border=True):
            col_info, col_vend = st.columns([4, 3])
            with col_info:
                st.markdown(f"**{row['Cliente_Nombre']}**")
                _extra = ""
                if mostrar_ultimo and pd.notna(row.get("Ultimo_Pedido")):
                    _extra = f"  ·  Último pedido: **{row['Ultimo_Pedido'].strftime('%b %Y')}**"
                st.caption(
                    f"Ventas: **${row['Ventas']:,.0f} MXN**  ·  "
                    f"{int(row['Pedidos'])} pedido(s){_extra}"
                )
            with col_vend:
                vend_sel = st.selectbox(
                    "Vendedor", options=opciones_vend, index=0,
                    key=f"{prefijo}_sel_{i}", label_visibility="collapsed",
                )
                if vend_sel == "✏️ Escribir nombre…":
                    vend_custom = st.text_input(
                        "Nombre del vendedor", key=f"{prefijo}_custom_{i}",
                        placeholder="Nombre completo…", label_visibility="collapsed",
                    )
                else:
                    vend_custom = ""
            selecciones_v[row["Cliente_Nombre"]] = {"sel": vend_sel, "custom": vend_custom}

    st.markdown("")
    col_btn, _ = st.columns([2, 5])
    with col_btn:
        if st.button(
            "💾 Guardar asignaciones", type="primary",
            use_container_width=True, key=f"{prefijo}_save",
        ):
            guardados = 0
            for cliente, vals in selecciones_v.items():
                vend_final = (
                    vals["custom"].strip() if vals["sel"] == "✏️ Escribir nombre…"
                    else vals["sel"]
                )
                if vend_final and vend_final != "— seleccionar —":
                    upsert_vendedor_cliente(cliente, vend_final)
                    log_evento("asignacion_vendedor", f"{cliente} → {vend_final}")
                    guardados += 1
            if guardados:
                st.success(
                    f"✅ {guardados} cliente(s) asignado(s). "
                    "El dashboard de Ventas se actualizará automáticamente."
                )
                st.rerun()
            else:
                st.warning("No seleccionaste ningún vendedor.")


def _render_tabla_vendedores(base_df, prefijo, opciones_vend_dd):
    """
    Excel-like editable client→vendor table: filter by vendor/name, Top-N
    selector, inline vendor reassignment via dropdown, and save. Covers ALL
    clients in `base_df` regardless of current assignment status.
    `opciones_vend_dd` = ["Sin asignar", <vendedor...>] — dropdown-only, no
    free-text entry (use the "Pendientes" tab to introduce a brand-new
    vendor name for the first time).
    `base_df` must include: Cliente_Nombre, Vendedor, Ventas, Pedidos, Ultimo_Pedido.
    """
    fc1, fc2, fc3 = st.columns([3, 3, 2])
    with fc1:
        vend_filtro = st.multiselect(
            "Filtrar por vendedor", options=opciones_vend_dd, default=[],
            placeholder="Todos los vendedores", key=f"{prefijo}_vend_filter",
        )
    with fc2:
        busqueda = st.text_input(
            "Buscar cliente", placeholder="Escribe parte del nombre…",
            key=f"{prefijo}_busq",
        )
    with fc3:
        top_sel = st.selectbox(
            "Mostrar",
            ["Top 50", "Top 100", "Top 200", "Todas (lista completa)"],
            key=f"{prefijo}_topn",
        )

    tabla = base_df.copy()
    if vend_filtro:
        tabla = tabla[tabla["Vendedor"].isin(vend_filtro)]
    if busqueda:
        tabla = tabla[tabla["Cliente_Nombre"].str.contains(busqueda, case=False, na=False)]
    tabla = tabla.sort_values("Ventas", ascending=False).reset_index(drop=True)

    _limite = {"Top 50": 50, "Top 100": 100, "Top 200": 200}.get(top_sel, len(tabla))
    tabla = tabla.head(_limite).reset_index(drop=True)

    if len(tabla) == 0:
        st.info("Sin clientes para ese filtro.")
        return

    st.caption(
        f"Mostrando **{len(tabla)}** cliente(s) · "
        f"Ventas en pantalla: **${tabla['Ventas'].sum()/1e6:,.2f}M MXN**"
    )

    tabla["Ultima"] = tabla["Ultimo_Pedido"].dt.strftime("%b %Y")
    edit_df = tabla[["Cliente_Nombre", "Vendedor", "Ventas", "Pedidos", "Ultima"]].copy()

    _editor_key = f"{prefijo}_editor_{top_sel}_{busqueda}_{'-'.join(sorted(vend_filtro))}"

    edited = st.data_editor(
        edit_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key=_editor_key,
        column_config={
            "Cliente_Nombre": st.column_config.TextColumn("Cliente", disabled=True),
            "Vendedor": st.column_config.SelectboxColumn(
                "Vendedor", options=opciones_vend_dd, required=True, width="medium",
            ),
            "Ventas": st.column_config.NumberColumn(
                "Ventas (MXN)", format="$%,.0f", disabled=True,
            ),
            "Pedidos": st.column_config.NumberColumn("Pedidos", format="%d", disabled=True),
            "Ultima": st.column_config.TextColumn("Último pedido", disabled=True),
        },
        height=min(650, 45 + 36 * len(edit_df)),
    )

    if st.button("💾 Guardar cambios", type="primary", key=f"{prefijo}_save"):
        cambios = 0
        for i in range(len(edit_df)):
            cliente  = edit_df.iloc[i]["Cliente_Nombre"]
            vend_old = edit_df.iloc[i]["Vendedor"]
            vend_new = edited.iloc[i]["Vendedor"]
            if vend_new == vend_old:
                continue
            if vend_new == "Sin asignar":
                delete_vendedor_cliente(cliente)
                log_evento("desasignacion_vendedor", f"{cliente} → Sin asignar")
            else:
                upsert_vendedor_cliente(cliente, vend_new, origen="usuario")
                log_evento("reasignacion_vendedor", f"{cliente} → {vend_new}")
            cambios += 1

        if cambios:
            st.session_state.pop(_editor_key, None)
            st.success(f"✅ {cambios} cambio(s) guardado(s).")
            st.rerun()
        else:
            st.info("No hubo cambios que guardar.")


# ── Outer tabs ────────────────────────────────────────────────────────────────
tab_prov, tab_vend = st.tabs(["Proveedores", "Vendedores"])


# ════════════════════════════════════════════════════════════════════════════════
#  TAB PROVEEDORES
# ════════════════════════════════════════════════════════════════════════════════
with tab_prov:
    # ── Importador masivo desde CSV (subido por el usuario) ────────────────────
    with st.expander("⚙️ Importar clasificaciones desde CSV (masivo)"):
        st.caption(
            "Sube tu archivo **proveedoreslyon_clasificados.csv** (columnas «Proveedor "
            "original» y «Clasificación»; «Observaciones» opcional). Las clasificaciones se "
            "escriben en la base de datos usando el **nombre exacto del proveedor** como "
            "llave — el mismo con el que la app cruza el SAE. Sobrescribe lo que ya exista "
            "y es idempotente. El archivo **no** se guarda en el servidor: solo se leen las "
            "clasificaciones y se mandan a la base de datos."
        )
        _up = st.file_uploader(
            "Archivo CSV de clasificaciones", type=["csv"], key="csv_clasif_uploader",
        )
        if _up is not None and st.button(
            "📥 Importar / actualizar ahora", type="primary", key="btn_import_csv",
        ):
            try:
                df_csv = pd.read_csv(_up, dtype=str, encoding="utf-8-sig").fillna("")
            except UnicodeDecodeError:
                _up.seek(0)
                df_csv = pd.read_csv(_up, dtype=str, encoding="latin-1").fillna("")
            except Exception as e:
                st.error(f"No se pudo leer el CSV: {e}")
                st.stop()

            req = {"Proveedor original", "Clasificación"}
            if not req.issubset(df_csv.columns):
                st.error(
                    f"El CSV debe incluir las columnas {req}. "
                    f"Detectadas: {list(df_csv.columns)}"
                )
                st.stop()

            validas   = set(CATALOGO_CATEGORIAS)
            filas     = []
            omitidas  = 0
            desconoc  = set()
            for _, r in df_csv.iterrows():
                prov = str(r["Proveedor original"]).strip()
                cat  = str(r["Clasificación"]).strip()
                nota = str(r.get("Observaciones", "")).strip()
                if not prov or not cat:
                    omitidas += 1
                    continue
                if cat not in validas:
                    omitidas += 1
                    desconoc.add(cat)
                    continue
                filas.append((prov, cat, nota, "csv"))

            if not filas:
                st.warning("No hay filas válidas para importar.")
            else:
                n = bulk_upsert_clasificaciones(filas)
                log_evento("import_csv", f"{n} clasificaciones importadas desde CSV")
                msg = f"✅ {n} proveedor(es) importado(s)/actualizado(s)."
                if omitidas:
                    msg += f" {omitidas} fila(s) omitida(s)."
                st.success(msg)
                if desconoc:
                    st.warning(
                        "Categorías no reconocidas (omitidas): "
                        + ", ".join(sorted(desconoc))
                    )
                st.rerun()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Proveedores totales",   f"{total_prov:,}")
    c2.metric("Clasificados",          f"{n_clasif:,}",     delta=f"{n_clasif/total_prov*100:.0f}%" if total_prov else "0%")
    c3.metric("Pendientes",            f"{n_pendientes:,}", delta=f"-{n_pendientes}", delta_color="inverse")
    c4.metric("Cobertura del gasto",   f"{pct_cob:.1f}%")
    st.caption(
        f"Métricas sobre proveedores con actividad **2020 en adelante**. "
        f"Hay **{n_hist}** proveedores históricos (última factura antes de 2020) "
        f"en la pestaña «🕰 Histórico»."
    )

    st.divider()

    tab_pend, tab_clasif, tab_hist = st.tabs([
        f"⚠️ Pendientes de clasificar ({n_pendientes})",
        f"📝 Revisar y editar ({total_prov})",
        f"🕰 Histórico pre-2020 ({n_hist})",
    ])

    # ── Pendientes ─────────────────────────────────────────────────────────────
    with tab_pend:
        if n_pendientes == 0:
            st.success("¡Todos los proveedores están clasificados!")
        else:
            pendientes = prov_rec[pend_mask].copy().reset_index(drop=True)
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

    # ── Revisar y editar (tabla tipo Excel) — proveedores 2020+ ────────────────
    with tab_clasif:
        st.caption(
            "Filtra por categoría o nombre y **edita la categoría de cualquier proveedor "
            "directamente en la tabla** (columna «Categoría»). Ordenada por impacto en gasto "
            "(mayor a menor). Solo proveedores con actividad **2020 en adelante**. "
            "Al terminar, presiona **Guardar cambios**."
        )
        _render_tabla_editable(prov_rec, "rec")

    # ── Histórico pre-2020 ──────────────────────────────────────────────────────
    with tab_hist:
        st.caption(
            "Proveedores cuya **última factura es anterior a 2020** — sin actividad "
            "reciente. Suelen ser difíciles de identificar; se apartan aquí para no "
            "estorbar el flujo normal, pero puedes clasificarlos igual si lo necesitas."
        )
        if n_hist == 0:
            st.info("No hay proveedores históricos (todos tienen actividad 2020+).")
        else:
            _render_tabla_editable(prov_hist, "hist")


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
        df_v = aplicar_vendedores(st.session_state.df_ventas.copy())

        # ── Todos los clientes (asignados o no), con su último pedido ──────────
        clientes_full_df = (
            df_v.groupby("Cliente_Nombre", as_index=False)
            .agg(
                Vendedor=("Vendedor", "first"),
                Ventas=("Importe_MXN", "sum"),
                Pedidos=("Importe_MXN", "count"),
                Ultimo_Pedido=("Fecha", "max"),
            )
            .sort_values("Ventas", ascending=False)
        )

        # ── Split 2020+ vs histórico (por fecha del último pedido) — TODOS,
        #    sin importar si ya tienen vendedor asignado ───────────────────────
        clientes_rec  = clientes_full_df[clientes_full_df["Ultimo_Pedido"] >= _CORTE_HIST].copy()
        clientes_hist = clientes_full_df[clientes_full_df["Ultimo_Pedido"] <  _CORTE_HIST].copy()

        clientes_sin_rec = clientes_rec[clientes_rec["Vendedor"] == "Sin asignar"].copy()

        asig_db        = get_vendedor_clientes()   # {cliente: vendedor} from DB
        total_clientes = len(clientes_rec)          # solo 2020+
        n_sin          = len(clientes_sin_rec)
        n_asig         = total_clientes - n_sin
        pct_asig       = n_asig / total_clientes * 100 if total_clientes > 0 else 0
        n_en_db        = len(asig_db)
        n_hist_v       = len(clientes_hist)

        # Opciones de vendedor
        vendedores_conocidos = sorted(
            df_v[df_v["Vendedor"] != "Sin asignar"]["Vendedor"].dropna().unique().tolist()
        )
        opciones_vend    = ["— seleccionar —"] + vendedores_conocidos + ["✏️ Escribir nombre…"]
        opciones_vend_dd = ["Sin asignar"] + vendedores_conocidos

        # Summary
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Clientes totales",      f"{total_clientes:,}")
        c2.metric("Sin vendedor",          f"{n_sin:,}",
                  delta=f"-{n_sin}", delta_color="inverse")
        c3.metric("Con vendedor",          f"{n_asig:,}",
                  delta=f"{pct_asig:.0f}%")
        c4.metric("Asignados en esta app", f"{n_en_db:,}")
        st.caption(
            f"Métricas sobre clientes con pedidos **2020 en adelante**. "
            f"Hay **{n_hist_v}** clientes (asignados o no) cuyo último pedido "
            f"es anterior a 2020 en la pestaña «🕰 Histórico»."
        )

        st.divider()

        tab_todos, tab_pend_v, tab_hist_v = st.tabs([
            f"👥 Todos ({total_clientes})",
            f"⚠️ Pendientes de clasificar ({n_sin})",
            f"🕰 Histórico pre-2020 ({n_hist_v})",
        ])

        # ── Todos (2020+, asignados o no) ───────────────────────────────────────
        with tab_todos:
            st.caption(
                "Todos los clientes con actividad **2020 en adelante**, asignados o "
                "no. Reasigna directamente en la tabla (columna «Vendedor»)."
            )
            _render_tabla_vendedores(clientes_rec, "vtodos", opciones_vend_dd)

        # ── Pendientes de clasificar (2020+, sin asignar) ───────────────────────
        with tab_pend_v:
            if n_sin == 0:
                st.success("¡Todos los clientes 2020+ tienen vendedor asignado!")
            else:
                _render_asignacion(clientes_sin_rec, opciones_vend, "vsin")

        # ── Histórico pre-2020 (todos, asignados o no) ──────────────────────────
        with tab_hist_v:
            st.caption(
                "Clientes cuyo **último pedido es anterior a 2020** — asignados o "
                "no. Se apartan aquí para no estorbar el flujo normal, pero puedes "
                "reasignarlos igual en la tabla."
            )
            if n_hist_v == 0:
                st.info("No hay clientes históricos (todos tienen actividad 2020+).")
            else:
                _render_tabla_vendedores(clientes_hist, "vhistall", opciones_vend_dd)
