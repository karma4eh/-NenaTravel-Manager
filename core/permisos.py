from functools import wraps
from django.shortcuts import render


def es_admin(user):
    """Verifica si el usuario tiene rol de Administrador o es superusuario."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    perfil = getattr(user, "perfil", None)
    return bool(perfil and perfil.rol == "ADMIN")


def es_vendedor(user):
    """Verifica si el usuario tiene rol de Vendedor."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return False
    perfil = getattr(user, "perfil", None)
    return bool(perfil and perfil.rol == "VENDEDOR")


def obtener_rol_usuario(user):
    """Devuelve el código de rol ('ADMIN' o 'VENDEDOR') del usuario."""
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return "ADMIN"
    perfil = getattr(user, "perfil", None)
    if perfil:
        return perfil.rol
    return "ADMIN" if user.is_staff else "VENDEDOR"


def admin_requerido(vista):
    """
    Decorador que restringe el acceso exclusivamente a usuarios
    con rol de Administrador.
    """
    @wraps(vista)
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_authenticated and es_admin(request.user)):
            return render(
                request,
                "core/acceso_denegado.html",
                {
                    "mensaje": "Esta sección está reservada exclusivamente para Administradores de Viajes Nena. Tu usuario actual tiene rol de Vendedor.",
                },
                status=403,
            )
        return vista(request, *args, **kwargs)

    return wrapper


def acceso_restringido(condicion, mensaje):
    """
    Permite entrar a una vista únicamente cuando
    se cumple la condición indicada.
    """
    def decorador(vista):
        @wraps(vista)
        def wrapper(request, *args, **kwargs):
            if not condicion(request, *args, **kwargs):
                return render(
                    request,
                    "core/acceso_denegado.html",
                    {"mensaje": mensaje},
                    status=403,
                )

            return vista(request, *args, **kwargs)

        return wrapper
    return decorador
