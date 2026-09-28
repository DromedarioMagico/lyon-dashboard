import datetime as dt

import pandas as pd
import streamlit as st

from core.catalogos import COLOR_LYON, COLOR_GASTOS_EMPRESA, label_mes
from core.conciliacion import (
    contabilidad_de_sesion, resumen_conciliacion, gasto_empresa_por_concepto,
    gasto_empresa_por_periodo, cuadre_balanza_vs_libro, ESTADOS,
)
from core.database import init_db, log_evento
from core.etl_balanza import cargar_balanza, totales_por_mayor
from core.etl_cfdi import cargar_cfdi
from core.etl_contabilidad import cargar_contabilidad
from core.navigation import (
    render_sidebar_search, render_sidebar_status, inject_custom_css, handle_pending_nav,
)
from core.plots import (
    plot_conciliacion_sae, plot_gasto_fuera_sae, plot_barras_gastos_empresa,
    plot_cuadre_balanza,
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

_GRAY  = "#9E9E9E"
_AMBER = "#E97132"
_GREEN = "#548235"


def _kpi(label, value, color, desc=None):
    """Tarjeta KPI — misma gramática visual que Compras y Facturación."""
    tip = (
        f"<div style='font-size:.7rem;color:#6B7280;margin-top:.25rem'>{desc}</div>"
        if desc else ""
    )
    return (
        "<div style='border:1px solid #E5E7EB;border-radius:8px;padding:.7rem .9rem;"
        "background:#fff;height:100%'>"
        f"<div style='font-size:.75rem;color:#6B7280'>{label}</div>"
        f"<div style='font-size:1.5rem;font-weight:700;color:{color}'>{value}</div>"
        f"{tip}</div>"
    )


def _render_conciliacion(df_conc):
    """Conciliación del libro contable de la sesión contra las compras del SAE."""
    df_compras = st.session_state.get("df_compras")
    res        = resumen_conciliacion(df_conc)

    _meta = st.session_state.get("df_contabilidad_meta", {})
    st.caption(
        f"**{res['n_movimientos']:,}** movimientos · **{res['n_cuentas']}** cuentas · "
        f"periodos {_meta.get('periodos', '—')} · {_meta.get('archivo', '—')} "
        f"(cargado {_meta.get('uploaded_at', '—')})"
    )

    if df_compras is None:
        st.warning(
            "**Compras no está cargado**, así que no se puede saber qué movimientos ya "
            "pasaron por el SAE. Todo aparece como «Sin comparar» y nada se publica "
            "automáticamente. Carga el archivo de Compras para la conciliación real."
        )

    # ── Banner de cuentas sin clasificar ──────────────────────────────────────
    if res["n_cuentas_sin_clasificar"]:
        b1, b2 = st.columns([5, 1])
        with b1:
            st.warning(
                f"**{res['n_cuentas_sin_clasificar']} cuenta(s) contable(s) sin "
                f"clasificar** — ${res['sin_clasificar']/1e6:,.2f}M del libro todavía "
                f"**no cuentan como gasto**. Nómbralas y márcalas en el catálogo para "
                f"que entren al costo operativo.\n\n"
                f"Si ya las marcaste y sigue apareciendo este aviso: los cambios de la "
                f"tabla del catálogo **no se guardan solos**, hay que presionar "
                f"«Guardar catálogo de cuentas». El propio catálogo te dice cuántas "
                f"están guardadas en la base."
            )
        with b2:
            st.markdown("<div style='padding-top:.6rem'></div>", unsafe_allow_html=True)
            if st.button("Ir al catálogo →", key="ctb_btn_catalogo",
                         use_container_width=True):
                st.session_state["_goto"] = "pages/4_Clasificaciones.py"
                st.rerun()

    # ── KPIs ──────────────────────────────────────────────────────────────────
    st.markdown("#### Conciliación contra el SAE")
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_kpi(
        "Gasto contable total", f"${res['total']/1e6:,.2f}M", COLOR_LYON,
        "Todo lo que reportó Contabilidad en el libro cargado",
    ), unsafe_allow_html=True)
    k2.markdown(_kpi(
        "Ya está en el SAE", f"${res['en_sae']/1e6:,.2f}M", _GREEN,
        "Mismo proveedor y mismo mes — ya lo cuenta Compras",
    ), unsafe_allow_html=True)
    k3.markdown(_kpi(
        "Fuera del SAE", f"${res['fuera_de_sae']/1e6:,.2f}M", COLOR_GASTOS_EMPRESA,
        "Proveedor que nunca aparece en Compras — esto es Gasto de Empresa",
    ), unsafe_allow_html=True)
    k4.markdown(_kpi(
        "Por revisar", f"${(res['por_revisar'] + res['mes_sin_sae'])/1e6:,.2f}M", _AMBER,
        "Proveedor del SAE pero en otro mes, o meses que el archivo de Compras no cubre",
    ), unsafe_allow_html=True)

    st.markdown("#### Clasificación de las cuentas")
    c1, c2, c3 = st.columns(3)
    c1.markdown(_kpi(
        "Gasto operativo", f"${res['gasto_operativo']/1e6:,.2f}M", COLOR_LYON,
        "Cuentas que marcaste como gasto del periodo",
    ), unsafe_allow_html=True)
    c2.markdown(_kpi(
        "No operativo", f"${res['no_operativo']/1e6:,.2f}M", _GRAY,
        "Anticipos y movimientos de balance — no tocan el margen",
    ), unsafe_allow_html=True)
    c3.markdown(_kpi(
        "Sin clasificar", f"${res['sin_clasificar']/1e6:,.2f}M", _AMBER,
        "Todavía no cuentan para nada. Clasifícalas en el catálogo",
    ), unsafe_allow_html=True)

    with st.container(border=True):
        st.plotly_chart(plot_conciliacion_sae(res), use_container_width=True)

    with st.container(border=True):
        st.caption(
            "A quién se le paga sin que pase por una orden de compra. No todo es un "
            "problema —la nómina nunca va a pasar por el SAE— pero un proveedor de "
            "insumos en esta lista sí lo es."
        )
        st.plotly_chart(plot_gasto_fuera_sae(df_conc), use_container_width=True)

    # ── Desglose por cuenta ───────────────────────────────────────────────────
    with st.container(border=True):
        st.caption(
            "El libro contable agrupado por cuenta, con el nombre que le pusiste en "
            "el catálogo."
        )
        _por_cuenta = (
            df_conc.groupby("Cuenta_Nombre")["Monto_MXN"].sum()
            .sort_values(ascending=False).to_dict()
        )
        st.plotly_chart(
            plot_barras_gastos_empresa(_por_cuenta, res["total"]),
            use_container_width=True,
        )

    # ── Detalle de movimientos ────────────────────────────────────────────────
    st.markdown("#### Detalle de movimientos")
    f1, f2, f3 = st.columns([2, 2, 3])
    with f1:
        estados_pres = [e for e in ESTADOS if (df_conc["Estado_SAE"] == e).any()]
        est_sel = st.multiselect(
            "Estado", estados_pres, key="ctb_f_estado",
        )
    with f2:
        cta_sel = st.multiselect(
            "Cuenta", sorted(df_conc["Cuenta_Nombre"].unique()), key="ctb_f_cuenta",
        )
    with f3:
        busq = st.text_input(
            "Buscar proveedor o descripción", key="ctb_f_busq",
            placeholder="ej. nómina, flete, Tresguerras…",
        )

    tabla = df_conc.copy()
    if est_sel:
        tabla = tabla[tabla["Estado_SAE"].isin(est_sel)]
    if cta_sel:
        tabla = tabla[tabla["Cuenta_Nombre"].isin(cta_sel)]
    if busq:
        _m = (
            tabla["Proveedor"].str.contains(busq, case=False, na=False)
            | tabla["Descripcion"].str.contains(busq, case=False, na=False)
        )
        tabla = tabla[_m]

    st.caption(
        f"{len(tabla):,} movimiento(s) · ${tabla['Monto_MXN'].sum()/1e6:,.2f}M en pantalla"
    )
    _vista = tabla.sort_values("Monto_MXN", ascending=False).head(500).copy()
    _vista["Mes"] = [label_mes(m) for m in _vista["_Mes"]]
    st.dataframe(
        _vista[["Mes", "Cuenta", "Cuenta_Nombre", "Proveedor", "Monto_MXN",
                "Estado_SAE", "Naturaleza", "Descripcion"]],
        use_container_width=True, hide_index=True,
        column_config={
            "Cuenta_Nombre": st.column_config.TextColumn("Nombre de cuenta"),
            "Monto_MXN":     st.column_config.NumberColumn("Monto", format="$%,.2f"),
            "Estado_SAE":    st.column_config.TextColumn("Estado"),
            "Descripcion":   st.column_config.TextColumn("Descripción", width="large"),
        },
        height=min(520, 45 + 36 * min(len(_vista), 12)),
    )
    if len(tabla) > 500:
        st.caption("Se muestran los 500 movimientos de mayor monto. Usa los filtros.")

    # ── Lo que cuenta como Gasto de Empresa ───────────────────────────────────
    st.divider()
    st.markdown("#### Lo que entra como Gasto de Empresa")
    st.caption(
        "Solo entra lo que está **fuera del SAE** y cuya cuenta marcaste como **gasto "
        "operativo**. Lo que quedó «Por revisar» no entra: ahí el dato no alcanza "
        "para afirmar que el gasto no pasó por compras, y contarlo duplicaría lo que "
        "Compras ya muestra. Se calcula al vuelo — no hay nada que publicar ni "
        "guardar, y cambiar el catálogo se refleja de inmediato."
    )

    _por_concepto = gasto_empresa_por_concepto(df_conc)
    if not _por_concepto:
        st.info(
            "Todavía no hay nada que cuente como Gasto de Empresa. "
            + (
                "Clasifica las cuentas en el catálogo para que su gasto cuente."
                if res["n_cuentas_sin_clasificar"]
                else "Ningún movimiento quedó fuera del SAE con una cuenta de gasto."
            )
        )
    else:
        _por_periodo = gasto_empresa_por_periodo(df_conc)
        prev = pd.DataFrame(
            sorted(_por_concepto.items(), key=lambda kv: -kv[1]),
            columns=["Concepto", "Monto"],
        )
        total_ge = float(prev["Monto"].sum())
        st.dataframe(
            prev, use_container_width=True, hide_index=True,
            column_config={
                "Monto": st.column_config.NumberColumn("Monto", format="$%,.2f"),
            },
            height=min(400, 45 + 36 * min(len(prev), 9)),
        )
        st.caption(
            f"**${total_ge/1e6:,.2f}M** en **{len(prev)}** concepto(s), repartidos en "
            f"**{len(_por_periodo)}** mes(es). Ya se refleja en Compras, Comparativa "
            f"y Facturación mientras el libro siga cargado en esta sesión."
        )


