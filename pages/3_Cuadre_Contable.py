import pandas as pd
import streamlit as st

from core.catalogos import COLOR_LYON, COLOR_GASTOS_EMPRESA, label_mes
from core.conciliacion import (
    contabilidad_de_sesion, resumen_conciliacion, gasto_empresa_por_concepto,
    gasto_empresa_por_periodo, cuadre_balanza_vs_libro, ESTADOS, MES_SIN_LIBRO,
)
from core.database import get_cuentas_contables, init_db
from core.etl_balanza import totales_por_cuenta
from core.fuentes import kpi_card as _kpi, fmt_money, resumen_balanza, SIN_DATO
from core.navigation import (
    render_sidebar_search, render_sidebar_status, inject_custom_css, handle_pending_nav,
)
from core.plots import (
    plot_conciliacion_sae, plot_gasto_fuera_sae, plot_barras_gastos_empresa,
)

st.set_page_config(
    page_title="Cuadre Contable — Lyon AG",
    page_icon="🏦",
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
    "<span class='material-symbols-outlined'>account_balance</span>Cuadre Contable</h1>",
    unsafe_allow_html=True,
)

_GRAY  = "#9E9E9E"
_AMBER = "#E97132"
_GREEN = "#548235"


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
                st.session_state["_goto"] = "pages/6_Clasificaciones.py"
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
            f"**{len(_por_periodo)}** mes(es). Ya se refleja en Compras, Resultados "
            f"Financieros y Facturación mientras el libro siga cargado en esta sesión."
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

        # ── Tabla cuenta mayor x mes, tres renglones por cuenta ───────────────
        # Reemplaza al histograma: sumar todos los meses en una barra escondía
        # justo el patrón (una cuenta que descuadra todos los meses vs. una que
        # solo descuadra uno). Ordenada por el tamaño del hueco REAL — los pares
        # "Mes sin libro" no cuentan para ese orden, porque ausencia de archivo
        # no es un hueco que reclamarle a Contabilidad.
        st.markdown("#### Balanza vs. libro, cuenta mayor por mes")
        st.caption(
            "Cada cuenta mayor en tres renglones: lo que dice la balanza, lo que "
            "trae el libro, y su diferencia con signo (+ si la balanza es mayor, "
            "− si el libro es mayor). «—» significa que el libro no cubre ese "
            "mes — no es un descuadre, es que no hay con qué comparar todavía."
        )
        meses_orden = sorted(cuadre["_Mes"].unique())
        _comparables = cuadre[cuadre["Estado"] != MES_SIN_LIBRO]
        _peso_hueco = (
            _comparables.groupby(["Mayor", "Nombre_Oficial"])["Diferencia"]
            .apply(lambda s: float(s.abs().sum()))
        )
        _mayores = cuadre[["Mayor", "Nombre_Oficial"]].drop_duplicates()
        _mayores["_peso"] = [
            _peso_hueco.get((r.Mayor, r.Nombre_Oficial), 0.0)
            for r in _mayores.itertuples()
        ]
        _mayores = _mayores.sort_values("_peso", ascending=False)

        _idx = cuadre.set_index(["Mayor", "_Mes"])
        filas_tabla = []
        for r in _mayores.itertuples():
            etiqueta = f"{r.Mayor} · {r.Nombre_Oficial}"
            fila_bal = {"Cuenta": etiqueta, "Fuente": "Balanza"}
            fila_lib = {"Cuenta": etiqueta, "Fuente": "Libro"}
            fila_dif = {"Cuenta": etiqueta, "Fuente": "Diferencia"}
            for m in meses_orden:
                col = label_mes(m)
                try:
                    fila_cuadre = _idx.loc[(r.Mayor, m)]
                except KeyError:
                    fila_cuadre = None
                if fila_cuadre is None or fila_cuadre["Estado"] == MES_SIN_LIBRO:
                    fila_bal[col] = SIN_DATO
                    fila_lib[col] = SIN_DATO
                    fila_dif[col] = SIN_DATO
                else:
                    fila_bal[col] = f"${fila_cuadre['Balanza']:,.0f}"
                    fila_lib[col] = f"${fila_cuadre['Libro']:,.0f}"
                    d = float(fila_cuadre["Diferencia"])
                    signo = "+" if d > 0 else ("−" if d < 0 else "")
                    fila_dif[col] = f"{signo}${abs(d):,.0f}"
            filas_tabla.extend([fila_bal, fila_lib, fila_dif])

        with st.container(border=True):
            st.dataframe(
                pd.DataFrame(filas_tabla),
                use_container_width=True, hide_index=True,
                height=min(600, 45 + 36 * len(filas_tabla)),
            )

    # ── Las tres cifras de clasificación, también para la balanza ─────────────
    # Espejo de las que ya tiene el libro en _render_conciliacion: un total
    # parcial sin su pendiente al lado es un número engañoso. Esta sección no
    # depende de tener el libro cargado — solo de la balanza.
    st.markdown("#### Clasificación de las cuentas (balanza)")
    _res_bal = resumen_balanza(df_balanza)
    cb1, cb2, cb3 = st.columns(3)
    cb1.markdown(_kpi(
        "Gasto operativo", fmt_money(_res_bal["gasto_operativo"]), COLOR_LYON,
        "Cuentas auxiliares de la balanza que marcaste como gasto del periodo",
    ), unsafe_allow_html=True)
    cb2.markdown(_kpi(
        "No operativo", fmt_money(_res_bal["no_operativo"]), _GRAY,
        "Anticipos, depreciación/amortización y otros movimientos de balance",
    ), unsafe_allow_html=True)
    cb3.markdown(_kpi(
        "Sin clasificar", fmt_money(_res_bal["sin_clasificar"]), _AMBER,
        "Todavía no cuentan para nada. Clasifícalas en Clasificaciones",
    ), unsafe_allow_html=True)

    # ── Lo que solo tiene una fuente, lado a lado ─────────────────────────────
    st.markdown("#### Lo que solo reporta una fuente")
    st.caption(
        "Cuentas que una fuente nunca menciona, o meses que el libro no cubre "
        "en absoluto. Ninguna de las dos es un error — son huecos estructurales "
        "entre lo que cada archivo sabe reportar."
    )
    _cuentas_oficiales = (
        df_balanza.drop_duplicates("Cuenta", keep="last")
        .set_index("Cuenta")["Nombre_Oficial"].to_dict()
    )
    _catalogo = get_cuentas_contables()
    _bal_cta = totales_por_cuenta(df_balanza).groupby("Cuenta")["Debe"].sum()

    col_izq, col_der = st.columns(2)
    with col_izq:
        st.markdown("**Solo en la balanza**")
        if df_libro is None:
            st.caption("Sube también el libro para ver esta comparación.")
        else:
            lib_cta = df_libro.groupby("Cuenta")["Monto_MXN"].sum()
            _solo_bal_estructural = sorted(set(_bal_cta.index) - set(lib_cta.index))
            filas_izq = [
                {
                    "Cuenta": c, "Nombre": _cuentas_oficiales.get(c, c),
                    "Motivo": "Cuenta fuera del libro (todo el periodo)",
                    "Monto": float(_bal_cta[c]),
                }
                for c in _solo_bal_estructural
            ]
            _meses_solo_bal = sorted(set(df_balanza["_Mes"].unique()) - meses_libro, key=str)
            if _meses_solo_bal:
                _tmp = totales_por_cuenta(df_balanza, periodos=_meses_solo_bal)
                _tmp = _tmp[~_tmp["Cuenta"].isin(_solo_bal_estructural)]
                _rango = f"{label_mes(_meses_solo_bal[0])}–{label_mes(_meses_solo_bal[-1])}"
                _tmp_g = _tmp.groupby(["Cuenta", "Nombre_Oficial"], as_index=False)["Debe"].sum()
                for r in _tmp_g.itertuples():
                    filas_izq.append({
                        "Cuenta": r.Cuenta, "Nombre": r.Nombre_Oficial,
                        "Motivo": f"Mes fuera del libro ({_rango})",
                        "Monto": float(r.Debe),
                    })
            if not filas_izq:
                st.success("Nada — todo lo que reporta la balanza también está en el libro.")
            else:
                df_izq = pd.DataFrame(filas_izq).sort_values("Monto", ascending=False)
                st.dataframe(
                    df_izq, use_container_width=True, hide_index=True,
                    column_config={"Monto": st.column_config.NumberColumn(format="$%,.2f")},
                    height=min(360, 45 + 36 * min(len(df_izq), 8)),
                )
                st.caption(f"Total: **{fmt_money(df_izq['Monto'].sum())}**")

    with col_der:
        st.markdown("**Solo en el libro**")
        if df_libro is None:
            st.caption("Sube también el libro para ver esta comparación.")
        else:
            lib_cta = df_libro.groupby("Cuenta")["Monto_MXN"].sum()
            _solo_lib = sorted(set(lib_cta.index) - set(_bal_cta.index))
            if not _solo_lib:
                st.success("Nada — todo lo que trae el libro también está en la balanza.")
            else:
                filas_der = [
                    {
                        "Cuenta": c,
                        "Nombre": (_catalogo.get(c) or {}).get("nombre") or c,
                        "Monto": float(lib_cta[c]),
                    }
                    for c in _solo_lib
                ]
                df_der = pd.DataFrame(filas_der).sort_values("Monto", ascending=False)
                st.dataframe(
                    df_der, use_container_width=True, hide_index=True,
                    column_config={"Monto": st.column_config.NumberColumn(format="$%,.2f")},
                    height=min(360, 45 + 36 * min(len(df_der), 8)),
                )
                st.caption(f"Total: **{fmt_money(df_der['Monto'].sum())}**")


# ══════════════════════════════════════════════════════════════════════════════
#  Contenido — la carga vive en Carga de Archivos
# ══════════════════════════════════════════════════════════════════════════════
df_conc     = contabilidad_de_sesion()
df_balanza  = st.session_state.get("df_balanza")
df_cfdi     = st.session_state.get("df_cfdi")

if df_conc is None and df_balanza is None and df_cfdi is None:
    st.info(
        "Todavía no hay ningún archivo de Contabilidad cargado en esta sesión. "
        "Súbelos en **Carga de Archivos** para ver la conciliación contra el SAE."
    )
    if st.button("Ir a Carga de Archivos", type="primary"):
        st.switch_page("app.py")
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
