import sys
import os
import subprocess
import tempfile
import shutil
import json
import re

# Audioop-lts Fix für Python 3.13+
try:
    import audioop
except ImportError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop'] = audioop
    except ImportError:
        audioop = None

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFileDialog, QListWidget,
                             QProgressBar, QMessageBox, QLineEdit, QMenu, QComboBox, QGridLayout, QGroupBox,
                             QDoubleSpinBox, QCheckBox)
from PyQt6.QtCore import Qt, QMimeData, pyqtSignal, QSettings, QRunnable, QThreadPool, QObject, QDateTime
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent, QFont, QDoubleValidator, QIcon

class CustomDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
        
    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.lineEdit().selectAll()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.lineEdit().selectAll()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self.lineEdit().text():
                self.setValue(self.minimum())
            self.clearFocus()
        else:
            super().keyPressEvent(event)

class CustomLineEdit(QLineEdit):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clearFocus()
        else:
            super().keyPressEvent(event)

class DropZone(QLabel):
    clicked = pyqtSignal()
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("<b>Dateien oder Ordner hierher ziehen</b><br><span style='color: #666; font-size: 13px;'>oder klicken zum Durchsuchen</span>")
        self.setMinimumHeight(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #0078d4;
                border-radius: 8px;
                background-color: white;
                color: #0078d4;
                font-size: 15px;
                padding: 10px;
            }
            QLabel:hover {
                background-color: #f0f7ff;
                border-color: #005a9e;
            }
        """)
        self.setAcceptDrops(True)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                QLabel {
                    border: 2px dashed #004578;
                    border-radius: 8px;
                    background-color: #e1f0ff;
                    color: #004578;
                    font-size: 16px;
                    padding: 20px;
                }
            """)

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #0078d4;
                border-radius: 8px;
                background-color: white;
                color: #0078d4;
                font-size: 16px;
                padding: 20px;
            }
            QLabel:hover {
                background-color: #f0f7ff;
                border-color: #005a9e;
            }
        """)

    def dropEvent(self, event: QDropEvent):
        self.dragLeaveEvent(None)
        urls = event.mimeData().urls()
        new_files = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    for file in files:
                        if file.lower().endswith(('.wav', '.flac')):
                            new_files.append(os.path.join(root, file))
            elif path.lower().endswith(('.wav', '.flac')):
                new_files.append(path)
        
        if new_files:
            self.filesDropped.emit(new_files)

class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

class AudioWorker(QRunnable):
    def __init__(self, task_type, file_path, **kwargs):
        super().__init__()
        self.task_type = task_type # "analyze" oder "normalize"
        self.file_path = file_path
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            if self.task_type == "analyze":
                result = self.analyze()
                self.signals.finished.emit({"file": self.file_path, "stats": result})
            elif self.task_type == "normalize":
                self.normalize()
                self.signals.finished.emit({"file": self.file_path, "success": True})
        except Exception as e:
            self.signals.error.emit(f"Fehler bei {os.path.basename(self.file_path)}: {str(e)}")

    def analyze(self):
        ffmpeg_exe = self.kwargs.get("ffmpeg_exe", "ffmpeg")
        cmd = [
            ffmpeg_exe, "-i", self.file_path,
            "-af", "loudnorm=print_format=json",
            "-f", "null", "-"
        ]
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, encoding='utf-8')
        output = result.stderr
        match = re.search(r"\{.*\}", output, re.DOTALL)
        if match:
            stats = json.loads(match.group(0))
            return {
                "lufs": float(stats["input_i"]),
                "tp": float(stats["input_tp"])
            }
        raise Exception("Audio-Metadaten konnten nicht extrahiert werden.")

    def normalize(self):
        ffmpeg_exe = self.kwargs.get("ffmpeg_exe", "ffmpeg")
        params = self.kwargs.get("params")
        output_path = self.kwargs.get("output_path")
        stats = self.kwargs.get("stats")
        backup_dir = self.kwargs.get("backup_dir")

        mode = params["mode"]
        target_peak = params["target_peak"]
        target_lufs = params["target_lufs"]
        target_tp = params["target_tp"]
        target_dev = params["target_dev"]
        ref_lufs = params["ref_lufs"]

        # Bei Überschreiben-Modus: Backup erstellen, dann in temp-Datei schreiben und Original ersetzen
        actual_output = output_path
        temp_path = None
        if backup_dir:
            # Backup der Originaldatei anlegen (Ordnerstruktur relativ beibehalten)
            backup_path = os.path.join(backup_dir, os.path.basename(self.file_path))
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            shutil.copy2(self.file_path, backup_path)
            # In temp-Datei schreiben, danach Original ersetzen
            fd, temp_path = tempfile.mkstemp(suffix=os.path.splitext(output_path)[1],
                                             dir=os.path.dirname(output_path))
            os.close(fd)
            actual_output = temp_path
        else:
            out_dir = os.path.dirname(output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
        
        # Ausgabeformat/Codec-Argumente vorbereiten, um Bitrate/Format der Quelle zu erhalten
        ext = os.path.splitext(output_path)[1].lower()
        codec_args = []
        ainfo = self.probe_audio_params(ffmpeg_exe)
        if ainfo:
            ch = ainfo.get("channels") or 0
            sr = ainfo.get("sample_rate") or 0
            bps = ainfo.get("bits_per_sample") or 0
            sfmt = (ainfo.get("sample_fmt") or "").lower()
            if ext == ".wav":
                # Rekordbox-kompatibles PCM-Format wählen (nur 16-bit oder 24-bit Integer)
                pcm_codec = None
                if bps >= 24:
                    pcm_codec = "pcm_s24le"
                elif bps >= 16:
                    pcm_codec = "pcm_s16le"
                else:
                    # Fallback auf sample_fmt
                    if "s32" in sfmt or "flt" in sfmt or "s24" in sfmt:
                        pcm_codec = "pcm_s24le"
                    else:
                        pcm_codec = "pcm_s16le"
                codec_args += ["-c:a", pcm_codec]
                if sr:
                    # Rekordbox unterstützt max 96kHz
                    codec_args += ["-ar", str(min(sr, 96000))]
                if ch:
                    codec_args += ["-ac", str(ch)]
                # Standard RIFF WAV erzwingen (kein RF64) für Rekordbox-Kompatibilität
                codec_args += ["-rf64", "never"]
            elif ext == ".flac":
                # FLAC beibehalten, Rekordbox-kompatibel (max 24-bit, max 96kHz)
                codec_args += ["-c:a", "flac"]
                if sr:
                    codec_args += ["-ar", str(min(sr, 96000))]
                if ch:
                    codec_args += ["-ac", str(ch)]
                if bps >= 24:
                    codec_args += ["-sample_fmt", "s32"]  # entspricht 24-bit FLAC-Output
                else:
                    codec_args += ["-sample_fmt", "s16"]
        else:
            # Ohne Probe-Daten: sichere Rekordbox-kompatible Defaults
            if ext == ".wav":
                codec_args += ["-c:a", "pcm_s24le", "-rf64", "never"]
            elif ext == ".flac":
                codec_args += ["-c:a", "flac", "-sample_fmt", "s32"]

        actual_mode = ""
        if mode == "Hybrid-Normalizing":
            if stats:
                deviation = abs(stats["lufs"] - ref_lufs)
                actual_mode = "Loudness" if deviation >= target_dev else "Peak"
            else:
                actual_mode = "Loudness"
        elif mode == "Loudness-Normalizing":
            actual_mode = "Loudness"
        else:
            actual_mode = "Peak"

        track_num = "0" if actual_mode == "Peak" else "1"

        # WAV: keine Quell-Metadaten kopieren (verhindert unbekannte Chunks für Rekordbox)
        # FLAC: Metadaten beibehalten (Vorbis-Comments sind unproblematisch)
        metadata_args = ["-map_metadata", "-1"] if ext == ".wav" else ["-map_metadata", "0"]
        metadata_args += ["-metadata", f"track={track_num}"]

        if actual_mode == "Peak":
            # Peak messen (muss hier passieren da Multithreaded)
            max_vol = self.get_peak_volume(ffmpeg_exe)
            if max_vol is not None:
                gain = target_peak - max_vol
                cmd = [
                    ffmpeg_exe, "-y", "-i", self.file_path,
                    "-af", f"volume={gain}dB",
                ] + codec_args + metadata_args + [
                    actual_output
                ]
            else:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
                raise Exception("Konnte Peak-Lautstärke nicht ermitteln.")
        else:
            # Loudness-Normalisierung
            if not stats:
                # Falls keine Stats da sind (z.B. im reinen Loudness Modus), messen wir sie jetzt
                stats = self.analyze()

            actual_target_lufs = ref_lufs if mode == "Hybrid-Normalizing" else target_lufs
            tp_limit = min(target_tp, target_peak) if mode == "Hybrid-Normalizing" else target_tp

            gain = actual_target_lufs - stats["lufs"]
            max_allowed_gain = tp_limit - stats["tp"]
            applied_gain = min(gain, max_allowed_gain)

            cmd = [
                ffmpeg_exe, "-y", "-i", self.file_path,
                "-af", f"volume={applied_gain}dB",
            ] + codec_args + metadata_args + [
                actual_output
            ]

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo,
                                     encoding='utf-8', errors='replace')
            if result.returncode != 0:
                stderr_out = result.stderr.strip() if result.stderr else "(kein Output)"
                raise Exception(f"FFmpeg-Fehler (Exit {result.returncode}):\n{stderr_out[-2000:]}")

            # Bei Überschreiben-Modus: temp-Datei über Original verschieben
            if backup_dir and temp_path:
                shutil.move(temp_path, output_path)
        except Exception:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def probe_audio_params(self, ffmpeg_exe):
        # Ermittelt Quell-Parameter per ffprobe, um Bitrate/Format beizubehalten
        ffprobe_exe = None
        # 1) Neben ffmpeg.exe suchen
        if ffmpeg_exe and os.path.isfile(ffmpeg_exe):
            base_dir = os.path.dirname(ffmpeg_exe)
            cand = os.path.join(base_dir, "ffprobe.exe" if os.name == "nt" else "ffprobe")
            if os.path.isfile(cand):
                ffprobe_exe = cand
        # 2) Im PATH suchen
        if not ffprobe_exe:
            ffprobe_exe = shutil.which("ffprobe") or ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            cmd = [
                ffprobe_exe, "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_name,channels,sample_rate,bits_per_sample,sample_fmt,bit_rate",
                "-of", "json",
                self.file_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo,
                                 encoding='utf-8', errors='replace')
            if res.returncode != 0:
                # ffprobe nicht verfügbar oder Fehler – kein fataler Abbruch, nur Fallback
                return None
            data = json.loads(res.stdout or "{}")
            streams = data.get("streams") or []
            if streams:
                s = streams[0]
                def to_int(x, default=0):
                    try:
                        return int(x)
                    except Exception:
                        return default
                return {
                    "codec_name": s.get("codec_name"),
                    "channels": to_int(s.get("channels"), 0),
                    "sample_rate": to_int(s.get("sample_rate"), 0),
                    "bits_per_sample": to_int(s.get("bits_per_sample"), 0),
                    "sample_fmt": (s.get("sample_fmt") or "").lower(),
                    "bit_rate": to_int(s.get("bit_rate"), 0),
                }
        except FileNotFoundError:
            # ffprobe nicht installiert/nicht gefunden – Fallback ohne Codec-Infos
            return None
        except Exception:
            pass
        return None

    def get_peak_volume(self, ffmpeg_exe):
        cmd = [
            ffmpeg_exe, "-i", self.file_path,
            "-af", "volumedetect",
            "-vn", "-sn", "-dn",
            "-f", "null", "-"
        ]
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo,
                                    encoding='utf-8', errors='replace')
            if result.returncode != 0:
                raise Exception(f"volumedetect fehlgeschlagen (Exit {result.returncode}): {result.stderr.strip()[-1000:]}")
            output = result.stderr
            match = re.search(r"max_volume: ([\-\d\.]+) dB", output)
            if match:
                return float(match.group(1))
            raise Exception("Peak-Lautstärke konnte nicht aus FFmpeg-Output gelesen werden.")
        except Exception:
            raise

class NormalizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Normalizer")
        self.setMinimumSize(700, 700)
        
        # Icon setzen
        icon_path = self.get_resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # Einstellungen laden
        self.settings = QSettings("ChrisSoftware", "AudioNormalizer")
        
        self.all_files = []
        self.thread_pool = QThreadPool()
        self.ffmpeg_exe_path = "ffmpeg" # Default
        
        # State für Multithreading
        self.pending_tasks = 0
        self.success_count = 0
        self.error_count = 0
        self.ffmpeg_error_occurred = False
        self.analysis_results = {}
        self.current_output_mapping = {}
        self.current_params = {}

        # Neue State Variablen für Logging
        self.current_target_dir = ""
        self.current_source_folder_name = ""

        # Stylesheet für ein modernes Design
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f6f7;
            }
            QWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 14px;
            }
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
            QPushButton:pressed {
                background-color: #004578;
            }
            QPushButton:disabled {
                background-color: #c8c8c8;
                color: #a1a1a1;
            }
            QLineEdit, QDoubleSpinBox {
                padding: 6px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
                color: #333;
            }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                width: 20px;
                background-color: #f8f9fa;
                border-left: 1px solid #ccc;
            }
            QDoubleSpinBox::up-button {
                border-top-right-radius: 4px;
            }
            QDoubleSpinBox::down-button {
                border-bottom-right-radius: 4px;
            }
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #e9ecef;
            }
            QDoubleSpinBox::up-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 5px solid #555;
                width: 0;
                height: 0;
                margin-bottom: 2px;
            }
            QDoubleSpinBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #555;
                width: 0;
                height: 0;
                margin-top: 2px;
            }
            QLabel {
                color: #333;
            }
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 5px;
                background-color: white;
                color: #333;
                outline: none;
                min-height: 150px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #eee;
            }
            QListWidget::item:selected {
                background-color: #e1f0ff;
                color: #0078d4;
            }
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 5px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 4px;
            }
            QComboBox {
                padding: 8px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
                color: #333;
            }
            QComboBox:hover {
                border-color: #0078d4;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                color: #333;
                selection-background-color: #e1f0ff;
                selection-color: #0078d4;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #bbb;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 20px;
                color: #555;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                left: 10px;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(10)

        # Header
        header_label = QLabel("Audio Normalizer")
        header_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #333; margin-bottom: 2px;")
        layout.addWidget(header_label)

        # FFmpeg selection
        ffmpeg_layout = QVBoxLayout()
        ffmpeg_label = QLabel("FFmpeg Pfad:")
        ffmpeg_label.setStyleSheet("font-weight: bold; color: #666; font-size: 12px;")
        ffmpeg_layout.addWidget(ffmpeg_label)
        
        ffmpeg_input_layout = QHBoxLayout()
        ffmpeg_input_layout.setSpacing(5)
        self.edit_ffmpeg = CustomLineEdit()
        self.edit_ffmpeg.setFixedHeight(30)
        self.edit_ffmpeg.setPlaceholderText("Pfad zur ffmpeg.exe...")
        # Gespeicherten Pfad laden
        saved_path = self.settings.value("ffmpeg_path", "")
        self.edit_ffmpeg.setText(saved_path)
        self.update_ffmpeg_config(saved_path)
        self.edit_ffmpeg.editingFinished.connect(self.save_ffmpeg_path)
        
        ffmpeg_input_layout.addWidget(self.edit_ffmpeg)
        self.btn_browse_ffmpeg = QPushButton("Durchsuchen")
        self.btn_browse_ffmpeg.setStyleSheet("padding: 8px 15px; font-size: 12px;")
        self.btn_browse_ffmpeg.clicked.connect(self.browse_ffmpeg)
        ffmpeg_input_layout.addWidget(self.btn_browse_ffmpeg)
        ffmpeg_layout.addLayout(ffmpeg_input_layout)
        layout.addLayout(ffmpeg_layout)

        # Normalisierungseinstellungen
        settings_group = QGroupBox("Normalisierungseinstellungen")
        settings_layout = QVBoxLayout(settings_group)
        
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Modus:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Peak-Normalizing", "Loudness-Normalizing", "Hybrid-Normalizing"])
        self.combo_mode.currentIndexChanged.connect(self.toggle_settings_visibility)
        mode_layout.addWidget(self.combo_mode)
        mode_layout.addStretch()
        settings_layout.addLayout(mode_layout)

        # Parameter Grid
        self.params_widget = QWidget()
        self.params_grid = QGridLayout(self.params_widget)
        self.params_grid.setContentsMargins(0, 10, 0, 0)
        self.params_grid.setSpacing(15)
        self.params_grid.setColumnStretch(4, 1)

        # Peak Parameter
        self.lbl_peak = QLabel("Ziel Peak (dB):")
        self.edit_peak = CustomDoubleSpinBox()
        self.edit_peak.setRange(-100.0, 0.0)
        self.edit_peak.setDecimals(2)
        self.edit_peak.setValue(-3.0)
        self.edit_peak.setFixedWidth(100)
        
        # Loudness Parameter
        self.lbl_lufs = QLabel("Ziel Loudness (LUFS):")
        self.edit_lufs = CustomDoubleSpinBox()
        self.edit_lufs.setRange(-100.0, 0.0)
        self.edit_lufs.setDecimals(2)
        self.edit_lufs.setValue(-11.0)
        self.edit_lufs.setFixedWidth(100)
        
        self.lbl_tp = QLabel("Max True Peak (dB):")
        self.edit_tp = CustomDoubleSpinBox()
        self.edit_tp.setRange(-100.0, 0.0)
        self.edit_tp.setDecimals(2)
        self.edit_tp.setValue(-3.0)
        self.edit_tp.setFixedWidth(100)
        
        # Hybrid Parameter
        self.lbl_dev = QLabel("Max. Abweichung (dB):")
        self.edit_dev = CustomDoubleSpinBox()
        self.edit_dev.setRange(0.0, 20.0)
        self.edit_dev.setDecimals(2)
        self.edit_dev.setValue(3.0)
        self.edit_dev.setFixedWidth(100)

        self.lbl_ref_lufs = QLabel("Referenz LUFS (Optional):")
        self.edit_ref_lufs = CustomDoubleSpinBox()
        self.edit_ref_lufs.setRange(-100.01, 0.0)
        self.edit_ref_lufs.setDecimals(2)
        self.edit_ref_lufs.setMinimum(-100.01)
        self.edit_ref_lufs.setSpecialValueText("Auto")
        self.edit_ref_lufs.setValue(-100.01)
        self.edit_ref_lufs.setFixedWidth(100)

        # Standardwert-Hinweise
        hint_style = "font-size: 11px; color: #777; margin-left: 2px;"
        self.hint_peak = QLabel("(-3,0)")
        self.hint_peak.setStyleSheet(hint_style)
        self.hint_lufs = QLabel("(-11,0)")
        self.hint_lufs.setStyleSheet(hint_style)
        self.hint_tp = QLabel("(-3,0)")
        self.hint_tp.setStyleSheet(hint_style)
        self.hint_dev = QLabel("(3,0)")
        self.hint_dev.setStyleSheet(hint_style)
        self.hint_ref_lufs = QLabel("(Auto)")
        self.hint_ref_lufs.setStyleSheet(hint_style)

        settings_layout.addWidget(self.params_widget)

        # Checkbox: Dateien überschreiben (für Rekordbox CuePoints)
        self.chk_overwrite = QCheckBox("Originaldateien überschreiben (CuePoints in Rekordbox erhalten)")
        self.chk_overwrite.setToolTip(
            "Wenn aktiviert, werden die Originaldateien direkt überschrieben.\n"
            "Dadurch bleiben CuePoints, Loops und Beatgrids in Rekordbox erhalten,\n"
            "da Rekordbox Tracks anhand ihres Dateipfads identifiziert.\n\n"
            "Achtung: Die Originaldateien werden unwiderruflich verändert!"
        )
        self.chk_overwrite.setChecked(self.settings.value("overwrite_original", "false") == "true")
        self.chk_overwrite.stateChanged.connect(self.save_overwrite_setting)
        settings_layout.addWidget(self.chk_overwrite)

        layout.addWidget(settings_group)

        self.toggle_settings_visibility()

        # Drop Zone
        self.drop_zone = DropZone(self)
        self.drop_zone.clicked.connect(self.select_files)
        self.drop_zone.filesDropped.connect(self.add_files)
        layout.addWidget(self.drop_zone)

        # File List Label
        file_list_label = QLabel("Ausgewählte Dateien:")
        file_list_label.setStyleSheet("font-weight: bold; color: #666;")
        layout.addWidget(file_list_label)

        self.file_list = QListWidget()
        layout.addWidget(self.file_list)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Bottom Buttons
        button_layout = QHBoxLayout()
        
        self.btn_clear = QPushButton("Liste leeren")
        self.btn_clear.setStyleSheet("background-color: #f0f0f0; color: #333; border: 1px solid #ccc;")
        self.btn_clear.clicked.connect(self.clear_files)
        button_layout.addWidget(self.btn_clear)
        
        button_layout.addStretch()

        self.btn_normalize = QPushButton("Normalisieren")
        self.btn_normalize.clicked.connect(self.start_normalization)
        self.btn_normalize.setEnabled(False)
        self.btn_normalize.setMinimumWidth(250)
        button_layout.addWidget(self.btn_normalize)
        
        layout.addLayout(button_layout)

    def get_resource_path(self, relative_path):
        """ Holt den Pfad zu Ressourcen, funktioniert für Dev und für PyInstaller """
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def toggle_settings_visibility(self):
        mode = self.combo_mode.currentText()
        
        # Erst alle verstecken und aus dem Grid nehmen
        widgets = [
            (self.lbl_peak, self.edit_peak, self.hint_peak),
            (self.lbl_lufs, self.edit_lufs, self.hint_lufs),
            (self.lbl_tp, self.edit_tp, self.hint_tp),
            (self.lbl_dev, self.edit_dev, self.hint_dev),
            (self.lbl_ref_lufs, self.edit_ref_lufs, self.hint_ref_lufs)
        ]
        
        for lbl, edit, hint in widgets:
            lbl.hide()
            edit.hide()
            hint.hide()
            self.params_grid.removeWidget(lbl)
            self.params_grid.removeWidget(edit)
            self.params_grid.removeWidget(hint)
        
        # Stretch zurücksetzen
        for i in range(7):
            self.params_grid.setColumnStretch(i, 0)

        if mode == "Peak-Normalizing":
            self.params_grid.addWidget(self.lbl_peak, 0, 0, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_peak, 0, 1, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.hint_peak, 0, 2, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.setColumnStretch(3, 1)
            self.lbl_peak.show()
            self.edit_peak.show()
            self.hint_peak.show()
        elif mode == "Loudness-Normalizing":
            self.params_grid.addWidget(self.lbl_lufs, 0, 0, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_lufs, 0, 1, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.hint_lufs, 0, 2, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.lbl_tp, 1, 0, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_tp, 1, 1, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.hint_tp, 1, 2, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.setColumnStretch(3, 1)
            self.lbl_lufs.show()
            self.edit_lufs.show()
            self.hint_lufs.show()
            self.lbl_tp.show()
            self.edit_tp.show()
            self.hint_tp.show()
        elif mode == "Hybrid-Normalizing":
            # 3 Spalten pro Element-Gruppe (Label, Edit, Hint)
            self.params_grid.addWidget(self.lbl_peak, 0, 0, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_peak, 0, 1, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.hint_peak, 0, 2, Qt.AlignmentFlag.AlignLeft)
            
            self.params_grid.addWidget(self.lbl_tp, 0, 3, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_tp, 0, 4, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.hint_tp, 0, 5, Qt.AlignmentFlag.AlignLeft)
            
            self.params_grid.addWidget(self.lbl_dev, 1, 0, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_dev, 1, 1, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.hint_dev, 1, 2, Qt.AlignmentFlag.AlignLeft)
            
            self.params_grid.addWidget(self.lbl_ref_lufs, 1, 3, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_ref_lufs, 1, 4, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.hint_ref_lufs, 1, 5, Qt.AlignmentFlag.AlignLeft)
            
            self.params_grid.setColumnStretch(6, 1)

            self.lbl_peak.show()
            self.edit_peak.show()
            self.hint_peak.show()
            self.lbl_tp.show()
            self.edit_tp.show()
            self.hint_tp.show()
            self.lbl_dev.show()
            self.edit_dev.show()
            self.hint_dev.show()
            self.lbl_ref_lufs.show()
            self.edit_ref_lufs.show()
            self.hint_ref_lufs.show()

    def update_ffmpeg_config(self, path, show_warnings=False):
        if not path:
            return
            
        ffmpeg_dir = ""
        path = os.path.normpath(path)
        if os.path.isfile(path):
            # Prüfen ob die Datei tatsächlich ausführbar / ffmpeg ist
            if not os.access(path, os.X_OK) and os.name != 'nt':
                if show_warnings:
                    QMessageBox.warning(self, "FFmpeg-Pfad",
                        f"Die Datei '{path}' ist nicht ausführbar.\n"
                        f"Bitte stelle sicher, dass es sich um ffmpeg handelt.")
                return
            self.ffmpeg_exe_path = path
            ffmpeg_dir = os.path.dirname(path)
        elif os.path.isdir(path):
            found = False
            for exe in ["ffmpeg.exe", "ffmpeg"]:
                potential_exe = os.path.join(path, exe)
                if os.path.isfile(potential_exe):
                    self.ffmpeg_exe_path = potential_exe
                    ffmpeg_dir = path
                    found = True
                    break
            if not found:
                if show_warnings:
                    QMessageBox.warning(self, "FFmpeg nicht gefunden",
                        f"Im Ordner '{path}' wurde keine ffmpeg-Datei gefunden.\n"
                        f"Bitte wähle den Ordner, der ffmpeg.exe enthält, "
                        f"oder direkt die ffmpeg.exe-Datei.")
                return
        else:
            if show_warnings:
                QMessageBox.warning(self, "FFmpeg-Pfad ungültig",
                    f"Der angegebene Pfad existiert nicht:\n'{path}'\n\n"
                    f"Bitte gib einen gültigen Pfad zur ffmpeg.exe an.")
            return
        
        if ffmpeg_dir:
            ffmpeg_dir = os.path.abspath(ffmpeg_dir)
            paths = os.environ.get("PATH", "").split(os.pathsep)
            if ffmpeg_dir not in paths:
                os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    def save_overwrite_setting(self):
        self.settings.setValue("overwrite_original", "true" if self.chk_overwrite.isChecked() else "false")

    def save_ffmpeg_path(self):
        path = self.edit_ffmpeg.text().strip()
        self.settings.setValue("ffmpeg_path", path)
        self.update_ffmpeg_config(path, show_warnings=True)

    def browse_ffmpeg(self):
        if os.name == 'nt':
            file_filter = "Executables (ffmpeg.exe);;All Files (*)"
        else:
            file_filter = "All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "ffmpeg auswählen", "", file_filter)
        if file_path:
            self.edit_ffmpeg.setText(file_path)
            self.save_ffmpeg_path()

    def select_files(self):
        menu = QMenu(self)
        action_files = menu.addAction("Dateien auswählen")
        action_folder = menu.addAction("Ordner auswählen")
        
        # Positioniere das Menü unter der DropZone
        action = menu.exec(self.drop_zone.mapToGlobal(self.drop_zone.rect().center()))
        
        if action == action_files:
            files, _ = QFileDialog.getOpenFileNames(self, "Audio-Dateien auswählen", "", "Audio Files (*.wav *.flac)")
            if files:
                self.add_files(files)
        elif action == action_folder:
            folder = QFileDialog.getExistingDirectory(self, "Ordner auswählen")
            if folder:
                self.current_source_folder_name = os.path.basename(folder)
                new_files = []
                for root, dirs, files in os.walk(folder):
                    for file in files:
                        if file.lower().endswith(('.wav', '.flac')):
                            new_files.append(os.path.join(root, file))
                if new_files:
                    self.add_files(new_files)

    def add_files(self, files):
        if files and not self.current_source_folder_name:
            common_path = os.path.dirname(files[0])
            self.current_source_folder_name = os.path.basename(common_path)

        for f in files:
            if f not in self.all_files:
                self.all_files.append(f)
                # Zeige Elternordner + Dateiname um Verwechslungen bei gleichnamigen Dateien zu vermeiden
                parent = os.path.basename(os.path.dirname(f))
                display = os.path.join(parent, os.path.basename(f)) if parent else os.path.basename(f)
                self.file_list.addItem(display)
        
        if self.all_files:
            self.btn_normalize.setEnabled(True)

    def clear_files(self):
        self.all_files = []
        self.file_list.clear()
        self.btn_normalize.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.current_source_folder_name = ""

    def start_normalization(self):
        if not self.all_files:
            return

        if audioop is None:
            QMessageBox.critical(self, "Fehler", "Das erforderliche Modul 'audioop' fehlt.\n"
                                               "Bitte stellen Sie sicher, dass 'audioop-lts' installiert ist.")
            return

        mode = self.combo_mode.currentText()
        
        if mode == "Hybrid-Normalizing" and len(self.all_files) <= 1:
            QMessageBox.warning(self, "Modus nicht verfügbar", 
                                "Der Hybrid-Modus erfordert mindestens zwei Tracks.\n"
                                "Bei einem einzelnen Track wählen Sie bitte Peak- oder Loudness-Normalisierung.")
            return

        try:
            ref_val = self.edit_ref_lufs.value()
            self.current_params = {
                "mode": mode,
                "target_peak": self.edit_peak.value(),
                "target_lufs": self.edit_lufs.value(),
                "target_tp": self.edit_tp.value(),
                "target_dev": self.edit_dev.value(),
                "ref_lufs_override": ref_val if ref_val > -100.01 else None
            }
        except Exception:
            QMessageBox.warning(self, "Eingabefehler", "Bitte gültige numerische Werte in den Einstellungen eingeben.")
            return

        ffmpeg_exe = self.ffmpeg_exe_path
        is_only_wav_peak = mode == "Peak-Normalizing" and all(f.lower().endswith('.wav') for f in self.all_files)
        ffmpeg_required = not is_only_wav_peak
        
        if ffmpeg_required:
            if not ffmpeg_exe or not os.path.isfile(ffmpeg_exe):
                if not shutil.which("ffmpeg"):
                    msg = "FFmpeg wurde nicht gefunden. Es wird für "
                    if mode == "Peak-Normalizing":
                        msg += "die Verarbeitung von Nicht-WAV Dateien "
                    else:
                        msg += "Loudness/Hybrid Normalisierung "
                    msg += "benötigt.\nBitte geben Sie den Pfad zur ffmpeg.exe oben an."
                    QMessageBox.critical(self, "Fehler", msg)
                    return

        self.current_output_mapping = {}
        self.overwrite_original = self.chk_overwrite.isChecked()
        self.backup_dir = None

        if self.overwrite_original:
            # Überschreiben-Modus: Backup-Ordner wählen
            backup_dir = QFileDialog.getExistingDirectory(self, "Backup-Ordner für Originaldateien wählen")
            if not backup_dir:
                return
            self.backup_dir = backup_dir
            for f in self.all_files:
                self.current_output_mapping[f] = f
            self.current_target_dir = os.path.dirname(self.all_files[0])
        elif len(self.all_files) == 1:
            source_path = self.all_files[0]
            ext = os.path.splitext(source_path)[1]
            target_path, _ = QFileDialog.getSaveFileName(self, "Speichern unter", source_path, f"Audio Files (*{ext})")
            if not target_path: return
            self.current_output_mapping[source_path] = target_path
            self.current_target_dir = os.path.dirname(target_path)
        else:
            target_dir = QFileDialog.getExistingDirectory(self, "Zielordner wählen")
            if not target_dir: return
            self.current_target_dir = target_dir
            # Relative Pfade beibehalten, damit Unterordner-Struktur erhalten bleibt
            # und Dateinamen-Kollisionen bei gleichen Dateinamen in verschiedenen Unterordnern vermieden werden
            common_base = os.path.commonpath(self.all_files) if len(self.all_files) > 1 else os.path.dirname(self.all_files[0])
            if os.path.isfile(common_base):
                common_base = os.path.dirname(common_base)
            for f in self.all_files:
                try:
                    rel = os.path.relpath(f, common_base)
                except ValueError:
                    # Verschiedene Laufwerke unter Windows → Fallback auf Dateiname
                    rel = os.path.basename(f)
                out_path = os.path.join(target_dir, rel)
                self.current_output_mapping[f] = out_path

        # UI sperren
        self.btn_normalize.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.combo_mode.setEnabled(False)
        self.params_widget.setEnabled(False)
        self.drop_zone.setEnabled(False)
        self.progress_bar.setVisible(True)
        
        # State zurücksetzen
        self.success_count = 0
        self.error_count = 0
        self.ffmpeg_error_occurred = False
        self.analysis_results = {}
        
        # Start Phase 1 oder 2
        if mode == "Hybrid-Normalizing" and self.current_params["ref_lufs_override"] is None:
            self.run_analysis_phase()
        else:
            self.run_normalization_phase()

    def run_analysis_phase(self):
        self.pending_tasks = len(self.all_files)
        self.progress_bar.setMaximum(self.pending_tasks)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Analysiere Playlist: %p%")
        
        ffmpeg_exe = self.ffmpeg_exe_path or "ffmpeg"
        
        for file_path in self.all_files:
            worker = AudioWorker("analyze", file_path, ffmpeg_exe=ffmpeg_exe)
            worker.signals.finished.connect(self.on_analysis_finished)
            worker.signals.error.connect(self.on_task_error)
            self.thread_pool.start(worker)

    def on_analysis_finished(self, result):
        self.analysis_results[result["file"]] = result["stats"]
        self.pending_tasks -= 1
        self.progress_bar.setValue(self.progress_bar.maximum() - self.pending_tasks)
        
        if self.pending_tasks == 0:
            self.run_normalization_phase()

    def run_normalization_phase(self):
        # Referenz-LUFS berechnen falls nötig
        if self.current_params["mode"] == "Hybrid-Normalizing" and self.current_params["ref_lufs_override"] is None:
            lufs_values = [s["lufs"] for s in self.analysis_results.values() if s]
            if lufs_values:
                self.current_params["ref_lufs"] = sum(lufs_values) / len(lufs_values)
            else:
                self.current_params["ref_lufs"] = self.current_params["target_lufs"]
        else:
            override = self.current_params["ref_lufs_override"]
            self.current_params["ref_lufs"] = override if override is not None else self.current_params["target_lufs"]

        self.pending_tasks = len(self.all_files)
        self.progress_bar.setMaximum(self.pending_tasks)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Verarbeite: %p%")
        
        ffmpeg_exe = self.ffmpeg_exe_path or "ffmpeg"

        for file_path in self.all_files:
            try:
                worker = AudioWorker("normalize", file_path,
                                    ffmpeg_exe=ffmpeg_exe,
                                    params=self.current_params,
                                    output_path=self.current_output_mapping[file_path],
                                    stats=self.analysis_results.get(file_path),
                                    backup_dir=self.backup_dir)
                
                worker.signals.finished.connect(self.on_normalization_finished)
                worker.signals.error.connect(self.on_task_error)
                self.thread_pool.start(worker)
            except Exception as e:
                self.on_task_error(str(e))

    def on_normalization_finished(self, result):
        self.success_count += 1
        self.pending_tasks -= 1
        remaining = max(self.pending_tasks, 0)
        self.progress_bar.setValue(self.progress_bar.maximum() - remaining)
        
        if self.pending_tasks == 0:
            self.finish_normalization()

    def on_task_error(self, error_msg):
        print(f"[Fehler] {error_msg}")
        error_lower = error_msg.lower()
        if "ffmpeg" in error_lower or "ffprobe" in error_lower:
            self.ffmpeg_error_occurred = True
        self.error_count += 1
        self.pending_tasks -= 1
        remaining = max(self.pending_tasks, 0)
        self.progress_bar.setValue(self.progress_bar.maximum() - remaining)

        # Einzelne Fehlermeldung direkt anzeigen (max. 3 Dialoge um Spam zu vermeiden)
        if self.error_count <= 3:
            short_msg = error_msg if len(error_msg) <= 600 else error_msg[:600] + "\n...(gekürzt)"
            QMessageBox.warning(self, f"Fehler bei Datei ({self.error_count})", short_msg)
        
        if self.pending_tasks == 0:
            # Falls wir in der Analyse-Phase waren, müssen wir trotzdem weitermachen oder abbrechen
            # Wenn Analyse-Fehler, wird normalization_phase trotzdem aufgerufen wenn pending_tasks == 0
            if self.progress_bar.format().startswith("Analysiere"):
                # Sicherstellen dass finish_normalization nicht doppelt aufgerufen wird
                self.pending_tasks = -1  # Sentinel: verhindert erneuten Aufruf
                self.run_normalization_phase()
            else:
                self.finish_normalization()

    def finish_normalization(self):
        self.btn_normalize.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.combo_mode.setEnabled(True)
        self.params_widget.setEnabled(True)
        self.drop_zone.setEnabled(True)
        
        # Logging erstellen wenn erfolgreich
        if self.success_count > 0 and self.current_target_dir:
            self.create_log_file()

        msg = f"Fertig!\nErfolgreich: {self.success_count}"
        if self.error_count > 0:
            msg += f"\nFehler: {self.error_count}"
            if self.ffmpeg_error_occurred:
                ffmpeg_path_info = self.ffmpeg_exe_path or "(nicht gesetzt)"
                msg += ("\n\nFFmpeg-Hinweis: Mindestens ein Fehler stand im Zusammenhang mit FFmpeg/FFprobe.\n"
                        f"Aktuell konfigurierter Pfad: {ffmpeg_path_info}\n"
                        "Bitte stelle sicher, dass:\n"
                        "  • der Pfad zur ffmpeg.exe korrekt angegeben ist,\n"
                        "  • ffmpeg.exe im selben Ordner wie ffprobe.exe liegt,\n"
                        "  • die Dateien nicht durch Antivirus blockiert werden.")
        
        QMessageBox.information(self, "Abgeschlossen", msg)

    def create_log_file(self):
        try:
            now = QDateTime.currentDateTime()
            timestamp = now.toString("yyyy-MM-dd_HH-mm")
            folder_name = self.current_source_folder_name or "Audio-Files"
            log_filename = f"Audio-Normalizer-Log-{timestamp}-{folder_name}.txt"
            log_path = os.path.join(self.current_target_dir, log_filename)
            
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("Audio Normalizer Log\n")
                f.write("====================\n\n")
                f.write(f"Datum/Zeit: {now.toString('dd.MM.yyyy HH:mm:ss')}\n")
                f.write(f"Modus: {self.current_params['mode']}\n")
                
                mode = self.current_params['mode']
                if mode == "Peak-Normalizing":
                    f.write(f"Ziel Peak: {self.current_params['target_peak']} dB\n")
                elif mode == "Loudness-Normalizing":
                    f.write(f"Ziel Loudness: {self.current_params['target_lufs']} LUFS\n")
                    f.write(f"Max True Peak: {self.current_params['target_tp']} dB\n")
                elif mode == "Hybrid-Normalizing":
                    f.write(f"Ziel Peak: {self.current_params['target_peak']} dB\n")
                    f.write(f"Max True Peak: {self.current_params['target_tp']} dB\n")
                    f.write(f"Max. Abweichung: {self.current_params['target_dev']} dB\n")
                    ref_lufs = self.current_params.get('ref_lufs', 0.0)
                    f.write(f"Verwendete Referenz LUFS: {ref_lufs:.2f} LUFS\n")
                    if self.current_params.get('ref_lufs_override') is not None:
                        f.write(f"(Manuelle Referenz: {self.current_params['ref_lufs_override']} LUFS)\n")
                
                f.write("\nStatistik:\n")
                f.write(f"Erfolgreich verarbeitet: {self.success_count}\n")
                f.write(f"Fehler: {self.error_count}\n")
        except Exception as e:
            print(f"Fehler beim Erstellen der Log-Datei: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NormalizerApp()
    window.show()
    sys.exit(app.exec())
