"""
Conciliación entre el libro de Contabilidad y las compras del SAE.

La pregunta que contesta: de todo lo que Contabilidad reportó como gasto, ¿qué parte
pasó por el proceso de compras y qué parte no? Lo que no pasó por el SAE es lo que
debe registrarse como Gasto de Empresa, sin captura manual.

Sin dependencias de Streamlit.
"""

from core.etl_contabilidad import normalizar_proveedor

# Estados de conciliación por movimiento contable.
EN_SAE       = "En SAE"
OTRO_MES     = "Por revisar"
FUERA_DE_SAE = "Fuera de SAE"
MES_SIN_SAE  = "Mes sin SAE"
SIN_COMPARAR = "Sin comparar"

ESTADOS = [EN_SAE, FUERA_DE_SAE, OTRO_MES, MES_SIN_SAE, SIN_COMPARAR]

# Naturaleza de la cuenta contable — la decide el usuario en el catálogo.
NAT_SIN_CLASIFICAR = "Sin clasificar"
NAT_GASTO          = "Gasto operativo"
NAT_NO_OPERATIVO   = "No operativo"
NATURALEZAS = [NAT_SIN_CLASIFICAR, NAT_GASTO, NAT_NO_OPERATIVO]

# Override por cuenta, para cuando el cruce automático no aplica.
TRATO_AUTO   = "Auto"
TRATO_SIEMPRE = "Siempre GE"
TRATO_NUNCA   = "Nunca GE"
TRATOS = [TRATO_AUTO, TRATO_SIEMPRE, TRATO_NUNCA]


def conciliar_con_sae(df_ctb, df_compras=None):
    """
    Marca cada movimiento contable con su Estado_SAE.

    - `En SAE`       el proveedor coincide y el mes también → ya está contado en
                     Compras, no se vuelve a contar.
    - `Por revisar`  el proveedor existe en el SAE pero el movimiento cae en otro mes
                     → diferencia de temporalidad, la decide el usuario.
    - `Fuera de SAE` el proveedor nunca aparece en el SAE → gasto que no pasa por el
                     proceso de compras.
    - `Mes sin SAE`  el mes contable no existe en el archivo de Compras cargado.
                     No se puede concluir nada: ahí "no aparece en el SAE" solo
                     significa que el SAE no llega hasta ese mes. Se separa a
                     propósito para no publicar gasto que en realidad sí pasó por
                     compras, solo que en un archivo que no se cargó.
    - `Sin comparar` no hay archivo de Compras cargado; no se asume nada.

    Devuelve una copia de df_ctb con la columna Estado_SAE.
    """
    df = df_ctb.copy()

    if df_compras is None or len(df_compras) == 0:
        df["Estado_SAE"] = SIN_COMPARAR
        return df

    sae = df_compras[["Proveedor", "_Mes"]].copy()
    sae["_norm"] = sae["Proveedor"].map(normalizar_proveedor)
    sae = sae[sae["_norm"] != ""]

    provs_sae = set(sae["_norm"])
    pares_sae = set(zip(sae["_norm"], sae["_Mes"].astype(str)))
    meses_sae = set(sae["_Mes"].astype(str))

    estados = []
    for norm, mes in zip(df["Proveedor_Norm"], df["_Mes"].astype(str)):
        if (norm, mes) in pares_sae:
            estados.append(EN_SAE)
        elif mes not in meses_sae:
            estados.append(MES_SIN_SAE)
        elif not norm:
            estados.append(FUERA_DE_SAE)
        elif norm in provs_sae:
            estados.append(OTRO_MES)
        else:
            estados.append(FUERA_DE_SAE)

    df["Estado_SAE"] = estados
    return df


def aplicar_catalogo_cuentas(df_ctb, cuentas):
    """
    Enriquece los movimientos con el catálogo de cuentas contables.

    `cuentas` es el dict de `database.get_cuentas_contables()`:
    {cuenta: {"nombre", "categoria", "naturaleza", "trato", "notas"}}.

    Una cuenta que no está en el catálogo nace `Sin clasificar` y no cuenta como
    gasto hasta que el usuario la nombre — es una decisión explícita del usuario:
    nada entra al margen sin que alguien lo haya visto.
    """
    df = df_ctb.copy()
    cuentas = cuentas or {}

    nombres, cats, nats, tratos = [], [], [], []
    for cta in df["Cuenta"]:
        info = cuentas.get(cta)
        if info:
            nombres.append(info.get("nombre") or cta)
            cats.append(info.get("categoria") or "Otros / Sin clasificar")
            nats.append(info.get("naturaleza") or NAT_SIN_CLASIFICAR)
            tratos.append(info.get("trato") or TRATO_AUTO)
        else:
            nombres.append(cta)
            cats.append("Otros / Sin clasificar")
            nats.append(NAT_SIN_CLASIFICAR)
            tratos.append(TRATO_AUTO)

    df["Cuenta_Nombre"] = nombres
    df["Categoria"]     = cats
    df["Naturaleza"]    = nats
    df["Trato"]         = tratos
    return df


