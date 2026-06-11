# Webapp Local Interactiva — Sistema de Dashboards Lyon AG

## 1. Contexto del negocio

Lyon AG es una imprenta industrial que opera exclusivamente desde la planta QUMA. Cliente principal: CONALITEG (gobierno, libros de texto, ~54% del revenue). Clientes comerciales: DELMAN INTERNACIONAL, GD COMERCIALIZADORA, PENGUIN RANDOM HOUSE, INFORMACION INTEGRAL 24/7, CHEDRAUI BRANDS, EDITORIAL PANINI, entre otros.

El área financiera/operativa procesa mensualmente dos archivos Excel del SAE:

- **Compras** (`compras_SAE_2026.xlsx`): facturas de proveedores. Volumen típico ~2,000 facturas / ~$120M MXN por 5 meses.
- **Ventas** (`Facturas_SAE.xls`): pedidos a clientes. Volumen típico ~700 pedidos / ~$140M MXN por 5 meses.

Estos archivos se procesan hoy en Google Colab con scripts standalone (incluidos en este proyecto como referencia). El usuario quiere migrar todo a una webapp **local e interactiva** que centralice ambos módulos, agregue una vista comparativa, persista las clasificaciones manuales de proveedores en BD, y permita **drill-down a páginas dedicadas por entidad** (proveedor, categoría, cliente, vendedor).

## 2. Objetivo de la webapp

Una webapp **local** (no nube) que el usuario corre en su laptop y le permite:

1. Subir el archivo de Compras → ver dashboard general → **hacer clic en cualquier proveedor, categoría o mes** para abrir una página dedicada con KPIs y gráficas propias.
2. Subir el archivo de Ventas → ver dashboard general → **hacer clic en cualquier cliente, vendedor o celda de heatmap** para abrir una página dedicada.
3. Con ambos archivos cargados, ver un dashboard Comparativo Compras vs Ventas.
4. **Clasificar manualmente proveedores** en categorías operativas, con persistencia en SQLite local.
5. Buscar globalmente por nombre (proveedor / cliente / vendedor) desde el sidebar.

El usuario subirá el **mismo archivo SAE actualizado** cada mes (no se guarda histórico de archivos). Lo único que persiste son las clasificaciones manuales de proveedores.

## 3. Stack tecnológico

- **Python 3.10+**
- **Streamlit ≥ 1.31** (necesario para `on_select` en plotly_chart y st.dataframe)
- **Plotly** (gráficos interactivos)
- **SQLite** (persistencia local)
- **pandas, numpy, openpyxl, xlrd** (ETL)

Sin servicios externos. Sin internet requerido. SQLite en archivo único para backup trivial.

## 4. Archivos de referencia adjuntos

En el directorio del proyecto encontrarás:

- **`dashboard_compras_QUMA.py`** — Lógica completa de Compras: ETL, 7 anclas automáticas, catálogo cerrado de 11 categorías, gráficos Plotly pulidos.
- **`dashboard_ventas.py`** — Lógica completa de Ventas: ETL (parseo de strings con coma de miles, fechas dd/mm/yyyy), abreviaciones de clientes (CONALITEG), 7+ visualizaciones Plotly.

**Reutiliza estos scripts al máximo.** Los gráficos ya tienen 7 iteraciones de feedback del usuario encima: colores, márgenes, anotaciones, abreviaciones. **No reinventes; porta tal cual** y solo refactoriza las firmas de las funciones para hacerlas reutilizables (recibir DataFrame y parámetros, devolver figura Plotly).

## 5. Estructura del proyecto

