import re
import ssl
import urllib.request
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from .models import TasaBCV

BCV_URL = "https://www.bcv.org.ve"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def scrape_tasa_bcv():
    """
    Realiza web scraping a la página oficial del Banco Central de Venezuela (BCV).
    Siguiendo las reglas de negocio de Viajes Nena, se extrae la tasa oficial
    del EURO (la divisa con mayor valor en el BCV), utilizándola como referencia
    de cambio para el valor USD/Bs en el sistema.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        BCV_URL,
        headers={"User-Agent": USER_AGENT}
    )

    with urllib.request.urlopen(req, context=ctx, timeout=12) as response:
        html = response.read().decode("utf-8", errors="ignore")

    # Extraer la tasa del EURO (id="euro")
    m = re.search(
        r'id=["\']euro["\'].*?<strong[^>]*>\s*([0-9.,]+)\s*</strong>',
        html,
        re.DOTALL | re.IGNORECASE,
    )

    # Si por alguna eventualidad no se encontrara el contenedor del euro, usar el dólar
    if not m:
        m = re.search(
            r'id=["\']dolar["\'].*?<strong[^>]*>\s*([0-9.,]+)\s*</strong>',
            html,
            re.DOTALL | re.IGNORECASE,
        )

    if not m:
        raise ValueError(
            "No se encontró el contenedor de cotización de divisas en la página del BCV."
        )

    raw_val = m.group(1).strip().replace(".", "").replace(",", ".")
    try:
        tasa = Decimal(raw_val).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Valor de cotización no numérico en BCV: {m.group(1)}")

    # Extraer fecha valor si está disponible en la página
    m_fecha = re.search(
        r'Fecha Valor:\s*<span[^>]*>\s*([^<]+)\s*</span>',
        html,
        re.IGNORECASE,
    )
    fecha_valor = m_fecha.group(1).strip() if m_fecha else ""

    return tasa, fecha_valor


def obtener_tasa_bcv(forzar=False):
    """
    Obtiene la tasa de cambio oficial de referencia:
    - Si forzar=False y ya existe una tasa consultada HOY, retorna la guardada
      para no ralentizar el sistema ni saturar la web del BCV.
    - Si forzar=True o no se ha consultado hoy, realiza web scraping y actualiza la BD.
    - Si la web del BCV no responde, retorna la última tasa registrada como respaldo.
    """
    hoy = timezone.localdate()
    ultima = TasaBCV.objects.first()

    # Si ya se actualizó hoy y no se pidió forzar, usar la caché
    if not forzar and ultima and timezone.localdate(ultima.actualizado_en) == hoy:
        return {
            "tasa": ultima.tasa,
            "fecha_valor": ultima.fecha_valor,
            "actualizado_en": ultima.actualizado_en,
            "origen": "cache",
            "error": None,
        }

    # Realizar web scraping
    try:
        tasa, fecha_valor = scrape_tasa_bcv()
        registro = TasaBCV.objects.create(
            tasa=tasa,
            fecha_valor=fecha_valor,
        )
        return {
            "tasa": registro.tasa,
            "fecha_valor": registro.fecha_valor,
            "actualizado_en": registro.actualizado_en,
            "origen": "bcv",
            "error": None,
        }
    except Exception as exc:
        if ultima:
            return {
                "tasa": ultima.tasa,
                "fecha_valor": ultima.fecha_valor,
                "actualizado_en": ultima.actualizado_en,
                "origen": "fallback",
                "error": f"No se pudo conectar al BCV: {exc}",
            }
        else:
            return {
                "tasa": Decimal("994.04"),
                "fecha_valor": "",
                "actualizado_en": timezone.now(),
                "origen": "default",
                "error": f"No se pudo conectar al BCV: {exc}",
            }