def marcar_publicables(df):
    """
    Agrega `Publicable`: si el movimiento debe entrar a Gastos de Empresa.

    Regla: la cuenta tiene que ser gasto operativo **y** el movimiento no debe estar
    ya contado en el SAE. `Siempre GE` / `Nunca GE` en el catálogo ganan sobre el
    cruce automático, pero nunca sobre la naturaleza — una cuenta sin clasificar no
    entra por ningún camino.

    `Por revisar` y `Mes sin SAE` tampoco entran solos: en ambos casos el dato no
    alcanza para afirmar que el gasto está fuera de compras, y publicarlo duplicaría
    lo que Compras ya muestra.
    """
    df = df.copy()

    es_gasto = df["Naturaleza"] == NAT_GASTO
    auto_ok  = df["Estado_SAE"].isin([FUERA_DE_SAE, SIN_COMPARAR])

    publicable = es_gasto & auto_ok
    publicable = publicable.where(df["Trato"] != TRATO_SIEMPRE, es_gasto)
    publicable = publicable.where(df["Trato"] != TRATO_NUNCA, False)

    df["Publicable"] = publicable
    return df


def resumen_conciliacion(df):
    """
    Totales para los KPIs de la página. Devuelve un dict de floats/ints.

    Se reportan las tres cifras de clasificación juntas a propósito: un total de
    gasto sin su pendiente al lado es un número engañoso.
    """
    def _suma(mask):
        return float(df.loc[mask, "Monto_MXN"].sum()) if len(df) else 0.0

    return {
        "total":            float(df["Monto_MXN"].sum()) if len(df) else 0.0,
        "en_sae":           _suma(df["Estado_SAE"] == EN_SAE),
        "por_revisar":      _suma(df["Estado_SAE"] == OTRO_MES),
        "fuera_de_sae":     _suma(df["Estado_SAE"] == FUERA_DE_SAE),
        "mes_sin_sae":      _suma(df["Estado_SAE"] == MES_SIN_SAE),
        "sin_comparar":     _suma(df["Estado_SAE"] == SIN_COMPARAR),
        "gasto_operativo":  _suma(df["Naturaleza"] == NAT_GASTO),
        "no_operativo":     _suma(df["Naturaleza"] == NAT_NO_OPERATIVO),
        "sin_clasificar":   _suma(df["Naturaleza"] == NAT_SIN_CLASIFICAR),
        "publicable":       _suma(df["Publicable"]) if "Publicable" in df.columns else 0.0,
        "n_movimientos":    int(len(df)),
        "n_cuentas":        int(df["Cuenta"].nunique()) if len(df) else 0,
        "n_cuentas_sin_clasificar": int(
            df.loc[df["Naturaleza"] == NAT_SIN_CLASIFICAR, "Cuenta"].nunique()
        ) if len(df) else 0,
    }


def filas_para_gastos_empresa(df):
    """
    Agrupa los movimientos publicables en filas de `gastos_empresa`.

    Returns list[(concepto, periodo, monto, notas)] — la misma forma que consume
    `database.bulk_upsert_gastos_empresa`, agrupada por (cuenta, periodo) y usando
    el nombre del catálogo como concepto.
    """
    if "Publicable" not in df.columns:
        df = marcar_publicables(df)

    pub = df[df["Publicable"]]
    if len(pub) == 0:
        return []

    g = (
        pub.groupby(["Cuenta_Nombre", "_Mes"], as_index=False)
        .agg(Monto=("Monto_MXN", "sum"), N=("Monto_MXN", "size"))
        .sort_values("Monto", ascending=False)
    )

    filas = []
    for _, r in g.iterrows():
        periodo = f"{r['_Mes'].year}-{r['_Mes'].month:02d}"
        notas   = f"Contabilidad · {int(r['N'])} movimiento(s) fuera del SAE"
        filas.append((str(r["Cuenta_Nombre"]), periodo, float(r["Monto"]), notas))
    return filas
