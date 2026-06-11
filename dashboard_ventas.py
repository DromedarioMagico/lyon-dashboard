# ============================================================================
#  DASHBOARD DE CONTROL DE VENTAS — LYON AG
# ----------------------------------------------------------------------------
#  Herramienta de un solo uso. Al ejecutar la celda:
#    1. Pide subir el archivo de Pedidos del SAE (.xls o .xlsx).
#    2. Detecta los meses presentes y te pide elegir cuáles incluir.
#    3. Genera y descarga automáticamente:
#         • Dashboard_Ventas_LyonAG.html — Reporte interactivo (Plotly)
#
#  ETL:
#    • Filtra estatus a Remitido / Emitido / Rem.Parc.
#    • Convierte importes con coma de miles a float.
#    • Convierte fechas dd/mm/yyyy a datetime.
#    • Normaliza vendedor sin asignar a "Sin asignar".
# ============================================================================

# ---------- 0. CONFIGURACIÓN ------------------------------------------------
HOJA_VENTAS         = "Pedidos"
ESTATUS_VALIDOS     = ["Remitido", "Emitido", "Rem.Parc."]
TOP_N_CLIENTES      = 10
TOP_N_PEDIDOS       = 10
TOP_N_HEATMAP       = 15
NOMBRE_HTML         = "Dashboard_Ventas_LyonAG.html"

# Abreviaciones para clientes con nombres muy largos (mejor legibilidad en gráficas).
# El nombre completo siempre se preserva en hover y en las tablas.
ABREVIACIONES = {
    "COMISION NACIONAL DE LIBROS DE TEXTO GRATUITOS": "CONALITEG",
}

# ---------- 1. IMPORTS E INSTALACIONES --------------------------------------
import sys, subprocess, io, os, re, warnings, datetime as dt
warnings.filterwarnings("ignore")

def _ensure(spec, import_name=None):
    try:
        __import__(import_name or spec.split("==")[0])
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", spec], check=True)

for spec, imp in [("plotly", "plotly"), ("xlrd", "xlrd")]:
    _ensure(spec, imp)

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

# ---------- 2. SUBIDA DEL ARCHIVO -------------------------------------------
try:
    from google.colab import files
    from IPython.display import display, FileLink, HTML
except ImportError:
    raise EnvironmentError(
        "Este script está pensado para Google Colab. En otro entorno, define "
        "manualmente la ruta del archivo y omite la subida interactiva."
    )

print("📂 Sube el archivo de PEDIDOS del SAE (.xls o .xlsx)")
uploaded = files.upload()
if not uploaded:
    raise RuntimeError("No se subió ningún archivo.")

ARCHIVO = next((n for n in uploaded
                if n.lower().endswith((".xls", ".xlsx", ".xlsm"))), None)
if ARCHIVO is None:
    raise RuntimeError(f"Ningún archivo .xls/.xlsx subido. Recibido: {list(uploaded)}")
bytes_data = uploaded[ARCHIVO]
print(f"✅ Archivo recibido: {ARCHIVO}  ({len(bytes_data):,} bytes)\n")

# ---------- 3. CARGA Y LIMPIEZA (ETL) ---------------------------------------
try:
    df_raw = pd.read_excel(io.BytesIO(bytes_data), sheet_name=HOJA_VENTAS)
except ValueError as e:
    hojas = pd.ExcelFile(io.BytesIO(bytes_data)).sheet_names
    raise ValueError(
        f"La hoja '{HOJA_VENTAS}' no existe. Hojas disponibles: {hojas}.\n"
        f"Edita HOJA_VENTAS al inicio del script. Detalle: {e}"
    )

df_raw.columns = df_raw.columns.astype(str).str.strip()

COLS_REQ = ["Tipo", "Clave", "Nombre", "Estatus", "Fecha de elaboración",
            "Subtotal", "Total de comisiones", "Importe total", "Nombre del vendedor"]
faltantes = [c for c in COLS_REQ if c not in df_raw.columns]
if faltantes:
    raise KeyError(f"Faltan columnas: {faltantes}.\nDetectadas: {list(df_raw.columns)}")

# 3.1 — Filtro de estatus
df = df_raw[df_raw["Estatus"].astype(str).str.strip().isin(ESTATUS_VALIDOS)].copy()
descartadas = len(df_raw) - len(df)

# 3.2 — Fechas (SAE las exporta como strings dd/mm/yyyy)
df["Fecha"] = pd.to_datetime(df["Fecha de elaboración"], format="%d/%m/%Y", errors="coerce")
sin_fecha = df["Fecha"].isna().sum()
if sin_fecha:
    print(f"⚠️  {sin_fecha} fila(s) sin fecha válida — descartadas.")
df = df.dropna(subset=["Fecha"]).copy()

