"""
Carga de Archivos — la única puerta de entrada de datos a la app.

Antes cada sección tenía su propio uploader; para dejar la app lista había que
entrar a 4 páginas distintas. Aquí se sube todo junto — el SAE de Compras y
Ventas, la facturación mensual, y lo que manda Contabilidad (libro, balanza,
reportes CFDI) — y la app detecta cuál es cuál por su estructura, no por el
nombre del archivo: cada `cargar_*` ya sabe reconocer la suya y levanta
ValueError si el archivo no le corresponde, así que reusar esa detección evita
mantener un sniffer aparte que se pueda desalinear de los ETL reales.

Nada de esto se persiste — vive en `st.session_state` y hay que volver a
subirlo la próxima sesión. Lo único que se guarda son las DECISIONES del
usuario (categorías, vendedores, catálogo de cuentas), vía `core/database.py`.
"""
import datetime as dt

import pandas as pd
import streamlit as st

from core.catalogos import COLOR_LYON
from core.database import get_stats, init_db, log_evento
from core.etl_balanza import cargar_balanza
from core.etl_cfdi import cargar_cfdi
from core.etl_compras import cargar_compras
from core.etl_contabilidad import cargar_contabilidad
from core.etl_facturacion import cargar_facturacion
from core.etl_ventas import cargar_ventas
from core.fuentes import estado_fuentes, faltantes
from core.navigation import (
    handle_pending_nav, inject_custom_css, render_sidebar_search, render_sidebar_status,
)

st.set_page_config(
    page_title="Carga de Archivos — Lyon AG",
    page_icon="📥",
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
    "<span class='material-symbols-outlined'>cloud_upload</span>Carga de Archivos</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='color:#5b6b7a; font-size:14px; margin-bottom:24px'>"
    "Planta QUMA — Sistema de control de compras y ventas</p>",
    unsafe_allow_html=True,
)

st.caption(
    "Arrastra aquí todo lo que tengas — SAE de Compras, SAE de Ventas (pedidos), "
    "facturación mensual (puedes subir varios meses de un jalón) y lo que manda "
    "Contabilidad (libro de movimientos, balanza, reportes CFDI de ventas/notas "
    "de crédito) — en un solo arrastre. **Nada se guarda**: vive solo en esta "
    "sesión y hay que volver a subirlo la próxima vez. Lo único que persiste son "
    "tus decisiones (categorías, vendedores, catálogo de cuentas contables)."
)

# ── Dispatch por estructura, no por nombre de archivo ──────────────────────────
# El orden importa poco: las 6 estructuras son mutuamente excluyentes en los
# archivos reales (verificado contra las muestras del repo). Se prueban SAE
# primero por ser los más frecuentes.
_CARGADORES = [
    ("compras", cargar_compras),
    ("ventas", cargar_ventas),
    ("facturacion", cargar_facturacion),
    ("libro", cargar_contabilidad),
    ("balanza", cargar_balanza),
    ("cfdi", cargar_cfdi),
]


def _detectar_y_cargar(contenido):
    """
    Prueba cada cargador en orden y se queda con el primero que no truene.
    Returns (tipo, resultado, warnings) o (None, None, None) si nadie lo
    reconoció — un archivo que nadie reconoce se reporta con su nombre, nunca
    se traga en silencio.
    """
    for tipo, cargador in _CARGADORES:
        try:
            resultado, warns = cargador(contenido)
            return tipo, resultado, warns
        except ValueError:
            continue
    return None, None, None


archivos = st.file_uploader(
    "Archivos",
    type=["xlsx", "xlsm", "xls"],
    accept_multiple_files=True,
    key="carga_uploader",
    label_visibility="collapsed",
)

