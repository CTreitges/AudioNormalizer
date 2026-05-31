@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   Audio Normalizer - Build Script (VENV)
echo ========================================
echo.

:: 1. Suche Basis-Python
set "BASE_PYTHON="
echo [1/4] Suche installierte Python-Version...

:: Liste moeglicher Pfade
set "P1=%LocalAppData%\Programs\Python\Python313\python.exe"
set "P2=%LocalAppData%\Programs\Python\Python312\python.exe"
set "P3=%LocalAppData%\Programs\Python\Python311\python.exe"
set "P4=%ProgramFiles%\Python313\python.exe"
set "P5=%ProgramFiles%\Python312\python.exe"
set "P6=C:\Python313\python.exe"
set "P7=C:\Python312\python.exe"

:: Pruefe alle bekannten Pfade
for %%P in ("!P1!" "!P2!" "!P3!" "!P4!" "!P5!" "!P6!" "!P7!") do (
    if "!BASE_PYTHON!" == "" (
        if exist %%P (
            set "BASE_PYTHON=%%~P"
        )
    )
)

:: Falls kein Pfad gefunden, teste Launcher/Befehle
if "!BASE_PYTHON!" == "" (
    echo   Kein Standard-Pfad gefunden. Teste Befehle...
    py --version >nul 2>&1
    if !errorlevel! == 0 (
        set "BASE_PYTHON=py"
        echo   -^> OK: 'py' Launcher gefunden.
    )
)

if "!BASE_PYTHON!" == "" (
    python -c "import sys" >nul 2>&1
    if !errorlevel! == 0 (
        set "BASE_PYTHON=python"
        echo   -^> OK: 'python' gefunden.
    )
)

if "!BASE_PYTHON!" == "" (
    echo.
    echo [!!!] FEHLER: Python konnte nicht gefunden werden!
    echo.
    echo BITTE PRUEFEN:
    echo 1. Ist Python installiert? ^(Von python.org heruntergeladen?^)
    echo 2. Sind die Microsoft-Aliase auf AUS gestellt?
    echo    ^(Einstellungen -^> Apps -^> App-Ausfuehrungsaliase^)
    echo 3. Wurde 'Add Python to PATH' bei der Installation gewaehlt?
    echo.
    pause
    exit /b 1
)

if not "!BASE_PYTHON!" == "py" if not "!BASE_PYTHON!" == "python" (
    echo   -^> OK: Python in Pfad "!BASE_PYTHON!" gefunden.
)

:: Schnelltest ob Python wirklich funktioniert
"!BASE_PYTHON!" -c "import sys" >nul 2>&1
if !errorlevel! neq 0 (
    echo.
    echo [!!!] FEHLER: Python wurde gefunden, reagiert aber nicht korrekt.
    echo   Pfad: !BASE_PYTHON!
    echo   Bitte Python neu installieren ^(python.org^) mit 'Add Python to PATH'.
    echo.
    pause
    exit /b 1
)

:: 2. Virtuelle Umgebung (VENV) erstellen/pruefen
echo.
echo [2/4] Bereite virtuelle Umgebung (venv) vor...

set "VENV_PYTHON=venv\Scripts\python.exe"

:: Falls venv existiert, aber das Python-Binary fehlt, ist sie kaputt
if exist "venv" (
    if not exist "!VENV_PYTHON!" (
        echo   Bestehende 'venv' scheint beschaedigt zu sein. Loesche und erstelle neu...
        rmdir /s /q venv
    )
)

if not exist "venv" (
    echo   Erstelle neue venv...
    "!BASE_PYTHON!" -m venv venv
    if !errorlevel! neq 0 (
        echo   [WARNUNG] 'venv' konnte nicht erstellt werden.
        echo   Versuche es ohne venv direkt im System...
        set "VENV_PYTHON=!BASE_PYTHON!"
    )
) else (
    echo   Bestehende venv gefunden.
)

:: Sicherstellen dass VENV_PYTHON existiert
if not exist "!VENV_PYTHON!" (
    echo   [WARNUNG] venv-Python nicht gefunden, nutze System-Python...
    set "VENV_PYTHON=!BASE_PYTHON!"
)

:: 3. Abhaengigkeiten installieren
echo.
echo [3/4] Installiere/Aktualisiere Abhaengigkeiten...
"!VENV_PYTHON!" -m pip install --upgrade pip >nul 2>&1
"!VENV_PYTHON!" -m pip install -r requirements.txt pyinstaller
if !errorlevel! neq 0 (
    echo.
    echo [FEHLER] Installation der Requirements fehlgeschlagen.
    echo Pruefen Sie Ihre Internetverbindung.
    pause
    exit /b 1
)

:: 4. Build ausfuehren (Spec buendelt FFmpeg via imageio-ffmpeg + Icon)
echo.
echo [4/4] Erstelle EXE-Datei...
"!VENV_PYTHON!" -m PyInstaller --noconfirm AudioNormalizer.spec

if !errorlevel! == 0 (
    echo.
    echo ========================================
    echo   ERFOLG: EXE wurde erstellt!
    echo   Ort: dist\AudioNormalizer.exe
    echo ========================================
) else (
    echo.
    echo [FEHLER] Der Build-Prozess ist fehlgeschlagen.
)

pause