# 3.3 — Importes (strings con coma de miles "28,564.90" → float)
def _parse_num(v):
    if pd.isna(v):
        return 0.0
    s = str(v).strip().replace(",", "").replace("$", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0

df["Subtotal_MXN"] = df["Subtotal"].apply(_parse_num)
df["Comision_MXN"] = df["Total de comisiones"].apply(_parse_num)
df["Importe_MXN"]  = df["Importe total"].apply(_parse_num)
df["IVA_MXN"]      = df["Importe_MXN"] - df["Subtotal_MXN"]

# 3.4 — Normalizaciones
df["Vendedor"] = (df["Nombre del vendedor"].fillna("Sin asignar")
                   .astype(str).str.strip().replace({"": "Sin asignar"}))
df["Cliente_Nombre"] = df["Nombre"].fillna("(sin nombre)").astype(str).str.strip()

# 3.5 — Versión "Display" del cliente: abrevia los nombres demasiado largos.
def _abreviar(nombre):
    if nombre in ABREVIACIONES:
        return ABREVIACIONES[nombre]
    return nombre if len(nombre) <= 32 else nombre[:30] + "…"
df["Cliente_Display"] = df["Cliente_Nombre"].apply(_abreviar)

print(f"📥 Datos limpios: {len(df):,} pedidos válidos "
      f"({descartadas} cancelados/inválidos descartados)")

# ---------- 3b. SELECTOR DE MESES -------------------------------------------
df["_Mes"] = df["Fecha"].dt.to_period("M")
meses_disponibles = sorted(df["_Mes"].unique())
ESPANOL_MES = {1:"Ene", 2:"Feb", 3:"Mar", 4:"Abr", 5:"May", 6:"Jun",
               7:"Jul", 8:"Ago", 9:"Sep", 10:"Oct", 11:"Nov", 12:"Dic"}
_label_mes = lambda p: f"{ESPANOL_MES[p.month]} {p.year}"

print("\n📅 Meses detectados en el archivo:")
for i, mes in enumerate(meses_disponibles, 1):
    sub = df[df["_Mes"] == mes]
    print(f"     {i}. {_label_mes(mes):12}  ·  {len(sub):>4} pedidos  ·  "
          f"${sub['Importe_MXN'].sum():>14,.2f} MXN")

if len(meses_disponibles) == 1:
    meses_seleccionados = list(meses_disponibles)
    print(f"\n   → Sólo hay un mes en el archivo, no hay selección por hacer.")
else:
    print(f"\n¿Qué meses quieres incluir en el reporte?")
    print(f"     • Números separados por coma (ej: 1,3,5)")
    print(f"     • Rangos con guion         (ej: 1-3)")
    print(f"     • Combinación              (ej: 1,3-5)")
    print(f"     • 'todos' o ENTER vacío    → incluir todos")

    def _parsear_seleccion(texto, n):
        indices = set()
        for parte in texto.replace(" ", "").split(","):
            if not parte:
                continue
            if "-" in parte:
                a, b = parte.split("-", 1)
                a, b = int(a), int(b)
                indices.update(range(min(a, b), max(a, b) + 1))
            else:
                indices.add(int(parte))
        return sorted([i for i in indices if 1 <= i <= n])

    while True:
        try:
            sel = input("\n   Tu selección: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            sel = "todos"
        if not sel or sel in ("todos", "all", "todo", "*"):
            meses_seleccionados = list(meses_disponibles)
            break
        try:
            idx = _parsear_seleccion(sel, len(meses_disponibles))
            if not idx:
                print(f"   ⚠️  Ninguna opción válida en '{sel}'. Intenta de nuevo.")
                continue
            meses_seleccionados = [meses_disponibles[i-1] for i in idx]
            break
        except Exception as e:
            print(f"   ⚠️  No entendí '{sel}' ({e}). Usa '1,3' o '1-3' o 'todos'.")

df = df[df["_Mes"].isin(meses_seleccionados)].copy()
etiquetas_sel = ", ".join(_label_mes(m) for m in meses_seleccionados)
print(f"\n✅ Reporte incluirá: {etiquetas_sel}")
print(f"   Pedidos filtrados: {len(df):,}")
if len(df) == 0:
    raise RuntimeError("El filtro de meses no dejó ningún pedido. Aborto.")

# ---------- 4. KPIs ---------------------------------------------------------
venta_total      = df["Importe_MXN"].sum()
subtotal_total   = df["Subtotal_MXN"].sum()
iva_total        = df["IVA_MXN"].sum()
total_pedidos    = len(df)
ticket_promedio  = df["Importe_MXN"].mean()
ticket_mediano   = df["Importe_MXN"].median()
fecha_min        = df["Fecha"].min()
fecha_max        = df["Fecha"].max()
dias_cubiertos   = (fecha_max - fecha_min).days + 1

clientes_unicos   = df["Cliente_Nombre"].nunique()
vendedores_unicos = df["Vendedor"].nunique() - (1 if "Sin asignar" in df["Vendedor"].values else 0)

comision_total   = df["Comision_MXN"].sum()
n_con_comision   = (df["Comision_MXN"] > 0).sum()
pct_con_comision = n_con_comision / total_pedidos * 100 if total_pedidos else 0

ventas_por_cliente_sorted = (df.groupby("Cliente_Nombre")["Importe_MXN"].sum()
                               .sort_values(ascending=False))
acum_pct = ventas_por_cliente_sorted.cumsum() / venta_total * 100
n_clientes_80pct = int((acum_pct <= 80).sum()) + 1 if len(acum_pct) > 0 else 0

gasto_remitido = df[df["Estatus"]=="Remitido"]["Importe_MXN"].sum()
gasto_emitido  = df[df["Estatus"]=="Emitido"]["Importe_MXN"].sum()
gasto_parc     = df[df["Estatus"]=="Rem.Parc."]["Importe_MXN"].sum()

gasto_sin_vend = df[df["Vendedor"]=="Sin asignar"]["Importe_MXN"].sum()
n_sin_vend     = (df["Vendedor"]=="Sin asignar").sum()
pct_sin_vend   = gasto_sin_vend / venta_total * 100 if venta_total else 0

print("\n" + "═"*74)
print("  RESUMEN EJECUTIVO — VENTAS LYON AG")
print("═"*74)
print(f"  Periodo                       : {fecha_min:%d-%b-%Y} → {fecha_max:%d-%b-%Y}  ({dias_cubiertos} días)")
print(f"  Importe total facturado       : ${venta_total:>18,.2f} MXN")
print(f"    de los cuales subtotal      : ${subtotal_total:>18,.2f} MXN")
print(f"    de los cuales IVA/impuestos : ${iva_total:>18,.2f} MXN  ({iva_total/subtotal_total*100 if subtotal_total else 0:.1f}%)")
print(f"  Pedidos válidos               : {total_pedidos:>22,}")
print(f"  Ticket promedio               : ${ticket_promedio:>18,.2f} MXN")
print(f"  Ticket mediano                : ${ticket_mediano:>18,.2f} MXN")
print(f"  Clientes únicos               : {clientes_unicos:>22,}")
print(f"  Vendedores activos            : {vendedores_unicos:>22,}")
print("─"*74)
print(f"  Comisiones pagadas            : ${comision_total:>18,.2f} MXN")
print(f"  Pedidos con comisión          : {n_con_comision:>3} de {total_pedidos}  ({pct_con_comision:.1f}%)")
print(f"  Concentración cliente (80/20) : {n_clientes_80pct} clientes hacen el 80% del revenue")
print(f"  Ventas sin vendedor asignado  : ${gasto_sin_vend:>18,.2f}  ({pct_sin_vend:.1f}%)")
print("─"*74)
print(f"  Por estatus:")
print(f"    Remitido                    : ${gasto_remitido:>18,.2f}  ({gasto_remitido/venta_total*100:5.1f}%)")
print(f"    Emitido (pendiente remitir) : ${gasto_emitido:>18,.2f}  ({gasto_emitido/venta_total*100:5.1f}%)")
print(f"    Remitido parcial            : ${gasto_parc:>18,.2f}  ({gasto_parc/venta_total*100:5.1f}%)")
print("═"*74)

# ---------- 5. PALETA -------------------------------------------------------
# Paleta más viva que la versión anterior — el usuario pidió colores menos apagados.
COLORES_VIVOS = ["#1F4E79", "#C00000", "#E97132", "#7030A0", "#548235",
                 "#2E75B6", "#BF8F00", "#A02B93", "#385723", "#806000",
                 "#5B9BD5", "#ED7D31"]
COLOR_RESTO    = "#9FA8DA"
COLOR_SIN_VEND = "#9E9E9E"

# Mapeo estable de cliente → color basado en posición en el ranking
ranking_clientes = ventas_por_cliente_sorted.index.tolist()
color_cliente = {c: COLORES_VIVOS[i % len(COLORES_VIVOS)]
                 for i, c in enumerate(ranking_clientes)}

# Mapeo cliente_display → cliente_nombre (para hovers y consistencia)
disp_to_full = (df.drop_duplicates("Cliente_Display")
                  .set_index("Cliente_Display")["Cliente_Nombre"].to_dict())

# ============================================================================
#  GRÁFICO 1 — DONUT: Top 10 clientes + "Resto" (leyenda lateral con montos)
# ============================================================================
top_clientes_full = ventas_por_cliente_sorted  # por nombre completo
top10_full  = top_clientes_full.head(TOP_N_CLIENTES)
resto_total = top_clientes_full.iloc[TOP_N_CLIENTES:].sum()
resto_count = len(top_clientes_full) - TOP_N_CLIENTES
RESTO_LABEL = f"Resto ({resto_count} clientes)"

# Datos del donut: usar Cliente_Display para etiquetas
donut_labels_full = [_abreviar(c) for c in top10_full.index] + [RESTO_LABEL]
donut_values      = list(top10_full.values) + [resto_total]
donut_colors      = [color_cliente[c] for c in top10_full.index] + [COLOR_RESTO]

# Para leyenda: incluir monto y % en cada etiqueta
donut_legend_labels = [
    f"{lab} — ${v/1e6:,.2f}M ({v/venta_total*100:.1f}%)"
    for lab, v in zip(donut_labels_full, donut_values)
]
# Hover usa el nombre COMPLETO (no abreviado)
hover_names = list(top10_full.index) + [RESTO_LABEL]

fig1 = go.Figure(data=[go.Pie(
    labels=donut_legend_labels,
    values=donut_values,
    hole=0.55,
    marker=dict(colors=donut_colors, line=dict(color="white", width=2)),
    text=hover_names,
    textinfo="percent",
    textposition="inside",
    insidetextorientation="radial",
    insidetextfont=dict(color="white", size=12, family="Arial Black"),
    hovertemplate="<b>%{text}</b><br>Ventas: $%{value:,.0f} MXN<br>"
                  "Participación: %{percent}<extra></extra>",
    sort=False,
    direction="clockwise",
)])
fig1.update_layout(
    title=(f"<b>Distribución de Ventas por Cliente</b>"
           f"<br><sup>Top {TOP_N_CLIENTES} clientes vs el resto  ·  "
           f"<b>{n_clientes_80pct} clientes</b> concentran el 80% del revenue</sup>"),
    template="plotly_white",
    annotations=[dict(text=f"<b>${venta_total/1e6:,.1f}M</b><br>"
                            f"<span style='font-size:12px'>MXN total</span>",
                      x=0.18, y=0.5, font=dict(size=20), showarrow=False)],
    height=560,
    margin=dict(t=110, b=40, l=20, r=20),
    legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=0.45,
                font=dict(size=11)),
)
# Forzar donut a la mitad izquierda dejando leyenda a la derecha
fig1.update_traces(domain=dict(x=[0.0, 0.40], y=[0.0, 1.0]))

# ============================================================================
#  GRÁFICO 2 — DONUT del "Resto" (desglose de los clientes 11+)
# ============================================================================
resto_clientes = top_clientes_full.iloc[TOP_N_CLIENTES:]
fig2 = None
if len(resto_clientes) > 0:
    resto_labels_full = [_abreviar(c) for c in resto_clientes.index]
    resto_values      = list(resto_clientes.values)
    resto_colors      = [color_cliente[c] for c in resto_clientes.index]
    resto_legend = [
        f"{lab} — ${v/1e3:,.0f}K ({v/resto_total*100:.1f}%)"
        for lab, v in zip(resto_labels_full, resto_values)
    ]
    fig2 = go.Figure(data=[go.Pie(
        labels=resto_legend,
        values=resto_values,
        hole=0.50,
        marker=dict(colors=resto_colors, line=dict(color="white", width=1.5)),
        text=list(resto_clientes.index),
        textinfo="percent",
        textposition="inside",
        insidetextorientation="auto",
        insidetextfont=dict(color="white", size=11, family="Arial Black"),
        hovertemplate="<b>%{text}</b><br>Ventas: $%{value:,.0f} MXN<br>"
                      "Participación del resto: %{percent}<extra></extra>",
        sort=False,
    )])
    fig2.update_layout(
        title=(f"<b>Desglose del 'Resto' — {resto_count} Clientes fuera del Top {TOP_N_CLIENTES}</b>"
               f"<br><sup>Total agregado: <b>${resto_total/1e6:,.2f}M MXN</b>  ·  "
               f"{resto_total/venta_total*100:.1f}% del revenue total</sup>"),
        template="plotly_white",
        annotations=[dict(text=f"<b>${resto_total/1e6:,.2f}M</b><br>"
                                f"<span style='font-size:11px'>resto</span>",
                          x=0.18, y=0.5, font=dict(size=16), showarrow=False)],
        height=520,
        margin=dict(t=110, b=40, l=20, r=20),
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=0.45,
                    font=dict(size=10)),
    )
    fig2.update_traces(domain=dict(x=[0.0, 0.40], y=[0.0, 1.0]))

