CATALOGO_CATEGORIAS = [
    "Sustratos (Papel)",
    "Pre-prensa y Químicos",
    "Insumos de Producción",
    "Empaque y Embalaje",
    "Maquila",
    "Mantenimiento y Refacciones",
    "Logística / Fletes",
    "Almacenaje y Renta",
    "Energía y Servicios",
    "Limpieza y Sanitarios",
    "TI y Software",
    "Seguros e Impuestos/Derechos",
    "Servicios Profesionales",
    "Otros gastos de operación",
    "Proyectos Especiales",
    "Otros / Sin clasificar",
]

ETIQ_PENDIENTE = "Pendiente clasificar"


def aplicar_ancla(proveedor):
    if not proveedor:
        return None
    p = str(proveedor).upper()
    if "DELMAN INTERNACIONAL" in p:                         return "Sustratos (Papel)"
    if "SANCHEZ S.A"          in p:                         return "Pre-prensa y Químicos"
    if "JAQUELINA REYES"      in p or "GUTMAN BROS" in p:   return "Mantenimiento y Refacciones"
    if "VIGMAN GRAPHICS"      in p:                         return "Almacenaje y Renta"
    if "INFOVITA"             in p:                         return "Maquila"
    return None


ABREVIACIONES = {
    "COMISION NACIONAL DE LIBROS DE TEXTO GRATUITOS": "CONALITEG",
}

ESTATUS_VALIDOS_COMPRAS = ["Emitida", "Dev.Parc.", "Dev. Parcial"]
ESTATUS_VALIDOS_VENTAS  = ["Remitido", "Emitido", "Rem.Parc."]

# ── Colores corporativos ──────────────────────────────────────────────────────
COLOR_LYON    = "#1F4E79"
COLOR_VENTAS  = "#548235"
COLOR_COMPRAS = "#C00000"
COLOR_PICO    = "#C00000"

PALETA_PRINCIPAL = [
    "#1F4E79", "#C00000", "#E97132", "#7030A0", "#548235",
    "#2E75B6", "#BF8F00", "#A02B93", "#385723", "#806000",
]

COLOR_PENDIENTE = "#9E9E9E"
COLOR_VALIDADO  = "#DCE7F5"
COLOR_ANCLA     = "#E6F2D8"
COLOR_AMBAR     = "#FFF8E1"

# Paleta por categoría: índice estable
PALETA_CATEGORIAS = {
    cat: PALETA_PRINCIPAL[i % len(PALETA_PRINCIPAL)]
    for i, cat in enumerate(CATALOGO_CATEGORIAS[:-1])
}
PALETA_CATEGORIAS["Otros / Sin clasificar"] = COLOR_PENDIENTE
PALETA_CATEGORIAS[ETIQ_PENDIENTE]           = COLOR_PENDIENTE

ESPANOL_MES = {
    1: "Ene", 2: "Feb", 3: "Mar",  4: "Abr",
    5: "May", 6: "Jun", 7: "Jul",  8: "Ago",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
}


def label_mes(period):
    """pandas Period → 'Ene 2026'"""
    return f"{ESPANOL_MES[period.month]} {period.year}"