```
lyon_dashboard/
├── README.md
├── requirements.txt
├── run.bat                              # Windows
├── run.sh                               # macOS/Linux
├── app.py                               # entry point + Home + search global
├── pages/
│   ├── 1_📥_Compras.py                  # vista general Compras
│   ├── 2_💰_Ventas.py                   # vista general Ventas
│   ├── 3_⚖️_Comparativa.py             # vista comparativa
│   ├── _Proveedor.py                    # detalle de proveedor (oculto en menú)
│   ├── _Categoria.py                    # detalle de categoría (oculto)
│   ├── _Cliente.py                      # detalle de cliente (oculto)
│   └── _Vendedor.py                     # detalle de vendedor (oculto)
├── core/
│   ├── __init__.py
│   ├── etl_compras.py                   # ETL del SAE de compras
│   ├── etl_ventas.py                    # ETL del archivo de pedidos
│   ├── database.py                      # operaciones SQLite
│   ├── plots.py                         # generadores de figuras Plotly
│   ├── plots_detalle.py                 # gráficas específicas de páginas detalle
│   ├── catalogos.py                     # constantes
│   ├── navigation.py                    # helpers para query_params, breadcrumbs, search
│   └── exporters.py                     # generación de HTML descargable
├── data/
│   └── lyon.db                          # SQLite (autogenerado)
├── .gitignore
└── (scripts de referencia adjuntos)
    ├── dashboard_compras_QUMA.py
    └── dashboard_ventas.py
```

**Nota sobre páginas ocultas:** Streamlit muestra en el menú lateral todas las páginas de `pages/`. Para ocultar las de detalle, prefíjalas con `_` o usa `st.set_page_config(initial_sidebar_state="collapsed")` con `st.navigation` custom. Las páginas de detalle se acceden vía `st.switch_page()` o links HTML, nunca por el menú.

## 6. Modelo de datos (SQLite)

```sql
CREATE TABLE proveedores_clasificacion (
    proveedor_exacto_sae TEXT PRIMARY KEY,
    categoria            TEXT NOT NULL,
    notas                TEXT DEFAULT '',
    origen               TEXT NOT NULL DEFAULT 'usuario',  -- 'usuario' | 'ancla'
    fecha_creacion       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_modificacion   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_proveedores_categoria ON proveedores_clasificacion(categoria);

-- Opcional pero útil para debugging
CREATE TABLE eventos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tipo      TEXT NOT NULL,
    detalle   TEXT
);
```

**Sobre persistencia:**
- El SAE NO se guarda. Vive en `st.session_state.df_compras` y `st.session_state.df_ventas` durante la sesión.
- Solo las clasificaciones manuales persisten (con `origen='usuario'`).
- Las 7 anclas automáticas se aplican en runtime; si el usuario acepta una ancla la grabamos como `usuario`.

## 7. Especificación funcional de páginas generales

### 7.1 Home (`app.py`)

- Título: "Dashboards Lyon AG" con color corporativo `#1F4E79`.
- Tarjetas grandes de navegación a los 3 módulos.
- Indicadores globales: número de proveedores clasificados en BD, última modificación.
- **Búsqueda global en el sidebar** (presente en TODAS las páginas):
  ```
  🔍 [____________________________]
  ```
  Cuando el usuario tipea, debajo aparecen sugerencias agrupadas:
  - Proveedores que matchean (si hay df_compras cargado)
  - Clientes que matchean (si hay df_ventas cargado)
  - Vendedores que matchean
  - Categorías que matchean
  
  Cada sugerencia es clickable y lleva a la página de detalle correspondiente.

### 7.2 Página Compras (`pages/1_📥_Compras.py`) — vista general

**Flujo:**
1. Si no hay `df_compras` en session_state: mostrar `st.file_uploader` y procesar al subir.
2. Si ya hay datos: mostrar dashboard.
3. Filtros en sidebar:
   - **Meses** (`st.multiselect`, default: todos).
   - **Categorías** (`st.multiselect` con las 11 + "Pendiente clasificar", default: todas).
4. Resumen ejecutivo: gasto total, # facturas, ticket promedio/mediano, proveedores únicos, cobertura % por origen.
5. **Visualizaciones interactivas** (cada una con click handler):

| Gráfica | Click en… | Acción |
|---|---|---|
| Donut por categoría | rebanada de categoría | → `_Categoria.py?categoria=X` |
| Curva semanal | punto/área de un mes | filtra el dashboard a ese mes |
| Pareto Top 10 proveedores | barra de proveedor | → `_Proveedor.py?proveedor=X` |
| Top pendientes (barras grises) | barra de proveedor | → `_Proveedor.py?proveedor=X` |
| Top 10 facturas (tabla) | fila | modal con detalle de la factura |