# ============================================================================
#  GRÁFICO 3 — CURVA SEMANAL con pico destacado
# ============================================================================
df_sem = (df.set_index("Fecha").resample("W-MON")["Importe_MXN"].sum().reset_index())
promedio_sem = df_sem["Importe_MXN"].mean()
pico_idx = df_sem["Importe_MXN"].idxmax()
pico_x   = df_sem.loc[pico_idx, "Fecha"]
pico_y   = df_sem.loc[pico_idx, "Importe_MXN"]

fig3 = go.Figure()
# Área principal
fig3.add_trace(go.Scatter(
    x=df_sem["Fecha"], y=df_sem["Importe_MXN"],
    mode="lines+markers", fill="tozeroy",
    line=dict(color="#548235", width=2.8),
    fillcolor="rgba(84, 130, 53, 0.18)",
    marker=dict(size=8, color="#548235",
                line=dict(color="white", width=1.5)),
    hovertemplate="Semana del %{x|%d-%b-%Y}<br>"
                  "Ventas: $%{y:,.0f} MXN<extra></extra>",
    name="Ventas",
))
# Línea de promedio
fig3.add_hline(y=promedio_sem, line_dash="dash", line_color="#1F4E79", line_width=1.5,
               annotation_text=f"Promedio semanal: ${promedio_sem:,.0f}",
               annotation_position="top left", annotation_font_color="#1F4E79",
               annotation_font_size=11)

