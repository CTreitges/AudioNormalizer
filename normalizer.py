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
                             QProgressBar, QMessageBox, QLineEdit, QMenu, QComboBox, QGridLayout, QGroupBox)
from PyQt6.QtCore import Qt, QMimeData, pyqtSignal, QSettings
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent, QFont, QDoubleValidator, QIcon
from pydub import AudioSegment, effects

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

class NormalizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Normalizer")
        self.setMinimumSize(700, 600)
        
        # Icon setzen
        icon_path = self.get_resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # Einstellungen laden
        self.settings = QSettings("ChrisSoftware", "AudioNormalizer")
        
        self.all_files = []

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
            QLineEdit {
                padding: 8px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
                color: #333;
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
                border: 1px solid #ddd;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 20px;
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
        self.edit_ffmpeg = QLineEdit()
        self.edit_ffmpeg.setFixedHeight(30)
        self.edit_ffmpeg.setPlaceholderText("Pfad zur ffmpeg.exe...")
        # Gespeicherten Pfad laden
        saved_path = self.settings.value("ffmpeg_path", "")
        self.edit_ffmpeg.setText(saved_path)
        self.update_ffmpeg_config(saved_path)
        self.edit_ffmpeg.textChanged.connect(self.save_ffmpeg_path)
        
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
        self.edit_peak = QLineEdit("-3.0")
        self.edit_peak.setFixedWidth(80)
        self.edit_peak.setValidator(QDoubleValidator(-100.0, 0.0, 2))
        
        # Loudness Parameter
        self.lbl_lufs = QLabel("Ziel Loudness (LUFS):")
        self.edit_lufs = QLineEdit("-11.0")
        self.edit_lufs.setFixedWidth(80)
        self.edit_lufs.setValidator(QDoubleValidator(-100.0, 0.0, 2))
        
        self.lbl_tp = QLabel("Max True Peak (dB):")
        self.edit_tp = QLineEdit("-1.0")
        self.edit_tp.setFixedWidth(80)
        self.edit_tp.setValidator(QDoubleValidator(-100.0, 0.0, 2))
        
        # Hybrid Parameter
        self.lbl_dev = QLabel("Max. Abweichung (dB):")
        self.edit_dev = QLineEdit("3.0")
        self.edit_dev.setFixedWidth(80)
        self.edit_dev.setValidator(QDoubleValidator(0.0, 20.0, 2))

        self.lbl_ref_lufs = QLabel("Referenz LUFS (Optional):")
        self.edit_ref_lufs = QLineEdit("")
        self.edit_ref_lufs.setFixedWidth(80)
        self.edit_ref_lufs.setPlaceholderText("Auto")
        self.edit_ref_lufs.setValidator(QDoubleValidator(-100.0, 0.0, 2))

        settings_layout.addWidget(self.params_widget)
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
            (self.lbl_peak, self.edit_peak),
            (self.lbl_lufs, self.edit_lufs),
            (self.lbl_tp, self.edit_tp),
            (self.lbl_dev, self.edit_dev),
            (self.lbl_ref_lufs, self.edit_ref_lufs)
        ]
        
        for lbl, edit in widgets:
            lbl.hide()
            edit.hide()
            self.params_grid.removeWidget(lbl)
            self.params_grid.removeWidget(edit)
        
        if mode == "Peak-Normalizing":
            self.params_grid.addWidget(self.lbl_peak, 0, 0, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_peak, 0, 1, Qt.AlignmentFlag.AlignLeft)
            self.lbl_peak.show()
            self.edit_peak.show()
        elif mode == "Loudness-Normalizing":
            self.params_grid.addWidget(self.lbl_lufs, 0, 0, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_lufs, 0, 1, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.lbl_tp, 1, 0, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_tp, 1, 1, Qt.AlignmentFlag.AlignLeft)
            self.lbl_lufs.show()
            self.edit_lufs.show()
            self.lbl_tp.show()
            self.edit_tp.show()
        elif mode == "Hybrid-Normalizing":
            # 2x2 Layout: (Row, Col)
            # Spalte 0/1: Links, Spalte 2/3: Rechts
            self.params_grid.addWidget(self.lbl_peak, 0, 0, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_peak, 0, 1, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.lbl_tp, 0, 2, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_tp, 0, 3, Qt.AlignmentFlag.AlignLeft)
            
            self.params_grid.addWidget(self.lbl_dev, 1, 0, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_dev, 1, 1, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.lbl_ref_lufs, 1, 2, Qt.AlignmentFlag.AlignLeft)
            self.params_grid.addWidget(self.edit_ref_lufs, 1, 3, Qt.AlignmentFlag.AlignLeft)
            
            self.lbl_peak.show()
            self.edit_peak.show()
            self.lbl_tp.show()
            self.edit_tp.show()
            self.lbl_dev.show()
            self.edit_dev.show()
            self.lbl_ref_lufs.show()
            self.edit_ref_lufs.show()

    def update_ffmpeg_config(self, path):
        if not path:
            return
            
        ffmpeg_dir = ""
        path = os.path.normpath(path)
        if os.path.isfile(path):
            AudioSegment.converter = path
            ffmpeg_dir = os.path.dirname(path)
        elif os.path.isdir(path):
            for exe in ["ffmpeg.exe", "ffmpeg"]:
                potential_exe = os.path.join(path, exe)
                if os.path.isfile(potential_exe):
                    AudioSegment.converter = potential_exe
                    ffmpeg_dir = path
                    break
        
        if ffmpeg_dir:
            ffmpeg_dir = os.path.abspath(ffmpeg_dir)
            paths = os.environ.get("PATH", "").split(os.pathsep)
            if ffmpeg_dir not in paths:
                os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    def save_ffmpeg_path(self):
        path = self.edit_ffmpeg.text().strip()
        self.settings.setValue("ffmpeg_path", path)
        self.update_ffmpeg_config(path)

    def browse_ffmpeg(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "ffmpeg.exe auswählen", "", "Executables (ffmpeg.exe);;All Files (*)")
        if file_path:
            self.edit_ffmpeg.setText(file_path)

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
                new_files = []
                for root, dirs, files in os.walk(folder):
                    for file in files:
                        if file.lower().endswith(('.wav', '.flac')):
                            new_files.append(os.path.join(root, file))
                if new_files:
                    self.add_files(new_files)

    def add_files(self, files):
        for f in files:
            if f not in self.all_files:
                self.all_files.append(f)
                self.file_list.addItem(os.path.basename(f))
        
        if self.all_files:
            self.btn_normalize.setEnabled(True)

    def clear_files(self):
        self.all_files = []
        self.file_list.clear()
        self.btn_normalize.setEnabled(False)
        self.progress_bar.setVisible(False)

    def get_audio_stats(self, file_path):
        ffmpeg_exe = AudioSegment.converter
        if not ffmpeg_exe or not os.path.isfile(ffmpeg_exe):
            if not shutil.which("ffmpeg"):
                return None
            ffmpeg_exe = "ffmpeg"
            
        cmd = [
            ffmpeg_exe, "-i", file_path,
            "-af", "loudnorm=print_format=json",
            "-f", "null", "-"
        ]
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, encoding='utf-8')
            # FFmpeg schreibt das JSON oft in stderr bei -f null
            output = result.stderr
            match = re.search(r"\{.*\}", output, re.DOTALL)
            if match:
                stats = json.loads(match.group(0))
                return {
                    "lufs": float(stats["input_i"]),
                    "tp": float(stats["input_tp"])
                }
        except Exception as e:
            print(f"Fehler beim Messen von {file_path}: {e}")
        return None

    def get_peak_volume(self, file_path):
        ffmpeg_exe = AudioSegment.converter
        if not ffmpeg_exe or not os.path.isfile(ffmpeg_exe):
            if not shutil.which("ffmpeg"):
                return None
            ffmpeg_exe = "ffmpeg"
            
        cmd = [
            ffmpeg_exe, "-i", file_path,
            "-af", "volumedetect",
            "-vn", "-sn", "-dn",
            "-f", "null", "-"
        ]
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, encoding='utf-8')
            output = result.stderr
            match = re.search(r"max_volume: ([\-\d\.]+) dB", output)
            if match:
                return float(match.group(1))
        except Exception as e:
            print(f"Fehler beim Messen der Peak-Lautstärke von {file_path}: {e}")
        return None

    def start_normalization(self):
        if not self.all_files:
            return

        if audioop is None:
            QMessageBox.critical(self, "Fehler", "Das erforderliche Modul 'audioop' fehlt.\n"
                                               "Bitte stellen Sie sicher, dass 'audioop-lts' installiert ist.")
            return

        # Einstellungen auslesen
        mode = self.combo_mode.currentText()
        
        # Validierung für Hybrid Modus
        if mode == "Hybrid-Normalizing" and len(self.all_files) <= 1:
            QMessageBox.warning(self, "Modus nicht verfügbar", 
                                "Der Hybrid-Modus erfordert mindestens zwei Tracks.\n"
                                "Bei einem einzelnen Track wählen Sie bitte Peak- oder Loudness-Normalisierung.")
            return

        try:
            target_peak = float(self.edit_peak.text().replace(',', '.'))
            target_lufs = float(self.edit_lufs.text().replace(',', '.'))
            target_tp = float(self.edit_tp.text().replace(',', '.'))
            target_dev = float(self.edit_dev.text().replace(',', '.'))
            
            ref_lufs_val = self.edit_ref_lufs.text().strip().replace(',', '.')
            ref_lufs_override = float(ref_lufs_val) if ref_lufs_val else None
        except ValueError:
            QMessageBox.warning(self, "Eingabefehler", "Bitte gültige numerische Werte in den Einstellungen eingeben.")
            return

        # FFmpeg Prüfung
        ffmpeg_exe = AudioSegment.converter
        is_only_wav_peak = mode == "Peak-Normalizing" and all(f.lower().endswith('.wav') for f in self.all_files)
        ffmpeg_required = not is_only_wav_peak
        
        ffmpeg_missing = False
        if ffmpeg_required:
            if not ffmpeg_exe or not os.path.isfile(ffmpeg_exe):
                if not shutil.which("ffmpeg"):
                    ffmpeg_missing = True

        if ffmpeg_missing:
            msg = "FFmpeg wurde nicht gefunden. Es wird für "
            if mode == "Peak-Normalizing":
                msg += "die Verarbeitung von Nicht-WAV Dateien "
            else:
                msg += "Loudness/Hybrid Normalisierung "
            msg += "benötigt.\nBitte geben Sie den Pfad zur ffmpeg.exe oben an."
            QMessageBox.critical(self, "Fehler", msg)
            self.progress_bar.setVisible(False)
            self.btn_normalize.setEnabled(True)
            self.btn_clear.setEnabled(True)
            return

        # Ziel-Mapping erstellen (Quelldatei -> Zielpfad)
        output_mapping = {}
        
        if len(self.all_files) == 1:
            # Bei einer einzelnen Datei nach Dateiname fragen
            source_path = self.all_files[0]
            ext = os.path.splitext(source_path)[1]
            filter_str = f"Audio Files (*{ext})"
            target_path, _ = QFileDialog.getSaveFileName(self, "Speichern unter", source_path, filter_str)
            if not target_path:
                return
            output_mapping[source_path] = target_path
        else:
            # Bei mehreren Dateien nach Zielordner fragen
            target_dir = QFileDialog.getExistingDirectory(self, "Zielordner wählen (Neuer Ordner möglich)")
            if not target_dir:
                return
            for f in self.all_files:
                output_mapping[f] = os.path.join(target_dir, os.path.basename(f))

        self.progress_bar.setVisible(True)
        self.btn_normalize.setEnabled(False)
        self.btn_clear.setEnabled(False)

        # Referenz-LUFS für Hybrid ermitteln
        ref_lufs = ref_lufs_override
        if mode == "Hybrid-Normalizing" and ref_lufs is None:
            self.progress_bar.setMaximum(len(self.all_files))
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Analysiere Playlist: %p%")
            
            lufs_values = []
            for i, file_path in enumerate(self.all_files):
                QApplication.processEvents()
                stats = self.get_audio_stats(file_path)
                if stats:
                    lufs_values.append(stats["lufs"])
                self.progress_bar.setValue(i + 1)
                
            if lufs_values:
                ref_lufs = sum(lufs_values) / len(lufs_values)
            else:
                ref_lufs = target_lufs # Fallback

        self.progress_bar.setMaximum(len(self.all_files))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Verarbeite: %p%")

        success_count = 0
        error_count = 0
        ffmpeg_error = False

        for i, file_path in enumerate(self.all_files):
            try:
                # Update UI
                QApplication.processEvents()
                
                output_path = output_mapping[file_path]
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                
                actual_mode = ""
                stats = None
                
                if mode in ["Loudness-Normalizing", "Hybrid-Normalizing"]:
                    stats = self.get_audio_stats(file_path)
                    
                if mode == "Hybrid-Normalizing":
                    if stats:
                        deviation = abs(stats["lufs"] - ref_lufs)
                        if deviation >= target_dev:
                            actual_mode = "Loudness"
                        else:
                            actual_mode = "Peak"
                    else:
                        actual_mode = "Loudness" # Fallback
                elif mode == "Loudness-Normalizing":
                    actual_mode = "Loudness"
                else:
                    actual_mode = "Peak"

                track_num = "0" if actual_mode == "Peak" else "1"
                
                # Basis FFmpeg Pfad
                current_ffmpeg = ffmpeg_exe
                if not current_ffmpeg or not os.path.isfile(current_ffmpeg):
                    current_ffmpeg = "ffmpeg"

                if actual_mode == "Peak":
                    # Peak messen für Normalisierung
                    max_vol = self.get_peak_volume(file_path)
                    if max_vol is not None:
                        # Gain berechnen: target_peak - current_peak
                        gain = target_peak - max_vol
                        cmd = [
                            current_ffmpeg, "-y", "-i", file_path,
                            "-af", f"volume={gain}dB",
                            "-map_metadata", "0",
                            "-metadata", f"track={track_num}",
                            output_path
                        ]
                    else:
                        raise Exception("Konnte Peak-Lautstärke nicht ermitteln.")
                else:
                    # Loudness-Normalisierung (Linearer Gain um Dynamik zu erhalten)
                    if stats:
                        actual_target_lufs = ref_lufs if mode == "Hybrid-Normalizing" else target_lufs
                        # Bei Hybrid ist das TP-Limit das Minimum aus dem Peak-Ziel und dem TP-Limit
                        tp_limit = min(target_tp, target_peak) if mode == "Hybrid-Normalizing" else target_tp
                        
                        # Gain berechnen, um Ziel-LUFS zu erreichen
                        gain = actual_target_lufs - stats["lufs"]
                        # Sicherstellen, dass True Peak nicht überschritten wird (Linearer Gain Limit)
                        max_allowed_gain = tp_limit - stats["tp"]
                        
                        applied_gain = min(gain, max_allowed_gain)
                        
                        cmd = [
                            current_ffmpeg, "-y", "-i", file_path,
                            "-af", f"volume={applied_gain}dB",
                            "-map_metadata", "0",
                            "-metadata", f"track={track_num}",
                            output_path
                        ]
                    else:
                        # Fallback falls Messung fehlschlägt (sollte nicht passieren)
                        lra = target_dev if mode == "Hybrid-Normalizing" else 7.0
                        tp_val = min(target_tp, target_peak) if mode == "Hybrid-Normalizing" else target_tp
                        actual_target_lufs = ref_lufs if mode == "Hybrid-Normalizing" else target_lufs
                        
                        cmd = [
                            current_ffmpeg, "-y", "-i", file_path,
                            "-af", f"loudnorm=I={actual_target_lufs}:TP={tp_val}:LRA={lra}",
                            "-map_metadata", "0",
                            "-metadata", f"track={track_num}",
                            output_path
                        ]

                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
                if result.returncode != 0:
                    raise Exception(f"FFmpeg Fehler: {result.stderr}")

                success_count += 1
            except Exception as e:
                print(f"Fehler bei {file_path}: {e}")
                if "ffmpeg" in str(e).lower() or "avconv" in str(e).lower():
                    ffmpeg_error = True
                error_count += 1
            
            self.progress_bar.setValue(i + 1)

        self.btn_normalize.setEnabled(True)
        self.btn_clear.setEnabled(True)
        
        msg = f"Fertig!\nErfolgreich: {success_count}"
        if error_count > 0:
            msg += f"\nFehler: {error_count}"
            if ffmpeg_error:
                msg += "\n\nHinweis: Loudness/Hybrid-Normalisierung und FLAC-Dateien benötigen 'ffmpeg'. Bitte stelle sicher, dass der Pfad zur ffmpeg.exe oben korrekt angegeben ist."
        
        QMessageBox.information(self, "Abgeschlossen", msg)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NormalizerApp()
    window.show()
    sys.exit(app.exec())