6. **Sección "Clasificar Proveedores"** (tabla editable con `st.data_editor`):
   - Columnas: # | Proveedor (read-only) | Gasto | # Facturas | Cat. Sugerida (ancla, read-only) | **Categoría Validada** (dropdown editable) | **Notas** (texto libre)
   - El nombre del proveedor en la primera columna NO es clickable desde data_editor (limitación de Streamlit), pero junto a cada fila pon un pequeño botón "🔍" que abra la página de detalle del proveedor.
   - Cada edición de Categoría Validada o Notas dispara UPSERT inmediato a SQLite.
   - Color de fondo por origen: azul claro = usuario, verde claro = ancla, ámbar = pendiente.
   - Buscador encima de la tabla para filtrar por nombre.
   - Indicador grande de cobertura.
7. Botón "📥 Exportar reporte como HTML" que reproduce el output del script standalone.

### 7.3 Página Ventas (`pages/2_💰_Ventas.py`) — vista general

**Flujo similar a Compras.** Filtros sidebar: Meses, Vendedores (incluyendo "Sin asignar"), Clientes.

Resumen ejecutivo organizado en 5 secciones (igual al HTML del script de ventas).

**Visualizaciones interactivas:**

| Gráfica | Click en… | Acción |
|---|---|---|
| Donut Top 10 + Resto | rebanada de cliente | → `_Cliente.py?cliente=X` |
| Donut desglose del Resto | rebanada | → `_Cliente.py?cliente=X` |
| Curva semanal con pico | punto/mes | filtra el dashboard al mes |
| Pareto Top 10 clientes | barra | → `_Cliente.py?cliente=X` |
| Tabla del Resto (clientes 11+) | fila | → `_Cliente.py?cliente=X` |
| Ventas por Vendedor | barra | → `_Vendedor.py?vendedor=X` |
| Heatmap Cliente × Mes | celda | → `_Cliente.py?cliente=X&mes=YYYY-MM` |
| Top 10 pedidos | fila | modal con detalle del pedido |

Botón "📥 Exportar como HTML".

### 7.4 Página Comparativa (`pages/3_⚖️_Comparativa.py`)

**Pre-requisito:** ambos archivos cargados en la sesión. Si no, mensaje con botones a páginas de Compras y Ventas.

**Filtros sidebar sincronizados:** meses aplicados a ambos datasets.

**KPIs comparativos:**
- Ingresos (Ventas) / Egresos (Compras) / **Margen operativo bruto** / Ratio Compras/Ventas
- # Facturas vs # Pedidos / Ticket promedio comparado
- Top categoría de gasto / Top cliente

**Visualizaciones:**

| Gráfica | Click en… | Acción |
|---|---|---|
| Cascada del margen (Waterfall) | (sin drill-down en esta fase) | — |
| Tendencia mensual comparada (barras agrupadas) | barra de un mes | filtra TODAS las visualizaciones al mes |
| Curva acumulada Ventas vs Compras | (sin drill-down) | — |
| Top 10 Clientes \| Top 10 Proveedores (lado a lado) | barra de cliente | → `_Cliente.py` |
|  | barra de proveedor | → `_Proveedor.py` |
| Donut categorías Compras | rebanada | → `_Categoria.py` |

**Nota a documentar en pie de página:** el margen es **bruto operativo**, no neto fiscal. Pedidos de venta no necesariamente corresponden 1-a-1 con facturas de compra del mismo mes; hay desfase de cadena de valor. No inventar correlaciones.

## 8. Especificación funcional de páginas de detalle

Todas las páginas de detalle siguen el mismo patrón:

1. Leer parámetro de URL (`st.query_params`).
2. Validar que existan los datos en `st.session_state`. Si no:
   ```
   ⚠️ No hay datos cargados en la sesión.
   Para ver el detalle de [entidad] necesitas haber subido el archivo de [Compras/Ventas].
   [Botón: 📥 Ir a Compras / Ventas]
   ```
