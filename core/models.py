from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    categoria = models.CharField(max_length=100, blank=True)
    precio_base = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Precio base en COP predeterminado para los viajes."
    )
    activo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nombre} ({self.precio_base} COP)"


class Actividad(models.Model):
    nombre = models.CharField(max_length=100)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre


class TasaBCV(models.Model):
    tasa = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Valor del USD en Bolívares según el BCV."
    )
    fecha_valor = models.CharField(
        max_length=50,
        blank=True,
        help_text="Fecha valor reportada por el BCV."
    )
    actualizado_en = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["-actualizado_en"]
        verbose_name = "Tasa BCV"
        verbose_name_plural = "Tasas BCV"

    def __str__(self):
        return f"USD/Bs {self.tasa} ({self.actualizado_en:%d/%m/%Y %H:%M})"


class PerfilUsuario(models.Model):
    ROL_ADMIN = 'ADMIN'
    ROL_VENDEDOR = 'VENDEDOR'

    ROLES = [
        (ROL_ADMIN, 'Administrador'),
        (ROL_VENDEDOR, 'Vendedor'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='perfil',
        verbose_name="Usuario"
    )
    rol = models.CharField(
        max_length=20,
        choices=ROLES,
        default=ROL_VENDEDOR,
        verbose_name="Rol en el sistema"
    )
    telefono = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Teléfono / WhatsApp"
    )
    creado_en = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación"
    )
    actualizado_en = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización"
    )

    class Meta:
        verbose_name = "Perfil de Usuario"
        verbose_name_plural = "Perfiles de Usuario"
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user.username} ({self.get_rol_display()})"

    @property
    def es_admin(self):
        return self.rol == self.ROL_ADMIN or self.user.is_superuser

    @property
    def es_vendedor(self):
        return self.rol == self.ROL_VENDEDOR and not self.user.is_superuser


@receiver(post_save, sender=User)
def asegurar_perfil_usuario(sender, instance, created, **kwargs):
    """
    Garantiza que todo usuario de Django tenga su perfil con rol asignado.
    Los superusuarios se inicializan por defecto como ADMIN.
    """
    if created:
        rol_inicial = PerfilUsuario.ROL_ADMIN if instance.is_superuser else PerfilUsuario.ROL_VENDEDOR
        PerfilUsuario.objects.get_or_create(user=instance, defaults={'rol': rol_inicial})