# Halo grande en el pico (efecto de "destello")
fig3.add_trace(go.Scatter(
    x=[pico_x], y=[pico_y],
    mode="markers",
    marker=dict(size=32, color="rgba(192, 0, 0, 0.15)",
                line=dict(color="rgba(192, 0, 0, 0.4)", width=2)),
    hoverinfo="skip", showlegend=False,
))
# Marcador del pico (estrella roja)
fig3.add_trace(go.Scatter(
    x=[pico_x], y=[pico_y],
    mode="markers+text",
    marker=dict(size=18, color="#C00000", symbol="star",
                line=dict(color="white", width=2)),
    text=[f"<b>PICO ${pico_y/1e6:.2f}M</b>"],
    textposition="top center",
    textfont=dict(color="#C00000", size=13, family="Arial Black"),
    hovertemplate=f"<b>PICO</b><br>Semana del %{{x|%d-%b-%Y}}<br>"
                  f"Ventas: ${pico_y:,.0f} MXN<extra></extra>",
    showlegend=False,
))
fig3.update_layout(
    title="<b>Curva de Ventas Semanal — Detección de Picos</b>"
          "<br><sup>Agrupación dinámica de lunes a domingo</sup>",
    xaxis_title="Semana", yaxis_title="Ventas (MXN)",
    template="plotly_white", height=480, showlegend=False,
    margin=dict(t=100, b=60, l=80, r=40),
)
fig3.update_yaxes(tickformat=",.0f", tickprefix="$")

