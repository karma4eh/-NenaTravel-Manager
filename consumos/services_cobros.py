
from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from viajes.models import Cargo, Grupo
from .models import AplicacionPago, Pago


CENTAVO = Decimal("0.01")
OCHO_DECIMALES = Decimal("0.00000001")


def _centavos(valor):
    """Convierte un importe a dos decimales, sin utilizar float."""
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _repartir_proporcional(total, pesos):
    """
    Distribuye un total monetario proporcionalmente a los pesos.
    El método de mayores residuos garantiza que la suma final
    sea exactamente igual al total, incluidos los centavos.
    """
    total = _centavos(total)
    pesos = {clave: Decimal(peso) for clave, peso in pesos.items()}

    if total < 0:
        raise ValidationError("El importe que se repartirá no puede ser negativo.")

    if any(peso < 0 for peso in pesos.values()):
        raise ValidationError("Los saldos no pueden ser negativos.")

    if not pesos:
        if total:
            raise ValidationError("No existen destinatarios para el abono.")
        return {}

    suma_pesos = sum(pesos.values(), Decimal("0"))

    if suma_pesos <= 0:
        if total:
            raise ValidationError("No existen saldos pendientes para distribuir.")
        return {clave: Decimal("0.00") for clave in pesos}

    unidades = int((total / CENTAVO).to_integral_value())
    cuotas = {}

    for clave, peso in pesos.items():
        cuota = Decimal(unidades) * peso / suma_pesos
        cuotas[clave] = int(cuota.to_integral_value(rounding=ROUND_FLOOR))

    restantes = unidades - sum(cuotas.values())

    orden = sorted(
        pesos,
        key=lambda clave: (
            -(Decimal(unidades) * pesos[clave] / suma_pesos
              - cuotas[clave]),
            str(clave),
        ),
    )

    for clave in orden[:restantes]:
        cuotas[clave] += 1

    return {
        clave: (Decimal(unidades_centavos) * CENTAVO).quantize(CENTAVO)
        for clave, unidades_centavos in cuotas.items()
    }




def _repartir_secuencial(total, saldos):
    """
    Distribuye el importe secuencialmente entre los cargos (FIFO):
    cancela al 100% el primer cargo, luego el segundo, etc., hasta agotar
    el total disponible. El último cargo afectado absorbe el remanente.
    Esto garantiza que los productos se liquiden de forma limpia y completa,
    sin repartir centavos o saldos fraccionados entre todos los productos.
    """
    total = _centavos(total)
    reparto = {}
    restante = total

    for cargo_id, saldo in saldos.items():
        saldo = _centavos(saldo)
        if restante <= Decimal("0.00"):
            reparto[cargo_id] = Decimal("0.00")
        elif restante >= saldo:
            reparto[cargo_id] = saldo
            restante -= saldo
        else:
            reparto[cargo_id] = restante
            restante = Decimal("0.00")

    return reparto


