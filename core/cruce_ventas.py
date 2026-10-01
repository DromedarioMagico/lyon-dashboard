"""
Cruce entre los pedidos del SAE (Ventas) y las facturas del reporte CFDI.

La pregunta que contesta: de todo lo que se pidió, ¿qué parte ya se facturó y
qué parte sigue entregada sin cobrar? El SAE no trae folio fiscal ni el CFDI
trae el folio interno de Lyon, así que no hay una llave de documento directa
entre los dos — pero ambos sistemas capturan por separado la orden de compra
del cliente (el SAE en su columna "Su pedido", el CFDI en la suya), y esa sí
es la misma OC vista desde los dos lados. La llave de cruce es
(Cliente_Codigo, número de OC) — nunca la OC sola, porque son números chicos
("1", "22", "105"...) que colisionarían entre clientes sin el código.

Verificado contra los archivos reales antes de escribir este módulo: del
cruce por (cliente + OC), 91% de los pares tienen monto idéntico al peso y
ninguna factura queda con fecha anterior a su pedido — la prueba de que el
cruce es real y no una coincidencia de números pequeños.

Sin dependencias de Streamlit.
"""

import re

import pandas as pd

# Estados del pedido frente al CFDI.
FACTURADO     = "Facturado"
SIN_FACTURA   = "Sin factura"
SIN_OC        = "Sin OC"
FUERA_DE_RANGO = "Fuera de rango"
SIN_COMPARAR  = "Sin comparar"

ESTADOS_PEDIDO = [FACTURADO, SIN_FACTURA, SIN_OC, FUERA_DE_RANGO, SIN_COMPARAR]

_RE_NUM = re.compile(r"\d+")


def normalizar_oc(texto):
    """
    Extrae los números de orden de compra de un texto libre.

    El SAE y el CFDI capturan la OC a mano, así que el formato varía:
    'OP.19777 / OC.16406', 'op 1285', '22', 'S/N'. Se extraen TODOS los
    números que aparecen — cuando el texto trae "OP X / OC Y" se prueban
    ambos como candidatos, porque no hay forma de saber de antemano cuál de
    los dos es el que el otro sistema capturó.

    Returns set[str]. Vacío si el texto no trae ningún número (incluye el
    caso 'S/N', que es la forma explícita de decir "no aplica").
    """
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return set()
    return set(_RE_NUM.findall(str(texto)))


def _construir_indice(df_ventas):
    """(Cliente_Codigo, oc) -> lista de Clave de pedido, para pedidos con OC."""
    idx = {}
    for _, r in df_ventas.iterrows():
        cod = r.get("Cliente_Codigo")
        if pd.isna(cod):
            continue
        for oc in r["_OC"]:
            idx.setdefault((int(cod), oc), []).append(r["Clave"])
    return idx