# ============================================================================
#  GRÁFICO 4 — PARETO TOP 10 CLIENTES (con márgenes generosos)
# ============================================================================
top10_df = top10_full.reset_index()
top10_df.columns = ["Cliente_Full", "Ventas"]
top10_df["Cliente_Display"] = top10_df["Cliente_Full"].apply(_abreviar)
top10_df["Pct_Acumulado"] = top10_df["Ventas"].cumsum() / venta_total * 100
pct_top10 = top10_df["Pct_Acumulado"].iloc[-1]

colors_pareto = [color_cliente[c] for c in top10_df["Cliente_Full"]]

fig4 = go.Figure()
fig4.add_trace(go.Bar(
    x=top10_df["Ventas"].iloc[::-1],
    y=top10_df["Cliente_Display"].iloc[::-1],
    orientation="h",
    marker=dict(color=colors_pareto[::-1], line=dict(color="white", width=1)),
    text=[f"${v/1e6:,.2f}M" for v in top10_df["Ventas"].iloc[::-1]],
    textposition="outside",
    textfont=dict(size=11, color="#1F4E79"),
    customdata=top10_df["Cliente_Full"].iloc[::-1].values,
    hovertemplate="<b>%{customdata}</b><br>Ventas: $%{x:,.0f} MXN<extra></extra>",
))
fig4.update_layout(
    title=(f"<b>Pareto — Top {TOP_N_CLIENTES} Clientes por Volumen de Ventas (MXN)</b>"
           f"<br><sup>El top {TOP_N_CLIENTES} concentra el <b>{pct_top10:.1f}%</b> "
           f"del revenue del periodo</sup>"),
    xaxis_title="Ventas (MXN)", yaxis_title="",
    template="plotly_white", height=540, showlegend=False,
    margin=dict(t=110, b=60, l=200, r=140),  # left más generoso para nombres
)
fig4.update_xaxes(tickformat=",.0f", tickprefix="$")
fig4.update_yaxes(tickfont=dict(size=11))

# ============================================================================
#  TABLA: Resto de clientes (los que NO están en top 10)
# ============================================================================
resto_df = resto_clientes.reset_index()
resto_df.columns = ["Cliente", "Ventas"]
resto_df["Cliente_Display"] = resto_df["Cliente"].apply(_abreviar)
resto_df["Pct"] = resto_df["Ventas"] / venta_total * 100
resto_df_disp = resto_df.copy()
resto_df_disp["Ventas_fmt"] = resto_df_disp["Ventas"].apply(lambda x: f"${x:,.2f}")
resto_df_disp["Pct_fmt"]    = resto_df_disp["Pct"].apply(lambda x: f"{x:.2f}%")
resto_df_disp.index = range(TOP_N_CLIENTES + 1, TOP_N_CLIENTES + 1 + len(resto_df_disp))

fig_resto_tbl = None
if len(resto_df_disp) > 0:
    fig_resto_tbl = go.Figure(data=[go.Table(
        columnwidth=[40, 80, 320, 130, 70],
        header=dict(
            values=["<b>#</b>", "<b>Posición</b>", "<b>Cliente</b>",
                    "<b>Ventas (MXN)</b>", "<b>% Revenue</b>"],
            fill_color="#1F4E79", font=dict(color="white", size=12),
            align="left", height=32,
        ),
        cells=dict(
            values=[
                list(range(1, len(resto_df_disp)+1)),
                [f"#{i}" for i in resto_df_disp.index],
                resto_df_disp["Cliente"],
                resto_df_disp["Ventas_fmt"],
                resto_df_disp["Pct_fmt"],
            ],
            fill_color=[["#F4F7FA", "#FFFFFF"] * len(resto_df_disp)],
            align=["center", "center", "left", "right", "right"],
            font=dict(size=10), height=26,
        ),
    )])
    altura_tbl = max(200, 60 + 26 * len(resto_df_disp))
    fig_resto_tbl.update_layout(
        title=(f"<b>Resto de Clientes (posiciones {TOP_N_CLIENTES+1} a {len(top_clientes_full)})</b>"
               f"<br><sup>{resto_count} clientes que suman ${resto_total:,.2f} MXN "
               f"({resto_total/venta_total*100:.1f}% del revenue)</sup>"),
        height=altura_tbl, margin=dict(t=70, b=20, l=10, r=10),
    )

