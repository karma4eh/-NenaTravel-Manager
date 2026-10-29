from decimal import Decimal
from core.models import Producto
from viajes.models import PrecioProducto


def sincronizar_precios_viaje(viaje, sobrescribir=False):
    """
    Garantiza que todos los productos activos tengan su precio configurado
    para el viaje especificado a partir de la lista de precios base.
    - Si sobrescribir=True: actualiza los precios del viaje al precio base actual.
    - Si sobrescribir=False: solo crea los precios de productos que falten.
    """
    productos = Producto.objects.filter(activo=True)
    contador_creados = 0
    contador_actualizados = 0

    for prod in productos:
        pp, created = PrecioProducto.objects.get_or_create(
            viaje=viaje,
            producto=prod,
            defaults={"precio": prod.precio_base or Decimal("0.00")},
        )
        if created:
            contador_creados += 1
        elif sobrescribir:
            pp.precio = prod.precio_base or Decimal("0.00")
            pp.save(update_fields=["precio"])
            contador_actualizados += 1

    return {
        "creados": contador_creados,
        "actualizados": contador_actualizados,
    }
