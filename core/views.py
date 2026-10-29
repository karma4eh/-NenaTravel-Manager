import json
from decimal import Decimal, ROUND_HALF_UP
from core.models import Producto, PerfilUsuario, TasaBCV
from core.services_precios import sincronizar_precios_viaje
from core.permisos import admin_requerido
from viajes.models import PrecioProducto

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Sum, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404

from viajes.models import Viaje, Pasajero, Grupo, Cargo
from consumos.models import AplicacionPago, Pago, Consumo
from .services_bcv import obtener_tasa_bcv


def logout_view(request):
    """Cierra la sesión y redirige al inicio de sesión."""
    inactividad = request.GET.get("inactividad") == "1"
    logout(request)
    if inactividad:
        return redirect("/login/?inactividad=1")
    return redirect("login")


@login_required
def ping_session(request):
    """Refresca la sesión activa del usuario para prevenir expiración."""
    request.session.modified = True
    return JsonResponse({"ok": True, "user": request.user.username})


@login_required
def home(request):
    """
    Panel principal de Viajes Nena.
    Muestra el viaje activo, estadísticas y los accesos del sistema.
    """

    viaje_activo = (
        Viaje.objects
        .filter(estado="ACTIVO")
        .order_by("-fecha_inicio")
        .first()
    )

    # Tasa BCV (obtenida de caché si ya se consultó hoy)
    info_bcv = obtener_tasa_bcv(forzar=False)

    # Estadísticas en vivo del viaje activo.
    C = 339.292  # 2 * pi * 54
    stats = {
        "total_pasajeros": 0,
        "total_grupos": 0,
        "total_buses": 0,
        "total_cargos": Decimal("0.00"),
        "total_recaudado": Decimal("0.00"),
        "saldo_pendiente": Decimal("0.00"),
        "total_cargos_usd": Decimal("0.00"),
        "total_recaudado_usd": Decimal("0.00"),
        "saldo_pendiente_usd": Decimal("0.00"),
        "porcentaje_recaudado": 0,
        "porcentaje_pendiente": 0,
        "len_recaudado": 0,
        "len_pendiente": 0,
        "dash_offset": 339.29,
    }

    if viaje_activo:
        stats["total_pasajeros"] = Pasajero.objects.filter(
            viaje=viaje_activo,
        ).count()

        stats["total_grupos"] = Grupo.objects.filter(
            viaje=viaje_activo,
        ).count()

        buses = (
            Grupo.objects.filter(viaje=viaje_activo)
            .exclude(bus__isnull=True)
            .exclude(bus=0)
            .values_list("bus", flat=True)
            .distinct()
        )
        stats["total_buses"] = buses.count()

        cargos_total = (
            Cargo.objects.filter(pasajero__viaje=viaje_activo)
            .aggregate(total=Sum("total"))
        )
        stats["total_cargos"] = cargos_total["total"] or Decimal("0.00")

        recaudado = (
            AplicacionPago.objects.filter(
                cargo__pasajero__viaje=viaje_activo,
            )
            .aggregate(total=Sum("monto_cop"))
        )
        stats["total_recaudado"] = recaudado["total"] or Decimal("0.00")

        stats["saldo_pendiente"] = max(
            Decimal("0.00"), stats["total_cargos"] - stats["total_recaudado"]
        )

        tasa_cop = viaje_activo.tasa_usd_cop if viaje_activo.tasa_usd_cop > 0 else Decimal("3200")
        stats["total_cargos_usd"] = (stats["total_cargos"] / tasa_cop).quantize(Decimal("0.01"))
        stats["total_recaudado_usd"] = (stats["total_recaudado"] / tasa_cop).quantize(Decimal("0.01"))
        stats["saldo_pendiente_usd"] = (stats["saldo_pendiente"] / tasa_cop).quantize(Decimal("0.01"))

        if stats["total_cargos"] > 0:
            pct = (stats["total_recaudado"] / stats["total_cargos"]) * 100
            stats["porcentaje_recaudado"] = min(100.0, round(float(pct), 1))
            stats["porcentaje_pendiente"] = max(0.0, round(100.0 - stats["porcentaje_recaudado"], 1))
            stats["len_recaudado"] = round(C * (stats["porcentaje_recaudado"] / 100.0), 2)
            stats["len_pendiente"] = round(C * (stats["porcentaje_pendiente"] / 100.0), 2)
        else:
            stats["porcentaje_recaudado"] = 0
            stats["porcentaje_pendiente"] = 0
            stats["len_recaudado"] = 0
            stats["len_pendiente"] = 0

        stats["dash_offset"] = round(C * (1 - (stats["porcentaje_recaudado"] / 100.0)), 2)

    return render(
        request,
        "core/home.html",
        {
            "viaje_activo": viaje_activo,
            "hay_viaje_activo": viaje_activo is not None,
            "stats": stats,
            "info_bcv": info_bcv,
        },
    )


