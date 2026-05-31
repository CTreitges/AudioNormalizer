# Audio Normalizer

Ein Werkzeug zur Normalisierung von Audio-Dateien mit Fokus auf **höchste Klangqualität** und **vollständigen Erhalt der Dynamik**. Statt Kompression wird ausschließlich **lineare Verstärkung** verwendet – der Klangcharakter bleibt unverändert.

> **Version 2.0** – komplett überarbeitet: testbare Kern-Engine, automatische FFmpeg-Erkennung mit mitgelieferter Binary, zusätzliche Formate, Headless-CLI und zahlreiche Bugfixes (siehe [Changelog](#changelog)).

---

## Hauptfunktionen

- **Drei Normalisierungs-Modi**: Peak, Loudness (EBU R128) und ein intelligenter Hybrid-Modus.
- **Erhalt der Dynamik**: lineare Verstärkung statt Kompression – die Abstände zwischen leisen und lauten Passagen bleiben zu 100 % erhalten.
- **Clipping-Schutz**: ein konfigurierbares **Max True Peak**-Limit deckelt die Verstärkung, sodass es nie zu Übersteuerung kommt.
- **Metadaten- & Cover-Schutz**: Tags (Titel, Interpret, Album) **und das Album-Cover** bleiben erhalten.
- **Viele Formate**: WAV, FLAC (verlustfrei) sowie MP3, M4A/AAC, OGG, Opus.
- **Automatische FFmpeg-Erkennung**: findet FFmpeg im PATH, an üblichen Orten oder nutzt die **mitgelieferte Binary** – in der Regel keine Konfiguration nötig.
- **Multithreading**: mehrere Dateien werden parallel analysiert und verarbeitet.
- **Atomares Schreiben**: Ergebnisse werden erst in eine temporäre Datei geschrieben und dann umbenannt – keine halbfertigen oder beschädigten Dateien bei Fehler/Abbruch.
- **Abbrechen**: laufende Stapelverarbeitung kann jederzeit gestoppt werden.
- **Headless-CLI**: scriptbar und auch auf Servern/Linux nutzbar.
- **Automatisches Logging**: detailliertes Protokoll im Zielordner.
- **Normalisierungs-Indikator**: das Metadaten-Feld „Titelnummer" hält fest, welches Verfahren angewandt wurde (0 = Peak, 1 = Loudness).

---

## Die Normalisierungs-Modi

### 1. Peak-Normalisierung
Verstärkt das gesamte Signal gleichmäßig, bis der lauteste Punkt (Sample-Peak) den gewählten **Ziel Peak (dB)** erreicht. Ideal für einzelne Tracks.

### 2. Loudness-Normalisierung
Orientiert sich an der menschlichen Lautstärkewahrnehmung (LUFS, EBU R128). Es wird ein fester Gain berechnet, um die **Ziel Loudness** zu erreichen – ohne Kompression. Das **Max True Peak**-Limit verhindert Übersteuerung; greift es, bleibt der Track bewusst etwas leiser als das Ziel (statt zu clippen).

### 3. Hybrid-Normalisierung (intelligenter Batch-Modus)
Für Playlists/Alben (mindestens 2 Dateien). Zuerst werden **alle** Tracks analysiert und die durchschnittliche Lautheit ermittelt.
- Tracks nahe am Durchschnitt (innerhalb der **Max. Abweichung**) → **Peak-Normalisierung** (bewahrt gewollte Lautstärkeunterschiede).
- Ausreißer → **Loudness-Normalisierung** (sanft an den Durchschnitt angeglichen).

**Referenz LUFS** kann manuell vorgegeben werden (z.B. um mehrere Alben auf denselben Level zu bringen) oder auf „Auto" stehen (Mittelwert der aktuellen Liste). Auch bei manueller Referenz wird jeder Track gemessen, damit die Peak/Loudness-Entscheidung korrekt fällt.

---

## Parameter

| Parameter | Bedeutung | Standard |
|-----------|-----------|----------|
| **Ziel Peak (dB)** | Maximaler Sample-Pegel bei Peak-Normalisierung | -3,0 |
| **Ziel Loudness (LUFS)** | Gewünschte Ziel-Lautheit | -11,0 |
| **Max True Peak (dB)** | Sicherheitslimit gegen Clipping | -3,0 |
| **Max. Abweichung (dB)** | Toleranzbereich im Hybrid-Modus | 3,0 |
| **Referenz LUFS** | Feste Basis für Hybrid (oder „Auto") | Auto |

---

## Installation / Build

### Voraussetzungen
- Python 3.11+ (entwickelt/getestet mit 3.13)
- Abhängigkeiten: `pip install -r requirements.txt` (PyQt6, imageio-ffmpeg)

### Starten aus dem Quellcode
```bash
python normalizer.py            # GUI
python -m audionormalizer.cli   # Kommandozeile (siehe unten)
```

### EXE bauen (Windows)
```bat
build.bat
```
Erstellt `dist\AudioNormalizer.exe` (onefile, FFmpeg gebündelt). Cross-Platform-Builds (Windows/macOS/Linux) entstehen automatisch via GitHub Actions.

---

## Kommandozeile (CLI)

```bash
# Playlist im Hybrid-Modus in einen Ausgabeordner
python -m audionormalizer.cli -o out/ --mode hybrid playlist/

# Einzeldatei auf -14 LUFS, Ausgabe als FLAC
python -m audionormalizer.cli -o out.flac --mode loudness --target-lufs -14 input.flac

# Nur anzeigen, was passieren würde (nichts schreiben)
python -m audionormalizer.cli --dry-run --mode peak *.wav -o out/
```

Wichtige Optionen: `--mode {peak,loudness,hybrid}`, `--target-peak`, `--target-lufs`, `--target-tp`, `--max-dev`, `--ref-lufs`, `--format {wav,flac,mp3,m4a,aac,ogg,opus}`, `--suffix _norm`, `--workers N`, `--no-dither`, `--ffmpeg PFAD`, `--no-log`, `--dry-run`, `-v`.

---

## Architektur

```
audionormalizer/
  models.py          # Datenklassen, Mode-Enum, Konstanten
  procutil.py        # Subprozess-Helfer (verstecktes Fenster, robustes Decoding)
  ffmpeg_locator.py  # FFmpeg/FFprobe finden (PATH, gebündelt, übliche Orte)
  probe.py           # Stream-Parameter (ffprobe ODER ffmpeg -i Parsing)
  measure.py         # LUFS + True Peak (loudnorm) / Sample Peak (volumedetect)
  engine.py          # reine Gain-Mathematik + atomare, abbrechbare Verarbeitung
  batch.py           # Qt-freie Orchestrierung (Analyse-/Verarbeitungs-Phase)
  logwriter.py       # Protokolldatei (Legacy-Format)
  cli.py             # Headless-Kommandozeile
  gui/               # dünne PyQt6-Schicht (app, worker, widgets)
tests/               # pytest-Suite (läuft ohne FFmpeg, Subprozesse gemockt)
scripts/             # verify_roundtrip.py – End-to-End-Verifikation des Vertrags
```

Die gesamte Logik ist UI-frei und damit test- und scriptbar. Tests: `python -m pytest`.

---

## Technische Hinweise

- **FFmpeg** wird automatisch erkannt; die gebündelte Binary (imageio-ffmpeg) enthält kein `ffprobe` – die Stream-Analyse fällt dann auf das Parsen von `ffmpeg -i` zurück.
- **Bittiefe & Sample-Rate** verlustfreier Formate werden übernommen (24-bit-FLAC bleibt 24-bit). Bei Reduktion auf 16 bit wird Dither (triangular) angewandt.
- **Opus** wird immer auf 48 kHz resampled (libopus-Vorgabe).
- Das Feld „Titelnummer" (Track) wird als Indikator überschrieben (0 = Peak, 1 = Loudness).

---

## Changelog (v2.0)

**Bugfixes**
- „WAV-Peak ohne FFmpeg" war nie implementiert (`audioop`/`tempfile`/`shutil` importiert, aber ungenutzt) – die irreführende Logik wurde entfernt; FFmpeg wird sauber erkannt/gebündelt.
- Sinnloses `audioop`-Pflicht-Gate entfernt, das die App auf Python 3.13+ blockieren konnte.
- In-Place-Überschreiben (Ziel == Quelle) konnte Dateien beschädigen → jetzt **atomares** Schreiben (Temp + Rename).
- Absturz bei Multi-Drive-Auswahl (`os.path.commonpath`) → robuster Fallback.
- Decode-Absturz in der Analyse bei exotischen Dateinamen → durchgängig `errors="replace"`.
- Hybrid mit **manueller** Referenz übersprang die Analyse und behandelte alles als Loudness → analysiert jetzt immer korrekt.
- Cover-Erhalt crashte bei Opus/M4A bzw. erzeugte bei OGG ein Theora-Video → explizites Stream-Mapping pro Container.
- Opus-Export mit Quell-Sample-Rate (z.B. 44,1 kHz) schlug fehl → automatisches Resampling auf 48 kHz.

**Neu**
- Automatische FFmpeg-Erkennung + mitgelieferte Binary (Zero-Config).
- Formate MP3, M4A/AAC, OGG, Opus zusätzlich zu WAV/FLAC.
- Headless-CLI mit `--dry-run`.
- Abbrechen während der Verarbeitung.
- Modulare, getestete Architektur (pytest-Suite, End-to-End-Verifier).