@transaction.atomic
def registrar_pago(
    *,
    viaje_id,
    monto_original,
    moneda,
    cargo_ids,
    usuario=None,
    grupo_id=None,
    referencia="",
    observacion="",
):
    """
    Registra un pago y distribuye su equivalente en COP
    entre cargos existentes con saldo pendiente.

    Si se indica grupo_id, distribuye primero entre los pasajeros
    proporcionalmente a sus saldos y luego entre sus cargos.
    """
    if moneda not in dict(Pago.MONEDAS):
        raise ValidationError("Selecciona una moneda válida.")

    try:
        monto_original = Decimal(str(monto_original))
    except Exception:
        raise ValidationError("El monto del pago no es válido.")

    if not monto_original.is_finite() or monto_original <= 0:
        raise ValidationError("El monto debe ser mayor que cero.")

    if not cargo_ids:
        raise ValidationError("Selecciona al menos un cargo pendiente.")

    # Bloqueamos los cargos seleccionados mientras calculamos los saldos.
    cargos = list(
        Cargo.objects.select_for_update()
        .filter(
            id__in=set(cargo_ids),
            pasajero__viaje_id=viaje_id,
        )
        .select_related("pasajero", "pasajero__grupo", "pasajero__viaje")
        .order_by("creado_en", "id")
    )

    if len(cargos) != len(set(cargo_ids)):
        raise ValidationError(
            "Uno o más cargos no existen o no pertenecen al viaje seleccionado."
        )

    if grupo_id:
        grupo = Grupo.objects.get(pk=grupo_id, viaje_id=viaje_id)

        if any(cargo.pasajero.grupo_id != grupo.id for cargo in cargos):
            raise ValidationError(
                "Todos los cargos deben pertenecer al grupo seleccionado."
            )
    else:
        grupo = None

    aplicaciones_previas = (
        AplicacionPago.objects.filter(cargo_id__in=[c.id for c in cargos])
        .values("cargo_id")
        .annotate(abonado=Sum("monto_cop"))
    )

    abonado_por_cargo = {
        fila["cargo_id"]: fila["abonado"] or Decimal("0.00")
        for fila in aplicaciones_previas
    }

    saldos = {}

    for cargo in cargos:
        saldo = _centavos(
            cargo.total - abonado_por_cargo.get(
                cargo.id, Decimal("0.00")
            )
        )

        if saldo < 0:
            raise ValidationError(
                f"El cargo #{cargo.id} tiene pagos superiores a su total. "
                "Revisa el historial antes de continuar."
            )

        if saldo > 0:
            saldos[cargo.id] = saldo

    cargos_ya_pagados = [c for c in cargos if c.id not in saldos]
    if cargos_ya_pagados:
        nombres = ", ".join(f"'{c.concepto}' (#{c.id})" for c in cargos_ya_pagados[:3])
        raise ValidationError(
            f"Cobro concurrente detectado: {len(cargos_ya_pagados)} de los consumos seleccionados ({nombres}) "
            "acaban de ser liquidados por otro usuario. La pantalla se ha actualizado para evitar cobros duplicados."
        )

    if not saldos:
        raise ValidationError(
            "Los cargos seleccionados ya están pagados."
        )

    saldo_seleccionado = sum(saldos.values(), Decimal("0.00"))

    viaje = cargos[0].pasajero.viaje

    # Tasas del viaje: no se solicitan nuevamente al usuario.
    if viaje.tasa_usd_cop <= 0 or viaje.tasa_usd_bs <= 0:
        raise ValidationError(
            "El viaje tiene una tasa de cambio inválida."
        )

    # Convertimos el pago a COP con las tasas actuales del viaje.
    if moneda == "COP":
        pago_cop = _centavos(monto_original)
    elif moneda == "USD":
        pago_cop = _centavos(
            monto_original * viaje.tasa_usd_cop
        )
    else:
        pago_cop = _centavos(
            monto_original / viaje.tasa_usd_bs
            * viaje.tasa_usd_cop
        )

    if pago_cop <= 0:
        raise ValidationError(
            "El importe convertido es inferior a un centavo de COP."
        )

    # Permitir holgura por redondeo de USD al dólar entero (ej. cuenta de 18.90 USD pagada con 19 USD)
    # o por centavos en conversiones de Bolívares.
    if pago_cop > saldo_seleccionado:
        diferencia = pago_cop - saldo_seleccionado
        tolerancia = (
            viaje.tasa_usd_cop * Decimal("1.05")
            if moneda == "USD"
            else Decimal("100.00")
        )
        if diferencia <= tolerancia:
            pago_cop = saldo_seleccionado
            if not observacion and moneda == "USD":
                observacion = "Ajuste por redondeo de USD aplicado."
        else:
            raise ValidationError(
                f"El pago equivale a COP {pago_cop:,.2f}, "
                f"pero el saldo seleccionado es COP "
                f"{saldo_seleccionado:,.2f}. "
                "Reduce el monto o selecciona más cargos pendientes."
            )

    # Si el pago en Bs o USD queda a menos de 5 COP del total debido a decimales,
    # absorbemos la diferencia de centavos para liquidar el saldo al 100%.
    elif saldo_seleccionado > pago_cop and (saldo_seleccionado - pago_cop) <= Decimal("5.00"):
        pago_cop = saldo_seleccionado

    pago = Pago(
        viaje=viaje,
        grupo=grupo,
        moneda=moneda,
        monto_original=monto_original,
        tasa_usd_cop=viaje.tasa_usd_cop,
        tasa_usd_bs=viaje.tasa_usd_bs,
        referencia=referencia.strip(),
        observacion=observacion.strip(),
        registrado_por=(
            usuario if getattr(usuario, "is_authenticated", False)
            else None
        ),
    )
    pago.full_clean()
    pago.save()

    # Agrupamos los cargos por pasajero.
    saldos_por_pasajero = defaultdict(dict)

    for cargo in cargos:
        if cargo.id in saldos:
            saldos_por_pasajero[cargo.pasajero_id][cargo.id] = saldos[
                cargo.id
            ]

    deuda_por_pasajero = {
        pasajero_id: sum(
            cargos_pasajero.values(), Decimal("0.00")
        )
        for pasajero_id, cargos_pasajero
        in saldos_por_pasajero.items()
    }

    # Primer reparto: proporcional al saldo pendiente de cada pasajero.
    reparto_pasajeros = _repartir_proporcional(
        pago_cop,
        deuda_por_pasajero,
    )

    # Segundo reparto: dentro de cada pasajero, secuencial (FIFO)
    # para liquidar producto por producto completamente en orden cronológico.
    reparto_cargos = {}

    for pasajero_id, monto_pasajero in reparto_pasajeros.items():
        reparto = _repartir_secuencial(
            monto_pasajero,
            saldos_por_pasajero[pasajero_id],
        )
        reparto_cargos.update(reparto)

    # Distribuimos también el equivalente en la moneda original
    # para conservar la trazabilidad del abono.
    cargos_por_id = {cargo.id: cargo for cargo in cargos}
    cargos_aplicados = [
        cargo_id for cargo_id, importe in reparto_cargos.items()
        if importe > 0
    ]

    suma_aplicada = sum(
        (reparto_cargos[cargo_id] for cargo_id in cargos_aplicados),
        Decimal("0.00"),
    )

    reparto_moneda = _repartir_proporcional(
        monto_original,
        {
            cargo_id: reparto_cargos[cargo_id]
            for cargo_id in cargos_aplicados
        },
    )

    for cargo_id in cargos_aplicados:
        cargo = cargos_por_id[cargo_id]

        aplicacion = AplicacionPago(
            pago=pago,
            cargo=cargo,
            pasajero=cargo.pasajero,
            monto_cop=reparto_cargos[cargo_id],
            monto_moneda_pago=reparto_moneda[cargo_id],
            concepto_snapshot=cargo.concepto,
            total_cargo_snapshot=cargo.total,
        )
        aplicacion.full_clean()
        aplicacion.save()

    # Comprobación final dentro de la transacción.
    total_aplicado = sum(
        reparto_cargos.values(), Decimal("0.00")
    )

    if total_aplicado != pago_cop:
        raise ValidationError(
            "La distribución del pago no coincide con su equivalente en COP."
        )

    return pago
