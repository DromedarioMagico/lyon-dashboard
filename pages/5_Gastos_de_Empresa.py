import datetime as dt

import pandas as pd
import streamlit as st

from core.catalogos import COLOR_LYON, ESPANOL_MES
from core.database import (
    init_db, get_conceptos_gastos_empresa, get_años_gastos_empresa,
    get_gastos_empresa_año, bulk_upsert_gastos_empresa, delete_concepto_año,
    log_evento,
)
from core.navigation import (
    render_sidebar_search, render_sidebar_status, inject_custom_css, handle_pending_nav,
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
st.caption(
    "Gastos que **no** pasan por una compra en el SAE — nómina operativa, nómina "
    "administrativa, impuestos, renta directa, etc. Captúralos aquí; se guardan de "
    "forma permanente (igual que las clasificaciones) y se reflejan como un renglón "
    "adicional en Compras y Comparativa cuando tengas el archivo de Compras cargado."
)

_MESES_COLS = [ESPANOL_MES[m] for m in range(1, 13)]
_MES_A_NUM  = {ESPANOL_MES[m]: m for m in range(1, 13)}

año_actual      = dt.datetime.now().year
años_con_datos  = get_años_gastos_empresa()
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

# ── Captura por monto anual (se reparte en 12 meses) ────────────────────────────
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

# ── Grilla editable del año seleccionado ────────────────────────────────────────
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
st.metric("Total del año", f"${total_año:,.0f} MXN")

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

    filas = []
    for _, row in edited.iterrows():
        concepto = str(row["Concepto"]).strip()
        if not concepto:
            continue
        for mes_nombre in _MESES_COLS:
            monto = float(row[mes_nombre]) if pd.notna(row[mes_nombre]) else 0.0
            periodo = f"{int(año_sel)}-{_MES_A_NUM[mes_nombre]:02d}"
            filas.append((concepto, periodo, monto, ""))

    if filas:
        bulk_upsert_gastos_empresa(filas)

    if filas or eliminados:
        msg = f"✅ Guardado — {len(filas)} celda(s) actualizada(s)"
        if eliminados:
            msg += f", {len(eliminados)} concepto(s) eliminado(s) de {año_sel}"
        st.success(msg + ".")
        log_evento("gasto_empresa_guardado", f"{año_sel}: {len(filas)} celdas")
        st.rerun()
    else:
        st.info("No hubo cambios que guardar.")