def _render_cuadre_balanza(df_balanza):
    """
    Cuadre contra la Balanza de Comprobación: lo que dice el resumen oficial de
    Contabilidad contra lo que trae el libro de movimientos, mayor por mayor. No
    corrige ni decide cuál fuente tiene razón — solo expone el hueco con la cifra
    exacta, para reclamárselo a Contabilidad.
    """
    st.divider()
    st.markdown("### Cuadre contra la balanza de comprobación")
    st.caption(
        "La balanza es el resumen oficial y auditado de Contabilidad, con el nombre "
        "real de cada cuenta. Aquí se compara contra el libro de movimientos, mes por "
        "mes y cuenta mayor por cuenta mayor."
    )

    _meta_bal = st.session_state.get("df_balanza_meta", {})
    st.caption(
        f"**{df_balanza['Cuenta'].nunique()}** cuentas · periodos "
        f"{_meta_bal.get('periodos', '—')} · {_meta_bal.get('archivo', '—')} "
        f"(cargado {_meta_bal.get('uploaded_at', '—')})"
    )

    df_libro = st.session_state.get("df_contabilidad")

    if df_libro is None:
        st.info(
            "Sube también el libro de movimientos para comparar contra la balanza. "
            "Mientras tanto, solo se puede mostrar lo que reporta la balanza."
        )
        meses_libro = set()
        cuadre = None
    else:
        meses_libro = set(df_libro["_Mes"].unique())
        cuadre = cuadre_balanza_vs_libro(df_balanza, df_libro)

    if cuadre is not None and len(cuadre):
        gasto_bal = float(cuadre["Balanza"].sum())
        gasto_lib = float(cuadre["Libro"].sum())
        dif = gasto_bal - gasto_lib
        meses_bal = set(df_balanza["_Mes"].unique())
        meses_solo_balanza = sorted(meses_bal - meses_libro, key=str)

        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(_kpi(
            "Gasto según balanza", f"${gasto_bal/1e6:,.2f}M", COLOR_LYON,
        ), unsafe_allow_html=True)
        k2.markdown(_kpi(
            "Gasto según el libro", f"${gasto_lib/1e6:,.2f}M", COLOR_GASTOS_EMPRESA,
        ), unsafe_allow_html=True)
        k3.markdown(_kpi(
            "Diferencia", f"${dif/1e6:,.2f}M",
            _GREEN if abs(dif) <= 1.0 else "#C00000",
        ), unsafe_allow_html=True)
        k4.markdown(_kpi(
            "Meses solo en balanza", str(len(meses_solo_balanza)),
            _GREEN if not meses_solo_balanza else _AMBER,
        ), unsafe_allow_html=True)

        with st.container(border=True):
            st.plotly_chart(plot_cuadre_balanza(cuadre), use_container_width=True)

        with st.expander("Ver el detalle mayor por mayor y mes"):
            tabla = cuadre.copy()
            tabla["Mes"] = [label_mes(m) for m in tabla["_Mes"]]
            st.dataframe(
                tabla[["Mes", "Mayor", "Nombre_Oficial", "Balanza", "Libro",
                       "Diferencia", "Estado"]]
                .sort_values("Diferencia", key=lambda s: s.abs(), ascending=False),
                use_container_width=True, hide_index=True,
                column_config={
                    "Nombre_Oficial": st.column_config.TextColumn("Cuenta mayor"),
                    "Balanza": st.column_config.NumberColumn(format="$%,.2f"),
                    "Libro": st.column_config.NumberColumn(format="$%,.2f"),
                    "Diferencia": st.column_config.NumberColumn(format="$%,.2f"),
                },
                height=min(480, 45 + 36 * min(len(tabla), 12)),
            )

        # ── Gasto que la balanza trae y el libro nunca manda ──────────────────
        # Se detecta por patrón (Libro = 0 en TODOS los periodos comparados), no
        # por código de cuenta a la fuerza — así se generaliza si en el futuro
        # aparece otra cuenta que el libro nunca cubra, sin tocar código.
        por_mayor = (
            cuadre.groupby(["Mayor", "Nombre_Oficial"], as_index=False)
            [["Balanza", "Libro"]].sum()
        )
        nunca_en_libro = por_mayor[por_mayor["Libro"] == 0.0]
        if len(nunca_en_libro) and nunca_en_libro["Balanza"].sum() > 0:
            st.markdown("#### Gasto que no está en el margen")
            st.caption(
                "Estas cuentas mayor aparecen en la balanza pero el libro de "
                "movimientos nunca las manda — por su naturaleza, no generan "
                "proveedor ni orden de compra (depreciación, amortización…). "
                "**No cuentan** en el Costo Operativo de Compras ni en el Margen "
                "Operativo: es una decisión explícita, no un olvido. Se muestran "
                "aquí para que el monto no quede invisible."
            )
            st.dataframe(
                nunca_en_libro[["Mayor", "Nombre_Oficial", "Balanza"]]
                .rename(columns={"Balanza": "Monto (fuera del margen)"})
                .sort_values("Monto (fuera del margen)", ascending=False),
                use_container_width=True, hide_index=True,
                column_config={
                    "Monto (fuera del margen)": st.column_config.NumberColumn(format="$%,.2f"),
                },
            )

    # ── Meses que solo tiene la balanza (p. ej. antes de que empezara el libro) ──
    meses_bal_todos = sorted(set(df_balanza["_Mes"].unique()) - meses_libro, key=str)
    if meses_bal_todos:
        st.markdown(f"#### {label_mes(meses_bal_todos[0])} – {label_mes(meses_bal_todos[-1])} (solo balanza)")
        st.caption(
            "Estos meses no están en el libro de movimientos, así que no traen "
            "detalle de proveedor y **no entran a la conciliación contra el SAE**. "
            "Es el total que reporta la balanza, para que estos meses no queden "
            "completamente invisibles."
        )
        tot_solo = totales_por_mayor(df_balanza, periodos=meses_bal_todos)
        resumen = (
            tot_solo.groupby(["Mayor", "Nombre_Oficial"], as_index=False)["Debe"].sum()
            .sort_values("Debe", ascending=False)
            .rename(columns={"Debe": "Gasto"})
        )
        st.dataframe(
            resumen,
            use_container_width=True, hide_index=True,
            column_config={"Gasto": st.column_config.NumberColumn(format="$%,.2f")},
        )
        st.caption(f"Total: **${resumen['Gasto'].sum()/1e6:,.2f}M**")


