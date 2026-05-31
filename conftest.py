"""Stellt sicher, dass das Projekt-Root (mit dem ``audionormalizer``-Paket)
auf dem Importpfad liegt, egal von wo pytest gestartet wird."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