3. Si hay datos: renderizar la página.
4. **Breadcrumb arriba:** `Compras › DELMAN INTERNACIONAL` (links clickables).
5. **Filtro de meses** (multiselect en sidebar, default: todos).
6. Las gráficas y tablas de la página de detalle pueden tener sus propios drill-downs (transitivo).

### 8.1 `_Proveedor.py` — Detalle de Proveedor

URL: `?proveedor=DELMAN INTERNACIONAL, S.A. DE C.V.`

**Header:** nombre del proveedor + badge con categoría asignada (clickable → página de categoría) + indicador de origen (usuario/ancla/pendiente).

**Inline edit:** botón "✏️ Cambiar categoría" abre dropdown para reclasificar sin volver a la página general.

**KPIs:**
- Gasto total con este proveedor
- # facturas
- Ticket promedio / mediano
- Primera y última factura
- **Frecuencia:** días promedio entre facturas
- **Días desde última factura** (alerta visual si > 60)
- % que representa del gasto total

**Gráficas:**
1. Curva temporal de gasto (línea + área).
2. Histograma de tickets (distribución de tamaño de factura).
3. Comparación con otros proveedores de la misma categoría (mini-Pareto): "Eres el #2 de Sustratos (Papel)".

**Tabla:**
- Todas las facturas con este proveedor, ordenadas por fecha desc.
- Click en fila → modal con detalle de la factura.

### 8.2 `_Categoria.py` — Detalle de Categoría

URL: `?categoria=Sustratos (Papel)`

**Header:** nombre de la categoría + KPI principal (gasto total + %).

**KPIs:**
- Gasto total en la categoría
- # proveedores activos
- Ticket promedio
- % del gasto total
- Evolución mes a mes

**Gráficas:**
1. Pareto de proveedores dentro de la categoría (barras clickables → `_Proveedor.py`).
2. Curva temporal del gasto en la categoría.
3. Donut de concentración interna (¿qué proveedor pesa más dentro de la categoría?).

**Tabla:**
- Todos los proveedores de la categoría con métricas, clickables.

### 8.3 `_Cliente.py` — Detalle de Cliente

URL: `?cliente=COMISION NACIONAL DE LIBROS DE TEXTO GRATUITOS` o `?cliente=X&mes=2026-05`

**Header:** nombre del cliente (con abreviación visual si aplica) + ventas totales como KPI hero.

**KPIs:**
- Ventas totales con este cliente
- # pedidos
- Ticket promedio / mediano
- Primera y última venta
- **Frecuencia:** días promedio entre pedidos
- **Días desde último pedido**
- **Pendencias:** $ en Emitido + Rem.Parc. (lo que está facturado pero pendiente de remitir)
- Comisiones que ha generado
- Vendedor(es) que lo atienden

**Gráficas:**
1. Curva temporal de ventas con este cliente.
2. Pipeline por estatus (donut o barras: Remitido / Emitido / Parcial).
3. Distribución de pedidos por vendedor (si más de uno lo atiende, clickable → `_Vendedor.py`).
4. Histograma de tickets.

**Tabla — la "masa de playa" que pidió el usuario:**
- Todos los pedidos con este cliente, ordenados por fecha desc.
- Resaltar visualmente los pendientes (rojo suave si en Emitido > 30 días).
- Click en fila → modal con detalle del pedido.

### 8.4 `_Vendedor.py` — Detalle de Vendedor

URL: `?vendedor=Oscar Mejia`

**Header:** nombre del vendedor + ventas totales como KPI hero.

**KPIs:**
- Ventas totales
- # pedidos
- Ticket promedio
- # clientes únicos atendidos
- Comisiones generadas
- Pedidos por estatus (% Remitido / Emitido / Parcial)
- Pedido más grande

**Gráficas:**
1. Curva temporal de sus ventas.
2. Donut de sus clientes (concentración — clickable → `_Cliente.py`).
3. Heatmap cliente × mes (solo de sus clientes).
4. Comisiones acumuladas en el tiempo.

**Tabla:**
- Top clientes que atiende, ordenados por ventas, clickables → `_Cliente.py`.
- Todos sus pedidos del periodo (expandible).