# ============================================================================
#  GRÁFICO 5 — VENTAS POR VENDEDOR (colorido, márgenes corregidos)
# ============================================================================
ventas_vend = (df.groupby("Vendedor")
                 .agg(Ventas=("Importe_MXN", "sum"),
                      Pedidos=("Importe_MXN", "count"),
                      Comisiones=("Comision_MXN", "sum"))
                 .sort_values("Ventas", ascending=False)
                 .reset_index())

# Paleta: cada vendedor un color del catálogo vivo; "Sin asignar" siempre gris
PALETA_VENDEDORES = ["#1F4E79", "#C00000", "#E97132", "#7030A0", "#548235",
                     "#2E75B6", "#BF8F00", "#A02B93"]
colors_vend = []
idx_vend = 0
for v in ventas_vend["Vendedor"]:
    if v == "Sin asignar":
        colors_vend.append(COLOR_SIN_VEND)
    else:
        colors_vend.append(PALETA_VENDEDORES[idx_vend % len(PALETA_VENDEDORES)])
        idx_vend += 1

fig5 = go.Figure()
fig5.add_trace(go.Bar(
    x=ventas_vend["Ventas"].iloc[::-1],
    y=ventas_vend["Vendedor"].iloc[::-1],
    orientation="h",
    marker=dict(color=colors_vend[::-1], line=dict(color="white", width=1)),
    text=[f"${v/1e6:,.2f}M  ·  {p} pedidos"
          for v, p in zip(ventas_vend["Ventas"].iloc[::-1],
                          ventas_vend["Pedidos"].iloc[::-1])],
    textposition="outside",
    textfont=dict(size=11, color="#1F4E79"),
    customdata=ventas_vend[["Pedidos", "Comisiones"]].iloc[::-1].values,
    hovertemplate="<b>%{y}</b><br>"
                  "Ventas: $%{x:,.0f} MXN<br>"
                  "Pedidos: %{customdata[0]}<br>"
                  "Comisiones: $%{customdata[1]:,.2f}<extra></extra>",
))
fig5.update_layout(
    title=(f"<b>Ventas por Vendedor</b>"
           f"<br><sup>El segmento gris ({pct_sin_vend:.1f}% / "
           f"${gasto_sin_vend/1e6:,.2f}M) son pedidos sin vendedor asignado — "
           f"hallazgo operativo</sup>"),
    xaxis_title="Ventas (MXN)", yaxis_title="",
    template="plotly_white", height=440, showlegend=False,
    margin=dict(t=110, b=60, l=170, r=240),  # right grande para no truncar German
)
fig5.update_xaxes(tickformat=",.0f", tickprefix="$")
fig5.update_yaxes(tickfont=dict(size=11))

# ============================================================================
#  GRÁFICO 6 — HEATMAP CLIENTE × MES (estacionalidad y consistencia)
# ============================================================================
top_clientes_heat = top_clientes_full.head(TOP_N_HEATMAP).index.tolist()
pivot = (df[df["Cliente_Nombre"].isin(top_clientes_heat)]
            .pivot_table(index="Cliente_Nombre", columns="_Mes",
                         values="Importe_MXN", aggfunc="sum", fill_value=0))
pivot = pivot.reindex(top_clientes_heat)
pivot_display = pivot.copy()
pivot_display.index = [_abreviar(c) for c in pivot_display.index]
pivot_display.columns = [_label_mes(c) for c in pivot_display.columns]

fig6 = go.Figure(data=go.Heatmap(
    z=pivot.values,
    x=pivot_display.columns,
    y=pivot_display.index,
    colorscale=[[0.0, "#FFFFFF"], [0.001, "#F0F4F8"],
                [0.15, "#A6C8E0"], [0.5, "#5B9BD5"], [1.0, "#1F4E79"]],
    hovertemplate="<b>%{y}</b><br>Mes: %{x}<br>"
                  "Ventas: $%{z:,.0f} MXN<extra></extra>",
    colorbar=dict(title=dict(text="MXN", font=dict(size=11)),
                  tickformat=",.0f", tickprefix="$",
                  thickness=15),
    xgap=2, ygap=2,
))
fig6.update_layout(
    title=(f"<b>Estacionalidad por Cliente — Top {TOP_N_HEATMAP}</b>"
           f"<br><sup>Mapa de calor: qué clientes facturan en qué meses  ·  "
           f"detecta picos puntuales vs facturación recurrente</sup>"),
    template="plotly_white",
    height=max(420, 70 + 28 * len(pivot_display)),
    margin=dict(t=100, b=60, l=200, r=80),
    xaxis=dict(side="top", tickfont=dict(size=11)),
    yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
)

