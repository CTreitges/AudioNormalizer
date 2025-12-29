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
                             QDoubleSpinBox)
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
        
        mode = params["mode"]
        target_peak = params["target_peak"]
        target_lufs = params["target_lufs"]
        target_tp = params["target_tp"]
        target_dev = params["target_dev"]
        ref_lufs = params["ref_lufs"]

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
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

        if actual_mode == "Peak":
            # Peak messen (muss hier passieren da Multithreaded)
            max_vol = self.get_peak_volume(ffmpeg_exe)
            if max_vol is not None:
                gain = target_peak - max_vol
                cmd = [
                    ffmpeg_exe, "-y", "-i", self.file_path,
                    "-af", f"volume={gain}dB",
                    "-map_metadata", "0",
                    "-metadata", f"track={track_num}",
                    output_path
                ]
            else:
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
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, encoding='utf-8')
            output = result.stderr
            match = re.search(r"max_volume: ([\-\d\.]+) dB", output)
            if match:
                return float(match.group(1))
        except Exception:
            pass
        return None

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

    def update_ffmpeg_config(self, path):
        if not path:
            return
            
        ffmpeg_dir = ""
        path = os.path.normpath(path)
        if os.path.isfile(path):
            self.ffmpeg_exe_path = path
            ffmpeg_dir = os.path.dirname(path)
        elif os.path.isdir(path):
            for exe in ["ffmpeg.exe", "ffmpeg"]:
                potential_exe = os.path.join(path, exe)
                if os.path.isfile(potential_exe):
                    self.ffmpeg_exe_path = potential_exe
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
                self.file_list.addItem(os.path.basename(f))
        
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
        if len(self.all_files) == 1:
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
            for f in self.all_files:
                self.current_output_mapping[f] = os.path.join(target_dir, os.path.basename(f))

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
            self.current_params["ref_lufs"] = self.current_params["ref_lufs_override"] or self.current_params["target_lufs"]

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
                                    stats=self.analysis_results.get(file_path))
                
                worker.signals.finished.connect(self.on_normalization_finished)
                worker.signals.error.connect(self.on_task_error)
                self.thread_pool.start(worker)
            except Exception as e:
                self.on_task_error(str(e))

    def on_normalization_finished(self, result):
        self.success_count += 1
        self.pending_tasks -= 1
        self.progress_bar.setValue(self.progress_bar.maximum() - self.pending_tasks)
        
        if self.pending_tasks == 0:
            self.finish_normalization()

    def on_task_error(self, error_msg):
        print(error_msg)
        if "ffmpeg" in error_msg.lower():
            self.ffmpeg_error_occurred = True
        self.error_count += 1
        self.pending_tasks -= 1
        self.progress_bar.setValue(self.progress_bar.maximum() - self.pending_tasks)
        
        if self.pending_tasks == 0:
            # Falls wir in der Analyse-Phase waren, müssen wir trotzdem weitermachen oder abbrechen
            # Wenn Analyse-Fehler, wird normalization_phase trotzdem aufgerufen wenn pending_tasks == 0
            if self.progress_bar.format().startswith("Analysiere"):
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
                msg += "\n\nHinweis: Loudness/Hybrid-Normalisierung und FLAC-Dateien benötigen 'ffmpeg'. Bitte stelle sicher, dass der Pfad zur ffmpeg.exe oben korrekt angegeben ist."
        
        QMessageBox.information(self, "Abgeschlossen", msg)

    def create_log_file(self):
        try:
            now = QDateTime.currentDateTime()
            timestamp = now.toString("dd-MM-HH-mm")
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
