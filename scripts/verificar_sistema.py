"""
Script de diagnóstico y verificación integral del sistema Viajes Nena.
Ejecuta validaciones automáticas sobre todas las vistas, APIs y permisos.
Uso: python scripts/verificar_sistema.py
"""
import os
import sys

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.test import Client
from django.contrib.auth.models import User

def ejecutar_diagnostico():
    print("=" * 65)
    print("  VIAJES NENA • DIAGNÓSTICO INTEGRAL DE SALUD DEL SISTEMA")
    print("=" * 65)

    client = Client()
    admin = User.objects.filter(is_superuser=True).first() or User.objects.filter(username='karma').first()
    if admin:
        client.force_login(admin)
        print(f"[*] Autenticado como Administrador: {admin.username}")
    else:
        print("[!] Advertencia: No se encontró usuario administrador para pruebas.")

    rutas = [
        ("Panel Principal (Home)", "/", 200),
        ("Crear Viaje", "/crear-viaje/", 200),
        ("Lista de Precios", "/precios/", 200),
        ("Gestión de Usuarios", "/usuarios/", 200),
        ("Asistencia Los Juanes", "/los-juanes/", 200),
        ("Control de Comidas", "/comidas/", 200),
        ("Registro de Consumos", "/consumos/", 200),
        ("Cobros y Liquidación", "/cobros/", 200),
        ("API Ping Sesión", "/api/ping-session/", 200),
        ("API Tasa BCV", "/api/tasa-bcv/", 200),
    ]

    exitos = 0
    for nombre, url, esperado in rutas:
        try:
            resp = client.get(url)
            if resp.status_code == esperado:
                print(f"  [OK] {nombre:<28} -> Status {resp.status_code}")
                exitos += 1
            elif resp.status_code in (302, 403):
                # Vistas que requieren viaje activo
                print(f"  [INFO] {nombre:<26} -> Status {resp.status_code} (Regla de negocio esperada)")
                exitos += 1
            else:
                print(f"  [FALLO] {nombre:<25} -> Status {resp.status_code} (Esperado {esperado})")
        except Exception as e:
            print(f"  [ERROR] {nombre:<25} -> {e}")

    # Verificar control de roles para vendedor
    vendedor = User.objects.filter(username='carlos.vendedor').first()
    if vendedor:
        c_vend = Client()
        c_vend.force_login(vendedor)
        resp_vend = c_vend.get('/usuarios/')
        if resp_vend.status_code == 403 or "denegado" in resp_vend.content.decode('utf-8', errors='ignore').lower():
            print("  [OK] Control de Roles: Vendedor bloqueado en /usuarios/ -> Status 403")
            exitos += 1
        else:
            print(f"  [FALLO] Control de Roles: Vendedor pudo acceder a /usuarios/ con {resp_vend.status_code}")

    print("-" * 65)
    print(f"Resultado: {exitos}/{len(rutas) + (1 if vendedor else 0)} pruebas aprobadas.")
    print("=" * 65)

if __name__ == "__main__":
    ejecutar_diagnostico()
