@echo off
set ICON_PARAM=
if exist "icon.ico" set ICON_PARAM=--icon="icon.ico" --add-data "icon.ico;."

echo Baue AudioNormalizer EXE...
python -m PyInstaller --onefile --windowed --name "AudioNormalizer" --hidden-import=audioop_lts %ICON_PARAM% normalizer.py
echo.
echo Fertig! Die EXE befindet sich im "dist" Ordner.
pause