if archivos and st.button("Cargar archivos", type="primary", key="carga_btn"):
    with st.spinner(f"Procesando {len(archivos)} archivo(s)…"):
        cargados = []
        no_reconocidos = []
        cfdi_partes, cfdi_warns, cfdi_nombres = [], [], []
        _ahora = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

        for archivo in archivos:
            try:
                tipo, resultado, warns = _detectar_y_cargar(archivo.getvalue())
            except Exception as e:
                st.error(f"Error al procesar «{archivo.name}»:\n\n{e}")
                continue

            if tipo is None:
                no_reconocidos.append(archivo.name)
                continue

            if tipo == "compras":
                st.session_state["df_compras"] = resultado
                st.session_state["df_compras_meta"] = {
                    "archivo": archivo.name, "uploaded_at": _ahora,
                    "total_rows": len(resultado), "warnings": warns,
                }
                cargados.append(f"{archivo.name} → Compras ({len(resultado):,} facturas)")

            elif tipo == "ventas":
                st.session_state["df_ventas"] = resultado
                st.session_state["df_ventas_meta"] = {
                    "archivo": archivo.name, "uploaded_at": _ahora,
                    "total_rows": len(resultado), "warnings": warns,
                }
                cargados.append(f"{archivo.name} → Ventas ({len(resultado):,} pedidos)")

            elif tipo == "facturacion":
                periodo = resultado["periodo"]
                if periodo is None:
                    st.error(
                        f"«{archivo.name}» no trae un periodo identificable "
                        f"(mes/año) en el nombre de su hoja — no se pudo acumular."
                    )
                    continue
                meses = st.session_state.setdefault("df_facturacion_meses", {})
                meses[periodo] = {
                    "bundle": resultado,
                    "meta": {
                        "archivo": archivo.name, "uploaded_at": _ahora,
                        "periodo": str(periodo), "warnings": warns,
                    },
                }
                # df_facturacion / _meta (singular) apuntan al mes MÁS RECIENTE
                # acumulado — es lo que pages/5_Facturacion.py sigue leyendo sin
                # cambios; el selector de mes real llega en una fase posterior.
                _ultimo = max(meses.keys())
                st.session_state["df_facturacion"] = meses[_ultimo]["bundle"]
                st.session_state["df_facturacion_meta"] = meses[_ultimo]["meta"]
                cargados.append(f"{archivo.name} → Facturación, periodo {periodo}")

            elif tipo == "libro":
                st.session_state["df_contabilidad"] = resultado
                st.session_state["df_contabilidad_meta"] = {
                    "archivo": archivo.name, "uploaded_at": _ahora,
                    "periodos": f"{resultado['_Mes'].min()} → {resultado['_Mes'].max()}",
                    "warnings": warns,
                }
                log_evento(
                    "contabilidad_carga",
                    f"{archivo.name}: {len(resultado)} movimientos, "
                    f"${resultado['Monto_MXN'].sum():,.0f}",
                )
                cargados.append(f"{archivo.name} → Libro contable")

            elif tipo == "balanza":
                st.session_state["df_balanza"] = resultado
                st.session_state["df_balanza_meta"] = {
                    "archivo": archivo.name, "uploaded_at": _ahora,
                    "periodos": f"{resultado['_Mes'].min()} → {resultado['_Mes'].max()}",
                    "warnings": warns,
                }
                log_evento(
                    "balanza_carga",
                    f"{archivo.name}: {resultado['Cuenta'].nunique()} cuentas",
                )
                cargados.append(f"{archivo.name} → Balanza de comprobación")

            elif tipo == "cfdi":
                cfdi_partes.append(resultado)
                cfdi_nombres.append(archivo.name)
                cfdi_warns.extend(f"[{archivo.name}] {w}" for w in warns)
                continue  # el aviso de warnings va agrupado abajo, con los otros CFDI

            for w in warns:
                st.warning(f"[{archivo.name}] {w}")

        if cfdi_partes:
            # Ventas y Notas de Crédito comparten estructura: si llegan los dos
            # en la misma carga, se concatenan en un solo df_cfdi — el
            # `Tipo_Doc` de cada fila ya los distingue.
            df_cfdi_all = pd.concat(cfdi_partes, ignore_index=True)
            st.session_state["df_cfdi"] = df_cfdi_all
            st.session_state["df_cfdi_meta"] = {
                "archivo": " + ".join(cfdi_nombres),
                "uploaded_at": _ahora,
                "periodos": f"{df_cfdi_all['_Mes'].min()} → {df_cfdi_all['_Mes'].max()}",
                "warnings": cfdi_warns,
            }
            log_evento(
                "cfdi_carga",
                f"{' + '.join(cfdi_nombres)}: {len(df_cfdi_all)} documentos",
            )
            cargados.append(f"{', '.join(cfdi_nombres)} → Reporte(s) CFDI")

        for nombre in no_reconocidos:
            st.error(
                f"No reconocí «{nombre}» — no coincide con la estructura de "
                f"ninguna de las fuentes que la app sabe leer (Compras, Ventas, "
                f"Facturación, libro contable, balanza o reporte CFDI)."
            )

        if cargados:
            st.success("✅ " + " · ".join(cargados))
            st.rerun()

