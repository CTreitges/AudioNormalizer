# Audio Normalizer

Ein professionelles Werkzeug zur Normalisierung von Audio-Dateien (WAV, FLAC), das Wert auf höchste Klangqualität und den Erhalt der ursprünglichen Dynamik legt.

## Hauptfunktionen
- **Drei Normalisierungs-Modi**: Peak, Loudness (EBU R128) und ein intelligenter Hybrid-Modus.
- **Erhalt der Dynamik**: Im Gegensatz zu vielen anderen Tools verwendet dieser Normalizer lineare Verstärkung statt Kompression. Der Klangcharakter bleibt unverändert.
- **Metadaten-Schutz**: Alle Tags wie Titel, Interpret, Album und sogar Album-Cover bleiben vollständig erhalten. 
- **Multithreading**: Die Anwendung nutzt alle verfügbaren Prozessorkerne, um mehrere Dateien gleichzeitig zu analysieren und zu verarbeiten – ideal für große Musiksammlungen.
- **Automatisches Logging**: Bei der Stapelverarbeitung wird ein detaillierter Bericht über alle Einstellungen und Ergebnisse erstellt.
- **Normalisierungs-Indikator**: Das Programm hinterlegt im Metadaten-Feld "Titelnummer", welches Verfahren angewandt wurde (0 = Peak, 1 = Loudness).

---

## Die Normalisierungs-Modi

### 1. Peak-Normalisierung
Das Programm sucht den lautesten Punkt (Peak) in der Datei und verstärkt das gesamte Signal gleichmäßig, bis dieser Punkt den gewählten **Ziel Peak (dB)** erreicht.
*   **Vorteil**: Verhindert digitales Clipping und nutzt den verfügbaren Lautstärkebereich optimal aus, ohne den Klang zu verändern.
*   **Anwendung**: Ideal für einzelne Tracks, die lediglich auf einen Standardpegel gebracht werden sollen.

### 2. Loudness-Normalisierung
Dieser Modus orientiert sich an der menschlichen Lautstärkewahrnehmung (gemessen in LUFS nach EBU R128 Standard).
*   **Besonderheit**: Es findet **keine Kompression** statt. Das Tool berechnet einen festen Gain-Wert, um die **Ziel Loudness** zu erreichen. Die Dynamik (der Abstand zwischen leisen und lauten Passagen) bleibt zu 100% erhalten.
*   **Sicherheit**: Ein konfigurierbares **Max True Peak** Limit garantiert, dass es trotz Verstärkung niemals zu Übersteuerungen kommt.

### 3. Hybrid-Normalisierung (Intelligenter Batch-Modus)
Dieser Modus wurde speziell für Playlists und Alben entwickelt (erfordert mindestens 2 Dateien).
*   **Funktionsweise**: Zuerst werden alle Tracks analysiert, um die durchschnittliche Lautheit (Loudness) der gesamten Liste zu ermitteln.
*   **Die Logik**:
    - Tracks, deren Lautstärke nahe am Durchschnitt liegt (innerhalb der **Max. Abweichung**), werden mittels **Peak-Normalisierung** behandelt. Dies bewahrt die künstlerisch gewollten Lautstärkeunterschiede innerhalb eines Albums.
    - "Ausreißer", die deutlich zu leise oder zu laut sind, werden mittels **Loudness-Normalisierung** sanft an den Durchschnitt angepasst.
*   **Referenz LUFS**: Sie können den Ziel-Wert manuell festlegen oder auf "Auto" lassen, um den berechneten Durchschnitt der aktuellen Auswahl zu nutzen.

---

## Erklärung der Parameter

- **Ziel Peak (dB)**: Maximaler Pegel für die Peak-Normalisierung (Standard: -3,0 dB).
- **Ziel Loudness (LUFS)**: Die gewünschte Ziel-Lautheit (Standard: -11,0 LUFS).
- **Max True Peak (dB)**: Das absolute Sicherheitslimit gegen Clipping (Standard: -3,0 dB).
- **Max. Abweichung (dB)**: Der Toleranzbereich im Hybrid-Modus. Bestimmt, ab welcher Abweichung vom Durchschnitt die Loudness-Korrektur greift (Standard: 3,0 dB).
- **Referenz LUFS (Optional)**: Ermöglicht es, einen festen Wert als Basis für den Hybrid-Modus vorzugeben (z.B. um mehrere Alben auf exakt denselben Level zu bringen). "Auto" berechnet den Wert dynamisch aus der aktuellen Liste.

---

## Bedienungsanleitung

1. **FFmpeg Pfad**: Für fast alle Funktionen ist `ffmpeg` erforderlich. Geben Sie den Pfad zur `ffmpeg.exe` im oberen Feld an oder nutzen Sie den "Durchsuchen" Button. Der Pfad wird für den nächsten Start gespeichert.
2. **Dateien hinzufügen**: Ziehen Sie Audio-Dateien (WAV/FLAC) oder ganze Ordner in das Drag & Drop Feld oder klicken Sie darauf.
3. **Modus & Werte wählen**: Wählen Sie das gewünschte Verfahren. Die Standardwerte sind für hochwertige Ergebnisse optimiert.
4. **Normalisierung starten**: Klicken Sie auf "Normalisieren".
   - Bei einer Einzeldatei wählen Sie den neuen Dateinamen.
   - Bei mehreren Dateien wählen Sie einen Zielordner aus.
5. **Abschluss**: Nach der Bearbeitung erhalten Sie eine Zusammenfassung. Bei Ordner-Verarbeitung finden Sie ein Protokoll im Zielordner.

---

## Technische Hinweise & Voraussetzungen

- **FFmpeg**: Die `ffmpeg.exe` ist zwingend erforderlich (außer für Peak-Normalisierung bei reinen WAV-Dateien). Falls nicht vorhanden, kann sie kostenlos von der offiziellen FFmpeg-Website heruntergeladen werden.
- **Metadaten**: Das Feld "Titelnummer" (Track) wird als technischer Indikator verwendet (0=Peak, 1=Loudness). Falls Ihre Dateien bereits Titelnummern haben, werden diese überschrieben.
- **System**: Die Anwendung ist für Windows optimiert und läuft als eigenständige EXE-Datei ohne weitere Installationen.

---