## 9. Interactividad y navegación — la pieza crítica

### 9.1 Capturar clicks en gráficas Plotly

Streamlit ≥ 1.31 soporta:

```python
selection = st.plotly_chart(
    fig,
    on_select="rerun",
    selection_mode="points",
    key="donut_categorias_compras"
)
if selection and selection.get("selection", {}).get("points"):
    point = selection["selection"]["points"][0]
    categoria_clickeada = point["label"]  # o point["x"], depende del tipo de gráfica
    st.query_params["categoria"] = categoria_clickeada
    st.switch_page("pages/_Categoria.py")
```

Para cada gráfica clickable, debes:
1. Asignar una `key` única.
2. Usar `on_select="rerun"`.
3. Después de renderizar, revisar si hay selección y disparar la navegación.

### 9.2 Navegación con query_params

```python
# Setear parámetros antes de cambiar de página
st.query_params["proveedor"] = "DELMAN INTERNACIONAL, S.A. DE C.V."
st.switch_page("pages/_Proveedor.py")

# Leer en la página destino
proveedor = st.query_params.get("proveedor", None)
```

### 9.3 Compartir DataFrames entre páginas

```python
# En página de Compras al procesar upload:
st.session_state.df_compras = df_procesado
st.session_state.df_compras_meta = {"archivo": nombre, "uploaded_at": dt.now()}

# En página de detalle:
if "df_compras" not in st.session_state:
    st.warning("No hay datos cargados…")
    if st.button("📥 Ir a Compras"):
        st.switch_page("pages/1_📥_Compras.py")
    st.stop()
df = st.session_state.df_compras
```

### 9.4 Breadcrumbs

Implementa un helper en `core/navigation.py`:

```python
def breadcrumb(items):
    """items: lista de tuplas (texto, página o None)"""
    pieces = []
    for texto, pagina in items[:-1]:
        if pagina:
            pieces.append(f'<a href="#" onclick="...">{texto}</a>')
        else:
            pieces.append(texto)
    pieces.append(f"<b>{items[-1][0]}</b>")
    st.markdown(" › ".join(pieces), unsafe_allow_html=True)
```

Streamlit no soporta nativamente links que naveguen entre páginas con click handler de JS, así que la forma idiomática es usar `st.columns` con `st.button` chiquitos:

```python
cols = st.columns([1, 0.2, 2, 0.2, 3])
with cols[0]:
    if st.button("Compras", type="tertiary"):
        st.switch_page("pages/1_📥_Compras.py")
with cols[1]:
    st.markdown("›")
with cols[2]:
    if st.button("Sustratos (Papel)", type="tertiary"):
        st.query_params["categoria"] = "Sustratos (Papel)"
        st.switch_page("pages/_Categoria.py")
with cols[3]:
    st.markdown("›")
with cols[4]:
    st.markdown("**DELMAN INTERNACIONAL**")
```

Encapsula esto en `breadcrumb()` para reutilizar.

### 9.5 Búsqueda global en el sidebar

`core/navigation.py` debe exponer una función `render_sidebar_search()` que:

1. Muestra un `st.text_input("🔍 Buscar")`.
2. Al tipear (mínimo 3 caracteres), busca en los DataFrames cargados:
   - `df_compras["Proveedor"]` (substring match, case insensitive)
   - `df_ventas["Cliente_Nombre"]` y `df_ventas["Vendedor"]`
   - Lista de categorías
3. Muestra hasta 10 resultados agrupados por tipo, cada uno como `st.button` que dispara navegación.

Llama esta función al inicio de cada página dentro de un `with st.sidebar:`.

### 9.6 Modales para detalle de factura/pedido

Streamlit no tiene modales nativos, pero `st.dialog` (1.31+) hace eso:

```python
@st.dialog("Detalle del pedido")
def mostrar_detalle_pedido(pedido_dict):
    st.write(f"**Clave:** {pedido_dict['Clave']}")
    st.write(f"**Fecha:** {pedido_dict['Fecha']:%d-%b-%Y}")
    st.write(f"**Cliente:** {pedido_dict['Cliente_Nombre']}")
    # … todos los campos
    if st.button("Cerrar"):
        st.rerun()

# Invocar:
if selection_de_tabla:
    pedido = df.loc[selection_de_tabla[0]].to_dict()
    mostrar_detalle_pedido(pedido)
```

