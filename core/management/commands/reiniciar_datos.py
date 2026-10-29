from django.core.management.base import BaseCommand
from django.contrib.admin.models import LogEntry
from core.models import Producto, Actividad, TasaBCV
from django.contrib.auth.models import User
from viajes.models import (
    Viaje, Grupo, Pasajero, Evento, PrecioActividad,
    AsistenciaActividad, Cargo, ControlComida, PrecioProducto
)
from consumos.models import Consumo, ConsumoHistorial, Pago, AplicacionPago


class Command(BaseCommand):
    help = "Reinicia todos los datos operativos de viajes, consumos, cobros y comidas para pruebas o demostraciones."

    def handle(self, *args, **options):
        self.stdout.write("Reiniciando datos operativos del sistema...")

        AplicacionPago.objects.all().delete()
        Pago.objects.all().delete()
        ConsumoHistorial.objects.all().delete()
        Consumo.objects.all().delete()
        ControlComida.objects.all().delete()
        AsistenciaActividad.objects.all().delete()
        Cargo.objects.all().delete()
        Evento.objects.all().delete()
        PrecioActividad.objects.all().delete()
        PrecioProducto.objects.all().delete()
        Pasajero.objects.all().delete()
        Grupo.objects.all().delete()
        Viaje.objects.all().delete()
        LogEntry.objects.all().delete()

        self.stdout.write(self.style.SUCCESS(
            "[OK] Todos los datos operativos han sido reiniciados exitosamente.\n"
            f"Viajes restantes: {Viaje.objects.count()} | Usuarios preservados: {User.objects.count()}"
        ))
