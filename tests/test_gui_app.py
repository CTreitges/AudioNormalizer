"""GUI-Tests gegen die echte Qt-Klasse (offscreen, ohne Benutzerinteraktion).

Testet die Verdrahtung, die in der Vergangenheit still gefehlt hat: dass die
Ordner-Auswahl die Herkunft mitfuehrt und dass jedes fertige File in der Liste
eine Rueckmeldung bekommt.
"""
import os

import pytest

# Kein Fenster oeffnen - laeuft so auch in der CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Das Untermodul pruefen, nicht nur das Paket: "import PyQt6" gelingt auch auf
# einem nackten Runner, erst QtWidgets braucht die Qt-Systembibliotheken
# (libEGL/libGL). Ein Fehlschlag auf Modulebene waere ein Collection-Error und
# damit ein roter Build statt eines sauberen Skips.
pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication            # noqa: E402

from audionormalizer.gui.app import NormalizerApp   # noqa: E402
from audionormalizer.models import FileResult       # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    try:
        app = QApplication.instance() or QApplication([])
    except Exception as exc:                        # keine nutzbare Qt-Plattform
        pytest.skip(f"Qt-Plattform nicht verfuegbar: {exc}")
    yield app


@pytest.fixture
def window(qapp, monkeypatch):
    # FFmpeg-Suche im Test nicht ausfuehren (langsam, umgebungsabhaengig).
    monkeypatch.setattr("audionormalizer.gui.app.ffmpeg_locator.locate",
                        lambda *_a, **_k: None)
    win = NormalizerApp()
    # Ohne show() melden alle Kind-Widgets isVisible()==False und die
    # Geometrie ist unbestimmt - Layout-Regressionen waeren nicht pruefbar.
    win.show()
    qapp.processEvents()
    yield win
    win.close()


def _make_tree(tmp_path):
    album = tmp_path / "Album A" / "Disc 2"
    album.mkdir(parents=True)
    (tmp_path / "Album A" / "a.mp3").write_bytes(b"x")
    (album / "b.mp3").write_bytes(b"x")
    return tmp_path


def test_add_paths_keeps_folder_provenance(window, tmp_path):
    """Ordner-Auswahl merkt sich die Basis, sonst kollabiert die Zielstruktur."""
    root = _make_tree(tmp_path)
    window.add_paths([str(root)])
    assert len(window.all_files) == 2
    assert set(window.file_bases.values()) == {str(root)}


def test_list_shows_path_relative_to_selected_folder(window, tmp_path):
    root = _make_tree(tmp_path)
    window.add_paths([str(root)])
    shown = sorted(window.file_list.item(i).text()
                   for i in range(window.file_list.count()))
    assert shown == [os.path.join("Album A", "Disc 2", "b.mp3"),
                     os.path.join("Album A", "a.mp3")]


def test_add_paths_reports_empty_folder(window, tmp_path, monkeypatch):
    """Ordner ohne Audio darf nicht kommentarlos nichts tun."""
    shown = {}
    monkeypatch.setattr("audionormalizer.gui.app.QMessageBox.information",
                        lambda *a, **k: shown.setdefault("called", True))
    (tmp_path / "notizen.txt").write_bytes(b"x")
    window.add_paths([str(tmp_path)])
    assert shown.get("called")
    assert window.all_files == []


def test_file_done_marks_row_success(window, tmp_path):
    root = _make_tree(tmp_path)
    window.add_paths([str(root)])
    target = window.all_files[0]
    window._on_file_done(FileResult(input_path=target, output_path="out",
                                    mode_used="Loudness", applied_gain_db=-3.25,
                                    success=True))
    text = window.file_list.item(window.list_rows[target]).text()
    assert text.startswith("✓")
    assert "Loudness" in text and "-3.25 dB" in text


def test_file_done_marks_row_failure(window, tmp_path):
    root = _make_tree(tmp_path)
    window.add_paths([str(root)])
    target = window.all_files[0]
    window._on_file_done(FileResult(input_path=target, success=False, error="kaputt"))
    assert window.file_list.item(window.list_rows[target]).text().startswith("✗")


def test_collision_check_blocks_run(window, tmp_path, monkeypatch):
    """Zwei Quellen auf einem Ziel muss den Start verhindern."""
    seen = {}
    monkeypatch.setattr("audionormalizer.gui.app.QMessageBox.critical",
                        lambda *a, **k: seen.setdefault("called", True))
    assert window._check_collisions({"a.wav": "o/x.mp3", "b.flac": "o/x.mp3"},
                                    "Zielpfad") is False
    assert seen.get("called")
    assert window._check_collisions({"a.wav": "o/a.mp3"}, "Zielpfad") is True


@pytest.mark.parametrize("index,name", [(0, "Peak"), (1, "Loudness"), (2, "Hybrid")])
def test_no_hardcoded_minimum_height_below_layout_need(qapp, window, index, name):
    """Regression: eine fest verdrahtete Mindesthoehe (720 px) lag unter dem
    echten Bedarf des Layouts. Das Fenster liess sich dadurch kleiner ziehen,
    als sein Inhalt braucht - Eingabefelder wurden auf 0 px gequetscht und die
    Drop-Zone legte sich ueber die Ueberschreiben-Checkbox.

    Geprueft wird die Invariante, nicht die gerenderte Geometrie: eine gesetzte
    Mindesthoehe darf den Layout-Bedarf nie unterschreiten. Ueberlaesst man Qt
    die Mindesthoehe, sind beide Werte per Definition gleich. Ein Test ueber
    echte Pixelhoehen waere hier wertlos - die haengen an den Schriftmetriken
    der Plattform (offscreen ohne Fonts rechnet deutlich kompakter).
    """
    window.combo_mode.setCurrentIndex(index)
    qapp.processEvents()
    assert window.minimumHeight() <= window.minimumSizeHint().height(), (
        f"{name}: feste Mindesthoehe {window.minimumHeight()} px liegt unter dem "
        f"Layout-Bedarf {window.minimumSizeHint().height()} px")


@pytest.mark.parametrize("index,name", [(0, "Peak"), (1, "Loudness"), (2, "Hybrid")])
def test_parameter_fields_visible_in_every_mode(qapp, window, index, name):
    """Jeder Modus zeigt seine Felder - und zwar mit Hoehe."""
    window.combo_mode.setCurrentIndex(index)
    qapp.processEvents()
    visible = [w for w in (window.edit_peak, window.edit_lufs, window.edit_tp,
                           window.edit_dev, window.edit_ref) if w.isVisible()]
    assert visible, f"{name}: kein Parameterfeld sichtbar"
    for w in visible:
        assert w.height() > 0, f"{name}: Eingabefeld auf 0 px gequetscht"


def test_clear_files_resets_all_state(window, tmp_path):
    window.add_paths([str(_make_tree(tmp_path))])
    window.clear_files()
    assert window.all_files == [] and window.file_bases == {} and window.list_rows == {}
    assert window.file_list.count() == 0
