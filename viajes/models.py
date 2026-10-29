from django.db import models
from django.contrib.auth.models import User


class Viaje(models.Model):
    ESTADOS = [
        ('ACTIVO', 'Activo'),
        ('FINALIZADO', 'Finalizado'),
    ]

    nombre = models.CharField(
        max_length=150
    )

    destino = models.CharField(
        max_length=100
    )

    fecha_inicio = models.DateField()

    fecha_fin = models.DateField()

    tasa_usd_bs = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    tasa_usd_cop = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default='ACTIVO'
    )

    creado_en = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return (
            f"{self.nombre} - "
            f"{self.fecha_inicio} al {self.fecha_fin}"
        )


class Grupo(models.Model):
    viaje = models.ForeignKey(
        Viaje,
        on_delete=models.CASCADE,
        related_name='grupos'
    )

    nombre = models.CharField(
        max_length=150
    )

    bus = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Numero de bus al que pertenece este grupo.'
    )

    def __str__(self):
        return self.nombre


class Pasajero(models.Model):
    viaje = models.ForeignKey(
        Viaje,
        on_delete=models.CASCADE,
        related_name='pasajeros'
    )

    grupo = models.ForeignKey(
        Grupo,
        on_delete=models.CASCADE,
        related_name='pasajeros'
    )

    nombre = models.CharField(
        max_length=200
    )

    cedula = models.CharField(
        max_length=30,
        blank=True
    )

    def __str__(self):
        return self.nombre


class PrecioProducto(models.Model):
    viaje = models.ForeignKey(
        Viaje,
        on_delete=models.CASCADE,
        related_name='precios_productos'
    )

    producto = models.ForeignKey(
        'core.Producto',
        on_delete=models.CASCADE,
        related_name='precios_por_viaje'
    )

    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    def __str__(self):
        return (
            f"{self.producto.nombre} - "
            f"${self.precio}"
        )


class PrecioActividad(models.Model):
    viaje = models.ForeignKey(
        Viaje,
        on_delete=models.CASCADE,
        related_name='precios_actividades'
    )

    actividad = models.ForeignKey(
        'core.Actividad',
        on_delete=models.CASCADE,
        related_name='precios_por_viaje'
    )

    precio_por_persona = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    def __str__(self):
        return (
            f"{self.actividad.nombre} - "
            f"${self.precio_por_persona}"
        )


class Evento(models.Model):
    viaje = models.ForeignKey(
        Viaje,
        on_delete=models.CASCADE,
        related_name='eventos'
    )

    nombre = models.CharField(
        max_length=150
    )

    orden = models.PositiveIntegerField(
        default=1
    )

    fecha = models.DateField(
        null=True,
        blank=True
    )

    def __str__(self):
        return (
            f"{self.nombre} - "
            f"{self.viaje.nombre}"
        )


class AsistenciaActividad(models.Model):

    evento = models.ForeignKey(
        Evento,
        on_delete=models.CASCADE,
        related_name='asistencias'
    )

    actividad = models.ForeignKey(
        'core.Actividad',
        on_delete=models.CASCADE,
        related_name='asistencias'
    )

    pasajero = models.ForeignKey(
        Pasajero,
        on_delete=models.CASCADE,
        related_name='asistencias_actividades'
    )

    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    creado_en = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'evento',
                    'actividad',
                    'pasajero'
                ],
                name='asistencia_actividad_unica'
            )
        ]

    def __str__(self):
        return (
            f"{self.pasajero.nombre} - "
            f"{self.actividad.nombre} - "
            f"${self.precio}"
        )


class Cargo(models.Model):

    pasajero = models.ForeignKey(
        Pasajero,
        on_delete=models.CASCADE,
        related_name='cargos'
    )

    evento = models.ForeignKey(
        Evento,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cargos'
    )

    producto = models.ForeignKey(
        'core.Producto',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cargos'
    )

    concepto = models.CharField(
        max_length=200
    )

    cantidad = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1
    )

    precio_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    total = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    creado_en = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return (
            f"{self.pasajero.nombre} - "
            f"{self.concepto} - "
            f"${self.total}"
        )


class ControlComida(models.Model):
    TIPO_DESAYUNO = 'DESAYUNO'
    TIPO_ALMUERZO = 'ALMUERZO'
    TIPO_CENA = 'CENA'

    TIPOS_COMIDA = [
        (TIPO_DESAYUNO, 'Desayuno'),
        (TIPO_ALMUERZO, 'Almuerzo'),
        (TIPO_CENA, 'Cena'),
    ]

    viaje = models.ForeignKey(
        Viaje,
        on_delete=models.CASCADE,
        related_name='controles_comida'
    )
    evento = models.ForeignKey(
        Evento,
        on_delete=models.CASCADE,
        related_name='controles_comida',
        help_text='Día operativo del viaje.'
    )
    tipo_comida = models.CharField(
        max_length=20,
        choices=TIPOS_COMIDA,
        help_text='Tipo de comida: Desayuno, Almuerzo o Cena.'
    )
    pasajero = models.ForeignKey(
        Pasajero,
        on_delete=models.CASCADE,
        related_name='comidas_recibidas'
    )
    entregado = models.BooleanField(
        default=True,
        help_text='Indica si el pasajero ya recibió o consumió la comida.'
    )
    entregado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='comidas_repartidas',
        help_text='Usuario del sistema que registró la entrega.'
    )
    fecha_hora = models.DateTimeField(
        auto_now=True,
        help_text='Momento exacto en que se registró la entrega.'
    )
    notas = models.CharField(
        max_length=200,
        blank=True,
        help_text='Observaciones sobre la comida (ej: menú vegetariano, alergias).'
    )

    class Meta:
        verbose_name = 'Control de Comida'
        verbose_name_plural = 'Controles de Comidas'
        constraints = [
            models.UniqueConstraint(
                fields=['evento', 'tipo_comida', 'pasajero'],
                name='comida_unica_pasajero_evento_tipo'
            )
        ]
        indexes = [
            models.Index(fields=['viaje', 'evento', 'tipo_comida']),
        ]

    def __str__(self):
        return f"{self.pasajero.nombre} - {self.evento.nombre} ({self.get_tipo_comida_display()})"
