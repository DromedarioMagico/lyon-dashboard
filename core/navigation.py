import os
import streamlit as st
from core.database import get_stats

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
_LOGO = os.path.join(_ROOT, "assets", "lion.svg")


def inject_custom_css():
    """Inject shared CSS. Call once near the top of every page (after set_page_config)."""
    if os.path.exists(_LOGO):
        st.logo(_LOGO, size="large")
    st.markdown(
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,300,0,0">',
        unsafe_allow_html=True,
    )
    st.markdown("""
    <style>
    /* ── Material Symbols (icons for page headers) ────────────── */
    .material-symbols-outlined {
        font-variation-settings: 'FILL' 0, 'wght' 300, 'GRAD' 0, 'opsz' 24;
        vertical-align: middle;
        margin-right: 8px;
        font-size: 1.1em;
        line-height: 1;
        color: inherit;
        display: inline-block;
    }
    /* ── Metric cards ─────────────────────────────────────────── */
    [data-testid="metric-container"] {
        background: #FFFFFF;
        border: 1px solid #E1E7EC;
        border-radius: 10px;
        padding: 1rem 1.25rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    }
    [data-testid="stMetricValue"] {
        font-size: 1.75rem !important;
        font-weight: 700 !important;
        color: #1F4E79 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.75rem !important;
        color: #6B7280 !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.5px !important;
    }
    /* ── Layout & gaps ────────────────────────────────────────── */
    .main .block-container {
        padding-top: 0.25rem !important;
        padding-bottom: 2rem !important;
    }
    header[data-testid="stHeader"] { display: none !important; }
    /* Hide anchor-link icons that appear next to headings */
    a.anchor-link, h1 a, h2 a, h3 a { display: none !important; }
    /* Remove gap between auto-nav and custom sidebar content */
    [data-testid="stSidebarUserContent"] {
        padding-top: 0 !important;
        margin-top: 0 !important;
    }
    /* Make sidebar logo larger than Streamlit's default cap */
    [data-testid="stSidebarLogoLink"] img,
    [data-testid="stLogoImage"] img,
    [data-testid="stSidebarLogo"] img,
    section[data-testid="stSidebar"] img[class*="logo"] {
        height: 72px !important;
        width: auto !important;
        max-width: none !important;
        object-fit: contain !important;
    }
    [data-testid="stSidebarLogoLink"],
    [data-testid="stLogoImage"],
    [data-testid="stSidebarLogo"] {
        height: 72px !important;
        padding: 0.75rem 1rem !important;
    }
    /* Collapse the extra hr before Buscar — only keep 1 divider */
    [data-testid="stSidebarUserContent"] hr:first-child {
        display: none !important;
    }
    /* ── Section header visual indicators ────────────────────── */
    section[data-testid="stMain"] h3 {
        border-left: 3px solid #1F4E79;
        padding-left: 10px;
        margin-left: -2px;
    }
    section[data-testid="stMain"] h5 {
        border-left: 2px solid #CBD5E1;
        padding-left: 8px;
        color: #374151;
    }
    /* ── Sidebar branding ─────────────────────────────────────── */
    /* Hide Streamlit's auto-generated "app" section header */
    [data-testid="stSidebarNavSectionHeader"],
    [data-testid="stSidebarNav"] > div:first-child {
        display: none !important;
    }
    /* Create space at the top of the nav for our branded header */
    [data-testid="stSidebarNav"] {
        position: relative !important;
        padding-top: 5.2rem !important;
        padding-bottom: 0 !important;
    }
    /* LYON AG — large, dark green, absolute-positioned at top of nav */
    [data-testid="stSidebarNav"]::before {
        position: absolute;
        top: 0.85rem;
        left: 1.1rem;
        right: 1rem;
        content: "LYON AG";
        font-size: 1.35rem;
        font-weight: 900;
        color: #1B4D0F;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        line-height: 1;
    }
    /* Subtitle — below LYON AG, above nav items */
    [data-testid="stSidebarNav"]::after {
        position: absolute;
        top: 2.7rem;
        left: 1.1rem;
        right: 0;
        content: "Reportes de Compra-Venta Interactivos";
        font-size: 0.63rem;
        font-weight: 500;
        color: #6B7280;
        letter-spacing: 0.03em;
        line-height: 1.4;
        padding-bottom: 0.55rem;
        border-bottom: 1px solid #E5E7EB;
    }
    /* Remove gap below nav list */
    [data-testid="stSidebarNavItems"] {
        padding-bottom: 0 !important;
        margin-bottom: 0 !important;
    }
    /* ── Nav item icons via Material Symbols ligatures ────────── */
    [data-testid="stSidebarNavItems"] li a::before {
        font-family: 'Material Symbols Outlined';
        font-variation-settings: 'FILL' 0, 'wght' 300, 'GRAD' 0, 'opsz' 24;
        font-size: 16px;
        margin-right: 7px;
        vertical-align: middle;
        display: inline-block;
    }
    [data-testid="stSidebarNavItems"] li:nth-child(1) a::before { content: "home"; }
    [data-testid="stSidebarNavItems"] li:nth-child(2) a::before { content: "receipt_long"; }
    [data-testid="stSidebarNavItems"] li:nth-child(3) a::before { content: "bar_chart"; }
    [data-testid="stSidebarNavItems"] li:nth-child(4) a::before { content: "compare_arrows"; }
    [data-testid="stSidebarNavItems"] li:nth-child(5) a::before { content: "folder_open"; }
    /* Rename "app" → "Home" by zeroing out its text and injecting via ::after */
    [data-testid="stSidebarNavItems"] li:nth-child(1) a > span,
    [data-testid="stSidebarNavItems"] li:nth-child(1) a > div {
        font-size: 0 !important;
        letter-spacing: 0 !important;
        visibility: hidden;
        width: 0;
        overflow: hidden;
    }
    [data-testid="stSidebarNavItems"] li:nth-child(1) a::after {
        content: "Home";
        font-size: 0.875rem;
        color: inherit;
        letter-spacing: normal;
        font-weight: inherit;
    }
    /* ── Dividers ─────────────────────────────────────────────── */
    hr { border-top: 1px solid #E5E7EB !important; }
    </style>
    """, unsafe_allow_html=True)


