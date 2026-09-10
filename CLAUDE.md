# Lyon AG — Webapp de Dashboards

Webapp interactiva en Streamlit para procesar los archivos del SAE (Compras + Ventas) de Lyon AG, una imprenta industrial que opera desde la planta QUMA. Cliente principal: CONALITEG (~54% del revenue). El brief inicial completo del proyecto vive en `PROMPT_CLAUDE_CODE.md`.

## Stack

- **Python 3.10+** · **Streamlit ≥ 1.31** · **Plotly** · **pandas, openpyxl, xlrd**
- **BD:** SQLite local (`data/lyon.db`, autogenerado) por defecto. En la nube (Streamlit Cloud) usa **PostgreSQL/Supabase** vía `SUPABASE_DB_URL` env var o `st.secrets["supabase_db_url"]` — `core/database.py` abstrae ambos backends con la misma API (`_Conn`, placeholder `_PH`).
- El SAE se procesa localmente en cada sesión; no requiere internet salvo cuando la BD apunta a Supabase.

## Estructura del proyecto

```
core/         lógica reutilizable (ETL, plots, BD, navegación, catálogos, reporte HTML)
pages/        páginas de Streamlit (1_Compras … 6_Facturacion), todas visibles en el menú
data/         lyon.db (SQLite, autogenerado, en .gitignore)
docs/         planes y notas de diseño
muestras/     archivos de ejemplo del SAE / facturación para desarrollo
```

Módulos en `core/`: `etl_compras.py`, `etl_ventas.py`, `etl_facturacion.py`, `plots.py`, `database.py`, `navigation.py`, `catalogos.py`, `report.py`.

Los archivos `dashboard_compras_QUMA.py` y `dashboard_ventas.py` son **scripts de referencia** ya validados. Su lógica ETL y sus gráficos deben portarse a `core/` tal cual; no reinventar.

## Reglas no negociables

1. **No reinventes gráficos.** Los scripts de referencia tienen 7+ iteraciones de feedback del usuario encima (colores, márgenes, anotaciones, abreviaciones). Pórtalos como funciones puras que reciben DataFrame y devuelven `go.Figure`.
2. **El SAE NO se persiste.** Vive solo en `st.session_state.df_compras` y `st.session_state.df_ventas` durante la sesión. Cada upload reemplaza completamente. Lo mismo para archivos nuevos (`df_facturacion`, etc.).
3. **Solo lo capturado a mano persiste en la BD.** Tablas: `proveedores_clasificacion` (categoría por proveedor), `vendedor_cliente` (vendedor por cliente), `gastos_empresa` (gasto no-SAE por concepto y mes), `eventos` (bitácora). UPSERT por edición. Las anclas automáticas se aplican en runtime, no se guardan.
4. **Catálogo de categorías es CERRADO.** Son **18** opciones definidas en `core/catalogos.py` (`CATALOGO_CATEGORIAS`), incluyendo `Maquila Externa` y `Maquila de Destajo`. No agregar ni renombrar categorías sin permiso explícito.
5. **Prioridad de categorización:** usuario (BD) > ancla automática > "Pendiente clasificar" (`ETIQ_PENDIENTE`). El ancla de `INFOVITA` apunta a `Maquila Externa`.
6. **Validación por fases.** No avanzar a la siguiente fase sin aprobación explícita del usuario.

## Convenciones de código

- Cada gráfica de Plotly se define en `core/plots.py` como función pura: recibe DataFrame + parámetros, devuelve `go.Figure`. No hay `core/plots_detalle.py`.
- ETL puro en `core/etl_compras.py`, `core/etl_ventas.py`, `core/etl_facturacion.py`: sin dependencias de Streamlit, retornan `(df, warnings)` listos para renderizar. Detección de hoja por patrón (`_detectar_hoja`), no por nombre exacto.
- Constantes en `core/catalogos.py`: catálogo, anclas (`aplicar_ancla`), abreviaciones (`abreviar_cliente` está en `etl_ventas.py`), paleta de colores (`COLOR_LYON`, `PALETA_PRINCIPAL`, `PALETA_CATEGORIAS`), `label_mes`, `ESPANOL_MES`.
- BD en `core/database.py`: `init_db()`, `upsert_clasificacion()`, `get_clasificaciones()`, `delete_clasificacion()`, `upsert_vendedor_cliente()`, `bulk_upsert_gastos_empresa()`, `get_gastos_empresa_*()`, `log_evento()`, etc.
- Navegación, breadcrumbs y búsqueda global en `core/navigation.py`. También `render_periodo_filter(prefix, meses)` (filtro año/mes) y `render_sidebar_status()`.
- Reporte ejecutivo HTML autocontenido en `core/report.py` (`generate_report_html`).

## Patrones de Streamlit

- Preámbulo de cada página, en este orden: `st.set_page_config(layout="wide")` → `init_db()` → `inject_custom_css()` → `handle_pending_nav()` → `with st.sidebar: render_sidebar_search(); render_sidebar_status()` → `<h1>` con `COLOR_LYON` + un Material Symbol.
- Cada página tiene su **propio uploader**; los datos viven solo en `st.session_state` (`df_<x>`, `df_<x>_meta`).
- Operaciones lentas → `with st.spinner("…")`.
- Errores → `st.error()` con detalle claro, nunca silencioso.
- Clicks en gráficas → `st.plotly_chart(fig, on_select="rerun", selection_mode="points", key="...")`.
- **Drill-down inline (no páginas separadas):** se setea `st.session_state["drill_<algo>"] = valor` y `st.rerun()`. Al inicio de la página, si esa clave existe se renderiza la vista de detalle y se llama `st.stop()` antes del dashboard normal. El breadcrumb limpia esas claves. No se usa `st.query_params` para navegar.
- No se usa `@st.cache_data` en ningún lado. El ETL corre en cada rerun; los archivos del SAE son chicos.
- Gráficas siempre dentro de `st.container(border=True)`, con `st.caption` bajo el título explicando por qué importa el dato.
- Formato monetario: `f"${v/1e6:,.2f}M"`; porcentajes: `f"{p:.1f}%"`.
- Íconos del sidebar: se mapean por posición `li:nth-child(N)` en el CSS de `core/navigation.py` (~líneas 189-194). Home es `nth-child(1)`; cada página numerada corre el índice. Una página nueva al final solo agrega una regla; no rompe el mapeo previo.

## Cuándo pedir input al usuario

Pregunta antes de improvisar cuando:

- La especificación no cubre un caso UX concreto (¿qué pasa si el SAE viene con la hoja vacía? ¿qué orden default tienen los meses en el selector?).
- Detectas una decisión de diseño con consecuencias no triviales.
- Una librería se comporta diferente a lo documentado en este brief.

Prefiero contestar 5 preguntas que vivir con 5 decisiones improvisadas.

## Cómo correr

```bash
streamlit run app.py
```

Navegador abre en `http://localhost:8501`.

## Para respaldar los datos del usuario

Con SQLite local: copiar `data/lyon.db` a otra ubicación (archivo único). Con Supabase: el respaldo lo administra el proveedor.