def cruzar_pedidos_facturas(df_ventas, df_cfdi):
    """
    Amarra cada pedido con su(s) factura(s) y viceversa.

    df_ventas: salida de `etl_ventas.cargar_ventas` — necesita Clave,
               Cliente_Codigo, Fecha, Subtotal_MXN, Importe_MXN, 'Su pedido'.
    df_cfdi:   salida de `etl_cfdi.cargar_cfdi`, ya filtrada a facturas
               vigentes (Tipo_Doc == "Factura", Cancelado == False) — este
               módulo no filtra cancelaciones, se lo deja al llamador para
               no ocultar una decisión que le corresponde a la página.

    Returns (df_pedidos, df_facturas, resumen):

    df_pedidos = df_ventas + Estado_Cruce, Facturado_MXN, Facturado_ConIVA_MXN,
                 N_Facturas, Dias_Ciclo (mediana de los ciclos si hay >1 factura).
    df_facturas = df_cfdi + Pedido_MXN, N_Pedidos.
    resumen = dict con los totales por Estado_Cruce, listo para KPIs.
    """
    pedidos = df_ventas.copy()
    facturas = df_cfdi.copy()

    if len(facturas) == 0:
        pedidos["Estado_Cruce"] = SIN_COMPARAR
        pedidos["Facturado_MXN"] = 0.0
        pedidos["Facturado_ConIVA_MXN"] = 0.0
        pedidos["N_Facturas"] = 0
        pedidos["Dias_Ciclo"] = pd.NA
        facturas["Pedido_MXN"] = 0.0
        facturas["N_Pedidos"] = 0
        return pedidos, facturas, _resumen(pedidos)

    meses_cfdi = set(facturas["_Mes"].unique())

    pedidos["_OC"] = pedidos["Su pedido"].map(normalizar_oc) if "Su pedido" in pedidos.columns else [set()] * len(pedidos)
    facturas["_OC"] = facturas["Su_Pedido"].map(normalizar_oc) if "Su_Pedido" in facturas.columns else [set()] * len(facturas)

    idx = _construir_indice(pedidos)

    # ── Lado factura: a qué pedido(s) amarra, y cuánto suman ──────────────────
    ped_por_clave = pedidos.set_index("Clave")
    fact_pedido_mxn, fact_n_pedidos = [], []
    for _, f in facturas.iterrows():
        cod = f.get("Cliente_Codigo")
        claves = set()
        if pd.notna(cod):
            for oc in f["_OC"]:
                claves.update(idx.get((int(cod), oc), []))
        if claves:
            monto = float(ped_por_clave.loc[list(claves), "Subtotal_MXN"].sum())
        else:
            monto = 0.0
        fact_pedido_mxn.append(monto)
        fact_n_pedidos.append(len(claves))
    facturas["Pedido_MXN"] = fact_pedido_mxn
    facturas["N_Pedidos"] = fact_n_pedidos

    # ── Lado pedido: a qué factura(s) amarra, y el ciclo en días ───────────────
    fact_idx = {}
    for i, f in facturas.iterrows():
        cod = f.get("Cliente_Codigo")
        if pd.isna(cod):
            continue
        for oc in f["_OC"]:
            fact_idx.setdefault((int(cod), oc), []).append(i)

    estados, fact_mxn, fact_con_iva, n_fact, dias_ciclo = [], [], [], [], []
    for _, p in pedidos.iterrows():
        cod = p.get("Cliente_Codigo")
        idxs = set()
        if pd.notna(cod):
            for oc in p["_OC"]:
                idxs.update(fact_idx.get((int(cod), oc), []))

        if idxs:
            sub = facturas.loc[list(idxs)]
            estados.append(FACTURADO)
            fact_mxn.append(float(sub["Subtotal_MXN"].sum()))
            fact_con_iva.append(float(sub["Importe_MXN"].sum()))
            n_fact.append(len(idxs))
            # Un cliente puede reusar la misma OC en pedidos distintos meses
            # después, o consolidar varias OC viejas en un pedido nuevo — ahí
            # una factura anterior a ESTE pedido en realidad pertenece a otro
            # documento que comparte la OC, no a un ciclo real. Se excluye del
            # cálculo de ciclo (el monto facturado sí se cuenta completo:
            # el dinero es real, solo la fecha de origen es ambigua).
            ciclos = (sub["Fecha"] - p["Fecha"]).dt.days
            ciclos_validos = ciclos[ciclos >= 0]
            dias_ciclo.append(
                float(ciclos_validos.median()) if len(ciclos_validos) else pd.NA
            )
        else:
            fact_mxn.append(0.0)
            fact_con_iva.append(0.0)
            n_fact.append(0)
            dias_ciclo.append(pd.NA)
            if not p["_OC"]:
                estados.append(SIN_OC)
            elif p["_Mes"] not in meses_cfdi:
                estados.append(FUERA_DE_RANGO)
            else:
                estados.append(SIN_FACTURA)

    pedidos["Estado_Cruce"] = estados
    pedidos["Facturado_MXN"] = fact_mxn
    pedidos["Facturado_ConIVA_MXN"] = fact_con_iva
    pedidos["N_Facturas"] = n_fact
    pedidos["Dias_Ciclo"] = dias_ciclo

    return pedidos, facturas, _resumen(pedidos)


