import math

from core.services_precios import sincronizar_precios_viaje

from decimal import Decimal, ROUND_HALF_UP



from django.contrib.auth.decorators import login_required

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.core.cache import cache
from django.db.models import Q, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from viajes.models import (
    Viaje,
    Evento,
    Pasajero,
    PrecioProducto,
    Cargo,
    AsistenciaActividad,
)
from core.models import Producto
from .models import Consumo, AplicacionPago
from .services_cobros import registrar_pago


@login_required
def registrar_consumos(request):
    viajes = Viaje.objects.filter(
        estado='ACTIVO'
    ).order_by('-fecha_inicio')

    viaje_id = request.GET.get('viaje') or request.POST.get('viaje')
    evento_id = request.GET.get('evento') or request.POST.get('evento')

    viaje = None
    evento = None
    pasajero = None
    eventos = []
    productos_formulario = []
    consumos_existentes = []
    todos_los_pasajeros = []
    resultados_busqueda = []
    total_consumos_evento = Decimal("0.00")
    total_cuenta_pasajero = Decimal("0.00")
    buscar = request.GET.get('buscar', '').strip()

    if viaje_id:
        viaje = get_object_or_404(
            Viaje,
            id=viaje_id,
            estado='ACTIVO'
        )
    else:
        viaje = viajes.first()

    if viaje:
        eventos = list(
            Evento.objects.filter(
                viaje=viaje
            ).order_by('orden', 'id')
        )

        if evento_id:
            evento = get_object_or_404(
                Evento,
                id=evento_id,
                viaje=viaje
            )
        elif eventos:
            evento = eventos[0]

        # Asegurar que todos los productos activos tengan precio en este viaje
        sincronizar_precios_viaje(viaje, sobrescribir=False)

        precios_lista = list(
            PrecioProducto.objects.filter(
                viaje=viaje,
                producto__activo=True
            ).select_related(
                'producto'
            ).order_by(
                'producto__nombre'
            )
        )

        precios = {
            item.producto_id: item.precio
            for item in precios_lista
        }

        productos = [
            item.producto
            for item in precios_lista
        ]

        pasajeros = Pasajero.objects.filter(
            viaje=viaje
        ).select_related(
            'grupo'
        ).order_by('grupo__nombre', 'nombre')

        todos_los_pasajeros = list(pasajeros)

        if buscar:
            b_lower = buscar.lower()
            resultados_busqueda = [
                p for p in todos_los_pasajeros
                if b_lower in p.nombre.lower()
                or (p.cedula and b_lower in p.cedula.lower())
                or (p.grupo and b_lower in p.grupo.nombre.lower())
            ]
        else:
            resultados_busqueda = todos_los_pasajeros

        pasajero_id = (
            request.GET.get('pasajero')
            or request.POST.get('pasajero')
        )

        if pasajero_id:
            pasajero = next((p for p in todos_los_pasajeros if str(p.id) == str(pasajero_id)), None)

        if pasajero and evento:
            consumos_existentes = list(
                Consumo.objects.filter(
                    viaje=viaje,
                    evento=evento,
                    pasajero=pasajero
                ).select_related(
                    'producto',
                    'cargo'
                ).order_by('producto__nombre')
            )

            consumos_por_producto = {
                consumo.producto_id: consumo
                for consumo in consumos_existentes
            }

            total_consumos_evento = sum((c.total for c in consumos_existentes), Decimal("0.00"))

            total_cuenta_pasajero = (
                Cargo.objects.filter(pasajero=pasajero)
                .aggregate(total=Sum('total'))['total'] or Decimal("0.00")
            )

            productos_formulario = [
                {
                    'producto': producto,
                    'precio': precios[producto.id],
                    'precio_usd': (
                        (precios[producto.id] / viaje.tasa_usd_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        if viaje.tasa_usd_cop > 0 else Decimal("0.00")
                    ),
                    'cantidad_actual': (
                        consumos_por_producto[producto.id].cantidad
                        if producto.id in consumos_por_producto
                        else 0
                    ),
                    'total_actual': (
                        consumos_por_producto[producto.id].total
                        if producto.id in consumos_por_producto
                        else Decimal("0.00")
                    ),
                }
                for producto in productos
            ]

            if request.method == 'POST':
                accion = request.POST.get('accion', 'agregar')

                if accion == 'agregar':
                    cantidades = []
                    error = None

                    for producto in productos:
                        campo = f'producto_{producto.id}'
                        texto = request.POST.get(campo, '0').strip()

                        try:
                            cantidad = int(texto or 0)
                            if cantidad < 0:
                                raise ValueError
                        except (ValueError, TypeError):
                            error = (
                                f'La cantidad adicional de {producto.nombre} '
                                'debe ser un entero igual o mayor que cero.'
                            )
                            break

                        if cantidad > 0 and producto.id not in precios:
                            error = (
                                f'No hay precio configurado para '
                                f'{producto.nombre} en este viaje.'
                            )
                            break

                        if cantidad > 0:
                            cantidades.append({
                                'producto': producto,
                                'cantidad': cantidad,
                                'precio': precios[producto.id],
                            })

                    if error:
                        messages.error(request, error)

                    elif not cantidades:
                        messages.warning(
                            request,
                            'Introduce una cantidad adicional mayor que cero.'
                        )

                    else:
                        try:
                            with transaction.atomic():
                                for item in cantidades:
                                    producto = item['producto']

                                    consumo = (
                                        Consumo.objects
                                        .select_for_update()
                                        .filter(
                                            viaje=viaje,
                                            pasajero=pasajero,
                                            evento=evento,
                                            producto=producto,
                                        )
                                        .first()
                                    )

                                    if consumo:
                                        consumo.cantidad += item['cantidad']
                                        consumo._usuario_modificacion = (
                                            request.user
                                            if request.user.is_authenticated
                                            else None
                                        )
                                        consumo.save()
                                    else:
                                        Consumo.objects.create(
                                            viaje=viaje,
                                            pasajero=pasajero,
                                            evento=evento,
                                            producto=producto,
                                            cantidad=item['cantidad'],
                                            precio_unitario=item['precio'],
                                        )

                            total_agregado = sum(it['cantidad'] * it['precio'] for it in cantidades)
                            messages.success(
                                request,
                                f'Consumos registrados para {pasajero.nombre} (+{total_agregado:,.0f} COP).'
                            )

                            return redirect(
                                f'/consumos/?viaje={viaje.id}'
                                f'&evento={evento.id}'
                                f'&pasajero={pasajero.id}'
                            )

                        except IntegrityError:
                            messages.error(
                                request,
                                'Hubo un registro simultáneo de este consumo. '
                                'Recarga la cuenta y verifica las cantidades.'
                            )

    return render(
        request,
        'consumos/registrar_consumos.html',
        {
            'viajes': viajes,
            'viaje': viaje,
            'eventos': eventos,
            'evento': evento,
            'buscar': buscar,
            'resultados_busqueda': resultados_busqueda,
            'todos_los_pasajeros': todos_los_pasajeros,
            'pasajero': pasajero,
            'productos_formulario': productos_formulario,
            'consumos_existentes': consumos_existentes,
            'total_consumos_evento': total_consumos_evento,
            'total_cuenta_pasajero': total_cuenta_pasajero,
        }
    )

@login_required

def cobros(request):
    """
    Consulta bajo demanda las cuentas pendientes y registra abonos.
    Permite buscar por cliente o grupo, pagar en COP, USD o Bs (con redondeo
    de USD al entero superior si tiene decimales, y exacto en Bs y COP),
    pagar la cuenta total, abonos parciales o dividir la cuenta entre varios del grupo.
    """
    viajes = Viaje.objects.filter(
        estado="ACTIVO"
    ).order_by("-fecha_inicio")

    viaje = viajes.first()

    busqueda = request.GET.get("q", "").strip()
    grupo_id_filtro = request.GET.get("grupo_id", "").strip()
    consultar_todas = request.GET.get("todas") == "1"

    if not viaje:
        messages.info(
            request,
            "No hay viajes activos para consultar Cobros."
        )
        return render(
            request,
            "consumos/cobros.html",
            {
                "viaje": None,
                "cuentas": [],
                "grupos_con_deuda": [],
                "grupos": [],
                "busqueda": busqueda,
                "grupo_id_filtro": grupo_id_filtro,
                "consultar_todas": False,
                "mostrar_resultados": False,
            },
        )

    if request.method == "POST" and request.POST.get("accion") == "registrar_pago":
        token = request.POST.get("idempotency_token", "").strip()
        if token:
            cache_key = f"idemp_pay_{token}"
            if cache.get(cache_key):
                messages.warning(
                    request,
                    "Este cobro ya está siendo procesado o fue enviado previamente. Se ha prevenido el cobro duplicado."
                )
                return redirect(reverse("cobros"))
            cache.set(cache_key, True, timeout=120)

        try:
            cargo_ids = request.POST.getlist("cargos")
            if not cargo_ids:
                cargos_csv = request.POST.get("cargos_csv", "").strip()
                if cargos_csv:
                    cargo_ids = [cid.strip() for cid in cargos_csv.split(",") if cid.strip()]

            monto_str = request.POST.get("monto", "").strip().replace(",", ".")
            moneda = request.POST.get("moneda", "COP")
            metodo_pago = request.POST.get("metodo_pago", "").strip()
            observacion = request.POST.get("observacion", "").strip()

            metodos_nombres = {
                "EFECTIVO": "Efectivo",
                "PAGO_MOVIL": "Pago móvil",
                "TRANSFERENCIA": "Transferencia bancaria",
                "PUNTO_VENTA": "Punto de venta",
                "BANCOLOMBIA": "Bancolombia",
                "NEQUI": "Nequi",
                "ZELLE": "Zelle",
                "BINANCE": "Binance",
            }
            nombre_metodo = metodos_nombres.get(metodo_pago, metodo_pago)
            if nombre_metodo and f"[{nombre_metodo}]" not in observacion:
                observacion = f"[{nombre_metodo}] {observacion}".strip() if observacion else f"[{nombre_metodo}]"

            pago = registrar_pago(
                viaje_id=viaje.pk,
                monto_original=monto_str,
                moneda=moneda,
                cargo_ids=cargo_ids,
                usuario=request.user,
                grupo_id=request.POST.get("grupo_id") or None,
                referencia=request.POST.get("referencia", "").strip(),
                observacion=observacion,
            )

            messages.success(
                request,
                f"Pago #{pago.pk} de {pago.monto_original} {pago.moneda} registrado correctamente."
            )

            # Conservar filtros de búsqueda si los había
            params = []
            if busqueda:
                params.append(f"q={busqueda}")
            if grupo_id_filtro:
                params.append(f"grupo_id={grupo_id_filtro}")
            sufijo = ("?" + "&".join(params)) if params else ""

            return redirect(reverse("cobros") + sufijo)

        except (ValidationError, ValueError, IntegrityError) as error:
            detalle = (
                " ".join(error.messages)
                if hasattr(error, "messages")
                else str(error)
            )
            messages.error(request, detalle)
            busqueda = request.POST.get("busqueda", "").strip()
            grupo_id_filtro = request.POST.get("grupo_id_filtro", "").strip()
            consultar_todas = request.POST.get("consultar_todas") == "1"

    mostrar_resultados = True  # Siempre mostrar las cuentas pendientes para consultar de inmediato

    cuentas_por_pasajero = {}

    if mostrar_resultados:
        cargos = (
            Cargo.objects.filter(pasajero__viaje=viaje)
            .select_related(
                "pasajero",
                "pasajero__grupo",
                "evento",
                "producto",
            )
            .annotate(
                abonado=Sum("aplicaciones_pago__monto_cop")
            )
            .order_by(
                "pasajero__grupo__nombre",
                "pasajero__nombre",
                "creado_en",
                "id",
            )
        )

        if grupo_id_filtro:
            cargos = cargos.filter(pasajero__grupo_id=grupo_id_filtro)

        if busqueda:
            cargos = cargos.filter(
                Q(pasajero__nombre__icontains=busqueda)
                | Q(pasajero__grupo__nombre__icontains=busqueda)
                | Q(pasajero__cedula__icontains=busqueda)
            )

        for cargo in cargos:
            abonado = cargo.abonado or Decimal("0.00")
            saldo = cargo.total - abonado

            pasajero = cargo.pasajero
            pasajero_id = pasajero.pk

            if pasajero_id not in cuentas_por_pasajero:
                cuentas_por_pasajero[pasajero_id] = {
                    "pasajero": pasajero,
                    "grupo": pasajero.grupo,
                    "cargos": [],
                    "cargos_pendientes": [],
                    "cargos_pagados": [],
                    "total_cargos": Decimal("0.00"),
                    "total_abonado": Decimal("0.00"),
                    "saldo": Decimal("0.00"),
                    "total_historico_pagado": Decimal("0.00"),
                    "asistio_juanes": False,
                }

            cuenta = cuentas_por_pasajero[pasajero_id]

            # Equivalencias del valor total del producto (su precio real completo)
            total_usd = (cargo.total / viaje.tasa_usd_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if viaje.tasa_usd_cop > 0 else Decimal("0.00")
            total_bs = (total_usd * viaje.tasa_usd_bs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if viaje.tasa_usd_bs > 0 else Decimal("0.00")

            # Equivalencias del saldo pendiente (la diferencia restante por pagar)
            cargo_usd = (saldo / viaje.tasa_usd_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if viaje.tasa_usd_cop > 0 else Decimal("0.00")
            cargo_bs = (cargo_usd * viaje.tasa_usd_bs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if viaje.tasa_usd_bs > 0 else Decimal("0.00")

            esta_pagado = saldo <= Decimal("0.00")

            item_cargo = {
                "cargo": cargo,
                "total": cargo.total,
                "total_usd": total_usd,
                "total_bs": total_bs,
                "abonado": abonado,
                "saldo": saldo,
                "saldo_usd": cargo_usd,
                "saldo_bs": cargo_bs,
                "esta_pagado": esta_pagado,
                "es_juanes": (
                    cargo.concepto.strip().casefold() == "los juanes"
                ),
            }

            if esta_pagado:
                cuenta["cargos_pagados"].append(item_cargo)
                cuenta["total_historico_pagado"] += cargo.total
            else:
                cuenta["cargos_pendientes"].append(item_cargo)
                cuenta["cargos"].append(item_cargo)
                cuenta["total_cargos"] += cargo.total
                cuenta["total_abonado"] += abonado
                cuenta["saldo"] += saldo

        # En cobros SOLO deben figurar pasajeros que tienen saldo pendiente > 0
        cuentas_por_pasajero = {
            pid: c for pid, c in cuentas_por_pasajero.items()
            if c["saldo"] > Decimal("0.00")
        }

        pasajero_ids = list(cuentas_por_pasajero.keys())

        asistencias = AsistenciaActividad.objects.filter(
            pasajero_id__in=pasajero_ids,
            evento__viaje=viaje,
            actividad__nombre__iexact="Los Juanes",
        ).values_list("pasajero_id", flat=True)

        asistieron = set(asistencias)

        for pasajero_id, cuenta in cuentas_por_pasajero.items():
            cuenta["asistio_juanes"] = pasajero_id in asistieron
            cuenta["tiene_abono_parcial"] = cuenta["total_abonado"] > Decimal("0.00")

            # Equivalencias en USD y Bs para cada pasajero de la diferencia a pagar
            saldo_cop = cuenta["saldo"]
            usd_exacto = (saldo_cop / viaje.tasa_usd_cop) if viaje.tasa_usd_cop > 0 else Decimal("0.00")
            cuenta["saldo_usd_exacto"] = usd_exacto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            # Redondeo de USD: si la cuenta da ej. 18.90 redondear a 19
            cuenta["saldo_usd_redondeado"] = Decimal(str(math.ceil(float(usd_exacto)))) if usd_exacto > 0 else Decimal("0")
            bs_exacto = (usd_exacto * viaje.tasa_usd_bs) if viaje.tasa_usd_bs > 0 else Decimal("0.00")
            cuenta["saldo_bs"] = bs_exacto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            # Solo los cargos con saldo pendiente se envían para cobrar
            cuenta["cargos_ids_json"] = ",".join(str(item["cargo"].id) for item in cuenta["cargos"] if not item["esta_pagado"])

    cuentas = sorted(
        cuentas_por_pasajero.values(),
        key=lambda cuenta: (
            cuenta["grupo"].nombre.lower(),
            cuenta["pasajero"].nombre.lower(),
        ),
    )

    # Agrupación por Grupo familiar
    grupos_dict = {}
    for cuenta in cuentas:
        gid = cuenta["grupo"].id
        if gid not in grupos_dict:
            grupos_dict[gid] = {
                "grupo": cuenta["grupo"],
                "cuentas": [],
                "cargos_ids": [],
                "total_cargos": Decimal("0.00"),
                "total_abonado": Decimal("0.00"),
                "saldo": Decimal("0.00"),
                "integrantes_count": 0,
            }
        grupos_dict[gid]["cuentas"].append(cuenta)
        grupos_dict[gid]["cargos_ids"].extend([item["cargo"].id for item in cuenta["cargos"] if not item["esta_pagado"]])
        grupos_dict[gid]["total_cargos"] += cuenta["total_cargos"]
        grupos_dict[gid]["total_abonado"] += cuenta["total_abonado"]
        grupos_dict[gid]["saldo"] += cuenta["saldo"]
        grupos_dict[gid]["integrantes_count"] += 1

    grupos_con_deuda = [
        g for g in grupos_dict.values()
        if g["saldo"] > Decimal("0.00") and len(g["cuentas"]) > 0
    ]

    for g in grupos_con_deuda:
        g["tiene_abono_parcial"] = g["total_abonado"] > Decimal("0.00")
        saldo_cop = g["saldo"]
        usd_exacto = (saldo_cop / viaje.tasa_usd_cop) if viaje.tasa_usd_cop > 0 else Decimal("0.00")
        g["saldo_usd_exacto"] = usd_exacto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        g["saldo_usd_redondeado"] = Decimal(str(math.ceil(float(usd_exacto)))) if usd_exacto > 0 else Decimal("0")
        bs_exacto = (usd_exacto * viaje.tasa_usd_bs) if viaje.tasa_usd_bs > 0 else Decimal("0.00")
        g["saldo_bs"] = bs_exacto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        g["cargos_ids_json"] = ",".join(str(cid) for cid in g["cargos_ids"])

    grupos_con_deuda.sort(key=lambda g: g["grupo"].nombre.lower())

    # Totales globales de las cuentas mostradas
    total_general_cop = sum((c["saldo"] for c in cuentas), Decimal("0.00"))
    total_general_usd_exacto = (total_general_cop / viaje.tasa_usd_cop) if viaje.tasa_usd_cop > 0 else Decimal("0.00")
    total_general_usd = Decimal(str(math.ceil(float(total_general_usd_exacto)))) if total_general_usd_exacto > 0 else Decimal("0")
    total_general_bs = (total_general_usd_exacto * viaje.tasa_usd_bs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if viaje.tasa_usd_bs > 0 else Decimal("0.00")

    # Total general de cargos pendientes del viaje completo (para estadísticas de cabecera)
    resumen_cargos_viaje = (
        Cargo.objects.filter(pasajero__viaje=viaje)
        .annotate(abonado=Sum("aplicaciones_pago__monto_cop"))
    )
    total_cuentas_con_deuda_viaje = sum(
        1 for c in resumen_cargos_viaje if (c.total - (c.abonado or Decimal("0.00"))) > 0
    )

    dias_totales_viaje = 4
    if viaje and viaje.fecha_inicio and viaje.fecha_fin:
        eventos_dias = viaje.eventos.filter(nombre__istartswith="Día").count()
        dias_totales_viaje = eventos_dias if eventos_dias in (3, 4) else (viaje.fecha_fin - viaje.fecha_inicio).days

    return render(
        request,
        "consumos/cobros.html",
        {
            "viaje": viaje,
            "dias_totales_viaje": dias_totales_viaje,
            "cuentas": cuentas,
            "grupos_con_deuda": grupos_con_deuda,
            "grupos": viaje.grupos.order_by("nombre"),
            "busqueda": busqueda,
            "grupo_id_filtro": grupo_id_filtro,
            "consultar_todas": consultar_todas,
            "mostrar_resultados": mostrar_resultados,
            "total_general_cop": total_general_cop,
            "total_general_usd": total_general_usd,
            "total_general_usd_exacto": total_general_usd_exacto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "total_general_bs": total_general_bs,
            "total_cuentas_con_deuda_viaje": total_cuentas_con_deuda_viaje,
        },
    )