## 10. Catálogos y constantes (`core/catalogos.py`)

```python
CATALOGO_CATEGORIAS = [
    "Sustratos (Papel)", "Pre-prensa y Químicos", "Encuadernación",
    "Insumos de Producción", "Mantenimiento y Refacciones", "Maquila",
    "Logística / Fletes", "Almacenaje y Renta", "Limpieza y Sanitarios",
    "Servicios Profesionales", "Otros / Sin clasificar",
]

ETIQ_PENDIENTE = "Pendiente clasificar"

def aplicar_ancla(proveedor):
    if not proveedor: return None
    p = str(proveedor).upper()
    if "DELMAN INTERNACIONAL" in p:                          return "Sustratos (Papel)"
    if "SANCHEZ S.A"          in p:                          return "Pre-prensa y Químicos"
    if "LIBER ARTS"           in p:                          return "Encuadernación"
    if "JAQUELINA REYES"      in p or "GUTMAN BROS" in p:    return "Mantenimiento y Refacciones"
    if "VIGMAN GRAPHICS"      in p:                          return "Almacenaje y Renta"
    if "INFOVITA"             in p:                          return "Maquila"
    return None

ABREVIACIONES = {
    "COMISION NACIONAL DE LIBROS DE TEXTO GRATUITOS": "CONALITEG",
}

ESTATUS_VALIDOS_COMPRAS = ["Emitida", "Dev.Parc.", "Dev. Parcial"]
ESTATUS_VALIDOS_VENTAS  = ["Remitido", "Emitido", "Rem.Parc."]
```

## 11. Paleta de colores

```python
COLOR_LYON      = "#1F4E79"
COLOR_VENTAS    = "#548235"
COLOR_COMPRAS   = "#C00000"
COLOR_PICO      = "#C00000"

PALETA_PRINCIPAL = [
    "#1F4E79", "#C00000", "#E97132", "#7030A0", "#548235",
    "#2E75B6", "#BF8F00", "#A02B93", "#385723", "#806000",
]

COLOR_PENDIENTE = "#9E9E9E"
COLOR_VALIDADO  = "#DCE7F5"
COLOR_ANCLA     = "#E6F2D8"
COLOR_AMBAR     = "#FFF8E1"
```

## 12. Plan de implementación incremental

Implementa por fases. Después de cada una, valida que funcione antes de pasar a la siguiente. **Pídeme aprobación al final de cada fase.**

### Fase 1 — Setup base
- Estructura de directorios + `requirements.txt` + scripts de inicio + README.
- SQLite schema y `core/database.py`.
- `core/catalogos.py`.
- `app.py` con Home y navegación a las 3 páginas vacías.
- `core/navigation.py` con esqueleto de búsqueda global (sin resultados aún).

**Criterio:** `streamlit run app.py` arranca y se puede navegar.

### Fase 2 — Compras (vista general sin clasificación)
- Port del ETL: `core/etl_compras.py`.
- Port de gráficos: `core/plots.py`.
- Página Compras con upload, filtros básicos (meses), KPIs, todas las gráficas.
- **Sin drill-down todavía.** Solo gráficas estáticas.

**Criterio:** subir SAE y ver dashboard completo.

### Fase 3 — Ventas (vista general sin drill-down)
- Port del ETL: `core/etl_ventas.py`.
- Port de las 7+ gráficas a `core/plots.py`.
- Página Ventas con upload, filtros, KPIs y gráficas.

**Criterio:** subir Pedidos y ver dashboard completo.

### Fase 4 — Sistema de Clasificación de Proveedores
- Tabla editable en Compras con `st.data_editor`.
- Persistencia SQLite con UPSERT por edición.
- Indicador de cobertura con desglose por origen.

**Criterio:** clasificar 3 proveedores → refrescar browser → volver a subir SAE → las 3 clasificaciones persisten.

