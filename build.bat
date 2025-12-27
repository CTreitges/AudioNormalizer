@echo off
echo Baue AudioNormalizer EXE...
python -m PyInstaller --onefile --windowed --name "AudioNormalizer" --hidden-import=audioop_lts normalizer.py
echo.
echo Fertig! Die EXE befindet sich im "dist" Ordner.
pause
