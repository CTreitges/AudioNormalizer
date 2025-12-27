# Audio Normalizer

Ein einfaches Python-Programm zur Normalisierung von Audio-Dateien (WAV, FLAC).

## Features
- Drag & Drop von Dateien und ganzen Ordnern in einen zentralen Bereich.
- Klicke auf den zentralen Bereich, um Dateien oder Ordner über den Explorer auszuwählen.
- Der angegebene FFmpeg-Pfad wird automatisch gespeichert und beim nächsten Start geladen.
- Modernes UI-Design mit Fortschrittsanzeige und intuitiver Bedienung.
- Rekursives Durchsuchen von Ordnern nach Audio-Dateien (WAV, FLAC).

## Installation

1. Installiere die benötigten Python-Bibliotheken:
   ```bash
   pip install PyQt6 pydub audioop-lts
   ```

2. **Wichtig für FLAC:**
   Für die Verarbeitung von FLAC-Dateien wird `ffmpeg` benötigt. Stelle sicher, dass `ffmpeg` auf deinem System installiert und im PATH verfügbar ist.
   WAV-Dateien funktionieren in der Regel auch ohne `ffmpeg`.

## Benutzung
1. Starte das Programm:
   ```bash
   python normalizer.py
   ```
2. Ziehe Audio-Dateien oder Ordner in das gestrichelte Feld oder klicke darauf, um sie auszuwählen.
3. (Optional) Wähle den Pfad zu deiner `ffmpeg.exe` aus, falls FLAC-Dateien nicht erkannt werden.
4. Klicke auf "Normalisieren".
5. Wähle den Speicherort:
   - Bei einer einzelnen Datei kannst du den Namen der Ausgabedatei direkt wählen.
   - Bei mehreren Dateien oder Ordnern wählst du einen Zielordner aus (du kannst im Dialog auch einen neuen Ordner erstellen).

## Als Standalone-App (EXE) erstellen

Du kannst das Programm in eine einzelne ausführbare Datei (.exe) umwandeln, sodass es ohne Python-Installation läuft:

1. Installiere PyInstaller:
   ```bash
   pip install pyinstaller
   ```

2. Führe das Build-Skript aus:
   ```bash
   build.bat
   ```
   *Alternativ manuell:*
   ```bash
   python -m PyInstaller --onefile --windowed --name "AudioNormalizer" --hidden-import=audioop_lts normalizer.py
   ```

Die fertige Datei findest du im Ordner `dist/AudioNormalizer.exe`.