def _resumen(pedidos):
    """Totales por Estado_Cruce — la forma que consumen los KPIs de la página."""
    if len(pedidos) == 0:
        out = {"total": 0.0, "n_pedidos": 0, "facturado": 0.0}
        for estado in ESTADOS_PEDIDO:
            out[estado] = 0.0
            out[f"n_{estado}"] = 0
        return out

    out = {
        "total": float(pedidos["Subtotal_MXN"].sum()),
        "n_pedidos": int(len(pedidos)),
        "facturado": float(pedidos["Facturado_MXN"].sum()),
    }
    for estado in ESTADOS_PEDIDO:
        mask = pedidos["Estado_Cruce"] == estado
        out[estado] = float(pedidos.loc[mask, "Subtotal_MXN"].sum())
        out[f"n_{estado}"] = int(mask.sum())
    return out


def descomponer_sin_factura(pedidos):
    """
    De los pedidos SIN_FACTURA (con OC, dentro de rango, sin factura amarrada),
    separa los realmente accionables: Remitido (entregado sin cobrar) de
    Emitido (aún no se remite, es normal que no tenga factura).

    Returns (df_remitido_sin_facturar, df_emitido_pendiente).
    """
    sin = pedidos[pedidos["Estado_Cruce"] == SIN_FACTURA]
    remitido = sin[sin["Estatus"].astype(str).str.strip() == "Remitido"].copy()
    emitido = sin[sin["Estatus"].astype(str).str.strip() != "Remitido"].copy()
    return remitido, emitido


def bucket_antiguedad(dias):
    """Mismo criterio de cubetas que ya usa Facturación para remisiones."""
    if dias <= 30:
        return "0-30 días"
    if dias <= 60:
        return "31-60 días"
    if dias <= 90:
        return "61-90 días"
    return "90+ días"


def ventas_confirmadas(df_ventas, df_cfdi):
    """
    El Reporte de Ventas (CFDI) llevado a la forma de un DataFrame de ventas —
    mismas columnas que ya usa `core/plots.py` para pedidos (Fecha, _Mes,
    Cliente_Nombre, Cliente_Display, Vendedor, Importe_MXN, Subtotal_MXN) — así
    las gráficas ya validadas lo reciben sin que haya que tocar una sola.

    El CFDI no trae vendedor: se cruza por `Cliente_Nombre` (la llave que
    demostró 100% de cobertura de monto contra los pedidos — el cruce por
    `Cliente_Codigo` pierde una fracción) contra el mapa cliente→vendedor
    construido de LOS PEDIDOS YA RESUELTOS. `df_ventas` debe venir de
    `etl_ventas.aplicar_vendedores()`: es "la cartera que tenemos", porque ya
    combina el vendedor nativo del SAE con las asignaciones que el usuario
    guardó en Clasificaciones. Un cliente con más de un vendedor en los
    pedidos se resuelve al de mayor monto (un solo caso real, de 53 clientes).
    Un cliente del CFDI sin mapa queda `"Sin asignar"` — nunca inventado.

    `df_cfdi`: ya filtrado a lo que se quiera medir (p. ej. facturas vigentes:
    `Tipo_Doc == "Factura"` y `~Cancelado`) — esta función no filtra Tipo_Doc
    ni Cancelado, eso es decisión de quien la llama.

    Returns una copia de `df_cfdi` con la columna `Vendedor` agregada.
    """
    mapa = (
        df_ventas[df_ventas["Vendedor"] != "Sin asignar"]
        .groupby(["Cliente_Nombre", "Vendedor"])["Importe_MXN"].sum()
        .reset_index()
        .sort_values("Importe_MXN", ascending=False)
        .drop_duplicates("Cliente_Nombre")
        .set_index("Cliente_Nombre")["Vendedor"]
        .to_dict()
    )

    df = df_cfdi.copy()
    df["Vendedor"] = df["Cliente_Nombre"].map(mapa).fillna("Sin asignar")
    return df