# ============================================================================
#  TABLA — TOP 10 PEDIDOS INDIVIDUALES
# ============================================================================
top_ped = (df.nlargest(TOP_N_PEDIDOS, "Importe_MXN")
             [["Clave", "Fecha", "Cliente_Nombre", "Vendedor",
               "Importe_MXN", "Estatus"]]
             .copy().reset_index(drop=True))
top_ped_fmt = top_ped.copy()
top_ped_fmt["Fecha"] = top_ped_fmt["Fecha"].dt.strftime("%d-%b-%Y")
top_ped_fmt["Importe_MXN"] = top_ped_fmt["Importe_MXN"].apply(lambda x: f"${x:,.2f}")
top_ped_fmt.index = top_ped_fmt.index + 1
top_ped_fmt.columns = ["Clave", "Fecha", "Cliente", "Vendedor", "Importe (MXN)", "Estatus"]

fig7 = go.Figure(data=[go.Table(
    columnwidth=[30, 50, 70, 220, 130, 130, 70],
    header=dict(values=["<b>#</b>","<b>Clave</b>","<b>Fecha</b>","<b>Cliente</b>",
                        "<b>Vendedor</b>","<b>Importe (MXN)</b>","<b>Estatus</b>"],
                fill_color="#1F4E79", font=dict(color="white", size=12),
                align="left", height=34),
    cells=dict(values=[list(top_ped_fmt.index), top_ped_fmt["Clave"],
                       top_ped_fmt["Fecha"], top_ped_fmt["Cliente"],
                       top_ped_fmt["Vendedor"], top_ped_fmt["Importe (MXN)"],
                       top_ped_fmt["Estatus"]],
               fill_color=[["#F4F7FA","#FFFFFF"]*TOP_N_PEDIDOS],
               align="left", font=dict(size=11), height=28),
)])
fig7.update_layout(
    title="<b>Top 10 Pedidos Individuales por Monto</b>",
    height=460, margin=dict(t=70, b=20, l=10, r=10),
)

# ============================================================================
#  HTML INTERACTIVO con el Resumen Ejecutivo completo
# ============================================================================
print("\n🌐 Generando HTML interactivo…")

def fig_html(fig, include_js=False):
    if fig is None:
        return ""
    return pio.to_html(fig, full_html=False,
                       include_plotlyjs="inline" if include_js else False,
                       config={"displayModeBar": True, "displaylogo": False})

# Bloque del Resumen Ejecutivo: igual al de la consola pero formateado en HTML.
def _fmt_money(x):  return f"${x:,.2f} MXN"
def _fmt_int(x):    return f"{x:,}"
def _fmt_pct(x):    return f"{x:.1f}%"

kpi_secciones = [
    ("Periodo y volumen", [
        ("Periodo analizado",        f"{fecha_min:%d-%b-%Y} → {fecha_max:%d-%b-%Y} ({dias_cubiertos} días)"),
        ("Meses incluidos",          etiquetas_sel),
        ("Pedidos válidos",          _fmt_int(total_pedidos)),
        ("Pedidos descartados",      f"{descartadas} (Cancelado / Pend.Cancelado / sin fecha)"),
    ]),
    ("Importes", [
        ("Importe total facturado",  _fmt_money(venta_total)),
        ("Subtotal (sin IVA)",       _fmt_money(subtotal_total)),
        ("IVA / impuestos",          f"{_fmt_money(iva_total)}  ({iva_total/subtotal_total*100 if subtotal_total else 0:.1f}% del subtotal)"),
        ("Ticket promedio",          _fmt_money(ticket_promedio)),
        ("Ticket mediano",           _fmt_money(ticket_mediano)),
    ]),
    ("Clientes y vendedores", [
        ("Clientes únicos",          _fmt_int(clientes_unicos)),
        ("Concentración (80/20)",    f"<b>{n_clientes_80pct} clientes</b> hacen el 80% del revenue"),
        ("Vendedores activos",       _fmt_int(vendedores_unicos)),
        ("Pedidos sin vendedor",     f"{n_sin_vend} pedidos · {_fmt_money(gasto_sin_vend)} ({_fmt_pct(pct_sin_vend)})"),
    ]),
    ("Comisiones", [
        ("Comisiones pagadas",       _fmt_money(comision_total)),
        ("Pedidos con comisión",     f"{n_con_comision} de {total_pedidos} ({_fmt_pct(pct_con_comision)})"),
    ]),
    ("Pipeline por estatus", [
        ("Remitido",                 f"{_fmt_money(gasto_remitido)}  ({gasto_remitido/venta_total*100 if venta_total else 0:.1f}%)"),
        ("Emitido (pendiente)",      f"{_fmt_money(gasto_emitido)}  ({gasto_emitido/venta_total*100 if venta_total else 0:.1f}%)"),
        ("Remitido parcial",         f"{_fmt_money(gasto_parc)}  ({gasto_parc/venta_total*100 if venta_total else 0:.1f}%)"),
    ]),
]

kpi_html = ""
for titulo, filas in kpi_secciones:
    kpi_html += f"<h3 class='kpi-section'>{titulo}</h3>\n<table class='kpi'>"
    for k, v in filas:
        kpi_html += f"<tr><td>{k}</td><td>{v}</td></tr>\n"
    kpi_html += "</table>\n"

