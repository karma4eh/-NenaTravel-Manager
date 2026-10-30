@echo off
chcp 65001 > nul
title SUBIR PROYECTO A GITHUB • Karma Studio
cls

echo =====================================================================
echo           VIAJES NENA • SUBIENDO A GITHUB (Karma Studio)
echo =====================================================================
echo.
echo Repositorio: https://github.com/karma4eh/-NenaTravel-Manager.git
echo Usuario:     Karma4eh (Karma4eh@gmail.com)
echo.
echo =====================================================================
echo Enviando ramas, codigo y configuracion de APK a GitHub (git push)...
echo.
echo Si te aparece una ventana emergente de GitHub en tu navegador,
echo haz clic en "Sign in with your browser" y confirma la autorizacion.
echo =====================================================================
echo.

cd /d "C:\Users\karma\Documents\ViajesNena"
set PATH=C:\Users\karma\AppData\Local\Programs\Git\cmd;%PATH%

git push -u origin main

echo.
if %ERRORLEVEL% equ 0 (
    echo =====================================================================
    echo  EXITO: PROYECTO Y APK ENVIADOS A GITHUB!
    echo.
    echo  Tu APK se esta compilando gratis en GitHub Actions:
    echo  https://github.com/karma4eh/-NenaTravel-Manager/actions
    echo =====================================================================
) else (
    echo =====================================================================
    echo  Nota: Si no se abrio el navegador o fallo la autenticacion,
    echo  puedes generar un Personal Access Token (PAT) en GitHub.
    echo =====================================================================
)
echo.
pause
