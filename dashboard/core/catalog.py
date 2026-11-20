"""Catálogo de negocio: nombres legibles de productos, segmentos y variables.

Todo texto que ve el usuario sale de aquí, para que un mismo producto se llame
igual en todas las páginas.
"""

from __future__ import annotations

import re

# Meses disponibles en el dataset (fecha_dato de Kaggle, siempre día 28).
MONTHS: list[str] = [
    "2015-01-28", "2015-02-28", "2015-03-28", "2015-04-28", "2015-05-28",
    "2015-06-28", "2015-07-28", "2015-08-28", "2015-09-28", "2015-10-28",
    "2015-11-28", "2015-12-28", "2016-01-28", "2016-02-28", "2016-03-28",
    "2016-04-28", "2016-05-28",
]
LATEST_MONTH = MONTHS[-1]
# El primer mes no tiene mes anterior: no hay altas ni transiciones observables.
MONTHS_WITH_FLOWS = MONTHS[1:]

_MONTH_NAMES = ["ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic"]
_MONTH_NAMES_LONG = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                     "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def month_label(fecha: str, long: bool = False) -> str:
    """'2016-05-28' -> 'may 2016' (o 'mayo de 2016')."""
    year, month = int(fecha[:4]), int(fecha[5:7])
    if long:
        return f"{_MONTH_NAMES_LONG[month - 1]} de {year}"
    return f"{_MONTH_NAMES[month - 1]} {year}"


def month_short(fecha: str) -> str:
    """'2016-05-28' -> 'may<br>16' (etiqueta compacta para ejes de tiempo)."""
    return f"{_MONTH_NAMES[int(fecha[5:7]) - 1]}<br>{fecha[2:4]}"


# code -> (nombre, familia)
PRODUCTS: dict[str, tuple[str, str]] = {
    "ind_cco_fin_ult1": ("Cuenta corriente", "Cuentas"),
    "ind_ctop_fin_ult1": ("Cuenta Particular", "Cuentas"),
    "ind_ctpp_fin_ult1": ("Cuenta Particular Plus", "Cuentas"),
    "ind_ctma_fin_ult1": ("Cuenta Más Particular", "Cuentas"),
    "ind_ctju_fin_ult1": ("Cuenta júnior", "Cuentas"),
    "ind_cno_fin_ult1": ("Cuenta nómina", "Cuentas"),
    "ind_ecue_fin_ult1": ("Cuenta electrónica", "Cuentas"),
    "ind_viv_fin_ult1": ("Cuenta vivienda", "Cuentas"),
    "ind_cder_fin_ult1": ("Cuenta de derivados", "Cuentas"),
    "ind_ahor_fin_ult1": ("Cuenta de ahorros", "Ahorro e inversión"),
    "ind_deco_fin_ult1": ("Depósito a corto plazo", "Ahorro e inversión"),
    "ind_deme_fin_ult1": ("Depósito a mediano plazo", "Ahorro e inversión"),
    "ind_dela_fin_ult1": ("Depósito a largo plazo", "Ahorro e inversión"),
    "ind_fond_fin_ult1": ("Fondos de inversión", "Ahorro e inversión"),
    "ind_valo_fin_ult1": ("Valores", "Ahorro e inversión"),
    "ind_plan_fin_ult1": ("Plan de pensiones", "Ahorro e inversión"),
    "ind_tjcr_fin_ult1": ("Tarjeta de crédito", "Crédito"),
    "ind_pres_fin_ult1": ("Préstamo", "Crédito"),
    "ind_hip_fin_ult1": ("Hipoteca", "Crédito"),
    "ind_aval_fin_ult1": ("Avales y garantías", "Crédito"),
    "ind_recibo_ult1": ("Débito automático", "Pagos y servicios"),
    "ind_nomina_ult1": ("Abono de nómina", "Pagos y servicios"),
    "ind_nom_pens_ult1": ("Abono de pensión", "Pagos y servicios"),
    "ind_reca_fin_ult1": ("Pago de impuestos", "Pagos y servicios"),
}
PRODUCT_CODES = list(PRODUCTS)
FAMILIES = ["Cuentas", "Ahorro e inversión", "Crédito", "Pagos y servicios"]


def product_name(code: str | None) -> str:
    if code is None:
        return "—"
    if code == "sin_productos":
        return "Sin productos"
    return PRODUCTS.get(code, (code, ""))[0]


def product_family(code: str) -> str:
    return PRODUCTS.get(code, ("", "Otro"))[1]


NAME_TO_CODE = {name: code for code, (name, _) in PRODUCTS.items()}

SEGMENTS = {
    "01 - TOP": "Top (VIP)",
    "02 - PARTICULARES": "Particulares",
    "03 - UNIVERSITARIO": "Universitarios",
}


