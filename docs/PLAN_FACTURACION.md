# Facturación en lyon_dashboard — cerrar el tramo pedido → factura

## Context

`lyon_dashboard` cuenta hoy una historia clara: **compras contra pedidos**, con desglose de proveedores
y desempeño de vendedores. Esa historia no se toca.

El problema es dónde termina. El embudo comercial se corta en el pedido del SAE, y el análisis de
absorción arranca en la OP. El tramo intermedio no tiene dueño:

```
pedido (SAE) ──────► factura ──────► contabilidad
      ▲                  ▲                 ▲
lyon_dashboard      SIN DUEÑO         BI Consultoría
```

`Facturación AGOSTO 2026 - LYON.xlsx` es exactamente ese tramo. Y `5_Gastos_de_Empresa` ya existe en
la app, con su tabla en BD, pero **está vacía** — así que `3_Comparativa` calcula un margen operativo
que hoy es idéntico al bruto.

**Decisión de alcance: el análisis de absorción NO se integra.** Es otra unidad de análisis (la OP,
no el documento) y otra audiencia (Dirección, no comercial). Traerlo duplicaría una herramienta que
ya funciona. Este plan no lo toca ni lo referencia en los cálculos.

---

## Por qué vale la pena

**1. Las fugas no las ve nadie.** Agosto tuvo **$1,065,778 en penalizaciones y descuentos**, de los
cuales **$936,756 son de CONALITEG** (a tasa 0 %). Ocurren después del pedido y antes de la factura:
ni el SAE ni la absorción las registran.

**2. Hay $3,311,308 en remisiones sin facturar** (76 documentos), con anomalías dentro: una remisión
de enero marcada `*** REVISAR ***` y nueve fechadas el 2026-09-01 dentro del archivo de agosto.

**3. Facturación es la pieza que permite triangular.** Hoy solo se puede comparar SAE contra
contabilidad, y quedan muy lejos. Facturación va en medio:

| Ene–Jun 2026 | Importe |
|---|---:|
| Pedidos SAE (sin IVA) | 146,443,816 |
| **Facturado** (hoja `HISTORICO`) | **140,749,313** |
| Ventas netas según BI | 148,948,567 |

Conversión pedido→factura **96.1 %** — un KPI que no existe hoy. Y la diferencia contra BI (~$8.2 M)
es una pregunta nueva y contestable, no un misterio de $43 M.

**4. El segmento es una lente que la app no tiene.** `HISTORICO` clasifica el año en PRIVADA / FILIAL
/ GOBIERNO / PRIVADA-GOB / VARIOS. Hoy DELMAN ($14.96 M en 2026, todo FILIAL) está enterrado como un
cliente más dentro de Ventas.

---

## Alcance

### A. Nueva página `pages/6_Facturacion.py`

Continuación del embudo existente, con el mismo elenco (clientes, meses) y el mismo lenguaje visual.

**Llave de cruce disponible y verificada:** el campo `Cliente` de facturación es un **código numérico
que coincide con el campo `Cliente` de `Pedidos SAE.xls`** (18=DELMAN, 270=GD BAJIO, 287=PENGUIN,
307=CHEDRAUI, 311=INFORMA A PUEBLA, 312=INFO INTEGRAL 24/7, 336=GD EXPO COLCHONES…). Permite cruzar
**cliente × mes**. No permite cruzar documento a documento — facturación no trae pedido ni UUID.

Cinco bloques:

1. **Embudo del periodo** — Pedidos SAE (sin IVA) → Facturado → Pendiente por facturar, con el % de
   conversión. Tres KPIs y un waterfall.
2. **Facturación por segmento** — barras apiladas por mes del año completo, desde `HISTORICO`.
3. **Fugas** — penalizaciones y descuentos por cliente y mes, desde `DEV Y DESC`. Separar tasa 0 %
   (CONALITEG) del resto.
4. **Pendiente por facturar** — las 76 remisiones con antigüedad, marcando las que caen fuera del mes.
5. **Cliente: pedido vs facturado** — tabla cruzada por código de cliente y mes, con la brecha.

**Regla de lectura, visible en pantalla:** Ventas muestra **pedidos con IVA**; esta página muestra
**facturas sin IVA**. Son dos etapas distintas, no dos versiones del mismo número. El bloque 1 lleva
los pedidos a base sin IVA para que el embudo sea comparable.

### B. Importación masiva en `pages/5_Gastos_de_Empresa.py`