# ══════════════════════════════════════════════════════════════════════════════
#  Carga de los archivos de Contabilidad
# ══════════════════════════════════════════════════════════════════════════════
st.caption(
    "Sube aquí todo lo que te manda Contabilidad — el libro de movimientos, la "
    "balanza de comprobación y/o los reportes de ventas y notas de crédito — "
    "junto, en un solo arrastre. La app detecta cuál es cuál por su estructura, "
    "no por el nombre del archivo. Igual que el SAE, **nada de esto se guarda**: "
    "vive solo en esta sesión y hay que volver a subirlo la próxima vez. Lo único "
    "que se guarda son tus decisiones del catálogo de cuentas."
)

# El orden importa poco (las tres estructuras son mutuamente excluyentes en los
# archivos reales), pero se prueba primero el libro por ser el más frecuente.
_CARGADORES = [
    ("libro", cargar_contabilidad),
    ("balanza", cargar_balanza),
    ("cfdi", cargar_cfdi),
]


def _detectar_y_cargar(contenido):
    """
    Prueba cada cargador en orden y se queda con el primero que no truene. Cada
    `cargar_*` ya sabe reconocer su propia estructura (columnas/encabezado) y
    levanta ValueError si el archivo no le corresponde — reusar esa detección
    evita mantener un sniffer aparte que se pueda desalinear de los ETL reales.
    Returns (tipo, df, warnings) o (None, None, None) si nadie lo reconoció.
    """
    for tipo, cargador in _CARGADORES:
        try:
            df, warns = cargador(contenido)
            return tipo, df, warns
        except ValueError:
            continue
    return None, None, None


