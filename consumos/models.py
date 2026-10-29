from decimal import Decimal

from django.conf import settings
from django.db import models, transaction

from viajes.models import Cargo


class Consumo(models.Model):
    viaje = models.ForeignKey(
        'viajes.Viaje',
        on_delete=models.CASCADE,
        related_name='consumos'
    )

    pasajero = models.ForeignKey(
        'viajes.Pasajero',
        on_delete=models.CASCADE,
        related_name='consumos'
    )

    evento = models.ForeignKey(
        'viajes.Evento',
        on_delete=models.PROTECT,
        related_name='consumos'
    )

    producto = models.ForeignKey(
        'core.Producto',
        on_delete=models.PROTECT,
        related_name='consumos'
    )

    cantidad = models.PositiveIntegerField(default=1)

    precio_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )

    cargo = models.OneToOneField(
        'viajes.Cargo',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='consumo'
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'viaje',
                    'pasajero',
                    'evento',
                    'producto',
                ],
                name='consumo_unico_pasajero_evento_producto',
            )
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            anterior = None

            if self.pk:
                anterior = (
                    Consumo.objects
                    .filter(pk=self.pk)
                    .values(
                        'cantidad',
                        'precio_unitario',
                        'total',
                    )
                    .first()
                )

            self.total = (
                Decimal(self.cantidad) * self.precio_unitario
            )

            super().save(*args, **kwargs)

            if self.cargo_id:
                cargo = Cargo.objects.select_for_update().get(
                    pk=self.cargo_id
                )

                cargo.pasajero = self.pasajero
                cargo.evento = self.evento
                cargo.producto = self.producto
                cargo.concepto = self.producto.nombre
                cargo.cantidad = self.cantidad
                cargo.precio_unitario = self.precio_unitario
                cargo.total = self.total
                cargo.save()

            else:
                cargo = Cargo.objects.create(
                    pasajero=self.pasajero,
                    evento=self.evento,
                    producto=self.producto,
                    concepto=self.producto.nombre,
                    cantidad=self.cantidad,
                    precio_unitario=self.precio_unitario,
                    total=self.total,
                )

                self.cargo = cargo

                super().save(update_fields=['cargo'])

            if anterior:
                cambios = (
                    anterior['cantidad'] != self.cantidad
                    or anterior['precio_unitario'] != self.precio_unitario
                    or anterior['total'] != self.total
                )

                if cambios:
                    ConsumoHistorial.objects.create(
                        consumo=self,
                        cantidad_anterior=anterior['cantidad'],
                        precio_anterior=anterior['precio_unitario'],
                        total_anterior=anterior['total'],
                        cantidad_nueva=self.cantidad,
                        precio_nuevo=self.precio_unitario,
                        total_nuevo=self.total,
                        usuario=getattr(
                            self,
                            '_usuario_modificacion',
                            None
                        ),
                    )

    def __str__(self):
        return (
            f'{self.pasajero.nombre} - '
            f'{self.producto.nombre} - '
            f'${self.total}'
        )


class ConsumoHistorial(models.Model):
    consumo = models.ForeignKey(
        Consumo,
        on_delete=models.PROTECT,
        related_name='historial'
    )

    cantidad_anterior = models.PositiveIntegerField()
    precio_anterior = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    total_anterior = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    cantidad_nueva = models.PositiveIntegerField()
    precio_nuevo = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    total_nuevo = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    modificado_en = models.DateTimeField(auto_now_add=True)

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cambios_consumos'
    )

    def __str__(self):
        return (
            f'Consumo #{self.consumo_id}: '
            f'{self.total_anterior} → {self.total_nuevo}'
        )