No es página nueva: es un uploader en la que ya existe.

El usuario limpia y consolida los `info_contabilidad/GASTOS *.xlsx` bajo su propio criterio y produce
**un solo archivo** con el formato de la tabla que ya está en BD:

| Columna | Tipo | Ejemplo |
|---|---|---|
| `concepto` | texto | `Nómina operativa` |
| `periodo` | `YYYY-MM` | `2026-08` |
| `monto_mxn` | número | `2854648.62` |
| `notas` | texto, opcional | `incluye IMSS e INFONAVIT` |

La página lee el archivo, muestra un preview con el diff contra lo ya guardado, y aplica con el
`bulk_upsert_gastos_empresa()` que ya existe. Sin parser por mes.

**Por qué no se programa un parser de los GASTOS:** los nombres de hoja cambian cada mes
(`DB_LIMPIA` / `Clean_DB` / `BD_CLEAN`, y abril no tiene), los de columna también
(`CONCEPTO` / `Proveedor` / `PROVEEDOR/CONCEPTO`), hay filas de total embebidas que duplican los
importes, y **`Hoja1` está congelada en junio: md5 idéntico en los archivos de junio, julio y agosto.**
El criterio humano es más confiable que cualquier adaptador aquí.

**Efecto secundario, gratis:** al llenarse `gastos_empresa`, el `Margen_Operativo` y el waterfall de
`3_Comparativa` se encienden por primera vez, sin tocar esa página.

### Fuera de alcance

- Integrar el análisis de absorción. Se queda como herramienta de Dirección.
- Cruce documento a documento pedido↔factura: facturación no trae pedido ni UUID. Además la captura
  de `Su pedido` en el SAE se abandonó en junio 2026 (ENE 27, ABR 33, MAY 33, **JUN 2, JUL 0, AGO 0**).
  Se documenta como solicitud interna; el cruce cliente×mes cubre el embudo mientras tanto.
- Tocar `1_Compras`, `2_Ventas` o `3_Comparativa`.

---

## Qué pedir para que la sección rinda completa

Con **solo el archivo de agosto** ya funcionan: el segmento del año completo (bloque 2, sale de
`HISTORICO`), y los bloques 1, 3, 4 y 5 para agosto.

Pidiendo **`Facturación <MES> 2026 - LYON.xlsx` de enero a julio**, en el mismo formato, se obtiene la
serie completa del año en los cinco bloques: fugas mensuales, evolución del pendiente por facturar y
conversión pedido→factura mes a mes.

Es el mismo archivo que ya generan; no hay que pedir nada nuevo, solo los meses anteriores.

---

## Implementación

**`core/etl_facturacion.py`** (nuevo) — sin dependencias de Streamlit, como `etl_compras.py`.
Una función por hoja; **cada una recorta su fila de total embebida**, que es el problema recurrente:

```python
cargar_facturas(f)    -> (df, warnings)  # header=3; corta en la 1ª fila con FECHA nula (idx 108)
cargar_historico(f)   -> df              # header=2; matriz segmento×mes -> formato largo
cargar_dev_desc(f)    -> df              # header=2; solo filas de detalle (3-7)
cargar_remisiones(f)  -> df              # header=3; corta idx 77; avisa de fechas fuera del mes
cargar_resumen(f)     -> df              # header=2; solo filas 3-16
```

Columnas derivadas siguiendo la convención existente: `_Mes`, `Subtotal_MXN`, `IVA_MXN`,
`Importe_MXN`, `Cliente_Display` (reutilizar `abreviar_cliente()` de `etl_ventas.py`).

**`core/plots.py`** (extender, funciones puras `df -> go.Figure`, `template="plotly_white"`):
`plot_embudo_facturacion` · `plot_facturacion_segmento` · `plot_fugas_cliente` ·
`plot_aging_remisiones` · `plot_pedido_vs_facturado`

**`core/navigation.py`** — los íconos del sidebar se mapean por `li:nth-child(N)` (líneas 189-194).
`6_Facturacion.py` queda al final, así que **no rompe el mapeo existente**; solo hay que agregar:

```css
[data-testid="stSidebarNavItems"] li:nth-child(7) a::before { content: "request_quote"; }
```

