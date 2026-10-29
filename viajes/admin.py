from django.contrib import admin

from .models import (
    Viaje,
    Grupo,
    Pasajero,
    PrecioProducto,
    PrecioActividad,
    Evento,
    AsistenciaActividad,
    Cargo,
)


admin.site.register(Viaje)
admin.site.register(Grupo)
admin.site.register(Pasajero)
admin.site.register(PrecioProducto)
admin.site.register(PrecioActividad)
admin.site.register(Evento)
admin.site.register(AsistenciaActividad)
admin.site.register(Cargo)