### Fase 5 — Drill-down y páginas de detalle
- `pages/_Proveedor.py`, `_Categoria.py`, `_Cliente.py`, `_Vendedor.py`.
- `core/plots_detalle.py` con gráficas específicas.
- Capturar clicks en gráficas y tablas de las páginas generales.
- Implementar breadcrumbs.
- Modales para detalle de factura/pedido individual.

**Criterio:**
1. Desde Compras, clickear DELMAN en el Pareto → abre página de DELMAN con sus KPIs.
2. Desde la página de DELMAN, clickear su badge de categoría → abre página de categoría.
3. Desde Ventas, clickear celda del heatmap (CONALITEG, Mayo) → abre página de CONALITEG filtrada a Mayo.
4. Breadcrumbs visibles y funcionales en cada página de detalle.

### Fase 6 — Búsqueda global y polish
- Búsqueda funcional en el sidebar con resultados clickables.
- Botones "Exportar como HTML" en Compras y Ventas.
- Manejo elegante de errores y casos edge.
- Validaciones de upload.

### Fase 7 — Página Comparativa
- Lógica para combinar datasets en sesión.
- Cascada, tendencia mensual, curva acumulada.
- Drill-down básico: click en barra mensual filtra la página.
- Click en top clientes / top proveedores → páginas de detalle.

**Criterio:** con ambos archivos cargados, comparativa muestra margen correcto y los drill-downs funcionan.

## 13. Criterios de aceptación globales

- `streamlit run app.py` arranca sin errores.
- Los 3 módulos principales + 4 páginas de detalle funcionan.
- Las clasificaciones persisten entre sesiones y entre re-uploads.
- Los reportes HTML exportados son equivalentes a los scripts standalone.
- La interactividad de drill-down funciona en todas las gráficas mencionadas.
- Breadcrumbs siempre visibles en páginas de detalle.
- Búsqueda global funcional desde sidebar.
- Sin dependencias de servicios externos.
- Manejo de errores con mensajes útiles (`st.error`, `st.warning`).

## 14. Notas de implementación

- **No reinventes gráficos.** Los scripts de referencia están pulidos tras varias iteraciones; pórtalos tal cual.
- **session_state es la columna vertebral.** Todos los DataFrames procesados y filtros deben vivir ahí para que las páginas de detalle los reciban sin re-upload.
- **Wide layout.** `st.set_page_config(layout="wide")` en cada página.
- **Sidebar consistente.** Búsqueda global + estado de la BD + archivos cargados, en todas las páginas. Encapsula en `core/navigation.py` y llama desde cada página.
- **Spinners.** `with st.spinner("Procesando…")` para operaciones >1s.
- **Errores de upload.** Si falta columna del SAE, `st.error()` con detalle.
- **Pregunta cuando dudes.** Antes de improvisar UX o estructura, pregúntame.
- **Cuidado con `on_select` de plotly_chart.** Requiere `key` única por gráfica y manejo cuidadoso del rerun para no entrar en loop. Si una página tiene 5 gráficas clickables, prueba cada una en aislamiento primero.
- **`st.switch_page` con query_params.** Setea `st.query_params["key"] = value` ANTES de llamar `st.switch_page("pages/...")`.
- **Páginas ocultas en el menú.** Prefíjalas con `_` (Streamlit las oculta del menú automático) o construye navegación manual con `st.navigation`.

## 15. Cómo correr la app

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
streamlit run app.py
```

El navegador se abre en `http://localhost:8501`.

Para respaldar las clasificaciones: copiar `data/lyon.db`.

## 16. Empieza por…

Empieza por **Fase 1 (Setup base)**. Confirma conmigo la estructura de archivos y el esquema de BD antes de implementar ETL o UI. Una vez aprobada la base, pasamos a Fase 2.

**Antes de cada fase nueva, valida la anterior conmigo.** No avances sin aprobación.

Si en cualquier punto tienes dudas sobre el negocio, sobre UX, o ves una mejor forma de implementar algo no especificado aquí, pregúntame. Conozco el contexto operativo de Lyon AG y prefiero contestar 5 preguntas que vivir con 5 decisiones improvisadas.
