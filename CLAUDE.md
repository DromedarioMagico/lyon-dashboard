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
refs_conta/   archivos adicionales de ejemplo que manda Contabilidad (balanza, CFDI) —
              cubiertos por la regla *.xlsx de .gitignore, no hace falta una entrada aparte
```

Módulos en `core/`: `etl_compras.py`, `etl_ventas.py`, `etl_facturacion.py`, `etl_contabilidad.py`, `etl_balanza.py`, `etl_cfdi.py`, `conciliacion.py`, `cruce_ventas.py`, `plots.py`, `database.py`, `navigation.py`, `catalogos.py`, `report.py`.

Los archivos `dashboard_compras_QUMA.py` y `dashboard_ventas.py` son **scripts de referencia** ya validados. Su lógica ETL y sus gráficos deben portarse a `core/` tal cual; no reinventar.

## Reglas no negociables

1. **No reinventes gráficos.** Los scripts de referencia tienen 7+ iteraciones de feedback del usuario encima (colores, márgenes, anotaciones, abreviaciones). Pórtalos como funciones puras que reciben DataFrame y devuelven `go.Figure`.
2. **Ningún archivo subido se persiste.** El SAE vive en `st.session_state.df_compras` / `df_ventas`, la facturación en `df_facturacion`, el libro contable en `df_contabilidad`, la balanza de comprobación en `df_balanza` y los reportes CFDI (ventas/notas de crédito) en `df_cfdi`. Todos se re-suben en cada sesión; cada upload reemplaza completamente. **Sin excepciones.**
3. **Solo se guardan las DECISIONES del usuario:** `proveedores_clasificacion` (categoría por proveedor), `vendedor_cliente` (vendedor por cliente), `cuentas_contables` (nombre, categoría, naturaleza y trato por cuenta contable) y `eventos` (bitácora). UPSERT por edición. Las anclas automáticas se aplican en runtime, no se guardan.
   **No hay tabla de gastos.** El Gasto de Empresa se calcula al vuelo desde el libro de la sesión más el catálogo, con `conciliacion.gasto_empresa_por_periodo()` / `gasto_empresa_por_concepto()`. Nada derivado de un archivo que no se persiste debe persistirse: un total guardado de un libro que ya no está cargado sería un número sin respaldo. `contabilidad_movimientos` y `gastos_empresa` existieron y se eliminan en `init_db()` (`_migrar_quitar_tablas_derivadas`).
4. **Catálogo de categorías es CERRADO.** Son **19** opciones definidas en `core/catalogos.py` (`CATALOGO_CATEGORIAS`), incluyendo `Maquila Externa`, `Maquila de Destajo` y `Nómina` (esta última solo para la cuenta contable `6002-000-00000`). No agregar ni renombrar categorías sin permiso explícito. **Una categoría nueva va SIEMPRE al final, antes del centinela `Otros / Sin clasificar`:** `PALETA_CATEGORIAS` asigna color por posición, así que insertar a media lista recolorea todo lo que sigue.
5. **Prioridad de categorización:** usuario (BD) > ancla automática > "Pendiente clasificar" (`ETIQ_PENDIENTE`). El ancla de `INFOVITA` apunta a `Maquila Externa`.
6. **Validación por fases.** No avanzar a la siguiente fase sin aprobación explícita del usuario.

## Convenciones de código

- Cada gráfica de Plotly se define en `core/plots.py` como función pura: recibe DataFrame + parámetros, devuelve `go.Figure`. No hay `core/plots_detalle.py`.
- ETL puro en `core/etl_compras.py`, `core/etl_ventas.py`, `core/etl_facturacion.py`, `core/etl_contabilidad.py`: sin dependencias de Streamlit, retornan `(df, warnings)` listos para renderizar. Detección de hoja por patrón (`_detectar_hoja`), no por nombre exacto.
- **Conciliación Contabilidad ↔ SAE** en `core/conciliacion.py` (tampoco depende de Streamlit). La llave de cruce es el **nombre de proveedor normalizado** (`normalizar_proveedor`): no hay RFC ni clave de proveedor en ninguno de los dos sistemas. Estados: `En SAE` (mismo proveedor y mes) · `Fuera de SAE` (proveedor que nunca aparece) · `Por revisar` (proveedor del SAE en otro mes) · `Mes sin SAE` (el archivo de Compras no cubre ese mes) · `Sin comparar` (Compras no cargado). **Solo `Fuera de SAE` con cuenta marcada `Gasto operativo` cuenta** como Gasto de Empresa; los demás no, porque el dato no alcanza para afirmar que el gasto no pasó por compras y contarlo duplicaría lo que Compras ya muestra. `Trato` (`Auto` / `Siempre GE` / `Nunca GE`) permite anular el cruce por cuenta, pero nunca la naturaleza.
- **Ninguna cuenta contable cuenta hasta que el usuario la clasifica.** Nace `Sin clasificar` y no entra al costo ni al margen. Es decisión explícita del usuario: no se adivina naturaleza por prefijo de cuenta (hay un botón que lo propone, pero lo presiona el usuario). Toda pantalla que muestre gasto contable debe mostrar las tres cifras juntas (`Gasto operativo` · `No operativo` · `Sin clasificar`) — un total parcial sin su pendiente al lado es un número engañoso.
- Las páginas leen el libro contable con `conciliacion.contabilidad_de_sesion()`, que ya lo concilia contra Compras y le aplica el catálogo. No leas `st.session_state.df_contabilidad` directo salvo para saber si está cargado.
- **El desglose de Gasto de Empresa agrupa por `Categoria`, no por `Cuenta_Nombre`.** `conciliacion.gasto_empresa_por_concepto()` y el waterfall de Facturación agrupan por Categoría a propósito: es el bucket que el usuario arma (p. ej. varias cuentas bajo "Nómina") y debe verse reflejado en las gráficas. La excepción es el detalle "libro contable agrupado por cuenta" de Gastos de Empresa, que sí es por cuenta individual porque su propósito es auditoría, no composición.
- **`st.caption`/`st.markdown`/`st.info` con DOS O MÁS `$` literales en el mismo bloque rompen:** Streamlit interpreta un par de `$` como delimitador de LaTeX y renderiza como fórmula todo lo que hay entre ellos (se come `**negritas**` y espacios). Escapa cada `$` como `\$` en cualquier texto que combine más de un monto en la misma llamada.
- **La balanza de comprobación** (`core/etl_balanza.py`) es jerárquica: una cuenta de `Nivel` 1 ("mayor") ya es la suma de sus cuentas hijas. Cualquier total debe filtrar `Nivel == NIVEL_MAYOR` (usar `totales_por_mayor()`, nunca sumar el df crudo) o duplica el gasto. Los bloques de mes se detectan por encabezado, no por posición fija — la balanza crece una columna cada mes.
- **Gastos de Empresa acepta varios archivos en un solo uploader** (`accept_multiple_files=True`) y los rutea por estructura, no por nombre: prueba `cargar_contabilidad` → `cargar_balanza` → `cargar_cfdi` en orden y se queda con el primero que no levante `ValueError`. `core/etl_cfdi.py` sirve tanto el reporte de Ventas como el de Notas de Crédito (mismas 15 columnas, se distinguen por `Tipo_Doc`); si llegan los dos en la misma carga se concatenan en un solo `df_cfdi`.
- **El cuadre balanza-vs-libro** (`conciliacion.cuadre_balanza_vs_libro`) no corrige nada, solo expone el hueco con la cifra exacta — nunca decide en silencio cuál fuente tiene razón. "Gasto que el libro nunca manda" (p. ej. depreciación/amortización) se detecta **por patrón** (`Libro == 0` en todos los periodos comparados), no por código de cuenta a la fuerza, para que se generalice sin tocar código si aparece otra cuenta así en el futuro. Ese gasto se muestra pero **no** entra al Costo Operativo ni al Margen — es una cuenta que no puede cruzarse contra el SAE (nunca aparece en el libro), así que forzarla dentro rompería la regla de "solo `Fuera de SAE` cuenta".
- **Cruce Pedido (SAE) ↔ Factura (CFDI)** en `core/cruce_ventas.py` (sin Streamlit). Ni el SAE ni el CFDI traen el folio del otro sistema, pero ambos capturan por separado la orden de compra del cliente (`Su pedido` / `Su_Pedido`) — la llave de cruce es **(Cliente_Codigo, número de OC)** extraído con `normalizar_oc()`, nunca la OC sola (son números chicos que colisionarían entre clientes). Estados: `Facturado` · `Sin factura` (tiene OC, dentro de rango, ninguna factura la referencia — el único bucket accionable) · `Sin OC` (no hay documento con el que amarrar; es normal, no es alarma — hay clientes que no emiten OC) · `Fuera de rango` (el pedido cae en un mes que el CFDI no cubre; sin este guard, todo pedido anterior al periodo del CFDI se vería como "sin factura") · `Sin comparar` (CFDI no cargado). Un cliente puede reusar la misma OC en pedidos distintos o consolidar varias OC viejas en un pedido nuevo: el módulo cuenta el monto facturado completo en cada pedido que comparte esa OC ("el dinero es real, solo la fecha de origen es ambigua") pero excluye esos pares de la mediana de `Dias_Ciclo` cuando la factura queda fechada antes que el pedido. Consecuencia visible: sumado a nivel periodo, `Facturado_MXN` puede rebasar ligeramente a `Subtotal_MXN` de los pedidos — `plot_embudo_facturacion` ya lo maneja (relabelea la barra como "Ajuste (OC compartida)" en vez de mostrar un "sin facturar" negativo).
- **Ventas mide con o sin IVA según un switch** (`st.session_state["vta_base"]`, radio en el sidebar de `pages/2_Ventas.py`). El truco para no reescribir las gráficas ya validadas: alias de columna, `df.assign(Importe_MXN=df["Subtotal_MXN"])` cuando el switch está en "Sin IVA" (mismo patrón que ya usa `pages/6_Facturacion.py` para el Pareto). Los bloques que dependen del cruce pedido↔factura (embudo, remitido sin facturar, ciclo, cliente pedido-vs-facturado) **siempre miden sin IVA**, independientemente del switch — es la base comparable contra Facturación y CFDI, y cada uno de esos bloques lo rotula explícitamente en su caption.
- Constantes en `core/catalogos.py`: catálogo, anclas (`aplicar_ancla`), abreviaciones (`abreviar_cliente` está en `etl_ventas.py`), paleta de colores (`COLOR_LYON`, `PALETA_PRINCIPAL`, `PALETA_CATEGORIAS`), `label_mes`, `ESPANOL_MES`.
- BD en `core/database.py`: `init_db()`, `upsert_clasificacion()`, `get_clasificaciones()`, `delete_clasificacion()`, `upsert_vendedor_cliente()`, `get_cuentas_contables()`, `bulk_upsert_cuentas_contables()`, `log_evento()`, etc. Escrituras masivas vía `_Conn.executemany()` (agrupa en pocos round-trips; contra Postgres remoto un `execute` por fila es la diferencia entre segundos y minutos).
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

**Ojo con lo que contiene ese archivo.** `data/lyon.db` guarda nombres reales de proveedores y clientes. No guarda montos: ni el SAE ni el libro contable se persisten. Aun así está en `.gitignore` (igual que `*.xlsx` y `muestras/`) y **no debe commitearse nunca**. Con backend Supabase esos datos salen de la máquina del usuario.
