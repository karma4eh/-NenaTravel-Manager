# Viajes Nena • Sistema Operativo Integral de Gestión Turística y Logística

![Versión](https://img.shields.io/badge/Versi%C3%B3n-v1.0.0%20Beta-0ea5e9?style=for-the-badge)
![Django](https://img.shields.io/badge/Django-6.1.1-092e20?style=for-the-badge&logo=django)
![Python](https://img.shields.io/badge/Python-3.13-3776ab?style=for-the-badge&logo=python)
![Database](https://img.shields.io/badge/Database-Supabase%20PostgreSQL%2017-3ecf8e?style=for-the-badge&logo=supabase)
![Mobile](https://img.shields.io/badge/Android-APK%20%2B%20PWA-34d399?style=for-the-badge&logo=android)
![Desarrollado por](https://img.shields.io/badge/Desarrollado%20por-Karma%20Studio-16b8b0?style=for-the-badge)

Plataforma de software desarrollada a medida para centralizar, digitalizar y resguardar la logística operativa, control de pasajeros, finanzas multimoneda y distribución de servicios en **Viajes Nena**.

---

## 🏛️ Arquitectura del Proyecto

El código está estructurado modularmente siguiendo las mejores prácticas de la ingeniería de software:

```
ViajesNena/
│
├── backups/                    # Copias de seguridad de la base de datos SQLite
│   ├── db.sqlite3.backup_*     # Instantáneas previas a reinicios
│   └── README.md               # Guía técnica de restauración
│
├── config/                     # Configuración central del proyecto
│   ├── settings.py             # Ajustes de Django, apps, middleware y seguridad
│   ├── urls.py                 # Enrutador central de vistas y APIs
│   ├── wsgi.py                 # Interfaz WSGI
│   └── asgi.py                 # Interfaz ASGI
│
├── core/                       # Módulo transversal y servicios centrales
│   ├── models.py               # Modelos de Productos, Tasas BCV y Perfiles de Usuario
│   ├── views.py                # Dashboard principal, autenticación, estadísticas y usuarios
│   ├── permisos.py             # Control de acceso y roles (ADMIN / VENDEDOR)
│   ├── services_bcv.py         # Consulta y sincronización de Tasa Oficial del BCV en vivo
│   ├── services_precios.py     # Sincronización automática de precios de catálogo al viaje
│   ├── templates/core/         # Vistas base, panel principal, login y modales
│   └── management/commands/    # Comandos personalizados (python manage.py reiniciar_datos)
│
├── viajes/                     # Ciclo de vida del viaje y operaciones en ruta
│   ├── models.py               # Viaje, Pasajero, Grupo, Evento, Cargos y ControlComida
│   ├── views.py                # Creación atómica de viajes, Los Juanes, comidas y cierre
│   ├── importadores/           # Motor de lectura de listines Excel (.xlsx)
│   │   └── listin.py           # Parser con detección de pasajeros duplicados
│   └── templates/viajes/       # Pantallas de creación, control de alimentos y cierre
│
├── consumos/                   # Facturación y cobranza multimoneda
│   ├── models.py               # Consumo, Historial de Consumos, Pagos y Aplicaciones
│   ├── views.py                # Registro de bebidas/snacks y liquidación por grupo
│   ├── services_cobros.py      # Lógica de imputación contable y prevención de duplicados
│   └── templates/consumos/     # Interfaces de registro de consumo y cobros
│
├── scripts/                    # Utilidades y diagnósticos
│   └── verificar_sistema.py    # Suite de diagnóstico automático del sistema
│
├── staticfiles/                # Archivos estáticos del sistema
├── venv/                       # Entorno virtual de Python
│
├── .env.example                # Plantilla de variables de entorno
├── .gitignore                  # Exclusiones de Git
├── db.sqlite3                  # Base de datos SQLite local
├── INICIAR_SERVIDOR_LOCAL.bat  # Lanzador en 1 clic para servidor local
├── manage.py                   # CLI oficial de Django
├── README.md                   # Documentación técnica
└── requirements.txt            # Dependencias del proyecto
```

---

## 🚀 Módulos Funcionales

1. **Gestión de Viajes y Listines:**
   - Destinos autorizados: **Mochima edo Sucre**, **Chichiriviche edo falcon** y **Margarita edo nueva esparta**.
   - Carga obligatoria de listín Excel (.xlsx) para 1 a 3 autobuses simultáneos.
   - Detección automática en vivo de pasajeros duplicados entre unidades.
   - Duración de 3 o 4 días operativos (el día de salida no cuenta).

2. **Control Secuencial de Comidas:**
   - Secuencia diaria obligatoria: **Desayuno ➔ Almuerzo ➔ Cena** por cada día de viaje.
   - Marcaje individual por autobús con un clic (pasajeros servidos vs. pendientes).
   - Bloqueo automático del servicio al completarse para impedir doble entrega de comida.

3. **Consumos y Cobros Multimoneda:**
   - Registro de bebidas, licores y snacks con liquidación en **USD**, **Pesos (COP)** y **Bolívares (Bs.)**.
   - Consulta y conversión automática con la **Tasa Oficial del BCV en vivo**.
   - Control de diferencias exactas y prevención inteligente de pagos duplicados.

4. **Paseo Náutico (Cayo Los Juanes):**
   - Asistencia con un clic por pasajero o grupo con cargo automático a la cuenta.

5. **Estadísticas y Métricas:**
   - Gráficos interactivos de ingresos totales desagregados en Bs., COP y USD.
   - Ranking de productos más vendidos y balance de solvencia.

6. **Seguridad y Roles:**
   - Perfil **ADMIN**: Control total (viajes, precios, tasas, auditoría y usuarios).
   - Perfil **VENDEDOR**: Interfaz exclusiva para operaciones de campo.
   - **Cierre de sesión por inactividad a los 10 minutos**: Advertencia interactiva al minuto 9 con cuenta atrás de 60 segundos antes de cerrar sesión.

7. **Cierre Seguro de Viaje:**
   - Bloqueo estricto que prohíbe finalizar o archivar un viaje si existen deudas pendientes por cobrar.

---

## 💻 Ejecución Local

### 1. Iniciar con el Lanzador de 1 Clic
Haz doble clic en:
- `VIAJES_NENA_SERVIDOR.bat` en tu **Escritorio**, o
- `INICIAR_SERVIDOR_LOCAL.bat` en la raíz del proyecto.

El lanzador detecta la IP local de tu máquina, abre el navegador y arranca el servidor.

### 2. Iniciar Manualmente por Terminal
```powershell
.\venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

- **Acceso en este computador:** [http://localhost:8000/](http://localhost:8000/) o [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Acceso desde otros dispositivos en la misma red Wi-Fi:** `http://<TU_IP_LOCAL>:8000/`

---

## 🔧 Comandos de Mantenimiento

### Diagnóstico Integral del Sistema:
Verifica que todas las vistas, APIs y controles de acceso respondan correctamente:
```powershell
python scripts/verificar_sistema.py
```

### Reinicio de Datos Operativos (Poner en Cero para Demo):
Limpia viajes, pasajeros, consumos, cobros y comidas, preservando catálogo de productos y usuarios:
```powershell
python manage.py reiniciar_datos
```

---

## 👥 Credenciales del Sistema

| Usuario | Rol | Permisos |
| :--- | :--- | :--- |
| `karma` | **ADMIN** | Acceso total a todas las configuraciones y módulos |
| `carlos.vendedor` | **VENDEDOR** | Operaciones de campo (consumos, cobros, comidas) |

---

<p align="center">
  <b>Desarrollado con altos estándares de ingeniería por Karma Studio</b><br>
  <i>Viajes Nena • v1.0.0</i>
</p>
