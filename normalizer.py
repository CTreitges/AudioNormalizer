import sys
import os

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
                             QProgressBar, QMessageBox, QLineEdit, QMenu)
from PyQt6.QtCore import Qt, QMimeData, pyqtSignal, QSettings
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent, QFont
from pydub import AudioSegment, effects

class DropZone(QLabel):
    clicked = pyqtSignal()
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("<b>Dateien oder Ordner hierher ziehen</b><br><span style='color: #666; font-size: 13px;'>oder klicken zum Durchsuchen</span>")
        self.setMinimumHeight(120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 5px;
                background-color: white;
                outline: none;
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
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header
        header_label = QLabel("Audio Normalizer")
        header_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #333; margin-bottom: 5px;")
        layout.addWidget(header_label)

        # FFmpeg selection (collapsed style or just cleaner)
        ffmpeg_layout = QVBoxLayout()
        ffmpeg_label = QLabel("FFmpeg Konfiguration (benötigt für FLAC):")
        ffmpeg_label.setStyleSheet("font-weight: bold; color: #666;")
        ffmpeg_layout.addWidget(ffmpeg_label)
        
        ffmpeg_input_layout = QHBoxLayout()
        self.edit_ffmpeg = QLineEdit()
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

    def start_normalization(self):
        if not self.all_files:
            return

        if audioop is None:
            QMessageBox.critical(self, "Fehler", "Das erforderliche Modul 'audioop' fehlt.\n"
                                               "Bitte stellen Sie sicher, dass 'audioop-lts' installiert ist.")
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

        self.progress_bar.setMaximum(len(self.all_files))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.btn_normalize.setEnabled(False)
        self.btn_clear.setEnabled(False)

        success_count = 0
        error_count = 0
        ffmpeg_error = False

        for i, file_path in enumerate(self.all_files):
            try:
                # Update UI
                QApplication.processEvents()
                
                # Load audio
                ext = os.path.splitext(file_path)[1][1:].lower()
                audio = AudioSegment.from_file(file_path, format=ext)
                
                # Normalize
                normalized_audio = effects.normalize(audio)
                
                # Export
                output_path = output_mapping[file_path]
                out_ext = os.path.splitext(output_path)[1][1:].lower()
                
                # Sicherstellen, dass das Zielverzeichnis existiert (falls manuell eingegeben)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                
                normalized_audio.export(output_path, format=out_ext)
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
                msg += "\n\nHinweis: FLAC-Dateien benötigen 'ffmpeg'. Bitte stelle sicher, dass der Pfad zur ffmpeg.exe oben korrekt angegeben ist oder ffmpeg im System-PATH verfügbar ist."
        
        QMessageBox.information(self, "Abgeschlossen", msg)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NormalizerApp()
    window.show()
    sys.exit(app.exec())