def segment_name(raw: str | None) -> str:
    if raw is None or raw in ("", "desconocido", "Sin dato"):
        return "Sin dato"
    return SEGMENTS.get(raw, raw)


# Dimensiones de la tabla gold_product_penetration.
DIMENSIONS = {
    "segmento": "Segmento",
    "age_band": "Rango de edad",
    "income_band": "Rango de renta",
    "tenure_band": "Antigüedad",
    "actividad": "Actividad",
    "sexo": "Sexo (código)",
    "provincia": "Provincia",
}

BAND_LABELS = {
    # edad
    "00-17": "0–17", "18-24": "18–24", "25-34": "25–34", "35-44": "35–44",
    "45-54": "45–54", "55-64": "55–64", "65+": "65+",
    # renta (euros/año en el dataset original)
    "000-050k": "< 50 mil", "050-100k": "50–100 mil", "100-200k": "100–200 mil",
    "200-500k": "200–500 mil", "500k+": "500 mil +",
    # antigüedad en meses
    "000-006m": "0–6 meses", "007-012m": "7–12 meses", "013-036m": "1–3 años",
    "037-060m": "3–5 años", "061-120m": "5–10 años", "121m+": "10 años +",
    "activo": "Activos", "inactivo": "Inactivos",
    "desconocido": "Sin dato",
}


def band_label(dimension: str, value: str | None) -> str:
    if value is None:
        return "Sin dato"
    if dimension == "segmento":
        return segment_name(value)
    if dimension == "provincia":
        return value.title() if value != "desconocido" else "Sin dato"
    return BAND_LABELS.get(value, value)


# Etiquetas de los segmentos de test_metrics_by_segment.csv (train.py).
EVAL_DIMENSIONS = {
    "segmento": "Segmento",
    "age_band": "Rango de edad",
    "income_band": "Rango de renta",
    "sexo": "Sexo (código)",
}
EVAL_BAND_ORDER = {
    "age_band": ["<=24", "25-34", "35-44", "45-54", "55-64", "65+"],
    "income_band": ["<=50k", "50-100k", "100-150k", "150-250k", ">250k"],
}
EVAL_BAND_LABELS = {
    "<=24": "≤ 24", "25-34": "25–34", "35-44": "35–44", "45-54": "45–54",
    "55-64": "55–64", "65+": "65+",
    "<=50k": "< 50 mil", "50-100k": "50–100 mil", "100-150k": "100–150 mil",
    "150-250k": "150–250 mil", ">250k": "> 250 mil",
}

_PLAIN_FEATURES = {
    "n_products": "N.º de productos que tiene",
    "n_products_added": "Productos contratados este mes",
    "n_products_dropped": "Productos dados de baja este mes",
    "has_previous_month": "Tiene registro el mes anterior",
    "antiguedad": "Antigüedad (meses)",
    "month_of_year": "Mes del año (estacionalidad)",
    "age": "Edad",
    "renta": "Renta del hogar",
    "segmento": "Segmento",
    "canal_entrada": "Canal de entrada",
    "cod_prov": "Provincia",
    "sexo": "Sexo",
    "ind_actividad_cliente": "Cliente activo",
    "ind_nuevo": "Cliente nuevo (< 6 meses)",
    "indrel": "Tipo de relación",
    "indrel_1mes": "Tipo de cliente al inicio del mes",
    "tiprel_1mes": "Relación al inicio del mes",
    "indresi": "Reside en España",
    "indext": "Nació en el extranjero",
    "ind_empleado": "Empleado del banco",
    "pais_residencia": "País de residencia",
    "indfall": "Fallecido",
}


def feature_label(feature: str) -> str:
    """Nombre legible de una variable del modelo."""
    if feature in _PLAIN_FEATURES:
        return _PLAIN_FEATURES[feature]
    match = re.fullmatch(r"(ind_\w+?_ult1)_lag(\d)", feature)
    if match:
        months = int(match.group(2))
        return f"{product_name(match.group(1))} · hace {months} {'mes' if months == 1 else 'meses'}"
    if feature.startswith("added_"):
        return f"Contrató {product_name(feature[6:]).lower()} este mes"
    if feature in PRODUCTS:
        return f"Tiene {product_name(feature).lower()}"
    if feature.startswith("conv_") or feature.endswith("_conversion_rate"):
        return f"Tasa de conversión del segmento · {feature}"
    return feature


def feature_group(feature: str) -> str:
    if re.fullmatch(r"ind_\w+?_ult1_lag\d", feature):
        return "Historial (rezagos)"
    if feature.startswith("added_") or feature in ("n_products_added", "n_products_dropped"):
        return "Movimientos del mes"
    if feature in PRODUCTS or feature == "n_products":
        return "Tenencia actual"
    return "Perfil del cliente"
