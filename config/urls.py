from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from core.views import (
    home,
    logout_view,
    ping_session,
    actualizar_tasa_bcv_view,
    api_tasa_bcv,
    cambiar_tasas,
    gestion_precios,
    estadisticas,
    gestion_usuarios,
    crear_usuario,
    editar_usuario,
    cambiar_password_usuario,
    toggle_estado_usuario,
)

from viajes.views import (
    crear_viaje,
    api_analizar_listin,
    importar_listin,
    los_juanes,
    finalizar_viaje,
    control_comidas,
)

from consumos.views import (
    registrar_consumos,
    cobros,
)


urlpatterns = [
    path("", home, name="home"),

    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html"
        ),
        name="login",
    ),

    path(
        "logout/",
        logout_view,
        name="logout",
    ),

    path("admin/", admin.site.urls),

    path(
        "actualizar-tasa-bcv/",
        actualizar_tasa_bcv_view,
        name="actualizar_tasa_bcv",
    ),

    path(
        "api/tasa-bcv/",
        api_tasa_bcv,
        name="api_tasa_bcv",
    ),

    path(
        "api/ping-session/",
        ping_session,
        name="api_ping_session",
    ),

    path(
        "cambiar-tasas/",
        cambiar_tasas,
        name="cambiar_tasas",
    ),

    path(
        "precios/",
        gestion_precios,
        name="gestion_precios",
    ),

    path(
        "crear-viaje/",
        crear_viaje,
        name="crear_viaje",
    ),

    path(
        "api/analizar-listin/",
        api_analizar_listin,
        name="api_analizar_listin",
    ),

    path(
        "importar-listin/",
        importar_listin,
        name="importar_listin",
    ),

    path(
        "los-juanes/",
        los_juanes,
        name="los_juanes",
    ),

    path(
        "consumos/",
        registrar_consumos,
        name="registrar_consumos",
    ),

    path(
        "cobros/",
        cobros,
        name="cobros",
    ),

    path(
        "estadisticas/",
        estadisticas,
        name="estadisticas",
    ),

    path(
        "finalizar-viaje/",
        finalizar_viaje,
        name="finalizar_viaje",
    ),

    path(
        "usuarios/",
        gestion_usuarios,
        name="gestion_usuarios",
    ),
    path(
        "usuarios/crear/",
        crear_usuario,
        name="crear_usuario",
    ),
    path(
        "usuarios/<int:user_id>/editar/",
        editar_usuario,
        name="editar_usuario",
    ),
    path(
        "usuarios/<int:user_id>/password/",
        cambiar_password_usuario,
        name="cambiar_password_usuario",
    ),
    path(
        "usuarios/<int:user_id>/toggle-estado/",
        toggle_estado_usuario,
        name="toggle_estado_usuario",
    ),

    path(
        "comidas/",
        control_comidas,
        name="control_comidas",
    ),
]