**Convenciones a respetar** (del código real, no del CLAUDE.md):
preámbulo `set_page_config(layout="wide")` → `init_db()` → `inject_custom_css()` →
`handle_pending_nav()` → sidebar → `<h1>` con `COLOR_LYON` + Material Symbol · uploader propio, datos
solo en `st.session_state` (`df_facturacion`, `df_facturacion_meta`) · `_kpi()` local copiado ·
`render_periodo_filter("fac", meses)` con prefijo nuevo · gráficas dentro de
`st.container(border=True)` · formato `f"${v/1e6:,.2f}M"` y `f"{p:.1f}%"` · `st.caption` bajo cada
título explicando por qué importa.

---

## Verificación

```powershell
cd lyon_dashboard; .\.venv\Scripts\streamlit run app.py
```

Cargar `Facturación AGOSTO 2026 - LYON.xlsx` en la página nueva y confirmar contra estas cifras, ya
verificadas contra el archivo:

| Control | Esperado |
|---|---:|
| Facturas de agosto | **107** (no 108 — se recorta la fila de total) |
| Subtotal agosto | 9,424,794.39 |
| IVA agosto | 1,507,967.10 |
| Devoluciones y descuentos | 1,065,778.14 |
| — de los cuales CONALITEG, tasa 0 % | 936,755.82 |
| Facturación neta agosto | 8,359,016.25 |
| Remisiones pendientes | 76 filas · 2,854,575.63 sin IVA |
| Total 2026 (`HISTORICO`) | 191,944,219.94 |
| Clientes distintos en agosto | 14 |
| Tasa de IVA en el detalle | 16 % en el 100 % de los renglones |

Cruces que deben cerrar:

- `RESUMEN` por cliente (14 filas) = detalle de facturas agrupado por `Cliente` → **al peso**.
- Facturación bruta − dev. y desc. = neta: `9,424,794.39 − 1,065,778.14 = 8,359,016.25` ✓
- Columna `AGOSTO` de `HISTORICO` = 8,359,016.25 ✓
- Conversión ene–jun contra pedidos SAE sin IVA: **140,749,313 / 146,443,816 = 96.1 %**

En `5_Gastos_de_Empresa`: importar un archivo de prueba con dos periodos, verificar que el preview
muestra el diff correcto, que `bulk_upsert_gastos_empresa` no duplica al reimportar el mismo archivo
(PK `concepto+periodo`), y que `3_Comparativa` pasa a mostrar `Margen_Operativo < Margen_Bruto`.

---

## Anexo — estructura de `Facturación <MES> 2026 - LYON.xlsx`

Verificado sobre el archivo de agosto. Los índices de fila son posición en el DataFrame **después**
de aplicar el `header` indicado.

### ⚠ Tres trampas que rompen cualquier parser ingenuo

1. **El nombre de la hoja lleva el mes**: `FACTURAS AGOSTO 2026`. Detectar por patrón
   (`startswith("FACTURAS")`), no por nombre exacto — igual que hace `_detectar_hoja()` en
   `core/etl_compras.py`. Aplica también a `GASTOS AGOSTO` en los archivos de contabilidad.
2. **Dos nombres de columna llevan el mes**: `Vtas del 01 al  De 31 AGOSTO 2026` (con doble espacio
   en `al  De`) y `Del 01 al 31 de AGOSTO 2026`. **Leer esas por posición, nunca por nombre.**
3. **Cada hoja trae su fila de total dentro del rango de datos.** Índices exactos abajo.

### Hojas

| Hoja | `header=` | Filas de datos | Fila de total | Columnas |
|---|---|---|---|---|
| `RESUMEN` | 2 | idx 0–13 (14 clientes) | idx 15–27 (varios bloques) | `CLIENTE`, `Total Sin IVA`, `IVA`, *[col 3: total del mes]*, `Segmento` |
| `FACTURAS <MES> 2026` | 3 | idx 0–106 (107 facturas) | **idx 108** (107 vacía) | `FECHA`, `FACT`, `Cliente`, `Nombre`, `Venta en M.N.`, `IVA en M.N.`, `Total` |
| `DEV Y DESC` | 2 | idx 0–4 (5 registros) | idx 8, y 10–12 por segmento | `FECHA`, `CLIENTE`, `Total Sin IVA`, `IVA`, *[col 4: total]*, *[col 5 vacía]*, *[col 6: tipo]* |
| `REMISIONES PTES FACTURAR` | 3 | idx 0–75 (76 remisiones) | **idx 77** | `FECHA`, `REMISION`, `Cliente`, `Nombre`, `Venta en M.N.`, `IVA en M.N.`, `Total`, `Unnamed: 7` |
| `HISTORICO` | 2 | idx 0–4 (5 segmentos) | idx 7 (total), 8–9 (IVA y total c/IVA) | `Unnamed: 0`, `ENERO`…`DICIEMBRE`, `TOTAL 2026` |