st.divider()

# ── Claves de sesión por fuente, para "quitar" individualmente ────────────────
# cfdi_ventas y cfdi_notas comparten df_cfdi (el Tipo_Doc ya las distingue
# adentro), así que "quitar" cualquiera de las dos limpia el reporte completo.
_CLAVES_SESION = {
    "compras":      ["df_compras", "df_compras_meta"],
    "ventas":       ["df_ventas", "df_ventas_meta"],
    "facturacion":  ["df_facturacion", "df_facturacion_meta", "df_facturacion_meses"],
    "contabilidad": ["df_contabilidad", "df_contabilidad_meta"],
    "balanza":      ["df_balanza", "df_balanza_meta"],
    "cfdi_ventas":  ["df_cfdi", "df_cfdi_meta"],
    "cfdi_notas":   ["df_cfdi", "df_cfdi_meta"],
}


def _quitar(claves):
    for k in claves:
        st.session_state.pop(k, None)
    st.rerun()


# ── 7 tarjetas de estado ────────────────────────────────────────────────────
st.markdown("### Estado de las fuentes")
estado = estado_fuentes(st.session_state)

cols = st.columns(4)
for i, (clave, info) in enumerate(estado.items()):
    with cols[i % 4]:
        with st.container(border=True):
            if info["cargada"]:
                st.markdown(f"✅ **{info['label']}**")
                st.caption(info["archivo"] or "cargado")
                if info["cobertura"]:
                    st.caption(f"📅 {info['cobertura']}")
                st.caption(f"{info['filas']:,} fila(s)")
                if info["warnings"]:
                    with st.expander(f"⚠️ {len(info['warnings'])} aviso(s)"):
                        for w in info["warnings"]:
                            st.caption(w)
                if st.button("Quitar", key=f"quitar_{clave}", use_container_width=True):
                    _quitar(_CLAVES_SESION[clave])
            else:
                st.markdown(f"⭕ {info['label']}")
                st.caption("No cargado")

st.divider()

# ── Qué se podrá ver y qué no ───────────────────────────────────────────────
st.markdown("### Qué vas a poder ver con lo que subiste")
_VISTAS = {
    "compras":                "Compras",
    "ventas":                 "Ventas",
    "cuadre_contable":        "Cuadre Contable",
    "resultados_financieros": "Resultados Financieros",
    "facturacion":            "Facturación",
}
for vista, nombre in _VISTAS.items():
    falta = faltantes(vista, st.session_state)
    if not falta:
        st.success(f"✅ **{nombre}** — completo")
    else:
        # Un requisito puede ser una sola clave o una tupla ("cualquiera de
        # estas basta", p. ej. libro O balanza) — se muestra como "X o Y".
        faltan_labels = ", ".join(
            estado[c]["label"] if isinstance(c, str)
            else " o ".join(estado[x]["label"] for x in c)
            for c in falta
        )
        st.warning(f"⚠️ **{nombre}** — falta: {faltan_labels}")
st.caption(
    "Clasificaciones no depende de un archivo específico: siempre se puede "
    "entrar, aunque con menos que clasificar si no has cargado Compras/Ventas "
    "ni el libro contable."
)

st.divider()

# ── Base de datos y limpieza total ──────────────────────────────────────────
stats = get_stats()
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Proveedores clasificados", stats["total_clasificados"])
with c2:
    ultima = stats["ultima_modificacion"]
    st.metric("Última clasificación", str(ultima)[:10] if ultima else "—")
with c3:
    st.metric("Fuentes cargadas", f"{sum(1 for v in estado.values() if v['cargada'])} / 7")

if any(v["cargada"] for v in estado.values()):
    if st.button("🗑 Limpiar toda la sesión", use_container_width=False):
        todas = {k for claves in _CLAVES_SESION.values() for k in claves}
        for k in todas:
            st.session_state.pop(k, None)
        st.rerun()
