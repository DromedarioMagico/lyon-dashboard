import streamlit as st
from core.database import init_db, get_stats
from core.navigation import render_sidebar_search, render_sidebar_status, inject_custom_css, handle_pending_nav
from core.catalogos import COLOR_LYON

st.set_page_config(
    page_title="Dashboards Lyon AG",
    page_icon="📊",
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
    f"<h1 style='color:{COLOR_LYON}; margin-bottom:4px'>"
    "<span class='material-symbols-outlined'>dashboard</span>Dashboards Lyon AG</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='color:#5b6b7a; font-size:14px; margin-bottom:24px'>"
    "Planta QUMA — Sistema de control de compras y ventas</p>",
    unsafe_allow_html=True,
)

stats = get_stats()
col_a, col_b, col_c = st.columns(3)
with col_a:
    st.metric("Proveedores clasificados", stats["total_clasificados"])
with col_b:
    ultima = stats["ultima_modificacion"]
    st.metric("Última clasificación", str(ultima)[:10] if ultima else "—")
with col_c:
    cargados = sum([
        "df_compras" in st.session_state,
        "df_ventas"  in st.session_state,
    ])
    st.metric("Archivos en sesión", f"{cargados} / 2")

st.markdown("---")
st.subheader("Módulos")

card1, card2, card3 = st.columns(3)

with card1:
    with st.container(border=True):
        st.markdown(
            "<h3><span class='material-symbols-outlined' style='color:#1F4E79'>receipt_long</span>Compras</h3>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "Control de facturas de proveedores. "
            "Categorización, Pareto, curva de gasto semanal."
        )
        if st.button("Ir a Compras →", key="nav_compras", use_container_width=True, type="primary"):
            st.switch_page("pages/1_Compras.py")

with card2:
    with st.container(border=True):
        st.markdown(
            "<h3><span class='material-symbols-outlined' style='color:#548235'>bar_chart</span>Ventas</h3>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "Control de pedidos por cliente y vendedor. "
            "Heatmap de estacionalidad."
        )
        if st.button("Ir a Ventas →", key="nav_ventas", use_container_width=True, type="primary"):
            st.switch_page("pages/2_Ventas.py")

with card3:
    with st.container(border=True):
        st.markdown(
            "<h3><span class='material-symbols-outlined' style='color:#1F4E79'>compare_arrows</span>Comparativa</h3>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "Margen operativo bruto: Ventas vs Compras. "
            "Requiere ambos archivos cargados."
        )
        if st.button("Ir a Comparativa →", key="nav_comp", use_container_width=True, type="primary"):
            st.switch_page("pages/3_Comparativa.py")