html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Dashboard Ventas Lyon AG</title>
  <style>
    body {{ font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
            margin: 0; padding: 0; background: #F4F7FA; color: #1f2933; }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
    h1 {{ color: #1F4E79; font-size: 26px; margin: 0 0 4px; }}
    .meta {{ color: #5b6b7a; font-size: 13px; margin-bottom: 24px; }}
    .card {{ background: white; border-radius: 8px; padding: 20px;
             margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
    .card h2 {{ color: #1F4E79; margin: 0 0 12px; font-size: 16px;
                border-bottom: 2px solid #1F4E79; padding-bottom: 8px; }}
    h3.kpi-section {{ color: #1F4E79; font-size: 13px;
                      text-transform: uppercase; letter-spacing: 0.5px;
                      margin: 18px 0 8px; padding-bottom: 4px;
                      border-bottom: 1px solid #D0D7DE; }}
    h3.kpi-section:first-child {{ margin-top: 0; }}
    table.kpi {{ width: 100%; border-collapse: collapse; font-size: 13.5px;
                 margin-bottom: 8px; }}
    table.kpi td {{ padding: 7px 12px; border-bottom: 1px solid #E1E7EC;
                    vertical-align: top; }}
    table.kpi td:first-child {{ font-weight: 600; color: #1F4E79;
                                background: #F4F7FA; width: 38%; }}
    .note {{ background: #E8F4E1; border-left: 4px solid #548235;
             padding: 12px 16px; font-size: 13px; color: #2d4a17;
             border-radius: 4px; margin-top: 16px; }}
    footer {{ text-align: center; color: #8a99a8; font-size: 12px;
              padding: 20px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Dashboard de Ventas — Lyon AG</h1>
    <p class="meta">Meses incluidos: <b>{etiquetas_sel}</b>  ·  
       Archivo: {ARCHIVO}  ·  Generado {dt.datetime.now():%d-%b-%Y %H:%M}</p>

    <div class="card">
      <h2>Resumen Ejecutivo</h2>
      {kpi_html}
      <div class="note">
        <b>Estatus incluidos:</b> Remitido, Emitido y Rem.Parc. Se excluyen Cancelado
        y Pend.Cancelado. <b>Ventas sin vendedor asignado</b> ({pct_sin_vend:.1f}% del
        revenue) es un hallazgo operativo para la mesa de ventas.
      </div>
    </div>

    <div class="card"><h2>Distribución de Ventas por Cliente</h2>{fig_html(fig1, include_js=True)}</div>
    {('<div class="card"><h2>Desglose del Resto de Clientes</h2>' + fig_html(fig2) + '</div>') if fig2 is not None else ''}
    <div class="card"><h2>Curva de Ventas Semanal</h2>{fig_html(fig3)}</div>
    <div class="card"><h2>Pareto — Top {TOP_N_CLIENTES} Clientes</h2>{fig_html(fig4)}</div>
    {('<div class="card"><h2>Detalle del Resto de Clientes</h2>' + fig_html(fig_resto_tbl) + '</div>') if fig_resto_tbl is not None else ''}
    <div class="card"><h2>Ventas por Vendedor</h2>{fig_html(fig5)}</div>
    <div class="card"><h2>Estacionalidad: Cliente × Mes</h2>{fig_html(fig6)}</div>
    <div class="card"><h2>Top {TOP_N_PEDIDOS} Pedidos Individuales</h2>{fig_html(fig7)}</div>

    <footer>Generado automáticamente · Lyon AG · Ventas</footer>
  </div>
</body>
</html>"""

with open(NOMBRE_HTML, "w", encoding="utf-8") as f:
    f.write(html)
print(f"✅ HTML generado: {NOMBRE_HTML}  ({os.path.getsize(NOMBRE_HTML):,} bytes)")

# ============================================================================
#  DESCARGA AUTOMÁTICA + LINK DE RESPALDO
# ============================================================================
print("\n⬇️  Iniciando descarga…")
descarga_ok = False
try:
    files.download(NOMBRE_HTML)
    descarga_ok = True
    print(f"   ↳ Descarga automática iniciada: {NOMBRE_HTML}")
except Exception as e:
    print(f"   ⚠️  La descarga automática falló: {e}")

# Siempre mostrar un link clickable como respaldo (confiable en cualquier Colab).
try:
    link_html = (f'<div style="padding:14px;border:2px solid #1F4E79;border-radius:6px;'
                 f'background:#F4F7FA;margin-top:10px;font-family:Arial">'
                 f'<b>📥 Descarga manual:</b> '
                 f'<a href="{NOMBRE_HTML}" download="{NOMBRE_HTML}" '
                 f'style="color:#1F4E79;font-weight:bold;font-size:14px">'
                 f'haz clic aquí para bajar {NOMBRE_HTML}</a></div>')
    display(HTML(link_html))
    display(FileLink(NOMBRE_HTML))
except Exception:
    pass

print("\n" + "═"*74)
print("  REPORTE GENERADO")
print("═"*74)
print(f"  → Dashboard interactivo : {NOMBRE_HTML}")
print(f"  → Tamaño                : {os.path.getsize(NOMBRE_HTML):,} bytes")
print("═"*74)