def render_sidebar_status():
    """Shows loaded files and DB stats. Call inside `with st.sidebar:`."""
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Estado de la sesión**")

    compras_loaded = "df_compras" in st.session_state
    ventas_loaded  = "df_ventas"  in st.session_state

    if compras_loaded:
        meta = st.session_state.get("df_compras_meta", {})
        st.sidebar.success(f"Compras: {meta.get('archivo', 'cargado')}")
    else:
        st.sidebar.info("Compras: no cargado")

    if ventas_loaded:
        meta = st.session_state.get("df_ventas_meta", {})
        st.sidebar.success(f"Ventas: {meta.get('archivo', 'cargado')}")
    else:
        st.sidebar.info("Ventas: no cargado")

    stats = get_stats()
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Base de datos**")
    st.sidebar.metric("Proveedores clasificados", stats["total_clasificados"])
    if stats["ultima_modificacion"]:
        st.sidebar.caption(f"Últ. modificación: {stats['ultima_modificacion'][:16]}")

    if compras_loaded and ventas_loaded:
        st.sidebar.markdown("---")
        if st.sidebar.button("📊 Generar reporte", use_container_width=True, type="primary"):
            from datetime import datetime
            from core.report import generate_report_html
            _bar  = st.sidebar.progress(0, text="Preparando datos…")
            _info = st.sidebar.empty()

            def _on_progress(step: int, total: int, label: str) -> None:
                _pct = step / total
                _bar.progress(_pct, text=f"Renderizando {step}/{total}: {label}")

            _html = generate_report_html(
                st.session_state.df_compras,
                st.session_state.df_ventas,
                st.session_state.get("df_compras_meta", {}),
                st.session_state.get("df_ventas_meta",  {}),
                on_progress=_on_progress,
            )
            _bar.empty()
            _info.empty()
            st.session_state["_report_html"]  = _html
            st.session_state["_report_fname"] = (
                f"reporte_lyon_ag_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
            )
        if st.session_state.get("_report_html"):
            st.sidebar.download_button(
                label="⬇️ Descargar HTML",
                data=st.session_state["_report_html"],
                file_name=st.session_state.get("_report_fname", "reporte.html"),
                mime="text/html",
                use_container_width=True,
            )


def _srch_label(s, max_len=28):
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


def _section_head(text):
    st.sidebar.markdown(
        f"<p style='margin:8px 0 2px;font-size:.68rem;font-weight:700;"
        f"color:#6B7280;text-transform:uppercase;letter-spacing:.6px'>{text}</p>",
        unsafe_allow_html=True,
    )


def handle_pending_nav():
    """
    Call this at the very top of each page (outside any 'with' block) to process
    navigation requests set by render_sidebar_search(). Safe because st.switch_page
    is called from the main script body, not from inside a context manager.
    """
    if "_goto" in st.session_state:
        target = st.session_state.pop("_goto")
        st.switch_page(target)


