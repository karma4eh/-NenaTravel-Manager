from core.permisos import es_admin, obtener_rol_usuario


def roles_context(request):
    """
    Inyecta datos de rol y permisos globales en todos los templates de la aplicación.
    """
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return {
            "es_admin": False,
            "user_rol": None,
            "user_rol_display": "Invitado",
        }

    es_adm = es_admin(request.user)
    rol = obtener_rol_usuario(request.user)
    rol_display = "Administrador" if es_adm else "Vendedor"

    return {
        "es_admin": es_adm,
        "user_rol": rol,
        "user_rol_display": rol_display,
    }
