@echo off
rem Doble clic para abrir la bitacora de alucinaciones.
rem Cierra esta ventana (o Ctrl+C) para apagarla.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
    python tools\bitacora\server.py
    goto fin
)
where py >nul 2>nul
if %errorlevel%==0 (
    py tools\bitacora\server.py
    goto fin
)
echo No se encontro Python en este computador.
echo Instalalo desde https://www.python.org/downloads/ y marca "Add python.exe to PATH".
:fin
echo.
pause