def render_sidebar_search():
    """Global search — proveedores, clientes, vendedores. Results navigate to inline drill-down."""
    st.sidebar.markdown("---")
    query = st.sidebar.text_input(
        "🔍 Buscar",
        placeholder="Proveedor, cliente, vendedor…",
        key="sidebar_global_search",
    )

    q = query.strip() if query else ""
    if len(q) < 3:
        return query

    q_up = q.upper()
    compras_loaded = "df_compras" in st.session_state
    ventas_loaded  = "df_ventas"  in st.session_state

    if not compras_loaded and not ventas_loaded:
        st.sidebar.caption("_Carga un archivo para buscar._")
        return query

    any_result = False

    # ── Proveedores ───────────────────────────────────────────────────────────
    if compras_loaded:
        df_c = st.session_state.df_compras
        ranked_p = (df_c.groupby("Proveedor")["Gasto_Total_MXN"]
                       .sum().sort_values(ascending=False).index.tolist())
        hits_p = [p for p in ranked_p if q_up in p.upper()][:5]
        if hits_p:
            any_result = True
            _section_head("Proveedores")
            for i, prov in enumerate(hits_p):
                if st.sidebar.button(
                    _srch_label(prov), key=f"srch_p_{i}",
                    use_container_width=True,
                ):
                    st.session_state["drill_proveedor"] = prov
                    st.session_state["_goto"] = "pages/1_Compras.py"
                    st.rerun()

    # ── Clientes ──────────────────────────────────────────────────────────────
    if ventas_loaded:
        df_v = st.session_state.df_ventas
        ranked_c = (df_v.groupby("Cliente_Nombre")["Importe_MXN"]
                       .sum().sort_values(ascending=False).index.tolist())
        hits_c = [c for c in ranked_c if q_up in c.upper()][:5]
        if hits_c:
            any_result = True
            _section_head("Clientes")
            for i, cli in enumerate(hits_c):
                if st.sidebar.button(
                    _srch_label(cli), key=f"srch_c_{i}",
                    use_container_width=True,
                ):
                    st.session_state["drill_cliente"] = cli
                    st.session_state["_goto"] = "pages/2_Ventas.py"
                    st.rerun()

        # ── Vendedores ────────────────────────────────────────────────────────
        ranked_v = (df_v[df_v["Vendedor"] != "Sin asignar"]
                    .groupby("Vendedor")["Importe_MXN"]
                    .sum().sort_values(ascending=False).index.tolist())
        hits_v = [v for v in ranked_v if q_up in v.upper()][:5]
        if hits_v:
            any_result = True
            _section_head("Vendedores")
            for i, vend in enumerate(hits_v):
                if st.sidebar.button(
                    _srch_label(vend), key=f"srch_v_{i}",
                    use_container_width=True,
                ):
                    st.session_state["drill_vendedor"] = vend
                    st.session_state["_goto"] = "pages/2_Ventas.py"
                    st.rerun()

    if not any_result:
        st.sidebar.caption("Sin resultados.")

    return query


def breadcrumb(items):
    """
    Renders a breadcrumb bar using st.columns + st.button (tertiary).

    items: list of (label, action, params)
      - action=None           → bold text (current page, last item)
      - action="pages/x.py"  → st.switch_page (cross-page navigation)
      - action={"clear": ["key1", ...]} → pops those session_state keys + st.rerun()
      - params: query_params dict, only used with page-path action

    Example:
        breadcrumb([
            ("Compras", {"clear": ["drill_proveedor"]}, None),
            ("DELMAN INTERNACIONAL", None, None),
        ])
    """
    if not items:
        return

    n = len(items)
    col_widths = []
    for i, (label, _, _) in enumerate(items):
        col_widths.append(max(1.0, len(label) * 0.13))
        if i < n - 1:
            col_widths.append(0.25)

    cols = st.columns(col_widths)
    col_idx = 0

    for i, (label, action, params) in enumerate(items):
        with cols[col_idx]:
            if i == n - 1:
                st.markdown(f"**{label}**")
            elif isinstance(action, dict):
                if st.button(label, key=f"bc_{i}_{label}", type="tertiary"):
                    for k in action.get("clear", []):
                        st.session_state.pop(k, None)
                    st.rerun()
            elif isinstance(action, str):
                if st.button(label, key=f"bc_{i}_{label}", type="tertiary"):
                    if params:
                        for k, v in params.items():
                            st.query_params[k] = v
                    st.switch_page(action)
            else:
                st.markdown(label)
        col_idx += 1

        if i < n - 1:
            with cols[col_idx]:
                st.markdown("›")
            col_idx += 1
