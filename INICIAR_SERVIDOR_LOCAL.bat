@echo off
chcp 65001 > nul
title VIAJES NENA • Servidor de Red Local (Karma Studio)
cls

echo =====================================================================
echo           VIAJES NENA • SISTEMA OPERATIVO BETA (v1.0.0)
echo                   Desarrollado por Karma Studio
echo =====================================================================
echo.

cd /d "%~dp0"

echo [1/3] Detectando direccion IP de la red local (Wi-Fi)...
for /f "tokens=*" %%i in ('".\venv\Scripts\python.exe" -c "import socket; print([ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith('127.') and not ip.startswith('169.254.')][0] if socket.gethostbyname_ex(socket.gethostname())[2] else '127.0.0.1')"') do set LOCAL_IP=%%i

echo.
echo =====================================================================
echo  SERVIDOR ACTIVO EN LA RED LOCAL
echo =====================================================================
echo.
echo  Puedes entrar desde este computador o desde cualquier telefono,
echo  tablet u otra laptop conectada al MISMO Wi-Fi / Router en:
echo.
echo       👉  http://%LOCAL_IP%:8000/  👈
echo.
echo  O de forma local en este equipo:
echo       👉  http://localhost:8000/  👈
echo.
echo =====================================================================
echo [2/3] Abriendo navegador predeterminado...
start http://localhost:8000/

echo [3/3] Iniciando servidor Django en 0.0.0.0:8000...
echo Presiona CTRL + C para detener el servidor.
echo =====================================================================
echo.

".\venv\Scripts\python.exe" manage.py runserver 0.0.0.0:8000
pause
