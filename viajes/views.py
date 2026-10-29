from consumos.models import AplicacionPago
from django.http import JsonResponse
from core.services_precios import sincronizar_precios_viaje
from core.services_bcv import obtener_tasa_bcv

from django.contrib.auth.decorators import login_required

from core.permisos import acceso_restringido, admin_requerido

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from core.models import Actividad

from .models import (
    Viaje,
    Grupo,
    Pasajero,
    Evento,
    PrecioActividad,
    AsistenciaActividad,
    Cargo,
    ControlComida,
)

from .importadores.listin import leer_listin, extraer_grupos


# ============================================================
# CONTROL DE ACCESO: CREAR VIAJE
# ============================================================

def no_hay_viaje_activo(request, *args, **kwargs):
    """
    Permite crear un viaje únicamente cuando no existe
    ningún viaje activo, independientemente del destino.
    """
    return not Viaje.objects.filter(estado="ACTIVO").exists()


# ============================================================
# API: PREVISUALIZAR Y VALIDAR LISTÍN ANTES DE CREAR VIAJE
# ============================================================

@login_required
@admin_requerido
def api_analizar_listin(request):
    """
    Analiza en memoria los archivos Excel de los buses cargados por el usuario,
    extrayendo grupos y pasajeros para mostrar una vista previa interactiva
    y validar que no existan duplicados ni errores de formato.
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)

    cantidad_buses_str = request.POST.get("cantidad_buses", "1")
    try:
        cantidad_buses = int(cantidad_buses_str)
        if cantidad_buses < 1 or cantidad_buses > 3:
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "La cantidad de buses debe ser entre 1 y 3."})

    buses_data = []
    total_pasajeros = 0
    total_grupos = 0

    for num_bus in range(1, cantidad_buses + 1):
        archivo = request.FILES.get(f"archivo_bus_{num_bus}")
        if not archivo:
            return JsonResponse({
                "ok": False,
                "error": f"Falta adjuntar el archivo Excel para el Bus {num_bus}."
            })

        if not archivo.name.lower().endswith(".xlsx"):
            return JsonResponse({
                "ok": False,
                "error": f"El archivo del Bus {num_bus} ({archivo.name}) debe ser de formato Excel (.xlsx)."
            })

        try:
            filas = leer_listin(archivo)
            grupos_bus = extraer_grupos(filas)
            if not grupos_bus:
                return JsonResponse({
                    "ok": False,
                    "error": f"No se encontraron grupos en el archivo del Bus {num_bus}. Verifica que contenga una hoja llamada 'LISTIN'."
                })

            pasajeros_bus = sum(len(g.get("pasajeros", [])) for g in grupos_bus)
            total_pasajeros += pasajeros_bus
            total_grupos += len(grupos_bus)

            buses_data.append({
                "bus": num_bus,
                "label": f"Bus {num_bus}",
                "nombre_archivo": archivo.name,
                "total_pasajeros": pasajeros_bus,
                "total_grupos": len(grupos_bus),
                "grupos": [
                    {
                        "nombre": g["nombre"],
                        "total_pasajeros": len(g["pasajeros"]),
                        "pasajeros": [
                            {
                                "nombre": p["nombre"],
                                "cedula": normalizar_cedula(p.get("cedula", ""))
                            }
                            for p in g["pasajeros"]
                        ]
                    }
                    for g in grupos_bus
                ]
            })
        except Exception as err:
            return JsonResponse({
                "ok": False,
                "error": f"Error al leer el archivo del Bus {num_bus}: {str(err)}"
            })

    # Verificar duplicados entre archivos de diferentes buses
    if len(buses_data) > 1:
        vistos = set()
        duplicados = []
        for b in buses_data:
            for g in b["grupos"]:
                for p in g["pasajeros"]:
                    ced = p["cedula"].strip().upper()
                    nom = p["nombre"].strip().upper()
                    clave = ced if ced else nom
                    if clave in vistos:
                        duplicados.append(p["nombre"])
                    else:
                        vistos.add(clave)
        if duplicados:
            return JsonResponse({
                "ok": False,
                "error": f"Se detectaron pasajeros duplicados entre los archivos de los buses: {', '.join(duplicados[:3])}."
            })

    # Verificar duración si se proporcionaron fechas
    duracion_info = None
    fecha_ini_str = request.POST.get("fecha_inicio", "").strip()
    fecha_fin_str = request.POST.get("fecha_fin", "").strip()
    if fecha_ini_str and fecha_fin_str:
        try:
            d_ini = date.fromisoformat(fecha_ini_str)
            d_fin = date.fromisoformat(fecha_fin_str)
            dias_calc = (d_fin - d_ini).days
            duracion_info = {
                "dias": dias_calc,
                "valida": dias_calc in (3, 4),
            }
        except Exception:
            pass

    return JsonResponse({
        "ok": True,
        "total_pasajeros": total_pasajeros,
        "total_grupos": total_grupos,
        "cantidad_buses": cantidad_buses,
        "buses": buses_data,
        "duracion": duracion_info,
    })


# ============================================================
# CREAR VIAJE (OBLIGATORIAMENTE CON LISTÍN)
# ============================================================

@login_required
@admin_requerido
@acceso_restringido(
    no_hay_viaje_activo,
    "Ya existe un viaje activo. Debes finalizarlo antes de crear otro.",
)
def crear_viaje(request):
    """
    Crea un viaje de forma atómica y completa.
    Es OBLIGATORIO importar el listín de pasajeros (Excel) para cada bus.
    El viaje NO se crea si falta el listín o si hay errores en el archivo.
    """
    viajes_activos = Viaje.objects.filter(
        estado="ACTIVO"
    ).order_by("-fecha_inicio")

    DESTINOS_MAP = {
        "mochima": "Mochima edo Sucre",
        "mochima edo sucre": "Mochima edo Sucre",
        "chichiriviche": "Chichiriviche edo falcon",
        "chichiriviche edo falcon": "Chichiriviche edo falcon",
        "margarita": "Margarita edo nueva esparta",
        "margarita edo nueva esparta": "Margarita edo nueva esparta",
    }
    DESTINOS_PERMITIDOS = (
        "Mochima edo Sucre",
        "Chichiriviche edo falcon",
        "Margarita edo nueva esparta",
    )

    datos = {
        "nombre": "",
        "destino": "Chichiriviche edo falcon",
        "fecha_inicio": "",
        "fecha_fin": "",
        "tasa_usd_bs": str(obtener_tasa_bcv(forzar=False).get("tasa", "887.30")),
        "tasa_usd_cop": "3200",
        "precio_juanes": "5.00",
        "cantidad_buses": "1",
    }

    if request.method == "POST":
        destino_raw = request.POST.get("destino", "Chichiriviche edo falcon").strip()
        destino_val = DESTINOS_MAP.get(destino_raw.lower(), destino_raw)

        datos = {
            "nombre": request.POST.get("nombre", "").strip(),
            "destino": destino_val,
            "fecha_inicio": request.POST.get("fecha_inicio", "").strip(),
            "fecha_fin": request.POST.get("fecha_fin", "").strip(),
            "tasa_usd_bs": request.POST.get("tasa_usd_bs", "").strip(),
            "tasa_usd_cop": request.POST.get("tasa_usd_cop", "").strip(),
            "precio_juanes": request.POST.get("precio_juanes", "5.00").strip() or "5.00",
            "cantidad_buses": request.POST.get("cantidad_buses", "1").strip() or "1",
        }

        try:
            # 1. Validaciones de datos básicos
            if not datos["nombre"]:
                raise ValueError("Debes ingresar el nombre del viaje.")

            if datos["destino"] not in DESTINOS_PERMITIDOS:
                raise ValueError("Selecciona un destino válido: Mochima edo Sucre, Chichiriviche edo falcon o Margarita edo nueva esparta.")

            if not datos["fecha_inicio"] or not datos["fecha_fin"]:
                raise ValueError("Debes ingresar la fecha de inicio y de finalización.")

            fecha_inicio = date.fromisoformat(datos["fecha_inicio"])
            fecha_fin = date.fromisoformat(datos["fecha_fin"])

            if fecha_fin < fecha_inicio:
                raise ValueError("La fecha de finalización no puede ser anterior a la fecha de inicio.")

            # El día de salida no cuenta como día operativo
            dias = (fecha_fin - fecha_inicio).days
            if dias not in (3, 4):
                raise ValueError(
                    f"El viaje debe tener una duración operativa de 3 o 4 días (días calculados: {dias}). "
                    "El día de salida no se cuenta como día operativo."
                )

            try:
                tasa_usd_bs = Decimal(datos["tasa_usd_bs"].replace(",", "."))
                tasa_usd_cop = Decimal(datos["tasa_usd_cop"].replace(",", "."))
            except (InvalidOperation, ValueError):
                raise ValueError("Las tasas de cambio deben ser números válidos.")

            if (
                not tasa_usd_bs.is_finite()
                or not tasa_usd_cop.is_finite()
                or tasa_usd_bs <= 0
                or tasa_usd_cop <= 0
            ):
                raise ValueError("Las tasas de cambio deben ser mayores que cero.")

            try:
                precio_juanes = Decimal(datos["precio_juanes"].replace(",", "."))
                if not precio_juanes.is_finite() or precio_juanes < 0:
                    raise InvalidOperation
                precio_juanes = precio_juanes.quantize(Decimal("0.01"))
            except (InvalidOperation, ValueError):
                raise ValueError("El precio de Los Juanes debe ser un número igual o mayor a cero.")

            try:
                cantidad_buses = int(datos["cantidad_buses"])
                if cantidad_buses < 1 or cantidad_buses > 3:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("La cantidad de buses debe ser entre 1 y 3.")

            # 2. VALIDACIÓN OBLIGATORIA DEL LISTÍN (NO SE CREA VIAJE SIN LISTÍN)
            buses_a_importar = []
            for num_bus in range(1, cantidad_buses + 1):
                archivo = request.FILES.get(f"archivo_bus_{num_bus}")
                if not archivo:
                    raise ValueError(
                        f"Es OBLIGATORIO subir el archivo del listín para el Bus {num_bus}. "
                        "El viaje no se puede terminar de crear sin importar su listín de pasajeros."
                    )

                if not archivo.name.lower().endswith(".xlsx"):
                    raise ValueError(
                        f"El archivo del Bus {num_bus} ({archivo.name}) debe ser de formato Excel (.xlsx)."
                    )

                try:
                    filas = leer_listin(archivo)
                    grupos_bus = extraer_grupos(filas)
                    if not grupos_bus:
                        raise ValueError(
                            f"No se encontraron grupos en el archivo del Bus {num_bus}. "
                            "Verifica que contenga una hoja llamada 'LISTIN'."
                        )
                    buses_a_importar.append({
                        "bus": num_bus,
                        "grupos": grupos_bus,
                    })
                except ValueError:
                    raise
                except Exception as err:
                    raise ValueError(f"Error al procesar el archivo del Bus {num_bus}: {err}")

            # Control de duplicados entre buses
            if len(buses_a_importar) > 1:
                vistos = set()
                duplicados_entre_archivos = []
                for b_info in buses_a_importar:
                    for grp in b_info["grupos"]:
                        for pas in grp["pasajeros"]:
                            ced = normalizar_cedula(pas.get("cedula", "")).strip().upper()
                            nom = pas.get("nombre", "").strip().upper()
                            clave = ced if ced else nom
                            if clave in vistos:
                                duplicados_entre_archivos.append(pas["nombre"])
                            else:
                                vistos.add(clave)
                if duplicados_entre_archivos:
                    raise ValueError(
                        f"Se detectaron pasajeros duplicados entre los archivos de los buses: "
                        f"{', '.join(duplicados_entre_archivos[:3])}. "
                        "Verifica que no hayas seleccionado el mismo archivo para más de un bus."
                    )

            # 3. CREACIÓN ATÓMICA: VIAJE + PRECIOS + EVENTOS + ACTIVIDAD + GRUPOS + PASAJEROS
            with transaction.atomic():
                viaje_creado = Viaje.objects.create(
                    nombre=datos["nombre"],
                    destino=datos["destino"],
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    tasa_usd_bs=tasa_usd_bs,
                    tasa_usd_cop=tasa_usd_cop,
                    estado="ACTIVO",
                )

                sincronizar_precios_viaje(viaje_creado)
                actividad = crear_eventos_automaticos(viaje_creado)

                PrecioActividad.objects.update_or_create(
                    viaje=viaje_creado,
                    actividad=actividad,
                    defaults={"precio_por_persona": precio_juanes},
                )

                total_pasajeros_creados = 0
                total_grupos_creados = 0

                for bus_info in buses_a_importar:
                    num_bus = bus_info["bus"]
                    for grupo_data in bus_info["grupos"]:
                        grupo = Grupo.objects.create(
                            viaje=viaje_creado,
                            nombre=grupo_data["nombre"],
                            bus=num_bus,
                        )
                        total_grupos_creados += 1

                        for pasajero_data in grupo_data["pasajeros"]:
                            Pasajero.objects.create(
                                viaje=viaje_creado,
                                grupo=grupo,
                                nombre=pasajero_data["nombre"],
                                cedula=normalizar_cedula(
                                    pasajero_data.get("cedula", "")
                                ),
                            )
                            total_pasajeros_creados += 1

            messages.success(
                request,
                f"¡Viaje «{viaje_creado.nombre}» creado con éxito! "
                f"Se importaron {total_pasajeros_creados} pasajeros en {total_grupos_creados} grupos familiares."
            )

            viajes_activos = Viaje.objects.filter(
                estado="ACTIVO"
            ).order_by("-fecha_inicio")

            return render(
                request,
                "viajes/crear_viaje.html",
                {
                    "viajes_activos": viajes_activos,
                    "viaje_creado": viaje_creado,
                    "total_pasajeros": total_pasajeros_creados,
                    "total_grupos": total_grupos_creados,
                    "cantidad_buses": len(buses_a_importar),
                    "precio_juanes": precio_juanes,
                    "duracion_dias": dias,
                    "datos": datos,
                },
            )

        except ValueError as error:
            messages.error(request, str(error))

        except Exception as error:
            messages.error(
                request,
                f"No se pudo crear el viaje: {error}",
            )

    return render(
        request,
        "viajes/crear_viaje.html",
        {
            "viajes_activos": viajes_activos,
            "datos": datos,
        },
    )
# ============================================================
# CREACIÓN AUTOMÁTICA DE EVENTOS
# ============================================================

def crear_eventos_automaticos(viaje):
    """
    Crea los eventos diarios y la Noche de Chiva.
    Los Juanes se administra como Actividad.
    El día de salida no se cuenta como día operativo.
    """
    dias = (
        viaje.fecha_fin - viaje.fecha_inicio
    ).days

    if dias not in (3, 4):
        raise ValueError(
            "La duración del viaje debe ser de 3 o 4 días operativos."
        )

    for numero in range(1, dias + 1):
        # El Día 1 corresponde al día siguiente a la salida.
        fecha_evento = viaje.fecha_inicio + timedelta(
            days=numero
        )

        Evento.objects.update_or_create(
            viaje=viaje,
            nombre=f"Día {numero}",
            defaults={
                "orden": numero,
                "fecha": fecha_evento,
            },
        )

    Evento.objects.update_or_create(
        viaje=viaje,
        nombre="Noche de Chiva",
        defaults={
            "orden": dias + 1,
            "fecha": viaje.fecha_fin,
        },
    )

    actividad = Actividad.objects.filter(
        nombre__iexact="Los Juanes"
    ).first()

    if actividad is None:
        actividad = Actividad.objects.create(
            nombre="Los Juanes"
        )

    return actividad


# ============================================================
# NORMALIZAR CÉDULAS
# ============================================================

def normalizar_cedula(cedula):
    """
    Agrega el prefijo V- sin duplicarlo.
    """
    valor = str(cedula or "").strip().upper()

    if not valor:
        return ""

    valor = re.sub(r"^V\s*-\s*", "", valor)
    valor = re.sub(r"\s+", "", valor)

    return f"V-{valor}"


# ============================================================
# IMPORTAR LISTÍN
# ============================================================
@login_required
@admin_requerido
def importar_listin(request):
    """
    Analiza archivos Excel (uno por bus), conserva la vista previa
    en sesión y permite confirmar la importación de grupos y pasajeros.
    - Soporta de 1 a 3 buses (1 predeterminado).
    - Impide importar el mismo listín más de una vez en el mismo viaje.
    """

    viajes = Viaje.objects.filter(
        estado="ACTIVO"
    ).order_by("-fecha_inicio")

    grupos_por_bus = None
    viaje_seleccionado = None
    total_pasajeros = 0
    total_grupos = 0
    precio_juanes = "5.00"
    cantidad_buses = 1  # Predeterminado: 1 bus

    viaje_id_url = request.GET.get("viaje")

    if viaje_id_url:
        viaje_seleccionado = Viaje.objects.filter(
            id=viaje_id_url,
            estado="ACTIVO",
        ).first()

    datos_sesion = request.session.get("buses_importar")
    viaje_guardado = request.session.get("viaje_importar")
    cantidad_buses_sesion = request.session.get(
        "cantidad_buses_importar"
    )

    if datos_sesion and viaje_guardado:
        viaje_de_sesion = Viaje.objects.filter(
            id=viaje_guardado,
            estado="ACTIVO",
        ).first()

        if viaje_de_sesion:
            viaje_seleccionado = viaje_de_sesion
            grupos_por_bus = datos_sesion

            if cantidad_buses_sesion:
                try:
                    cantidad_buses = int(cantidad_buses_sesion)
                except (ValueError, TypeError):
                    cantidad_buses = 1

            total_pasajeros = sum(
                len(grupo.get("pasajeros", []))
                for bus_data in grupos_por_bus
                for grupo in bus_data.get("grupos", [])
            )

            total_grupos = sum(
                len(bus_data.get("grupos", []))
                for bus_data in grupos_por_bus
            )

    pasajeros_existentes = 0
    buses_existentes = 0

    if viaje_seleccionado:
        pasajeros_existentes = Pasajero.objects.filter(
            viaje=viaje_seleccionado,
        ).count()

        buses_existentes = (
            Grupo.objects.filter(viaje=viaje_seleccionado)
            .exclude(bus__isnull=True)
            .exclude(bus=0)
            .values_list("bus", flat=True)
            .distinct()
            .count()
        )

    if request.method == "POST":
        accion = request.POST.get("accion")

        # --------------------------------------------------------
        # PASO 1: ANALIZAR ARCHIVOS EXCEL (1 a 3 buses)
        # --------------------------------------------------------

        if accion == "analizar":
            viaje_id = request.POST.get("viaje")
            duracion_dias = request.POST.get(
                "duracion_dias", "3"
            )
            cantidad_buses_str = request.POST.get(
                "cantidad_buses", "1"
            )

            try:
                cantidad_buses = int(cantidad_buses_str)
                if cantidad_buses < 1 or cantidad_buses > 3:
                    raise ValueError
            except (ValueError, TypeError):
                messages.error(
                    request,
                    "La cantidad de buses debe ser entre 1 y 3.",
                )
                return redirect(request.path)

            if duracion_dias not in ("3", "4"):
                messages.error(
                    request,
                    "Selecciona una duración válida.",
                )
                return redirect(request.path)

            if not viaje_id:
                messages.error(
                    request,
                    "Selecciona primero el viaje.",
                )
                return render(
                    request,
                    "viajes/importar_listin.html",
                    {
                        "viajes": viajes,
                        "grupos_por_bus": None,
                        "viaje_seleccionado": viaje_seleccionado,
                        "total_pasajeros": 0,
                        "total_grupos": 0,
                        "precio_juanes": precio_juanes,
                        "cantidad_buses": cantidad_buses,
                        "pasajeros_existentes": pasajeros_existentes,
                        "buses_existentes": buses_existentes,
                    },
                )

            viaje_seleccionado = get_object_or_404(
                Viaje,
                id=viaje_id,
                estado="ACTIVO",
            )

            # Comprobar la duración operativa.
            dias_registrados = (
                viaje_seleccionado.fecha_fin
                - viaje_seleccionado.fecha_inicio
            ).days

            if dias_registrados != int(duracion_dias):
                messages.error(
                    request,
                    f"Las fechas de este viaje corresponden "
                    f"a {dias_registrados} días operativos, pero "
                    f"seleccionaste {duracion_dias}. Corrige las "
                    "fechas del viaje o selecciona la duración correcta.",
                )

                return render(
                    request,
                    "viajes/importar_listin.html",
                    {
                        "viajes": viajes,
                        "grupos_por_bus": None,
                        "viaje_seleccionado": viaje_seleccionado,
                        "total_pasajeros": 0,
                        "total_grupos": 0,
                        "precio_juanes": precio_juanes,
                        "cantidad_buses": cantidad_buses,
                        "pasajeros_existentes": pasajeros_existentes,
                        "buses_existentes": buses_existentes,
                    },
                )

            # Leer y parsear cada archivo de bus
            nuevos_buses = []
            hay_error = False

            for num_bus in range(1, cantidad_buses + 1):
                archivo = request.FILES.get(
                    f"archivo_bus_{num_bus}"
                )

                if not archivo:
                    messages.error(
                        request,
                        f"Selecciona el archivo Excel del Bus {num_bus}.",
                    )
                    hay_error = True
                    break

                if not archivo.name.lower().endswith(".xlsx"):
                    messages.error(
                        request,
                        f"El archivo del Bus {num_bus} debe tener "
                        "formato .xlsx.",
                    )
                    hay_error = True
                    break

                try:
                    filas = leer_listin(archivo)
                    grupos_bus = extraer_grupos(filas)

                    if not grupos_bus:
                        messages.error(
                            request,
                            f"No se encontraron grupos en el "
                            f"archivo del Bus {num_bus}. Verifica "
                            "que exista una hoja llamada LISTIN.",
                        )
                        hay_error = True
                        break

                    nuevos_buses.append({
                        "bus": num_bus + buses_existentes,
                        "label": f"Bus {num_bus + buses_existentes}",
                        "grupos": grupos_bus,
                    })

                except Exception as error:
                    messages.error(
                        request,
                        f"Error al analizar el archivo del "
                        f"Bus {num_bus}: "
                        f"{type(error).__name__}: {error}",
                    )
                    hay_error = True
                    break

            if not hay_error and nuevos_buses:
                # ========================================================
                # CONTROL DE DUPLICADOS: NO PERMITIR IMPORTAR EL MISMO LISTÍN
                # ========================================================

                # 1. Obtener pasajeros ya registrados en este viaje en BD
                pasajeros_db = Pasajero.objects.filter(viaje=viaje_seleccionado)
                cedulas_db = {
                    p.cedula.strip().upper()
                    for p in pasajeros_db
                    if p.cedula and p.cedula.strip()
                }
                nombres_db = {
                    p.nombre.strip().upper()
                    for p in pasajeros_db
                    if p.nombre and p.nombre.strip()
                }

                # 2. Comprobar si los pasajeros ya existen en la base de datos
                duplicados_con_db = []
                for bus_info in nuevos_buses:
                    for grp in bus_info["grupos"]:
                        for pas in grp["pasajeros"]:
                            ced = normalizar_cedula(pas.get("cedula", "")).strip().upper()
                            nom = pas.get("nombre", "").strip().upper()

                            if ced and ced in cedulas_db:
                                duplicados_con_db.append(f"{pas['nombre']} ({ced})")
                            elif nom and nom in nombres_db:
                                duplicados_con_db.append(pas['nombre'])

                if duplicados_con_db:
                    ejemplos = ", ".join(duplicados_con_db[:3])
                    extra = f" y {len(duplicados_con_db) - 3} más" if len(duplicados_con_db) > 3 else ""
                    messages.error(
                        request,
                        f"Este listín ya fue importado anteriormente. "
                        f"Se detectaron {len(duplicados_con_db)} pasajero(s) que ya están "
                        f"registrados en este viaje ({ejemplos}{extra}). "
                        "No se permite importar el mismo listín dos veces.",
                    )
                    hay_error = True

                # 3. Comprobar si hay duplicados entre los archivos subidos (ej. mismo archivo en Bus 1 y Bus 2)
                if not hay_error and len(nuevos_buses) > 1:
                    vistos = set()
                    duplicados_entre_archivos = []

                    for bus_info in nuevos_buses:
                        for grp in bus_info["grupos"]:
                            for pas in grp["pasajeros"]:
                                ced = normalizar_cedula(pas.get("cedula", "")).strip().upper()
                                nom = pas.get("nombre", "").strip().upper()
                                clave = ced if ced else nom

                                if clave in vistos:
                                    duplicados_entre_archivos.append(pas['nombre'])
                                else:
                                    vistos.add(clave)

                    if duplicados_entre_archivos:
                        messages.error(
                            request,
                            f"Se detectaron pasajeros duplicados entre los archivos de los buses "
                            f"({', '.join(duplicados_entre_archivos[:3])}). "
                            "Verifica que no hayas seleccionado el mismo archivo para más de un bus.",
                        )
                        hay_error = True

            # Si pasó todas las validaciones sin error, guardar en sesión
            if not hay_error and nuevos_buses:
                grupos_por_bus = nuevos_buses

                total_pasajeros = sum(
                    len(grupo.get("pasajeros", []))
                    for bus_data in grupos_por_bus
                    for grupo in bus_data.get("grupos", [])
                )

                total_grupos = sum(
                    len(bus_data.get("grupos", []))
                    for bus_data in grupos_por_bus
                )

                request.session["buses_importar"] = grupos_por_bus
                request.session["viaje_importar"] = str(
                    viaje_seleccionado.id
                )
                request.session["duracion_importar"] = duracion_dias
                request.session["cantidad_buses_importar"] = str(
                    cantidad_buses
                )
                request.session.modified = True

                messages.success(
                    request,
                    f"Se analizó {cantidad_buses} archivo(s) "
                    "correctamente y no se encontraron duplicados. "
                    "Revisa los grupos antes de confirmar.",
                )

            pasajeros_existentes = Pasajero.objects.filter(
                viaje=viaje_seleccionado,
            ).count()
            buses_existentes = (
                Grupo.objects.filter(viaje=viaje_seleccionado)
                .exclude(bus__isnull=True)
                .exclude(bus=0)
                .values_list("bus", flat=True)
                .distinct()
                .count()
            )

        # --------------------------------------------------------
        # PASO 2: CONFIRMAR IMPORTACIÓN
        # --------------------------------------------------------

        elif accion == "importar":
            grupos_por_bus = request.session.get("buses_importar")
            viaje_id = request.session.get("viaje_importar")
            duracion_dias = request.session.get("duracion_importar")

            if not grupos_por_bus or not viaje_id:
                grupos_por_bus = None
                messages.error(
                    request,
                    "No hay una vista previa disponible. "
                    "Selecciona nuevamente los archivos y analízalos.",
                )
                return redirect(request.path)

            elif duracion_dias not in ("3", "4"):
                messages.error(
                    request,
                    "La duración del viaje no está guardada. "
                    "Vuelve a analizar los archivos.",
                )
                return redirect(request.path)

            else:
                viaje = get_object_or_404(
                    Viaje,
                    id=viaje_id,
                    estado="ACTIVO",
                )
                viaje_seleccionado = viaje

                dias_registrados = (
                    viaje.fecha_fin - viaje.fecha_inicio
                ).days

                if dias_registrados != int(duracion_dias):
                    messages.error(
                        request,
                        f"Las fechas del viaje corresponden a "
                        f"{dias_registrados} días operativos, pero la "
                        f"vista previa indica {duracion_dias}.",
                    )
                    return redirect(request.path)

                try:
                    precio_juanes = Decimal(
                        request.POST.get(
                            "precio_juanes", "5.00"
                        ).strip() or "5.00"
                    )
                    if not precio_juanes.is_finite() or precio_juanes < 0:
                        raise InvalidOperation
                    precio_juanes = precio_juanes.quantize(
                        Decimal("0.01")
                    )
                except (InvalidOperation, ValueError, TypeError):
                    messages.error(
                        request,
                        "El precio de Los Juanes debe ser un número igual o mayor que cero.",
                    )
                    return render(
                        request,
                        "viajes/importar_listin.html",
                        {
                            "viajes": viajes,
                            "grupos_por_bus": grupos_por_bus,
                            "viaje_seleccionado": viaje,
                            "total_pasajeros": sum(
                                len(grupo.get("pasajeros", []))
                                for bus_data in grupos_por_bus
                                for grupo in bus_data.get("grupos", [])
                            ),
                            "total_grupos": sum(
                                len(bus_data.get("grupos", []))
                                for bus_data in grupos_por_bus
                            ),
                            "precio_juanes": request.POST.get(
                                "precio_juanes", "5.00"
                            ),
                            "cantidad_buses": len(grupos_por_bus),
                            "pasajeros_existentes": Pasajero.objects.filter(viaje=viaje).count(),
                            "buses_existentes": 0,
                        },
                    )

                # Guardado atómico con verificación de no duplicados final
                try:
                    with transaction.atomic():
                        # Verificación final contra duplicados en BD
                        cedulas_actuales = set(
                            Pasajero.objects.filter(viaje=viaje)
                            .exclude(cedula="")
                            .values_list("cedula", flat=True)
                        )
                        nombres_actuales = {
                            p.strip().upper()
                            for p in Pasajero.objects.filter(viaje=viaje).values_list("nombre", flat=True)
                        }

                        for bus_data in grupos_por_bus:
                            for grp in bus_data["grupos"]:
                                for pas in grp["pasajeros"]:
                                    c_norm = normalizar_cedula(pas.get("cedula", "")).strip().upper()
                                    n_norm = pas.get("nombre", "").strip().upper()
                                    if (c_norm and c_norm in cedulas_actuales) or (n_norm and n_norm in nombres_actuales):
                                        raise ValueError(
                                            f"El pasajero «{pas['nombre']}» ya se encuentra registrado en el viaje. "
                                            "No se puede importar el mismo listín dos veces."
                                        )

                        actividad = crear_eventos_automaticos(viaje)

                        PrecioActividad.objects.update_or_create(
                            viaje=viaje,
                            actividad=actividad,
                            defaults={
                                "precio_por_persona": precio_juanes,
                            },
                        )

                        for bus_data in grupos_por_bus:
                            num_bus = bus_data.get("bus", 1)

                            for grupo_data in bus_data["grupos"]:
                                grupo = Grupo.objects.create(
                                    viaje=viaje,
                                    nombre=grupo_data["nombre"],
                                    bus=num_bus,
                                )

                                for pasajero_data in grupo_data["pasajeros"]:
                                    Pasajero.objects.create(
                                        viaje=viaje,
                                        grupo=grupo,
                                        nombre=pasajero_data["nombre"],
                                        cedula=normalizar_cedula(
                                            pasajero_data.get("cedula", "")
                                        ),
                                    )

                except ValueError as err:
                    messages.error(request, str(err))
                    return redirect(request.path)

                except Exception as error:
                    messages.error(
                        request,
                        f"No se completó la importación: {type(error).__name__}: {error}",
                    )
                    return redirect(request.path)

                request.session.pop("buses_importar", None)
                request.session.pop("viaje_importar", None)
                request.session.pop("duracion_importar", None)
                request.session.pop("cantidad_buses_importar", None)

                total_importados = sum(
                    len(grupo.get("pasajeros", []))
                    for bus_data in grupos_por_bus
                    for grupo in bus_data.get("grupos", [])
                )
                buses_importados = len(grupos_por_bus)

                messages.success(
                    request,
                    f"Listín importado correctamente. "
                    f"Se registraron {total_importados} pasajeros "
                    f"en {buses_importados} bus(es). "
                    f"Precio de Los Juanes: ${precio_juanes} por persona.",
                )

                return render(
                    request,
                    "viajes/importar_listin.html",
                    {
                        "viajes": viajes,
                        "grupos_por_bus": None,
                        "viaje_seleccionado": viaje,
                        "total_pasajeros": 0,
                        "total_grupos": 0,
                        "precio_juanes": str(precio_juanes),
                        "cantidad_buses": 1,
                        "importacion_exitosa": True,
                        "pasajeros_existentes": Pasajero.objects.filter(viaje=viaje).count(),
                        "buses_existentes": (
                            Grupo.objects.filter(viaje=viaje)
                            .exclude(bus__isnull=True)
                            .exclude(bus=0)
                            .values_list("bus", flat=True)
                            .distinct()
                            .count()
                        ),
                    },
                )

        else:
            messages.error(
                request,
                "Acción no reconocida. Vuelve a intentarlo.",
            )

    return render(
        request,
        "viajes/importar_listin.html",
        {
            "viajes": viajes,
            "grupos_por_bus": grupos_por_bus,
            "viaje_seleccionado": viaje_seleccionado,
            "total_pasajeros": total_pasajeros,
            "total_grupos": total_grupos,
            "precio_juanes": precio_juanes,
            "cantidad_buses": cantidad_buses,
            "pasajeros_existentes": pasajeros_existentes,
            "buses_existentes": buses_existentes,
        },
    )

# ============================================================
# LOS JUANES
# ============================================================

@login_required

def los_juanes(request):
    """
    Registra quién participa en Los Juanes y genera
    el cargo correspondiente al precio configurado para el viaje.
    """
    viajes = Viaje.objects.filter(
        estado="ACTIVO"
    ).order_by("-fecha_inicio")

    viaje_id = request.GET.get("viaje")
    if not viaje_id and viajes.exists():
        viaje_id = str(viajes.first().id)

    viaje = None
    evento = None
    actividad = None
    precio = None
    precio_cop = Decimal("0.00")
    pasajeros = []
    asistencia_ids = set()
    buses = []
    stats = {
        "total": 0,
        "asisten": 0,
        "no_asisten": 0,
        "porcentaje": 0,
        "total_usd": Decimal("0.00"),
        "total_cop": Decimal("0.00"),
    }

    if viaje_id:
        viaje = get_object_or_404(
            Viaje,
            id=viaje_id,
            estado="ACTIVO",
        )

        # Los Juanes se registra asociado al Día 2.
        evento = Evento.objects.filter(
            viaje=viaje,
            nombre="Día 2",
        ).first()

        precio_actividad = (
            viaje.precios_actividades
            .filter(
                actividad__nombre__iexact="Los Juanes"
            )
            .select_related("actividad")
            .first()
        )

        if not evento:
            messages.error(
                request,
                "Este viaje no tiene configurado el Día 2. "
                "Revisa sus eventos.",
            )

        elif not precio_actividad:
            messages.error(
                request,
                "No hay precio de Los Juanes configurado para este viaje.",
            )

        else:
            actividad = precio_actividad.actividad
            precio = precio_actividad.precio_por_persona
            precio_cop = (
                (precio * viaje.tasa_usd_cop).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if viaje.tasa_usd_cop > 0
                else Decimal("0.00")
            )

            pasajeros = list(
                viaje.pasajeros.select_related("grupo").order_by(
                    "grupo__bus",
                    "grupo__nombre",
                    "nombre",
                )
            )

            asistencias = AsistenciaActividad.objects.filter(
                evento=evento,
                actividad=actividad,
                pasajero__viaje=viaje,
            )

            asistencia_ids = set(
                asistencias.values_list(
                    "pasajero_id",
                    flat=True,
                )
            )

            # Lista de buses únicos
            buses = sorted(list(set(p.grupo.bus for p in pasajeros if p.grupo and p.grupo.bus)))

            # Estadísticas en vivo
            stats["total"] = len(pasajeros)
            stats["asisten"] = len(asistencia_ids)
            stats["no_asisten"] = max(0, stats["total"] - stats["asisten"])
            stats["porcentaje"] = round((stats["asisten"] / stats["total"] * 100), 1) if stats["total"] > 0 else 0
            stats["total_usd"] = (Decimal(stats["asisten"]) * precio).quantize(Decimal("0.01"))
            stats["total_cop"] = (stats["total_usd"] * viaje.tasa_usd_cop).quantize(Decimal("0.01"))

            if request.method == "POST":
                ids_validos = {
                    str(pasajero.id)
                    for pasajero in pasajeros
                }

                ids_recibidos = request.POST.getlist("pasajeros")

                seleccionados = {
                    int(pid)
                    for pid in ids_recibidos
                    if pid in ids_validos
                }

                with transaction.atomic():
                    # Eliminar asistencia y cargos de quienes
                    # fueron desmarcados.
                    AsistenciaActividad.objects.filter(
                        evento=evento,
                        actividad=actividad,
                        pasajero__viaje=viaje,
                    ).exclude(
                        pasajero_id__in=seleccionados
                    ).delete()

                    Cargo.objects.filter(
                        evento=evento,
                        pasajero__viaje=viaje,
                        concepto="Los Juanes",
                    ).exclude(
                        pasajero_id__in=seleccionados
                    ).delete()

                    # Guardar asistencia y actualizar el cargo en COP correspondiente a los USD.
                    for pasajero_id in seleccionados:
                        AsistenciaActividad.objects.update_or_create(
                            evento=evento,
                            actividad=actividad,
                            pasajero_id=pasajero_id,
                            defaults={
                                "precio": precio,
                            },
                        )

                        Cargo.objects.update_or_create(
                            pasajero_id=pasajero_id,
                            evento=evento,
                            concepto="Los Juanes",
                            defaults={
                                "cantidad": 1,
                                "precio_unitario": precio_cop,
                                "total": precio_cop,
                            },
                        )

                is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest" or request.POST.get("is_ajax") == "1"
                if is_ajax:
                    total_usd = (Decimal(len(seleccionados)) * precio).quantize(Decimal("0.01"))
                    total_cop = (total_usd * viaje.tasa_usd_cop).quantize(Decimal("0.01"))
                    return JsonResponse({
                        "status": "success",
                        "message": f"Asistencia actualizada: {len(seleccionados)} confirmados.",
                        "asistentes_count": len(seleccionados),
                        "pendientes_count": len(pasajeros) - len(seleccionados),
                        "porcentaje": round((len(seleccionados) / len(pasajeros)) * 100, 1) if pasajeros else 0,
                        "total_usd": str(total_usd),
                        "total_cop": str(total_cop),
                    })

                messages.success(
                    request,
                    "Asistencia guardada correctamente. "
                    f"{len(seleccionados)} personas confirmadas a Los Juanes (${precio} USD c/u).",
                )

                return redirect(
                    f"/los-juanes/?viaje={viaje.id}"
                )

    return render(
        request,
        "viajes/los_juanes.html",
        {
            "viajes": viajes,
            "viaje": viaje,
            "evento": evento,
            "actividad": actividad,
            "precio": precio,
            "precio_cop": precio_cop,
            "pasajeros": pasajeros,
            "asistencia_ids": asistencia_ids,
            "buses": buses,
            "stats": stats,
        },
    )


@login_required
@admin_requerido
def finalizar_viaje(request):
    """
    Cierra operativamente el ciclo del viaje activo.
    REGLA DE NEGOCIO ESTRICTA:
    NO se puede finalizar el viaje bajo ninguna circunstancia si existen
    deudas o saldos pendientes por cobrar en los consumos del listín.
    """
    viaje_activo = (
        Viaje.objects.filter(estado="ACTIVO")
        .order_by("-fecha_inicio")
        .first()
    )

    if not viaje_activo:
        messages.info(request, "No hay ningún viaje activo en este momento.")
        return redirect("home")

    tasa_cop = viaje_activo.tasa_usd_cop if viaje_activo.tasa_usd_cop > 0 else Decimal("3200")
    tasa_bs = viaje_activo.tasa_usd_bs if viaje_activo.tasa_usd_bs > 0 else Decimal("989.72")

    # Obtener todos los cargos del viaje con su total abonado
    cargos = (
        Cargo.objects.filter(pasajero__viaje=viaje_activo)
        .select_related("pasajero", "pasajero__grupo", "evento")
        .annotate(abonado=Sum("aplicaciones_pago__monto_cop"))
    )

    total_facturado_cop = cargos.aggregate(t=Sum("total"))["t"] or Decimal("0.00")
    total_recaudado_cop = AplicacionPago.objects.filter(
        cargo__pasajero__viaje=viaje_activo
    ).aggregate(t=Sum("monto_cop"))["t"] or Decimal("0.00")

    total_deuda_cop = max(Decimal("0.00"), total_facturado_cop - total_recaudado_cop)

    # Agrupar deudores
    deudores_dict = {}
    cargos_pendientes_count = 0

    for c in cargos:
        abono = c.abonado or Decimal("0.00")
        saldo = c.total - abono
        if saldo > Decimal("0.00"):
            cargos_pendientes_count += 1
            pid = c.pasajero_id
            if pid not in deudores_dict:
                deudores_dict[pid] = {
                    "pasajero": c.pasajero,
                    "grupo": c.pasajero.grupo,
                    "saldo": Decimal("0.00"),
                    "cargos_pendientes": 0,
                    "cargos_nombres": [],
                }
            deudores_dict[pid]["saldo"] += saldo
            deudores_dict[pid]["cargos_pendientes"] += 1
            if len(deudores_dict[pid]["cargos_nombres"]) < 3:
                deudores_dict[pid]["cargos_nombres"].append(c.concepto)

    deudores = sorted(deudores_dict.values(), key=lambda d: d["saldo"], reverse=True)
    for d in deudores:
        d["saldo_usd"] = (d["saldo"] / tasa_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        d["saldo_bs"] = (d["saldo_usd"] * tasa_bs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    puede_finalizar = (total_deuda_cop <= Decimal("0.00") and len(deudores) == 0)

    total_deuda_usd = (total_deuda_cop / tasa_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_deuda_bs = (total_deuda_usd * tasa_bs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    total_facturado_usd = (total_facturado_cop / tasa_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_recaudado_usd = (total_recaudado_cop / tasa_cop).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if request.method == "POST":
        if not puede_finalizar:
            messages.error(
                request,
                f"BLOQUEO DE CIERRE: No es posible finalizar el viaje '{viaje_activo.nombre}' "
                f"porque aún existen deudas pendientes por un total de COP {total_deuda_cop:,.2f} "
                f"en {len(deudores)} pasajero(s). Se debe liquidar cada cuenta en Cobros antes de cerrar el viaje."
            )
            return redirect("finalizar_viaje")

        with transaction.atomic():
            viaje_activo.estado = "FINALIZADO"
            viaje_activo.save(update_fields=["estado"])

        messages.success(
            request,
            f"¡El viaje '{viaje_activo.nombre}' ha sido finalizado con éxito! "
            "Todas las cuentas quedaron completamente solventes y el listín ha sido archivado."
        )
        return redirect("home")

    return render(
        request,
        "viajes/finalizar_viaje.html",
        {
            "viaje": viaje_activo,
            "puede_finalizar": puede_finalizar,
            "total_facturado_cop": total_facturado_cop,
            "total_facturado_usd": total_facturado_usd,
            "total_recaudado_cop": total_recaudado_cop,
            "total_recaudado_usd": total_recaudado_usd,
            "total_deuda_cop": total_deuda_cop,
            "total_deuda_usd": total_deuda_usd,
            "total_deuda_bs": total_deuda_bs,
            "deudores": deudores,
            "cargos_pendientes_count": cargos_pendientes_count,
            "total_pasajeros": Pasajero.objects.filter(viaje=viaje_activo).count(),
        },
    )


# ============================================================
# CONTROL Y REPARTICIÓN DE COMIDAS (DESAYUNO, ALMUERZO, CENA)
# ============================================================

@login_required
def control_comidas(request):
    """
    Control y seguimiento operativo secuencial de comidas (Desayuno, Almuerzo, Cena).
    Flujo diario estricto:
      Día 1 Desayuno -> Día 1 Almuerzo -> Día 1 Cena -> Día 2 Desayuno -> ...
    Una comida finalizada queda CERRADA y no se puede volver a repartir,
    habilitando de inmediato el siguiente servicio en la secuencia cronológica.
    """
    viajes = Viaje.objects.filter(estado="ACTIVO").order_by("-fecha_inicio")
    viaje_id = request.GET.get("viaje") or request.POST.get("viaje")
    if not viaje_id and viajes.exists():
        viaje_id = str(viajes.first().id)

    viaje = None
    eventos = []
    evento_sel = None
    bus_filtro = request.GET.get("bus") or request.POST.get("bus") or "todos"
    estado_filtro = request.GET.get("estado_filtro") or "todos"
    busqueda = request.GET.get("q", "").strip()

    if viaje_id:
        viaje = get_object_or_404(Viaje, id=viaje_id, estado="ACTIVO")
        eventos = list(viaje.eventos.filter(nombre__startswith="Día").order_by("orden"))
        if not eventos:
            eventos = list(viaje.eventos.all().order_by("orden"))

    # Generar la secuencia cronológica completa de todas las sesiones de comida del viaje
    # [(Día 1, DESAYUNO), (Día 1, ALMUERZO), (Día 1, CENA), (Día 2, DESAYUNO), ...]
    secuencia_turnos = []
    total_pasajeros_viaje = viaje.pasajeros.count() if viaje else 0

    tipos_info = [
        (ControlComida.TIPO_DESAYUNO, "Desayuno", "El", "finalizado", "desayunaron", "Mañana • 7:00 AM - 10:30 AM"),
        (ControlComida.TIPO_ALMUERZO, "Almuerzo", "El", "finalizado", "almorzaron", "Mediodía • 12:00 PM - 3:30 PM"),
        (ControlComida.TIPO_CENA, "Cena", "La", "finalizada", "cenaron", "Noche • 7:00 PM - 10:00 PM"),
    ]

    idx_sec = 0
    if viaje and eventos:
        for ev in eventos:
            for tc, nom, art, term, acc, hor in tipos_info:
                idx_sec += 1
                c_cnt = ControlComida.objects.filter(
                    viaje=viaje,
                    evento=ev,
                    tipo_comida=tc,
                    entregado=True
                ).count()
                fin = (c_cnt >= total_pasajeros_viaje and total_pasajeros_viaje > 0)
                secuencia_turnos.append({
                    "indice": idx_sec,
                    "evento_id": ev.id,
                    "evento_nombre": ev.nombre,
                    "evento_fecha": ev.fecha,
                    "tipo": tc,
                    "nombre": nom,
                    "articulo": art,
                    "terminado": term,
                    "accion": acc,
                    "horario": hor,
                    "comieron": c_cnt,
                    "total": total_pasajeros_viaje,
                    "pendientes": max(0, total_pasajeros_viaje - c_cnt),
                    "finalizado": fin,
                    "pct": round((c_cnt / total_pasajeros_viaje * 100), 1) if total_pasajeros_viaje else 0
                })

    # Turno actual operativo: la primera sesión de la secuencia que NO esté finalizada
    turno_actual = next((t for t in secuencia_turnos if not t["finalizado"]), secuencia_turnos[0] if secuencia_turnos else None)

    # Determinar qué sesión mostrar:
    # Si el usuario no especificó ?evento ni ?tipo, usamos automáticamente el turno_actual en curso
    param_evento = request.GET.get("evento") or request.POST.get("evento")
    param_tipo = request.GET.get("tipo") or request.POST.get("tipo")

    if not param_evento and not param_tipo and turno_actual:
        evento_sel = viaje.eventos.filter(id=turno_actual["evento_id"]).first()
        tipo_sel = turno_actual["tipo"]
    else:
        if param_evento:
            evento_sel = viaje.eventos.filter(id=param_evento).first() if viaje else None
        if not evento_sel and eventos:
            evento_sel = eventos[0]

        tipos_validos = [ControlComida.TIPO_DESAYUNO, ControlComida.TIPO_ALMUERZO, ControlComida.TIPO_CENA]
        if param_tipo and param_tipo.upper() in tipos_validos:
            tipo_sel = param_tipo.upper()
        elif turno_actual and evento_sel and turno_actual["evento_id"] == evento_sel.id:
            tipo_sel = turno_actual["tipo"]
        else:
            tipo_sel = ControlComida.TIPO_DESAYUNO

    # Metadatos del tipo de comida seleccionado
    def get_tipo_meta(t):
        if t == ControlComida.TIPO_CENA:
            return ("Cena", "La", "finalizada", "cenaron")
        elif t == ControlComida.TIPO_DESAYUNO:
            return ("Desayuno", "El", "finalizado", "desayunaron")
        else:
            return ("Almuerzo", "El", "finalizado", "almorzaron")

    tipo_nombre, tipo_articulo, tipo_terminado, tipo_accion = get_tipo_meta(tipo_sel)
    mensaje_finalizado = f"¡Todos los clientes ya comieron! {tipo_articulo} {tipo_nombre} del {evento_sel.nombre if evento_sel else ''} está {tipo_terminado}."

    # Identificar el slot actual dentro de secuencia_turnos
    slot_actual = next((t for t in secuencia_turnos if evento_sel and t["evento_id"] == evento_sel.id and t["tipo"] == tipo_sel), None)
    
    # ¿Este servicio ya está cerrado?
    servicio_cerrado = bool(slot_actual and slot_actual["finalizado"])

    # ¿Cuál es el siguiente servicio en la secuencia cronológica?
    siguiente_turno = None
    if slot_actual:
        cur_idx = slot_actual["indice"]
        siguiente_turno = next((t for t in secuencia_turnos if t["indice"] == cur_idx + 1), None)

    # Preguntar comida solo si expresamente se pasa ?elegir=1
    preguntar_comida = (request.method == "GET" and request.GET.get("elegir") == "1")

    stats = {
        "total": 0,
        "comieron": 0,
        "pendientes": 0,
        "porcentaje": 0,
    }
    buses_stats = []
    pasajeros_data = []
    comidas_resumen = {}

    if viaje and evento_sel:
        pasajeros_todos = list(
            viaje.pasajeros.select_related("grupo").order_by(
                "grupo__bus",
                "grupo__nombre",
                "nombre",
            )
        )

        # POST: Procesamiento de acciones
        if request.method == "POST":
            action = request.POST.get("action", "toggle")
            is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest" or request.POST.get("is_ajax") == "1"
            reabrir_admin = request.POST.get("reabrir_admin") == "1" and (request.user.is_superuser or hasattr(request.user, "perfil") and request.user.perfil.rol == "ADMIN")

            # REABRIR SERVICIO CERRADO (Solo Admin)
            if action == "reabrir_servicio" and reabrir_admin:
                servicio_cerrado = False
                if is_ajax:
                    return JsonResponse({
                        "status": "success",
                        "mensaje": f"Servicio de {tipo_nombre} reabierto para edición.",
                        "reabierto": True
                    })
                return redirect(f"/comidas/?viaje={viaje.id}&evento={evento_sel.id}&tipo={tipo_sel}")

            # REGLA ESTRICTA: No se puede repartir ni modificar un servicio ya cerrado
            if servicio_cerrado and not reabrir_admin:
                msg_err = f"El servicio de {tipo_nombre} del {evento_sel.nombre} ya fue finalizado y cerrado. No se puede volver a repartir."
                if is_ajax:
                    return JsonResponse({"status": "error", "mensaje": msg_err, "bloqueado": True}, status=400)
                messages.error(request, msg_err)
                return redirect(f"/comidas/?viaje={viaje.id}&evento={evento_sel.id}&tipo={tipo_sel}")

            if action == "toggle":
                pasajero_id = request.POST.get("pasajero_id")
                if pasajero_id:
                    reg = ControlComida.objects.filter(
                        viaje=viaje,
                        evento=evento_sel,
                        tipo_comida=tipo_sel,
                        pasajero_id=pasajero_id
                    ).first()

                    if reg:
                        # Si ya existía y el servicio no está cerrado, se puede desmarcar
                        reg.delete()
                        nuevo_estado = False
                        hora_str = ""
                    else:
                        nuevo_reg = ControlComida.objects.create(
                            viaje=viaje,
                            evento=evento_sel,
                            tipo_comida=tipo_sel,
                            pasajero_id=pasajero_id,
                            entregado=True,
                            entregado_por=request.user
                        )
                        nuevo_estado = True
                        hora_str = timezone.localtime(nuevo_reg.fecha_hora).strftime("%I:%M %p")

                    total_act = len(pasajeros_todos)
                    comieron_act = ControlComida.objects.filter(
                        viaje=viaje,
                        evento=evento_sel,
                        tipo_comida=tipo_sel,
                        entregado=True
                    ).count()
                    pendientes_act = max(0, total_act - comieron_act)
                    pct_act = round((comieron_act / total_act * 100), 1) if total_act else 0
                    finalizado_act = (comieron_act >= total_act and total_act > 0)

                    # Si acaba de finalizar, calcular el siguiente turno en la secuencia
                    sig_url = ""
                    sig_nombre = ""
                    sig_dia = ""
                    if finalizado_act and siguiente_turno:
                        sig_url = f"/comidas/?viaje={viaje.id}&evento={siguiente_turno['evento_id']}&tipo={siguiente_turno['tipo']}"
                        sig_nombre = siguiente_turno["nombre"]
                        sig_dia = siguiente_turno["evento_nombre"]

                    if is_ajax:
                        return JsonResponse({
                            "status": "success",
                            "nuevo_estado": nuevo_estado,
                            "hora_entrega": hora_str,
                            "total": total_act,
                            "comieron": comieron_act,
                            "pendientes": pendientes_act,
                            "porcentaje": pct_act,
                            "finalizado": finalizado_act,
                            "tipo_comida": tipo_sel,
                            "tipo_nombre": tipo_nombre,
                            "tipo_articulo": tipo_articulo,
                            "tipo_terminado": tipo_terminado,
                            "mensaje_finalizado": mensaje_finalizado,
                            "siguiente_url": sig_url,
                            "siguiente_nombre": sig_nombre,
                            "siguiente_dia": sig_dia,
                            "mensaje": "Estado de comida actualizado"
                        })

            elif action in ["marcar_grupo", "desmarcar_grupo"]:
                grupo_id = request.POST.get("grupo_id")
                marcar = (action == "marcar_grupo")
                p_grupo = [p.id for p in pasajeros_todos if str(p.grupo_id) == str(grupo_id)]
                with transaction.atomic():
                    if marcar:
                        for pid in p_grupo:
                            ControlComida.objects.update_or_create(
                                viaje=viaje,
                                evento=evento_sel,
                                tipo_comida=tipo_sel,
                                pasajero_id=pid,
                                defaults={
                                    "entregado": True,
                                    "entregado_por": request.user
                                }
                            )
                    else:
                        ControlComida.objects.filter(
                            viaje=viaje,
                            evento=evento_sel,
                            tipo_comida=tipo_sel,
                            pasajero_id__in=p_grupo
                        ).delete()

                if is_ajax:
                    comieron_act = ControlComida.objects.filter(viaje=viaje, evento=evento_sel, tipo_comida=tipo_sel, entregado=True).count()
                    total_act = len(pasajeros_todos)
                    pendientes_act = max(0, total_act - comieron_act)
                    pct_act = round((comieron_act / total_act * 100), 1) if total_act else 0
                    finalizado_act = (comieron_act >= total_act and total_act > 0)
                    sig_url = f"/comidas/?viaje={viaje.id}&evento={siguiente_turno['evento_id']}&tipo={siguiente_turno['tipo']}" if (finalizado_act and siguiente_turno) else ""

                    return JsonResponse({
                        "status": "success",
                        "total": total_act,
                        "comieron": comieron_act,
                        "pendientes": pendientes_act,
                        "porcentaje": pct_act,
                        "finalizado": finalizado_act,
                        "tipo_comida": tipo_sel,
                        "tipo_nombre": tipo_nombre,
                        "tipo_articulo": tipo_articulo,
                        "tipo_terminado": tipo_terminado,
                        "mensaje_finalizado": mensaje_finalizado,
                        "siguiente_url": sig_url,
                        "siguiente_nombre": siguiente_turno["nombre"] if (finalizado_act and siguiente_turno) else "",
                        "siguiente_dia": siguiente_turno["evento_nombre"] if (finalizado_act and siguiente_turno) else "",
                        "mensaje": "Grupo actualizado exitosamente"
                    })

            elif action in ["marcar_bus", "desmarcar_bus"]:
                bus_num = request.POST.get("bus_num")
                marcar = (action == "marcar_bus")
                p_bus = [p.id for p in pasajeros_todos if p.grupo and str(p.grupo.bus) == str(bus_num)]
                with transaction.atomic():
                    if marcar:
                        for pid in p_bus:
                            ControlComida.objects.update_or_create(
                                viaje=viaje,
                                evento=evento_sel,
                                tipo_comida=tipo_sel,
                                pasajero_id=pid,
                                defaults={
                                    "entregado": True,
                                    "entregado_por": request.user
                                }
                            )
                    else:
                        ControlComida.objects.filter(
                            viaje=viaje,
                            evento=evento_sel,
                            tipo_comida=tipo_sel,
                            pasajero_id__in=p_bus
                        ).delete()

                if is_ajax:
                    comieron_act = ControlComida.objects.filter(viaje=viaje, evento=evento_sel, tipo_comida=tipo_sel, entregado=True).count()
                    total_act = len(pasajeros_todos)
                    pendientes_act = max(0, total_act - comieron_act)
                    pct_act = round((comieron_act / total_act * 100), 1) if total_act else 0
                    finalizado_act = (comieron_act >= total_act and total_act > 0)
                    sig_url = f"/comidas/?viaje={viaje.id}&evento={siguiente_turno['evento_id']}&tipo={siguiente_turno['tipo']}" if (finalizado_act and siguiente_turno) else ""

                    return JsonResponse({
                        "status": "success",
                        "total": total_act,
                        "comieron": comieron_act,
                        "pendientes": pendientes_act,
                        "porcentaje": pct_act,
                        "finalizado": finalizado_act,
                        "tipo_comida": tipo_sel,
                        "tipo_nombre": tipo_nombre,
                        "mensaje_finalizado": mensaje_finalizado,
                        "siguiente_url": sig_url,
                        "siguiente_nombre": siguiente_turno["nombre"] if (finalizado_act and siguiente_turno) else "",
                        "siguiente_dia": siguiente_turno["evento_nombre"] if (finalizado_act and siguiente_turno) else "",
                        "mensaje": f"Bus {bus_num} actualizado exitosamente"
                    })

            elif action in ["marcar_todos", "desmarcar_todos"]:
                marcar = (action == "marcar_todos")
                with transaction.atomic():
                    if marcar:
                        for p in pasajeros_todos:
                            ControlComida.objects.update_or_create(
                                viaje=viaje,
                                evento=evento_sel,
                                tipo_comida=tipo_sel,
                                pasajero_id=p.id,
                                defaults={
                                    "entregado": True,
                                    "entregado_por": request.user
                                }
                            )
                    else:
                        ControlComida.objects.filter(
                            viaje=viaje,
                            evento=evento_sel,
                            tipo_comida=tipo_sel
                        ).delete()

                if is_ajax:
                    comieron_act = ControlComida.objects.filter(viaje=viaje, evento=evento_sel, tipo_comida=tipo_sel, entregado=True).count()
                    total_act = len(pasajeros_todos)
                    pendientes_act = max(0, total_act - comieron_act)
                    pct_act = round((comieron_act / total_act * 100), 1) if total_act else 0
                    finalizado_act = (comieron_act >= total_act and total_act > 0)
                    sig_url = f"/comidas/?viaje={viaje.id}&evento={siguiente_turno['evento_id']}&tipo={siguiente_turno['tipo']}" if (finalizado_act and siguiente_turno) else ""

                    return JsonResponse({
                        "status": "success",
                        "total": total_act,
                        "comieron": comieron_act,
                        "pendientes": pendientes_act,
                        "porcentaje": pct_act,
                        "finalizado": finalizado_act,
                        "tipo_comida": tipo_sel,
                        "tipo_nombre": tipo_nombre,
                        "tipo_articulo": tipo_articulo,
                        "tipo_terminado": tipo_terminado,
                        "mensaje_finalizado": mensaje_finalizado,
                        "siguiente_url": sig_url,
                        "siguiente_nombre": siguiente_turno["nombre"] if (finalizado_act and siguiente_turno) else "",
                        "siguiente_dia": siguiente_turno["evento_nombre"] if (finalizado_act and siguiente_turno) else "",
                        "mensaje": "Todos los pasajeros actualizados"
                    })

            return redirect(f"/comidas/?viaje={viaje.id}&evento={evento_sel.id}&tipo={tipo_sel}&bus={bus_filtro}")

        # Resumen de estado de las 3 comidas para el evento_sel actual (en el modal de selección)
        for s in secuencia_turnos:
            if s["evento_id"] == evento_sel.id:
                # Determinar si este slot es el turno_actual o es cerrado o es futuro
                es_turno_actual = (turno_actual and turno_actual["evento_id"] == s["evento_id"] and turno_actual["tipo"] == s["tipo"])
                s_copy = dict(s)
                s_copy["es_turno_actual"] = es_turno_actual
                comidas_resumen[s["tipo"]] = s_copy

        # Cargar registros de comida para la sesión seleccionada
        controles_comida = ControlComida.objects.filter(
            viaje=viaje,
            evento=evento_sel,
            tipo_comida=tipo_sel,
            entregado=True
        ).select_related("entregado_por")

        comidas_map = {c.pasajero_id: c for c in controles_comida}
        comieron_ids = set(comidas_map.keys())

        # Estadísticas globales de la sesión
        stats["total"] = len(pasajeros_todos)
        stats["comieron"] = len(comieron_ids)
        stats["pendientes"] = max(0, stats["total"] - stats["comieron"])
        stats["porcentaje"] = round((stats["comieron"] / stats["total"] * 100), 1) if stats["total"] > 0 else 0

        # Actualizar flag de servicio_cerrado con base en comieron actual
        servicio_cerrado = (stats["pendientes"] == 0 and stats["total"] > 0)

        # Estadísticas por bus
        buses_nums = sorted(list(set(p.grupo.bus for p in pasajeros_todos if p.grupo and p.grupo.bus)))
        for b in buses_nums:
            p_en_bus = [p for p in pasajeros_todos if p.grupo and p.grupo.bus == b]
            com_en_bus = [p for p in p_en_bus if p.id in comieron_ids]
            buses_stats.append({
                "bus": b,
                "total": len(p_en_bus),
                "comieron": len(com_en_bus),
                "pendientes": len(p_en_bus) - len(com_en_bus),
                "pct": round((len(com_en_bus) / len(p_en_bus) * 100), 1) if p_en_bus else 0
            })

        # Construir datos de pasajeros enriquecidos
        for p in pasajeros_todos:
            comio = p.id in comieron_ids
            reg = comidas_map.get(p.id)
            hora_formateada = timezone.localtime(reg.fecha_hora).strftime("%I:%M %p") if reg else ""
            usuario_entrega = reg.entregado_por.username if (reg and reg.entregado_por) else ""

            pasajeros_data.append({
                "id": p.id,
                "nombre": p.nombre,
                "cedula": p.cedula,
                "grupo": p.grupo.nombre if p.grupo else "Sin grupo",
                "grupo_id": p.grupo_id,
                "bus": p.grupo.bus if p.grupo else None,
                "comio": comio,
                "hora_entrega": hora_formateada,
                "entregado_por": usuario_entrega,
            })

    # Filtrar pasajeros para la vista
    pasajeros_filtrados = pasajeros_data

    if bus_filtro and bus_filtro != "todos":
        try:
            b_num = int(bus_filtro)
            pasajeros_filtrados = [p for p in pasajeros_filtrados if p["bus"] == b_num]
        except (ValueError, TypeError):
            pass

    if estado_filtro == "comieron":
        pasajeros_filtrados = [p for p in pasajeros_filtrados if p["comio"]]
    elif estado_filtro == "pendientes":
        pasajeros_filtrados = [p for p in pasajeros_filtrados if not p["comio"]]

    if busqueda:
        q_low = busqueda.lower()
        pasajeros_filtrados = [
            p for p in pasajeros_filtrados
            if (q_low in p["nombre"].lower() or
                q_low in (p["cedula"] or "").lower() or
                q_low in p["grupo"].lower())
        ]

    # Agrupar pasajeros por Grupo
    grupos_dict = {}
    for p in pasajeros_filtrados:
        g_name = p["grupo"]
        if g_name not in grupos_dict:
            grupos_dict[g_name] = {
                "nombre": g_name,
                "grupo_id": p["grupo_id"],
                "bus": p["bus"],
                "pasajeros": [],
                "total": 0,
                "comieron": 0,
            }
        grupos_dict[g_name]["pasajeros"].append(p)
        grupos_dict[g_name]["total"] += 1
        if p["comio"]:
            grupos_dict[g_name]["comieron"] += 1

    grupos_lista = list(grupos_dict.values())
    es_admin = bool(request.user.is_superuser or hasattr(request.user, "perfil") and request.user.perfil.rol == "ADMIN")

    context = {
        "viajes": viajes,
        "viaje": viaje,
        "eventos": eventos,
        "evento_sel": evento_sel,
        "tipo_sel": tipo_sel,
        "tipo_nombre": tipo_nombre,
        "tipo_articulo": tipo_articulo,
        "tipo_terminado": tipo_terminado,
        "tipo_accion": tipo_accion,
        "mensaje_finalizado": mensaje_finalizado,
        "secuencia_turnos": secuencia_turnos,
        "turno_actual": turno_actual,
        "siguiente_turno": siguiente_turno,
        "servicio_cerrado": servicio_cerrado,
        "es_admin": es_admin,
        "preguntar_comida": preguntar_comida,
        "comidas_resumen": comidas_resumen,
        "bus_filtro": bus_filtro,
        "estado_filtro": estado_filtro,
        "busqueda": busqueda,
        "stats": stats,
        "buses_stats": buses_stats,
        "buses_nums": [b["bus"] for b in buses_stats],
        "pasajeros": pasajeros_filtrados,
        "grupos_lista": grupos_lista,
    }
    return render(request, "viajes/control_comidas.html", context)