@login_required
@admin_requerido
def actualizar_tasa_bcv_view(request):
    """
    Fuerza la consulta a la página oficial del BCV y actualiza
    la tasa USD/Bs del viaje activo si existe.
    """
    res = obtener_tasa_bcv(forzar=True)
    viaje_activo = (
        Viaje.objects
        .filter(estado="ACTIVO")
        .order_by("-fecha_inicio")
        .first()
    )

    if viaje_activo and res.get("tasa"):
        viaje_activo.tasa_usd_bs = res["tasa"]
        viaje_activo.save(update_fields=["tasa_usd_bs"])

    if res.get("error"):
        messages.warning(request, f"Aviso al consultar BCV: {res['error']}")
    else:
        fecha_str = f" ({res['fecha_valor']})" if res.get("fecha_valor") else ""
        messages.success(
            request,
            f"Tasa oficial BCV actualizada: {res['tasa']} Bs.{fecha_str}"
        )

    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "home"
    return redirect(next_url)


@login_required
def api_tasa_bcv(request):
    """
    API JSON para consultar o refrescar la tasa del BCV sin recargar la página.
    Parámetro GET: forzar=1 para hacer scraping en vivo.
    """
    forzar = request.GET.get("forzar") == "1"
    res = obtener_tasa_bcv(forzar=forzar)
    return JsonResponse({
        "tasa": str(res["tasa"]),
        "fecha_valor": res.get("fecha_valor", ""),
        "origen": res.get("origen", ""),
        "error": res.get("error"),
    })


@login_required
@admin_requerido
def cambiar_tasas(request):
    """
    Permite consultar y actualizar las tasas de cambio (USD/Bs y USD/COP)
    del viaje activo, con botón para obtener la tasa del BCV.
    """
    viaje_activo = (
        Viaje.objects
        .filter(estado="ACTIVO")
        .order_by("-fecha_inicio")
        .first()
    )

    if not viaje_activo:
        messages.warning(request, "No hay ningún viaje activo para cambiar tasas.")
        return redirect("home")

    info_bcv = obtener_tasa_bcv(forzar=False)

    if request.method == "POST":
        accion = request.POST.get("accion")

        if accion == "actualizar_bcv":
            info_bcv = obtener_tasa_bcv(forzar=True)
            if info_bcv.get("error"):
                messages.warning(request, info_bcv["error"])
            else:
                viaje_activo.tasa_usd_bs = info_bcv["tasa"]
                viaje_activo.save(update_fields=["tasa_usd_bs"])
                messages.success(
                    request,
                    f"Tasa USD/Bs actualizada desde el BCV: {info_bcv['tasa']} Bs."
                )
            return redirect("cambiar_tasas")

        elif accion == "guardar_tasas":
            try:
                tasa_bs = Decimal(
                    request.POST.get("tasa_usd_bs", "").replace(",", ".").strip()
                )
                tasa_cop = Decimal(
                    request.POST.get("tasa_usd_cop", "").replace(",", ".").strip()
                )

                if tasa_bs <= 0 or tasa_cop <= 0:
                    raise ValueError

                viaje_activo.tasa_usd_bs = tasa_bs
                viaje_activo.tasa_usd_cop = tasa_cop
                viaje_activo.save(update_fields=["tasa_usd_bs", "tasa_usd_cop"])

                messages.success(request, "Tasas de cambio actualizadas correctamente.")
                return redirect("home")
            except Exception:
                messages.error(
                    request,
                    "Las tasas de cambio deben ser números válidos mayores a cero."
                )

    return render(
        request,
        "core/cambiar_tasas.html",
        {
            "viaje_activo": viaje_activo,
            "info_bcv": info_bcv,
        },
    )