_hay_algo_cargado = any(
    k in st.session_state for k in ("df_contabilidad", "df_balanza", "df_cfdi")
)

with st.expander(
    "📥 Cargar archivos de Contabilidad", expanded=not _hay_algo_cargado,
):
    archivos = st.file_uploader(
        "Archivos de Contabilidad",
        type=["xlsx", "xlsm"],
        accept_multiple_files=True,
        key="ctb_uploader",
        label_visibility="collapsed",
    )
    st.caption(
        "Libro de movimientos: columnas `MES`, `CUENTA CONTABLE`, `PROVEEDOR`, "
        "`MONTO`. Balanza: encabezado `No. de cuenta` con bloques Saldo/Debe/"
        "Haber por mes. Ventas o Notas de Crédito: columnas `Serie y Folio`, "
        "`UUID`, `Subtotal`, `Tipo`."
    )
    if archivos and st.button(
        "Cargar archivos", type="primary", key="ctb_btn_cargar"
    ):
        with st.spinner(f"Procesando {len(archivos)} archivo(s)…"):
            cargados = []
            no_reconocidos = []
            cfdi_partes, cfdi_warns, cfdi_nombres = [], [], []

            for archivo in archivos:
                try:
                    tipo, df_x, warns = _detectar_y_cargar(archivo.getvalue())
                except Exception as e:
                    st.error(f"Error al procesar «{archivo.name}»:\n\n{e}")
                    continue

                if tipo is None:
                    no_reconocidos.append(archivo.name)
                    continue

                _ahora = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

                if tipo == "libro":
                    st.session_state["df_contabilidad"] = df_x
                    st.session_state["df_contabilidad_meta"] = {
                        "archivo": archivo.name, "uploaded_at": _ahora,
                        "periodos": f"{df_x['_Mes'].min()} → {df_x['_Mes'].max()}",
                    }
                    log_evento(
                        "contabilidad_carga",
                        f"{archivo.name}: {len(df_x)} movimientos, "
                        f"${df_x['Monto_MXN'].sum():,.0f}",
                    )
                    cargados.append(f"{archivo.name} → libro de movimientos")
                elif tipo == "balanza":
                    st.session_state["df_balanza"] = df_x
                    st.session_state["df_balanza_meta"] = {
                        "archivo": archivo.name, "uploaded_at": _ahora,
                        "periodos": f"{df_x['_Mes'].min()} → {df_x['_Mes'].max()}",
                    }
                    log_evento(
                        "balanza_carga",
                        f"{archivo.name}: {df_x['Cuenta'].nunique()} cuentas",
                    )
                    cargados.append(f"{archivo.name} → balanza de comprobación")
                elif tipo == "cfdi":
                    cfdi_partes.append(df_x)
                    cfdi_nombres.append(archivo.name)
                    cfdi_warns.extend(f"[{archivo.name}] {w}" for w in warns)
                    continue  # el aviso de warnings va agrupado abajo

                for w in warns:
                    st.warning(f"[{archivo.name}] {w}")

            if cfdi_partes:
                # Ventas y Notas de Crédito comparten estructura: si llegan los
                # dos en la misma carga, se concatenan en un solo df_cfdi — el
                # `Tipo_Doc` de cada fila ya los distingue.
                df_cfdi_all = pd.concat(cfdi_partes, ignore_index=True)
                st.session_state["df_cfdi"] = df_cfdi_all
                st.session_state["df_cfdi_meta"] = {
                    "archivo": " + ".join(cfdi_nombres),
                    "uploaded_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "periodos": (
                        f"{df_cfdi_all['_Mes'].min()} → {df_cfdi_all['_Mes'].max()}"
                    ),
                }
                log_evento(
                    "cfdi_carga",
                    f"{' + '.join(cfdi_nombres)}: {len(df_cfdi_all)} documentos",
                )
                cargados.append(f"{', '.join(cfdi_nombres)} → reporte(s) CFDI")
                for w in cfdi_warns:
                    st.warning(w)

            for nombre in no_reconocidos:
                st.error(
                    f"No reconocí «{nombre}» — no coincide con la estructura del "
                    f"libro, la balanza ni un reporte CFDI de Contabilidad."
                )

            if cargados:
                st.success("✅ " + " · ".join(cargados))
                st.rerun()

