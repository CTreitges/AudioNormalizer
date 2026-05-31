"""Hauptfenster des Audio Normalizers (dünne Qt-Schicht über dem Kern-Paket)."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QMainWindow, QMenu, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from .. import __app_name__, ffmpeg_locator
from .. import batch as _batch
from .. import logwriter
from ..ffmpeg_locator import FFmpegTools
from ..models import (
    DEFAULT_TARGET_DEV, DEFAULT_TARGET_LUFS, DEFAULT_TARGET_PEAK,
    DEFAULT_TARGET_TP, LOSSLESS_EXTS, LOSSY_EXTS, Mode, NormalizeParams,
    REF_LUFS_AUTO_SENTINEL, SUPPORTED_EXTS,
)
from .widgets import CustomDoubleSpinBox, CustomLineEdit, DropZone
from .worker import NormalizeWorker

_STYLESHEET = """
QMainWindow { background-color: #f5f6f7; }
QWidget { font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; }
QPushButton {
    background-color: #0078d4; color: white; border: none;
    padding: 10px 20px; border-radius: 5px; font-weight: bold;
}
QPushButton:hover { background-color: #005a9e; }
QPushButton:pressed { background-color: #004578; }
QPushButton:disabled { background-color: #c8c8c8; color: #a1a1a1; }
QLineEdit, QDoubleSpinBox {
    padding: 6px; border: 1px solid #ccc; border-radius: 4px;
    background-color: white; color: #333;
}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 20px; background-color: #f8f9fa; border-left: 1px solid #ccc;
}
QLabel { color: #333; }
QListWidget {
    border: 1px solid #ddd; border-radius: 5px; background-color: white;
    color: #333; outline: none; min-height: 150px;
}
QListWidget::item { padding: 8px; border-bottom: 1px solid #eee; }
QListWidget::item:selected { background-color: #e1f0ff; color: #0078d4; }
QProgressBar {
    border: 1px solid #ddd; border-radius: 5px; text-align: center; height: 20px;
}
QProgressBar::chunk { background-color: #0078d4; border-radius: 4px; }
QComboBox {
    padding: 8px; border: 1px solid #ccc; border-radius: 4px;
    background-color: white; color: #333;
}
QComboBox:hover { border-color: #0078d4; }
QComboBox QAbstractItemView {
    background-color: white; color: #333;
    selection-background-color: #e1f0ff; selection-color: #0078d4;
}
QGroupBox {
    font-weight: bold; border: 1px solid #bbb; border-radius: 8px;
    margin-top: 15px; padding-top: 20px; color: #555;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 5px; left: 10px;
}
"""

# Dateifilter für Öffnen-Dialoge.
_OPEN_FILTER = "Audio Files (" + " ".join(f"*{e}" for e in SUPPORTED_EXTS) + ")"


class NormalizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(__app_name__)
        self.setMinimumSize(700, 720)

        icon_path = self._resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.settings = QSettings("ChrisSoftware", "AudioNormalizer")

        self.all_files: List[str] = []
        self.tools: Optional[FFmpegTools] = None
        self.worker: Optional[NormalizeWorker] = None
        self.current_source_folder_name = ""
        self.current_target_dir = ""
        self.current_output_mapping: Dict[str, str] = {}
        self.current_params: Optional[NormalizeParams] = None

        self.setStyleSheet(_STYLESHEET)
        self._build_ui()
        self._relocate_ffmpeg()

    # ------------------------------------------------------------------ #
    # UI-Aufbau
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(10)

        header = QLabel(__app_name__)
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #333;")
        layout.addWidget(header)

        # --- FFmpeg ---
        ff_label = QLabel("FFmpeg Pfad (optional – wird automatisch erkannt):")
        ff_label.setStyleSheet("font-weight: bold; color: #666; font-size: 12px;")
        layout.addWidget(ff_label)

        ff_row = QHBoxLayout()
        ff_row.setSpacing(5)
        self.edit_ffmpeg = CustomLineEdit()
        self.edit_ffmpeg.setFixedHeight(30)
        self.edit_ffmpeg.setPlaceholderText("Pfad zur ffmpeg(.exe) – leer = Auto")
        self.edit_ffmpeg.setText(self.settings.value("ffmpeg_path", "") or "")
        self.edit_ffmpeg.editingFinished.connect(self._on_ffmpeg_edited)
        ff_row.addWidget(self.edit_ffmpeg)
        self.btn_browse = QPushButton("Durchsuchen")
        self.btn_browse.setStyleSheet("padding: 8px 15px; font-size: 12px;")
        self.btn_browse.clicked.connect(self._browse_ffmpeg)
        ff_row.addWidget(self.btn_browse)
        layout.addLayout(ff_row)

        self.lbl_ffmpeg_status = QLabel("")
        self.lbl_ffmpeg_status.setStyleSheet("font-size: 11px; color: #777;")
        self.lbl_ffmpeg_status.setWordWrap(True)
        layout.addWidget(self.lbl_ffmpeg_status)

        # --- Einstellungen ---
        settings_group = QGroupBox("Normalisierungseinstellungen")
        settings_layout = QVBoxLayout(settings_group)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Modus:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems([m.label for m in (Mode.PEAK, Mode.LOUDNESS, Mode.HYBRID)])
        self.combo_mode.currentIndexChanged.connect(self._toggle_params)
        mode_row.addWidget(self.combo_mode)
        mode_row.addStretch()
        settings_layout.addLayout(mode_row)

        self.params_widget = QWidget()
        self.params_grid = QGridLayout(self.params_widget)
        self.params_grid.setContentsMargins(0, 10, 0, 0)
        self.params_grid.setSpacing(15)

        self.lbl_peak = QLabel("Ziel Peak (dB):")
        self.edit_peak = self._spin(-100.0, 0.0, DEFAULT_TARGET_PEAK)
        self.lbl_lufs = QLabel("Ziel Loudness (LUFS):")
        self.edit_lufs = self._spin(-100.0, 0.0, DEFAULT_TARGET_LUFS)
        self.lbl_tp = QLabel("Max True Peak (dB):")
        self.edit_tp = self._spin(-100.0, 0.0, DEFAULT_TARGET_TP)
        self.lbl_dev = QLabel("Max. Abweichung (dB):")
        self.edit_dev = self._spin(0.0, 20.0, DEFAULT_TARGET_DEV)
        self.lbl_ref = QLabel("Referenz LUFS (Optional):")
        self.edit_ref = self._spin(REF_LUFS_AUTO_SENTINEL, 0.0, REF_LUFS_AUTO_SENTINEL)
        self.edit_ref.setSpecialValueText("Auto")

        hint = "font-size: 11px; color: #777; margin-left: 2px;"
        self.hint_peak = self._hint("(-3,0)", hint)
        self.hint_lufs = self._hint("(-11,0)", hint)
        self.hint_tp = self._hint("(-3,0)", hint)
        self.hint_dev = self._hint("(3,0)", hint)
        self.hint_ref = self._hint("(Auto)", hint)

        settings_layout.addWidget(self.params_widget)
        layout.addWidget(settings_group)
        self._toggle_params()

        # --- Drop Zone + Liste ---
        self.drop_zone = DropZone(self)
        self.drop_zone.clicked.connect(self._select_files)
        self.drop_zone.filesDropped.connect(self.add_files)
        layout.addWidget(self.drop_zone)

        lst_label = QLabel("Ausgewählte Dateien:")
        lst_label.setStyleSheet("font-weight: bold; color: #666;")
        layout.addWidget(lst_label)

        self.file_list = QListWidget()
        layout.addWidget(self.file_list)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.btn_clear = QPushButton("Liste leeren")
        self.btn_clear.setStyleSheet("background-color: #f0f0f0; color: #333; border: 1px solid #ccc;")
        self.btn_clear.clicked.connect(self.clear_files)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch()
        self.btn_normalize = QPushButton("Normalisieren")
        self.btn_normalize.clicked.connect(self._on_normalize_clicked)
        self.btn_normalize.setEnabled(False)
        self.btn_normalize.setMinimumWidth(250)
        btn_row.addWidget(self.btn_normalize)
        layout.addLayout(btn_row)

    def _spin(self, lo, hi, val) -> CustomDoubleSpinBox:
        sb = CustomDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(2)
        sb.setValue(val)
        sb.setFixedWidth(100)
        return sb

    def _hint(self, text, style) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    # ------------------------------------------------------------------ #
    # FFmpeg-Erkennung
    # ------------------------------------------------------------------ #
    def _resource_path(self, rel: str) -> str:
        base = getattr(sys, "_MEIPASS", os.path.abspath("."))
        return os.path.join(base, rel)

    def _relocate_ffmpeg(self):
        preferred = self.edit_ffmpeg.text().strip() or None
        self.tools = ffmpeg_locator.locate(preferred)
        if self.tools:
            probe = self.tools.ffprobe or "(ohne ffprobe – ffmpeg-Parsing)"
            self.lbl_ffmpeg_status.setText(
                f"✓ FFmpeg: {self.tools.ffmpeg}\n   FFprobe: {probe}"
            )
            self.lbl_ffmpeg_status.setStyleSheet("font-size: 11px; color: #157347;")
        else:
            self.lbl_ffmpeg_status.setText(
                "✗ FFmpeg nicht gefunden. Bitte Pfad angeben oder FFmpeg installieren."
            )
            self.lbl_ffmpeg_status.setStyleSheet("font-size: 11px; color: #b02a37;")

    def _on_ffmpeg_edited(self):
        self.settings.setValue("ffmpeg_path", self.edit_ffmpeg.text().strip())
        self._relocate_ffmpeg()

    def _browse_ffmpeg(self):
        flt = "Executables (ffmpeg.exe);;All Files (*)" if os.name == "nt" else "All Files (*)"
        path, _ = QFileDialog.getOpenFileName(self, "ffmpeg auswählen", "", flt)
        if path:
            self.edit_ffmpeg.setText(path)
            self._on_ffmpeg_edited()

    # ------------------------------------------------------------------ #
    # Parameter-Sichtbarkeit
    # ------------------------------------------------------------------ #
    def _toggle_params(self):
        mode = Mode.from_label(self.combo_mode.currentText())
        groups = [
            (self.lbl_peak, self.edit_peak, self.hint_peak),
            (self.lbl_lufs, self.edit_lufs, self.hint_lufs),
            (self.lbl_tp, self.edit_tp, self.hint_tp),
            (self.lbl_dev, self.edit_dev, self.hint_dev),
            (self.lbl_ref, self.edit_ref, self.hint_ref),
        ]
        for lbl, edit, h in groups:
            for w in (lbl, edit, h):
                w.hide()
                self.params_grid.removeWidget(w)
        for i in range(7):
            self.params_grid.setColumnStretch(i, 0)

        def place(items, row_specs):
            for (lbl, edit, h), (r, c) in zip(items, row_specs):
                self.params_grid.addWidget(lbl, r, c, Qt.AlignmentFlag.AlignLeft)
                self.params_grid.addWidget(edit, r, c + 1, Qt.AlignmentFlag.AlignLeft)
                self.params_grid.addWidget(h, r, c + 2, Qt.AlignmentFlag.AlignLeft)
                for w in (lbl, edit, h):
                    w.show()

        if mode is Mode.PEAK:
            place([(self.lbl_peak, self.edit_peak, self.hint_peak)], [(0, 0)])
            self.params_grid.setColumnStretch(3, 1)
        elif mode is Mode.LOUDNESS:
            place([(self.lbl_lufs, self.edit_lufs, self.hint_lufs),
                   (self.lbl_tp, self.edit_tp, self.hint_tp)], [(0, 0), (1, 0)])
            self.params_grid.setColumnStretch(3, 1)
        else:  # Hybrid
            place([(self.lbl_peak, self.edit_peak, self.hint_peak),
                   (self.lbl_tp, self.edit_tp, self.hint_tp),
                   (self.lbl_dev, self.edit_dev, self.hint_dev),
                   (self.lbl_ref, self.edit_ref, self.hint_ref)],
                  [(0, 0), (0, 3), (1, 0), (1, 3)])
            self.params_grid.setColumnStretch(6, 1)

    # ------------------------------------------------------------------ #
    # Datei-Auswahl
    # ------------------------------------------------------------------ #
    def _select_files(self):
        menu = QMenu(self)
        a_files = menu.addAction("Dateien auswählen")
        a_folder = menu.addAction("Ordner auswählen")
        action = menu.exec(self.drop_zone.mapToGlobal(self.drop_zone.rect().center()))
        if action == a_files:
            files, _ = QFileDialog.getOpenFileNames(self, "Audio-Dateien auswählen", "", _OPEN_FILTER)
            if files:
                self.add_files(files)
        elif action == a_folder:
            folder = QFileDialog.getExistingDirectory(self, "Ordner auswählen")
            if folder:
                self.current_source_folder_name = os.path.basename(folder)
                self.add_files(_batch.collect_audio_files([folder]))

    def add_files(self, files: List[str]):
        if files and not self.current_source_folder_name:
            self.current_source_folder_name = os.path.basename(os.path.dirname(files[0]))
        for f in files:
            if f not in self.all_files:
                self.all_files.append(f)
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

    # ------------------------------------------------------------------ #
    # Normalisierung
    # ------------------------------------------------------------------ #
    def _gather_params(self) -> Optional[NormalizeParams]:
        mode = Mode.from_label(self.combo_mode.currentText())
        ref_val = self.edit_ref.value()
        return NormalizeParams(
            mode=mode,
            target_peak=self.edit_peak.value(),
            target_lufs=self.edit_lufs.value(),
            target_tp=self.edit_tp.value(),
            target_dev=self.edit_dev.value(),
            ref_lufs_override=ref_val if ref_val > REF_LUFS_AUTO_SENTINEL else None,
        )

    def _on_normalize_clicked(self):
        # Während eines Laufs dient der Button als Abbrechen.
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.btn_normalize.setText("Breche ab…")
            self.btn_normalize.setEnabled(False)
            return

        if not self.all_files:
            return
        if not self.tools:
            QMessageBox.critical(self, "Fehler",
                                 "FFmpeg wurde nicht gefunden. Bitte Pfad angeben.")
            return

        mode = Mode.from_label(self.combo_mode.currentText())
        if mode is Mode.HYBRID and len(self.all_files) <= 1:
            QMessageBox.warning(self, "Modus nicht verfügbar",
                                "Der Hybrid-Modus erfordert mindestens zwei Tracks.\n"
                                "Bei einem einzelnen Track Peak- oder Loudness-Modus wählen.")
            return

        params = self._gather_params()

        # Output-Mapping bestimmen.
        if len(self.all_files) == 1:
            src = self.all_files[0]
            ext = os.path.splitext(src)[1]
            target, _ = QFileDialog.getSaveFileName(
                self, "Speichern unter", src, f"Audio Files (*{ext})")
            if not target:
                return
            mapping = {src: target}
            self.current_target_dir = os.path.dirname(target)
        else:
            target_dir = QFileDialog.getExistingDirectory(self, "Zielordner wählen")
            if not target_dir:
                return
            self.current_target_dir = target_dir
            mapping = _batch.build_output_mapping(self.all_files, target_dir)

        self.current_output_mapping = mapping
        self.current_params = params

        self._set_running(True)
        self.worker = NormalizeWorker(self.all_files, mapping, params, self.tools)
        self.worker.phase.connect(self._on_phase)
        self.worker.progress.connect(self._on_progress)
        self.worker.error.connect(self._on_worker_error)
        self.worker.done.connect(self._on_done)
        self._error_dialogs = 0
        self.worker.start()

    def _set_running(self, running: bool):
        self.btn_clear.setEnabled(not running)
        self.combo_mode.setEnabled(not running)
        self.params_widget.setEnabled(not running)
        self.drop_zone.setEnabled(not running)
        self.edit_ffmpeg.setEnabled(not running)
        self.btn_browse.setEnabled(not running)
        self.progress_bar.setVisible(running)
        if running:
            self.btn_normalize.setText("Abbrechen")
            self.btn_normalize.setEnabled(True)
        else:
            self.btn_normalize.setText("Normalisieren")
            self.btn_normalize.setEnabled(bool(self.all_files))

    def _on_phase(self, name: str, total: int):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"{name}: %p%")

    def _on_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)

    def _on_worker_error(self, msg: str):
        print(f"[Fehler] {msg}")
        if getattr(self, "_error_dialogs", 0) < 3:
            self._error_dialogs += 1
            short = msg if len(msg) <= 600 else msg[:600] + "\n…(gekürzt)"
            QMessageBox.warning(self, f"Fehler ({self._error_dialogs})", short)

    def _on_done(self, result: _batch.BatchResult):
        self._set_running(False)
        if result.success_count > 0 and self.current_target_dir and self.current_params:
            logwriter.write_log_file(
                self.current_target_dir, self.current_source_folder_name,
                self.current_params, result.success_count, result.error_count,
                datetime.now(),
            )

        if result.cancelled:
            msg = f"Abgebrochen.\nErfolgreich vor Abbruch: {result.success_count}"
        else:
            msg = f"Fertig!\nErfolgreich: {result.success_count}"
        if result.error_count > 0:
            msg += f"\nFehler: {result.error_count}"
            if result.ffmpeg_error:
                ff = self.tools.ffmpeg if self.tools else "(nicht gesetzt)"
                msg += ("\n\nFFmpeg-Hinweis: Mindestens ein Fehler hing mit FFmpeg/FFprobe "
                        f"zusammen.\nAktueller Pfad: {ff}")
        QMessageBox.information(self, "Abgeschlossen", msg)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(8000)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = NormalizerApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
