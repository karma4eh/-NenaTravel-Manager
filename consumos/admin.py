
from django.contrib import admin

from .models import Consumo, ConsumoHistorial


class ConsumoHistorialInline(admin.TabularInline):
    model = ConsumoHistorial
    extra = 0
    can_delete = False
    readonly_fields = (
        'cantidad_anterior',
        'precio_anterior',
        'total_anterior',
        'cantidad_nueva',
        'precio_nuevo',
        'total_nuevo',
        'modificado_en',
        'usuario',
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Consumo)
class ConsumoAdmin(admin.ModelAdmin):
    list_display = (
        'pasajero',
        'producto',
        'evento',
        'cantidad',
        'precio_unitario',
        'total',
        'actualizado_en',
    )

    list_filter = (
        'viaje',
        'evento',
        'producto',
    )

    search_fields = (
        'pasajero__nombre',
        'producto__nombre',
    )

    readonly_fields = (
        'total',
        'cargo',
        'creado_en',
        'actualizado_en',
    )

    inlines = [ConsumoHistorialInline]


@admin.register(ConsumoHistorial)
class ConsumoHistorialAdmin(admin.ModelAdmin):
    list_display = (
        'consumo',
        'cantidad_anterior',
        'cantidad_nueva',
        'total_anterior',
        'total_nuevo',
        'modificado_en',
        'usuario',
    )

    list_filter = ('modificado_en',)
    search_fields = ('consumo__pasajero__nombre',)
    readonly_fields = (
        'consumo',
        'cantidad_anterior',
        'precio_anterior',
        'total_anterior',
        'cantidad_nueva',
        'precio_nuevo',
        'total_nuevo',
        'modificado_en',
        'usuario',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