@login_required
@admin_requerido
def gestion_precios(request):
    """
    Catálogo de productos y lista de precios base en COP.
    Permite editar los precios predeterminados que se aplican a los viajes,
    crear productos nuevos, activar/desactivar y sincronizar con el viaje activo.
    """
    viaje_activo = (
        Viaje.objects
        .filter(estado="ACTIVO")
        .order_by("-fecha_inicio")
        .first()
    )

    if request.method == "POST":
        accion = request.POST.get("accion")

        if accion == "guardar_precios":
            productos = Producto.objects.all()
            actualizados = 0
            for prod in productos:
                campo = f"precio_{prod.id}"
                if campo in request.POST:
                    try:
                        val_str = request.POST.get(campo, "").replace(",", ".").strip()
                        nuevo_precio = Decimal(val_str)
                        if nuevo_precio < 0:
                            continue
                        if prod.precio_base != nuevo_precio:
                            prod.precio_base = nuevo_precio
                            prod.save(update_fields=["precio_base"])
                            actualizados += 1
                    except Exception:
                        pass

            aplicar_viaje = request.POST.get("aplicar_viaje_activo") == "1"
            if aplicar_viaje and viaje_activo:
                sincronizar_precios_viaje(viaje_activo, sobrescribir=True)
                messages.success(
                    request,
                    "Lista de precios base guardada y aplicada al viaje activo."
                )
            else:
                messages.success(
                    request,
                    f"Lista de precios base guardada correctamente ({actualizados} producto(s) actualizados)."
                )
            return redirect("gestion_precios")

        elif accion == "crear_producto":
            nombre = request.POST.get("nombre", "").strip()
            categoria = request.POST.get("categoria", "").strip() or "Bebidas"
            try:
                precio_base = Decimal(
                    request.POST.get("precio_base", "0").replace(",", ".").strip()
                )
            except Exception:
                precio_base = Decimal("0.00")

            if nombre:
                prod = Producto.objects.create(
                    nombre=nombre,
                    categoria=categoria,
                    precio_base=precio_base,
                    activo=True,
                )
                if viaje_activo:
                    PrecioProducto.objects.get_or_create(
                        viaje=viaje_activo,
                        producto=prod,
                        defaults={"precio": precio_base},
                    )
                messages.success(request, f"Producto «{nombre}» agregado a la lista de precios.")
            else:
                messages.error(request, "El nombre del producto es obligatorio.")
            return redirect("gestion_precios")

        elif accion == "sincronizar_viaje":
            if viaje_activo:
                res = sincronizar_precios_viaje(viaje_activo, sobrescribir=True)
                messages.success(
                    request,
                    f"Precios sincronizados con el viaje activo: {res['actualizados']} actualizados, {res['creados']} creados."
                )
            return redirect("gestion_precios")

        elif accion == "toggle_activo":
            prod_id = request.POST.get("producto_id")
            prod = Producto.objects.filter(id=prod_id).first()
            if prod:
                prod.activo = not prod.activo
                prod.save(update_fields=["activo"])
                estado = "activado" if prod.activo else "desactivado"
                messages.info(request, f"Producto «{prod.nombre}» {estado}.")
            return redirect("gestion_precios")

    productos = list(Producto.objects.all().order_by("categoria", "nombre"))

    precios_viaje = {}
    if viaje_activo:
        precios_viaje = {
            pp.producto_id: pp.precio
            for pp in PrecioProducto.objects.filter(viaje=viaje_activo)
        }

    productos_data = [
        {
            "producto": prod,
            "precio_base": prod.precio_base,
            "precio_viaje": precios_viaje.get(prod.id),
        }
        for prod in productos
    ]

    return render(
        request,
        "core/gestion_precios.html",
        {
            "viaje_activo": viaje_activo,
            "productos_data": productos_data,
            "total_productos": len(productos),
            "total_activos": sum(1 for p in productos if p.activo),
        },
    )


