"""GUI smoke tests — run offscreen; verify pages build, navigate, and the
canvas/param generators work with real state. Skipped if PySide6 is absent."""

import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from umbra_noctis.core.image import AstroImage  # noqa: E402
from umbra_noctis.ingest import parse_session  # noqa: E402
from umbra_noctis.synth import make_star_field, write_demo_session  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_main_window_builds_and_navigates(app, tmp_path):
    from umbra_noctis.gui.app import MainWindow
    win = MainWindow()
    assert win.stack_widget.count() == 5

    # without a session, later steps bounce back to library
    win.goto(3)
    assert win.stack_widget.currentIndex() == 0

    light_dir, dark_dir = write_demo_session(tmp_path, n_lights=4, n_darks=2)
    win.library_page.load_folder(str(tmp_path))
    assert win.library_page.table.rowCount() == 2

    win.state.session = parse_session(light_dir)
    win.goto(1)
    assert win.stack_widget.currentIndex() == 1
    win.close()


def test_canvas_displays_images(app):
    from umbra_noctis.gui.canvas import ImageCanvas, ndarray_to_qimage
    canvas = ImageCanvas()
    mono = make_star_field(120, 160)
    canvas.set_image(mono)
    rgb = np.stack([mono] * 3, axis=-1)
    canvas.set_image(rgb)
    qimg = ndarray_to_qimage(rgb)
    assert qimg.width() == 160 and qimg.height() == 120
    canvas.set_autostretch(False)
    canvas.set_image(mono)


def test_process_page_param_generation(app):
    from PySide6.QtCore import Qt

    from umbra_noctis.gui.pages_process import ProcessPage
    from umbra_noctis.gui.state import AppState

    state = AppState()
    base = make_star_field(100, 140)
    state.stacked = AstroImage(data=np.stack([base] * 3, axis=-1))
    state.reset_edits()
    page = ProcessPage(state)
    page.on_enter()

    # select every registered tool: parameter forms must build without error
    tree = page.tree
    n_tools = 0
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        for j in range(top.childCount()):
            tree.setCurrentItem(top.child(j))
            assert top.child(j).data(0, Qt.UserRole) is not None
            n_tools += 1
    assert n_tools >= 20

    # apply an op through the page machinery (synchronously via internals)
    from umbra_noctis.core.ops import apply_op
    state.push_edit(apply_op(state.current, "autostretch"))
    page._refresh_history()
    assert page.history.count() >= 1
    page.undo()


def test_grade_and_stack_pages(app, tmp_path):
    from umbra_noctis.grade import grade_session
    from umbra_noctis.gui.pages_data import GradePage
    from umbra_noctis.gui.pages_process import StackPage
    from umbra_noctis.gui.state import AppState

    light_dir, dark_dir = write_demo_session(tmp_path, n_lights=4, n_darks=2)
    state = AppState()
    state.session = parse_session(light_dir)
    state.dark_session = parse_session(dark_dir)

    grade = GradePage(state)
    grade.on_enter()
    state.qualities = grade_session(state.session.lights)
    grade._graded(state.qualities)
    assert grade.table.rowCount() == 4
    grade.table.setCurrentCell(0, 0)
    grade.reject_current()
    assert not state.qualities[0].accepted
    grade.accept_current()
    assert state.qualities[0].accepted

    stack = StackPage(state)
    stack.on_enter()
    assert "auto-matched" in stack.dark_label.text()