from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Pago(models.Model):
    MONEDAS = [
        ("COP", "Pesos colombianos"),
        ("USD", "Dólares"),
        ("BS", "Bolívares"),
    ]

    viaje = models.ForeignKey(
        "viajes.Viaje",
        on_delete=models.PROTECT,
        related_name="pagos",
    )

    # Se completa cuando el pago corresponde a un grupo.
    grupo = models.ForeignKey(
        "viajes.Grupo",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pagos",
    )

    moneda = models.CharField(max_length=3, choices=MONEDAS)
    monto_original = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    # Tasas copiadas del viaje al registrar el pago.
    # Si luego cambian las tasas del viaje, el historial se conserva.
    tasa_usd_cop = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    tasa_usd_bs = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    # Equivalencias guardadas para auditoría.
    equivalente_usd = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        default=Decimal("0"),
    )
    equivalente_cop = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0"),
    )
    equivalente_bs = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0"),
    )

    referencia = models.CharField(
        max_length=150,
        blank=True,
    )
    observacion = models.TextField(blank=True)

    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_viajes",
    )

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en", "-id"]

    def clean(self):
        errores = {}

        if self.monto_original is not None and self.monto_original <= 0:
            errores["monto_original"] = (
                "El monto del pago debe ser mayor que cero."
            )

        if self.tasa_usd_cop is not None and self.tasa_usd_cop <= 0:
            errores["tasa_usd_cop"] = (
                "La tasa USD/COP debe ser mayor que cero."
            )

        if self.tasa_usd_bs is not None and self.tasa_usd_bs <= 0:
            errores["tasa_usd_bs"] = (
                "La tasa USD/Bs debe ser mayor que cero."
            )

        if self.grupo_id and self.viaje_id:
            if self.grupo.viaje_id != self.viaje_id:
                errores["grupo"] = (
                    "El grupo debe pertenecer al viaje seleccionado."
                )

        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        if self.moneda not in dict(self.MONEDAS):
            raise ValidationError("La moneda seleccionada no es válida.")

        if self.monto_original <= 0:
            raise ValidationError(
                "El monto del pago debe ser mayor que cero."
            )

        if self.tasa_usd_cop <= 0 or self.tasa_usd_bs <= 0:
            raise ValidationError(
                "Las tasas de cambio deben ser mayores que cero."
            )

        # Primero calculamos el equivalente exacto en USD.
        # No utilizamos el USD redondeado para calcular Bs.
        if self.moneda == "USD":
            usd_exacto = self.monto_original
        elif self.moneda == "COP":
            usd_exacto = self.monto_original / self.tasa_usd_cop
        else:
            usd_exacto = self.monto_original / self.tasa_usd_bs

        cop_exacto = usd_exacto * self.tasa_usd_cop
        bs_exacto = usd_exacto * self.tasa_usd_bs

        centavos = Decimal("0.01")
        ocho_decimales = Decimal("0.00000001")

        self.equivalente_usd = usd_exacto.quantize(
            ocho_decimales,
            rounding=ROUND_HALF_UP,
        )
        self.equivalente_cop = cop_exacto.quantize(
            centavos,
            rounding=ROUND_HALF_UP,
        )
        self.equivalente_bs = bs_exacto.quantize(
            centavos,
            rounding=ROUND_HALF_UP,
        )

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"Pago #{self.pk or 'nuevo'} - "
            f"{self.moneda} {self.monto_original}"
        )


class AplicacionPago(models.Model):
    pago = models.ForeignKey(
        Pago,
        on_delete=models.PROTECT,
        related_name="aplicaciones",
    )

    # Cada aplicación corresponde a un cargo existente.
    # No crea ni duplica cargos.
    cargo = models.ForeignKey(
        "viajes.Cargo",
        on_delete=models.PROTECT,
        related_name="aplicaciones_pago",
    )

    pasajero = models.ForeignKey(
        "viajes.Pasajero",
        on_delete=models.PROTECT,
        related_name="aplicaciones_pago",
    )

    # Importe aplicado al cargo, siempre expresado en COP.
    monto_cop = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    # Parte equivalente en la moneda original del pago.
    # Se conserva para auditar la distribución grupal.
    monto_moneda_pago = models.DecimalField(
        max_digits=18,
        decimal_places=8,
    )

    # Copias históricas para identificar la deuda abonada.
    concepto_snapshot = models.CharField(max_length=200)
    total_cargo_snapshot = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pago", "cargo"],
                name="aplicacion_pago_cargo_unica",
            ),
        ]

    def clean(self):
        errores = {}

        if self.monto_cop is not None and self.monto_cop <= 0:
            errores["monto_cop"] = (
                "El importe aplicado debe ser mayor que cero."
            )

        if self.pago_id and self.cargo_id:
            viaje_pago = self.pago.viaje_id
            viaje_cargo = self.cargo.pasajero.viaje_id

            if viaje_pago != viaje_cargo:
                errores["cargo"] = (
                    "El cargo y el pago deben pertenecer al mismo viaje."
                )

        if self.cargo_id and self.pasajero_id:
            if self.cargo.pasajero_id != self.pasajero_id:
                errores["pasajero"] = (
                    "El pasajero debe ser el titular del cargo."
                )

        if errores:
            raise ValidationError(errores)

    def __str__(self):
        return (
            f"Pago #{self.pago_id} aplicado a "
            f"{self.pasajero.nombre}: COP {self.monto_cop}"
        )