@login_required
@admin_requerido
def estadisticas(request):
    """
    Dashboard analítico dinámico con métricas financieras globales,
    recaudación por moneda (COP, USD, Bs), métodos de pago,
    top productos más vendidos y gráficos interactivos.
    """
    viajes = Viaje.objects.all().order_by("-fecha_inicio")
    viaje_id = request.GET.get("viaje")

    if viaje_id:
        viaje = Viaje.objects.filter(pk=viaje_id).first()
    else:
        viaje = Viaje.objects.filter(estado="ACTIVO").order_by("-fecha_inicio").first() or viajes.first()

    if not viaje:
        messages.info(request, "No hay ningún viaje registrado para consultar estadísticas.")
        return redirect("home")

    tasa_cop = viaje.tasa_usd_cop if viaje.tasa_usd_cop > 0 else Decimal("3200")
    tasa_bs = viaje.tasa_usd_bs if viaje.tasa_usd_bs > 0 else Decimal("989.72")

    cargos_qs = (
        Cargo.objects.filter(pasajero__viaje=viaje)
        .select_related("pasajero", "pasajero__grupo", "evento", "producto")
        .annotate(abonado=Sum("aplicaciones_pago__monto_cop"))
    )
    pagos_qs = (
        Pago.objects.filter(viaje=viaje)
        .select_related("registrado_por", "grupo")
        .order_by("-creado_en")
    )
    aplicaciones_qs = (
        AplicacionPago.objects.filter(cargo__pasajero__viaje=viaje)
        .select_related("pago", "cargo")
    )

    total_facturado_cop = cargos_qs.aggregate(t=Sum("total"))["t"] or Decimal("0.00")
    total_recaudado_cop = aplicaciones_qs.aggregate(t=Sum("monto_cop"))["t"] or Decimal("0.00")
    saldo_pendiente_cop = max(Decimal("0.00"), total_facturado_cop - total_recaudado_cop)

    # Conversiones a USD y Bs
    total_facturado_usd = (total_facturado_cop / tasa_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_recaudado_usd = (total_recaudado_cop / tasa_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    saldo_pendiente_usd = (saldo_pendiente_cop / tasa_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    total_facturado_bs = (total_facturado_usd * tasa_bs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_recaudado_bs = (total_recaudado_usd * tasa_bs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    saldo_pendiente_bs = (saldo_pendiente_usd * tasa_bs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    pct_recaudado = round(float((total_recaudado_cop / total_facturado_cop) * 100), 1) if total_facturado_cop > 0 else 0
    pct_pendiente = round(100.0 - pct_recaudado, 1) if total_facturado_cop > 0 else 0

    # Recaudado Real por Moneda Original
    recaudado_monedas = {}
    for m, nombre, symbol in [("COP", "Pesos Colombianos", "COP"), ("USD", "Dólares", "$"), ("BS", "Bolívares", "Bs")]:
        p_moneda = pagos_qs.filter(moneda=m)
        m_orig = p_moneda.aggregate(t=Sum("monto_original"))["t"] or Decimal("0.00")
        m_cop = p_moneda.aggregate(t=Sum("equivalente_cop"))["t"] or Decimal("0.00")
        m_usd = p_moneda.aggregate(t=Sum("equivalente_usd"))["t"] or Decimal("0.00")
        m_bs = p_moneda.aggregate(t=Sum("equivalente_bs"))["t"] or Decimal("0.00")
        recaudado_monedas[m] = {
            "nombre": nombre,
            "symbol": symbol,
            "monto_original": m_orig,
            "equivalente_cop": m_cop,
            "equivalente_usd": m_usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "equivalente_bs": m_bs.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "count": p_moneda.count(),
            "pct": round(float((m_cop / total_recaudado_cop) * 100), 1) if total_recaudado_cop > 0 else 0,
        }

    # Desglose por métodos de pago
    metodos_map = {
        "EFECTIVO": "Efectivo",
        "PAGO_MOVIL": "Pago Móvil",
        "TRANSFERENCIA": "Transferencia",
        "PUNTO_VENTA": "Punto de Venta",
        "BANCOLOMBIA": "Bancolombia",
        "NEQUI": "Nequi",
        "ZELLE": "Zelle",
        "BINANCE": "Binance",
    }
    pagos_por_metodo = {}
    for pago in pagos_qs:
        metodo = "Efectivo"
        for code, label in metodos_map.items():
            if f"[{label}]" in pago.observacion or f"[{code}]" in pago.observacion:
                metodo = label
                break
        key = f"{metodo} ({pago.moneda})"
        if key not in pagos_por_metodo:
            pagos_por_metodo[key] = {
                "metodo": metodo,
                "moneda": pago.moneda,
                "monto_original": Decimal("0.00"),
                "equivalente_cop": Decimal("0.00"),
                "equivalente_usd": Decimal("0.00"),
                "transacciones": 0,
            }
        pagos_por_metodo[key]["monto_original"] += pago.monto_original
        pagos_por_metodo[key]["equivalente_cop"] += pago.equivalente_cop
        pagos_por_metodo[key]["equivalente_usd"] += pago.equivalente_usd
        pagos_por_metodo[key]["transacciones"] += 1

    lista_metodos = sorted(pagos_por_metodo.values(), key=lambda x: x["equivalente_cop"], reverse=True)

    # Top Productos Más Vendidos
    prods_dict = {}
    tot_unidades = 0
    for c in cargos_qs:
        concepto = c.concepto.strip()
        if concepto not in prods_dict:
            prods_dict[concepto] = {
                "concepto": concepto,
                "unidades": 0,
                "total_cop": Decimal("0.00"),
                "es_juanes": concepto.casefold() == "los juanes",
            }
        prods_dict[concepto]["unidades"] += int(c.cantidad)
        prods_dict[concepto]["total_cop"] += c.total
        tot_unidades += int(c.cantidad)

    top_productos = []
    for concepto, data in sorted(prods_dict.items(), key=lambda x: x[1]["unidades"], reverse=True):
        u = data["unidades"]
        tot = data["total_cop"]
        usd = (tot / tasa_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        precio_prom = (tot / u).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if u > 0 else Decimal("0.00")
        pct_u = round((u / tot_unidades * 100), 1) if tot_unidades > 0 else 0
        pct_cop = round(float((tot / total_facturado_cop * 100)), 1) if total_facturado_cop > 0 else 0
        top_productos.append({
            "concepto": concepto,
            "unidades": u,
            "total_cop": tot,
            "total_usd": usd,
            "precio_promedio": precio_prom,
            "pct_unidades": pct_u,
            "pct_cop": pct_cop,
            "es_juanes": data["es_juanes"],
        })

    # Ventas por Evento / Día
    eventos_dict = {}
    for c in cargos_qs:
        ev_nombre = c.evento.nombre if c.evento else "General / Sin Evento"
        if ev_nombre not in eventos_dict:
            eventos_dict[ev_nombre] = {
                "nombre": ev_nombre,
                "unidades": 0,
                "total_cop": Decimal("0.00"),
            }
        eventos_dict[ev_nombre]["unidades"] += int(c.cantidad)
        eventos_dict[ev_nombre]["total_cop"] += c.total

    lista_eventos = []
    for ev_nombre, data in sorted(eventos_dict.items(), key=lambda x: x[1]["total_cop"], reverse=True):
        tot = data["total_cop"]
        usd = (tot / tasa_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        pct = round(float((tot / total_facturado_cop * 100)), 1) if total_facturado_cop > 0 else 0
        lista_eventos.append({
            "nombre": ev_nombre,
            "unidades": data["unidades"],
            "total_cop": tot,
            "total_usd": usd,
            "pct": pct,
        })

    # Top Grupos con Mayor Consumo
    grupos_consumo = {}
    for c in cargos_qs:
        grp = c.pasajero.grupo
        gid = grp.id
        if gid not in grupos_consumo:
            grupos_consumo[gid] = {
                "grupo": grp,
                "total_cop": Decimal("0.00"),
                "total_abonado": Decimal("0.00"),
                "saldo": Decimal("0.00"),
                "unidades": 0,
            }
        abono = c.abonado or Decimal("0.00")
        grupos_consumo[gid]["total_cop"] += c.total
        grupos_consumo[gid]["total_abonado"] += abono
        grupos_consumo[gid]["saldo"] += max(Decimal("0.00"), c.total - abono)
        grupos_consumo[gid]["unidades"] += int(c.cantidad)

    lista_grupos = []
    for data in sorted(grupos_consumo.values(), key=lambda x: x["total_cop"], reverse=True):
        tot = data["total_cop"]
        usd = (tot / tasa_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cant_pax = data["grupo"].pasajeros.count()
        prom_pax = (tot / cant_pax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if cant_pax > 0 else Decimal("0.00")
        lista_grupos.append({
            "grupo": data["grupo"],
            "total_cop": tot,
            "total_usd": usd,
            "saldo_cop": data["saldo"],
            "unidades": data["unidades"],
            "cant_pax": cant_pax,
            "promedio_pax": prom_pax,
        })

    # Pasajeros Solventes vs Deudores
    pasajeros_viaje = Pasajero.objects.filter(viaje=viaje)
    total_pasajeros = pasajeros_viaje.count()
    deudores_ids = set(c.pasajero_id for c in cargos_qs if (c.total - (c.abonado or Decimal("0.00"))) > Decimal("0.00"))
    cant_deudores = len(deudores_ids)
    cant_solventes = max(0, total_pasajeros - cant_deudores)
    pct_solventes = round((cant_solventes / total_pasajeros * 100), 1) if total_pasajeros > 0 else 100

    # JSON Data para gráficos interactivos
    chart_productos_labels = [p["concepto"] for p in top_productos[:10]]
    chart_productos_units = [p["unidades"] for p in top_productos[:10]]
    chart_productos_cop = [float(p["total_cop"]) for p in top_productos[:10]]

    chart_eventos_labels = [e["nombre"] for e in lista_eventos]
    chart_eventos_cop = [float(e["total_cop"]) for e in lista_eventos]

    chart_metodos_labels = [m["metodo"] + " (" + m["moneda"] + ")" for m in lista_metodos]
    chart_metodos_cop = [float(m["equivalente_cop"]) for m in lista_metodos]

    json_chart_data = json.dumps({
        "productos": {
            "labels": chart_productos_labels,
            "units": chart_productos_units,
            "cop": chart_productos_cop,
        },
        "eventos": {
            "labels": chart_eventos_labels,
            "cop": chart_eventos_cop,
        },
        "metodos": {
            "labels": chart_metodos_labels,
            "cop": chart_metodos_cop,
        },
        "solvencia": {
            "recaudado": float(total_recaudado_cop),
            "pendiente": float(saldo_pendiente_cop),
            "pct_recaudado": pct_recaudado,
            "pct_pendiente": pct_pendiente,
        }
    })

    return render(
        request,
        "core/estadisticas.html",
        {
            "viaje": viaje,
            "viajes": viajes,
            "total_facturado_cop": total_facturado_cop,
            "total_facturado_usd": total_facturado_usd,
            "total_facturado_bs": total_facturado_bs,
            "total_recaudado_cop": total_recaudado_cop,
            "total_recaudado_usd": total_recaudado_usd,
            "total_recaudado_bs": total_recaudado_bs,
            "saldo_pendiente_cop": saldo_pendiente_cop,
            "saldo_pendiente_usd": saldo_pendiente_usd,
            "saldo_pendiente_bs": saldo_pendiente_bs,
            "pct_recaudado": pct_recaudado,
            "pct_pendiente": pct_pendiente,
            "recaudado_monedas": recaudado_monedas,
            "top_productos": top_productos,
            "tot_unidades": tot_unidades,
            "lista_metodos": lista_metodos,
            "lista_eventos": lista_eventos,
            "lista_grupos": lista_grupos,
            "total_pasajeros": total_pasajeros,
            "cant_solventes": cant_solventes,
            "cant_deudores": cant_deudores,
            "pct_solventes": pct_solventes,
            "json_chart_data": json_chart_data,
        },
    )


# ============================================================
# GESTIÓN DE USUARIOS Y ROLES (SOLO ADMINISTRADORES)
# ============================================================

@login_required
@admin_requerido
def gestion_usuarios(request):
    """
    Listado y administración de usuarios y roles del sistema.
    Muestra estadísticas de personal, listado de cuentas, y modales
    para creación, edición de rol/perfil, reseteo de contraseñas y activación.
    """
    busqueda = request.GET.get("q", "").strip()
    filtro_rol = request.GET.get("rol", "").strip()
    filtro_estado = request.GET.get("estado", "").strip()

    todos = User.objects.select_related("perfil").order_by("-is_superuser", "username")

    # Asegura que cada usuario tenga un perfil enlazado
    for u in todos:
        if not hasattr(u, "perfil"):
            rol_def = PerfilUsuario.ROL_ADMIN if u.is_superuser else PerfilUsuario.ROL_VENDEDOR
            PerfilUsuario.objects.get_or_create(user=u, defaults={"rol": rol_def})

    todos = list(User.objects.select_related("perfil").order_by("-is_superuser", "username"))

    total_usuarios = len(todos)
    total_admins = sum(
        1 for u in todos
        if u.is_superuser or (hasattr(u, "perfil") and u.perfil.rol == PerfilUsuario.ROL_ADMIN)
    )
    total_vendedores = sum(
        1 for u in todos
        if not u.is_superuser and hasattr(u, "perfil") and u.perfil.rol == PerfilUsuario.ROL_VENDEDOR
    )
    total_activos = sum(1 for u in todos if u.is_active)
    total_inactivos = total_usuarios - total_activos

    # Filtrar usuarios para la tabla
    usuarios_filtrados = todos

    if busqueda:
        q_low = busqueda.lower()
        usuarios_filtrados = [
            u for u in usuarios_filtrados
            if (q_low in u.username.lower() or
                q_low in (u.first_name or "").lower() or
                q_low in (u.last_name or "").lower() or
                q_low in (u.email or "").lower() or
                (hasattr(u, "perfil") and q_low in (u.perfil.telefono or "").lower()))
        ]

    if filtro_rol == "ADMIN":
        usuarios_filtrados = [
            u for u in usuarios_filtrados
            if u.is_superuser or (hasattr(u, "perfil") and u.perfil.rol == PerfilUsuario.ROL_ADMIN)
        ]
    elif filtro_rol == "VENDEDOR":
        usuarios_filtrados = [
            u for u in usuarios_filtrados
            if not u.is_superuser and hasattr(u, "perfil") and u.perfil.rol == PerfilUsuario.ROL_VENDEDOR
        ]

    if filtro_estado == "activos":
        usuarios_filtrados = [u for u in usuarios_filtrados if u.is_active]
    elif filtro_estado == "inactivos":
        usuarios_filtrados = [u for u in usuarios_filtrados if not u.is_active]

    context = {
        "usuarios": usuarios_filtrados,
        "total_usuarios": total_usuarios,
        "total_admins": total_admins,
        "total_vendedores": total_vendedores,
        "total_activos": total_activos,
        "total_inactivos": total_inactivos,
        "busqueda": busqueda,
        "filtro_rol": filtro_rol,
        "filtro_estado": filtro_estado,
    }
    return render(request, "core/gestion_usuarios.html", context)


@login_required
@admin_requerido
def crear_usuario(request):
    """
    Crea un nuevo usuario en el sistema con credenciales y rol (ADMIN o VENDEDOR).
    """
    if request.method != "POST":
        return redirect("gestion_usuarios")

    username = request.POST.get("username", "").strip()
    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    email = request.POST.get("email", "").strip()
    password = request.POST.get("password", "").strip()
    password_confirm = request.POST.get("password_confirm", "").strip()
    rol = request.POST.get("rol", PerfilUsuario.ROL_VENDEDOR).strip().upper()
    telefono = request.POST.get("telefono", "").strip()

    if not username:
        messages.error(request, "El nombre de usuario es obligatorio.")
        return redirect("gestion_usuarios")

    if User.objects.filter(username__iexact=username).exists():
        messages.error(request, f"El usuario '{username}' ya existe. Por favor utiliza un nombre diferente.")
        return redirect("gestion_usuarios")

    if not password or len(password) < 4:
        messages.error(request, "La contraseña debe tener al menos 4 caracteres.")
        return redirect("gestion_usuarios")

    if password != password_confirm:
        messages.error(request, "Las contraseñas no coinciden. Por favor verifícalas.")
        return redirect("gestion_usuarios")

    if rol not in [PerfilUsuario.ROL_ADMIN, PerfilUsuario.ROL_VENDEDOR]:
        rol = PerfilUsuario.ROL_VENDEDOR

    try:
        nuevo_user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        nuevo_user.is_staff = (rol == PerfilUsuario.ROL_ADMIN)
        nuevo_user.save()

        PerfilUsuario.objects.update_or_create(
            user=nuevo_user,
            defaults={"rol": rol, "telefono": telefono}
        )
        rol_nombre = "Administrador" if rol == PerfilUsuario.ROL_ADMIN else "Vendedor"
        messages.success(request, f"¡Usuario '{username}' registrado exitosamente con rol {rol_nombre}!")
    except Exception as e:
        messages.error(request, f"Error al crear el usuario: {str(e)}")

    return redirect("gestion_usuarios")


@login_required
@admin_requerido
def editar_usuario(request, user_id):
    """
    Modifica datos personales, teléfono y rol de un usuario existente.
    """
    if request.method != "POST":
        return redirect("gestion_usuarios")

    usuario_obj = get_object_or_404(User, pk=user_id)
    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    email = request.POST.get("email", "").strip()
    rol = request.POST.get("rol", "").strip().upper()
    telefono = request.POST.get("telefono", "").strip()

    # Seguridad: no permitir auto-degradarse de admin si es el único admin activo
    if usuario_obj.id == request.user.id and rol == PerfilUsuario.ROL_VENDEDOR:
        admins_activos = User.objects.filter(is_active=True).filter(
            Q(is_superuser=True) | Q(perfil__rol=PerfilUsuario.ROL_ADMIN)
        ).count()
        if admins_activos <= 1:
            messages.error(request, "Acción bloqueada: No puedes retirar tu rol de Administrador siendo el único admin activo del sistema.")
            return redirect("gestion_usuarios")

    usuario_obj.first_name = first_name
    usuario_obj.last_name = last_name
    usuario_obj.email = email

    if rol in [PerfilUsuario.ROL_ADMIN, PerfilUsuario.ROL_VENDEDOR]:
        if not usuario_obj.is_superuser:
            usuario_obj.is_staff = (rol == PerfilUsuario.ROL_ADMIN)
        perfil, _ = PerfilUsuario.objects.get_or_create(user=usuario_obj)
        perfil.rol = rol
        perfil.telefono = telefono
        perfil.save()

    usuario_obj.save()
    messages.success(request, f"Datos del usuario '{usuario_obj.username}' actualizados correctamente.")
    return redirect("gestion_usuarios")


@login_required
@admin_requerido
def cambiar_password_usuario(request, user_id):
    """
    Permite a un Administrador resetear la contraseña de cualquier usuario.
    """
    if request.method != "POST":
        return redirect("gestion_usuarios")

    usuario_obj = get_object_or_404(User, pk=user_id)
    password = request.POST.get("nuevo_password", "").strip()
    password_confirm = request.POST.get("confirmar_password", "").strip()

    if not password or len(password) < 4:
        messages.error(request, "La nueva contraseña debe contener al menos 4 caracteres.")
        return redirect("gestion_usuarios")

    if password != password_confirm:
        messages.error(request, "Las contraseñas no coinciden. Por favor verifícalas.")
        return redirect("gestion_usuarios")

    usuario_obj.set_password(password)
    usuario_obj.save()

    if usuario_obj.id == request.user.id:
        update_session_auth_hash(request, usuario_obj)

    messages.success(request, f"Contraseña actualizada exitosamente para el usuario '{usuario_obj.username}'.")
    return redirect("gestion_usuarios")


@login_required
@admin_requerido
def toggle_estado_usuario(request, user_id):
    """
    Activa o desactiva la cuenta de un usuario.
    Impide que el usuario activo desactive su propia cuenta.
    """
    if request.method != "POST":
        return redirect("gestion_usuarios")

    usuario_obj = get_object_or_404(User, pk=user_id)

    if usuario_obj.id == request.user.id:
        messages.error(request, "Operación inválida: No puedes desactivar tu propia cuenta activa.")
        return redirect("gestion_usuarios")

    usuario_obj.is_active = not usuario_obj.is_active
    usuario_obj.save()

    estado_str = "activado" if usuario_obj.is_active else "desactivado (acceso bloqueado)"
    messages.success(request, f"El usuario '{usuario_obj.username}' ha sido {estado_str}.")
    return redirect("gestion_usuarios")