df_conc     = contabilidad_de_sesion()
df_balanza  = st.session_state.get("df_balanza")
df_cfdi     = st.session_state.get("df_cfdi")

if df_conc is None and df_balanza is None and df_cfdi is None:
    st.info(
        "Todavía no hay ningún archivo de Contabilidad cargado en esta sesión. "
        "Súbelos arriba para ver la conciliación contra el SAE."
    )
else:
    if df_conc is not None:
        _render_conciliacion(df_conc)

    if df_balanza is not None:
        _render_cuadre_balanza(df_balanza)

    if df_cfdi is not None:
        st.divider()
        _meta_cfdi = st.session_state.get("df_cfdi_meta", {})
        st.info(
            f"**Reporte(s) CFDI cargado(s):** {len(df_cfdi):,} documento(s) · "
            f"periodo {_meta_cfdi.get('periodos', '—')}. El detalle del año "
            f"facturado, cancelaciones y forma de cobro está en **Facturación**."
        )

    st.divider()
    if st.button("🗑 Quitar los archivos de Contabilidad de esta sesión"):
        for k in (
            "df_contabilidad", "df_contabilidad_meta",
            "df_balanza", "df_balanza_meta",
            "df_cfdi", "df_cfdi_meta",
        ):
            st.session_state.pop(k, None)
        st.rerun()
