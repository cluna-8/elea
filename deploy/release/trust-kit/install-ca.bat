@echo off
REM ---------------------------------------------------------------------------
REM  Confianza del certificado de la pasarela - lanzador de doble-click.
REM
REM  Existe porque el usuario final NO abre una consola: hace doble-click. Este
REM  .bat es lo unico que hay que tocar; llama al .ps1 saltandose la politica de
REM  ejecucion (por defecto Windows no deja ejecutar scripts .ps1 por doble-click).
REM
REM  Este fichero se mantiene en ASCII puro a proposito: cmd.exe usa la pagina de
REM  codigos OEM y cualquier acento aqui saldria como basura. Los acentos van en
REM  el .ps1, que si esta en UTF-8 con BOM.
REM
REM  Uso:  doble-click, o bien
REM        install-ca.bat -Url https://192.168.1.50 -CertPath C:\ruta\root.crt
REM
REM  El instalador SE DETIENE a que se coteje la huella SHA-256 de la CA antes de
REM  tocar el almacen del equipo. Por doble-click esa confirmacion se contesta en
REM  la ventana de administrador que abre Windows. Para despliegue desatendido
REM  (GPO / gestion de flota) hay que pasarle la huella esperada, que es lo que
REM  conserva la comprobacion cuando no hay nadie mirando:
REM        install-ca.bat -NoPause -Fingerprint A1:B2:...:FF
REM ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul 2>&1

set "PS1=%~dp0install-ca.ps1"
if not exist "%PS1%" (
    echo.
    echo  ERROR: no encuentro install-ca.ps1 junto a este fichero.
    echo  Copie la carpeta COMPLETA del kit, no solo este .bat.
    echo.
    pause
    exit /b 2
)

REM pwsh.exe (PowerShell 7) si existe; si no, el powershell.exe de siempre.
set "PSEXE=powershell.exe"
where pwsh.exe >nul 2>&1 && set "PSEXE=pwsh.exe"

"%PSEXE%" -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%ERRORLEVEL%"

REM El .ps1 se detiene solo antes de cerrar (codigos 0..4), asi que aqui NO se
REM vuelve a pausar: seria un doble "pulse una tecla". Solo pausamos ante un
REM codigo inesperado (p.ej. 9009 = no se encontro PowerShell).
REM
REM Codigos: 0 verde | 1 la verificacion TLS fallo | 2 error de entrada |
REM          3 no se pudo elevar | 4 huella no verificada (NO se instalo nada).
REM
REM Si esta ventana se cierra sola sin mostrar nada, ejecute desde una consola:
REM   powershell -NoProfile -ExecutionPolicy Bypass -File install-ca.ps1
if %RC% GEQ 5 (
    echo.
    echo  Codigo de salida inesperado: %RC%
    pause
)

exit /b %RC%