**Notas por hoja:**

- `RESUMEN` — en las filas de total, la columna `Segmento` contiene **porcentajes numéricos**, no
  texto. Es el marcador más simple para detectar dónde termina el detalle.
- `FACTURAS` — `FACT` es folio interno (`AA0000007097`…`AA0000007205`), **no es UUID ni folio fiscal**.
  En agosto faltan 2 números de la secuencia (probables cancelaciones). `Cliente` viene como `float64`:
  castear a `int` antes de cruzar.
- `DEV Y DESC` — la columna 6 marca `** PENALIZACION` o `** DESCUENTO`. **CONALITEG aparece aquí con
  `IVA` nulo (tasa 0 %) y como `COMISION NACIONAL DE LIBROS`**, no con el nombre abreviado. En esta
  hoja no hay código de cliente, y el nombre difiere del de facturas (`INFORMA PUEBLA` vs
  `INFORMA A PUEBLA`) — cruzar por nombre normalizado.
- `REMISIONES` — `Unnamed: 7` contiene la marca `*** REVISAR ***`. Las fechas **no están acotadas al
  mes**: en agosto hay una de enero, una de junio y nueve del 2026-09-01.
- `HISTORICO` — cinco segmentos: `VENTA PRIVADA`, `VENTA FILIAL`, `VENTA PRIVADA/GOBIERNO`,
  `VENTA GOBIERNO (CONALITEG)`, `VENTA VARIOS (RENTA)`. Importes **sin IVA**. El último se etiqueta
  `VENTA VARIOS (SERVICIOS)` en `RESUMEN` — misma cosa, nombre inconsistente. CONALITEG puede venir
  **negativo** (enero −47,249.10; agosto −936,755.82) cuando el mes solo tuvo penalizaciones.

### Llave de cruce con el SAE

`Cliente` (código numérico) coincide entre facturación y `Pedidos SAE.xls`. Los 14 de agosto:

```
 18 DELMAN INTERNACIONAL          270 GD COMERCIALIZADORA DEL BAJIO   314 EDITORIAL PANINI MEXICO
191 PROMOCIONALES E IMPRESOS AM.  287 PENGUIN RANDOM HOUSE           336 GD EXPO COLCHONES
267 EDITORIAL ESPACIOS DINAMICOS  307 CHEDRAUI BRANDS                337 EDICIONES BOB
268 IGLESIA UNIVERSAL             308 UNION EDITORIALISTA            339 ESTRATEGIA PUBLICITARIA
311 INFORMA A PUEBLA              312 INFORMACION INTEGRAL 24/7
```

---

## Anexo — repo canónico y deriva de `CLAUDE.md`

**El repo bueno es `CHAMBA\lyon_dashboard`.** La copia en `CUADRE_CONTABILIDAD\lyon_dashboard` está
**atrasada**: el canónico tiene commits que ella no (`6b12351` rediseño de la gráfica de proveedores,
`f8b052d` renombre del catálogo, `aab6081` reacomodo del dona de Gastos de Empresa). No trabajar
desde la copia.

`CLAUDE.md` es idéntico en ambas y está desactualizado. Una sesión nueva va a confiar en él; estas
siete afirmaciones son falsas contra el código real:

| Dice | Realidad |
|---|---|
| catálogo de 11 categorías | son **18** en `core/catalogos.py` — incluye `Maquila Externa` y `Maquila de Destajo`, y el ancla de `INFOVITA` apunta a `Maquila Externa` |
| existe `core/plots_detalle.py` | no existe; todo está en `plots.py` |
| `upsert_proveedor_clasificacion()` | se llama **`upsert_clasificacion()`** |
| páginas ocultas `_Proveedor.py`, `_Categoria.py`… | no existen; los drill-down son inline con `session_state` |
| navegación por `st.query_params` | se usa `st.session_state["drill_*"]` + `st.stop()` |
| `@st.cache_data` en ETL | **no se usa en ningún lado** |
| local-first, sin servicios externos | hay backend PostgreSQL/Supabase opcional en `database.py` |

Conviene corregirlo antes de trabajar, o el agente replicará patrones que no existen.
