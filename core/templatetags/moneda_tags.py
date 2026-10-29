from django import template
from decimal import Decimal

register = template.Library()

@register.filter(name="punto_miles")
def punto_miles(value):
    """
    Formatea un número con punto (.) como separador de miles.
    Ejemplo: 334000 -> 334.000, 1500000 -> 1.500.000, 0 -> 0.
    """
    if value is None or value == "":
        return "0"
    try:
        val_float = float(value)
        val_int = int(round(val_float))
        return f"{val_int:,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(value)

@register.filter(name="porcentaje_restante")
def porcentaje_restante(value):
    """
    Calcula el porcentaje restante (100 - value).
    """
    try:
        val = float(value)
        return max(0, round(100.0 - val, 1))
    except (ValueError, TypeError):
        return 0
