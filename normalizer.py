"""Einstiegspunkt des Audio Normalizers (GUI).

Die gesamte Logik liegt im Paket ``audionormalizer``. Diese Datei bleibt aus
Build-Kompatibilität bestehen (PyInstaller-Spec referenziert ``normalizer.py``)
und startet lediglich die Qt-Oberfläche.
"""
from audionormalizer.gui.app import main

if __name__ == "__main__":
    main()
