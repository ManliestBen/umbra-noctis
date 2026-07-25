"""Workflow pages 1–2: Library (open/import) and Grade (inspect/cull)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.image import AstroImage
from ..grade.metrics import grade_session
from ..ingest.session import discover_sessions
from ..library.catalog import Library
from ..recipes.auto import find_matching_darks
from .canvas import ImageCanvas
from .state import AppState
from .workers import FnWorker


def _header(title: str, hint: str) -> QVBoxLayout:
    lay = QVBoxLayout()
    t = QLabel(title)
    t.setObjectName("pageTitle")
    h = QLabel(hint)
    h.setObjectName("pageHint")
    h.setWordWrap(True)
    lay.addWidget(t)
    lay.addWidget(h)
    return lay


class LibraryPage(QWidget):
    """Step 1 — open a folder of Dwarf 3 data and pick a session."""

    session_chosen = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.sessions = []
        self.library = Library()

        lay = QVBoxLayout(self)
        lay.addLayout(_header(
            "1 · Library",
            "Open the folder you copied off your Dwarf 3 (or any folder of FITS "
            "sessions). Every capture session found is listed below — "
            "double-click one to start processing it. Dark sessions are matched "
            "to lights automatically."))

        row = QHBoxLayout()
        self.open_btn = QPushButton("Open folder…")
        self.open_btn.setObjectName("primary")
        self.open_btn.clicked.connect(self.open_folder)
        self.demo_btn = QPushButton("No data yet? Create a practice session")
        self.demo_btn.clicked.connect(self.make_demo)
        row.addWidget(self.open_btn)
        row.addWidget(self.demo_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Target", "Type", "Frames", "Exp (s)", "Gain", "Integration", "Folder"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._choose)
        lay.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setObjectName("pageHint")
        lay.addWidget(self.status)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Dwarf 3 data folder")
        if folder:
            self.load_folder(folder)

    def make_demo(self):
        folder = QFileDialog.getExistingDirectory(self, "Where should the practice data go?")
        if not folder:
            return
        from ..synth import write_demo_session
        write_demo_session(Path(folder) / "umbra-demo")
        self.load_folder(str(Path(folder) / "umbra-demo"))

    def load_folder(self, folder: str):
        try:
            self.sessions = discover_sessions(folder)
        except FileNotFoundError:
            self.status.setText(f"Folder not found: {folder}")
            return
        self.table.setRowCount(0)
        for s in self.sessions:
            self.library.import_session(s)
            r = self.table.rowCount()
            self.table.insertRow(r)
            mins, secs = divmod(int(s.integration_s), 60)
            for col, text in enumerate([
                    s.target or "—", s.kind, str(s.frame_count),
                    f"{s.exposure_s:g}" if s.exposure_s else "?",
                    str(s.gain or "?"), f"{mins}m{secs:02d}s", s.path.name]):
                item = QTableWidgetItem(text)
                if s.kind != "light":
                    item.setForeground(Qt.gray)
                self.table.setItem(r, col, item)
        n_lights = sum(1 for s in self.sessions if s.kind == "light")
        self.status.setText(
            f"{len(self.sessions)} sessions found ({n_lights} light). "
            "All imported into your library. Double-click a light session to continue.")

    def _choose(self, index):
        s = self.sessions[index.row()]
        if s.kind != "light":
            self.status.setText("Pick a LIGHT session (darks are used automatically).")
            return
        self.state.session = s
        self.state.dark_session = find_matching_darks(s)
        self.state.qualities = []
        self.state.stacked = None
        self.state.reset_edits()
        self.session_chosen.emit()


class GradePage(QWidget):
    """Step 2 — inspect every sub, auto-flag the bad ones, veto by hand."""

    grading_done = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.worker = None

        lay = QVBoxLayout(self)
        lay.addLayout(_header(
            "2 · Grade frames",
            "Umbra scores every sub-exposure (star count, sharpness, trailing, "
            "sky brightness) and rejects clouds and trailed frames automatically. "
            "Click a row to view that frame — use ← → to blink through frames, "
            "X to reject, A to accept. Rejected frames are excluded from stacking "
            "but never deleted."))

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        self.grade_btn = QPushButton("Grade all frames")
        self.grade_btn.setObjectName("primary")
        self.grade_btn.clicked.connect(self.run_grading)
        ll.addWidget(self.grade_btn)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Frame", "Stars", "FWHM", "Trail", "Score", "Verdict"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.currentCellChanged.connect(self._show_frame)
        ll.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setObjectName("pageHint")
        ll.addWidget(self.summary)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.canvas = ImageCanvas()
        rl.addWidget(self.canvas, 1)
        nav = QHBoxLayout()
        nav_buttons = [("◀ Prev (←)", self.prev_frame), ("Next (→) ▶", self.next_frame),
                       ("Reject (X)", self.reject_current), ("Accept (A)", self.accept_current)]
        for text, slot in nav_buttons:
            b = QPushButton(text)
            b.clicked.connect(slot)
            nav.addWidget(b)
        rl.addLayout(nav)
        split.addWidget(right)
        split.setSizes([460, 640])
        lay.addWidget(split, 1)

        self.next_btn = QPushButton("Continue to stacking  →")
        self.next_btn.setObjectName("primary")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self.grading_done.emit)
        lay.addWidget(self.next_btn, 0, Qt.AlignRight)

    # ------------------------------------------------------------- actions
    def on_enter(self):
        if self.state.session and not self.state.qualities:
            self.table.setRowCount(0)
            self.summary.setText(
                f"Session: {self.state.session.summary()}  —  press “Grade all frames”.")

    def run_grading(self):
        if not self.state.session:
            return
        self.grade_btn.setEnabled(False)
        self.grade_btn.setText("Grading…")
        self.worker = FnWorker(grade_session, self.state.session.lights,
                               wants_log=False)
        self.worker.succeeded.connect(self._graded)
        self.worker.failed.connect(lambda tb: self.summary.setText("Grading failed — see log"))
        self.worker.start()

    def _graded(self, results):
        self.state.qualities = results
        self.grade_btn.setEnabled(True)
        self.grade_btn.setText("Re-grade all frames")
        self._fill_table()
        self.next_btn.setEnabled(True)
        if self.table.rowCount():
            self.table.setCurrentCell(0, 0)

    def _fill_table(self):
        self.table.setRowCount(0)
        for _i, q in enumerate(self.state.qualities):
            r = self.table.rowCount()
            self.table.insertRow(r)
            verdict = "OK" if q.accepted else "✗ " + ", ".join(q.reject_reasons or [])
            cells = [Path(q.path).name, str(q.n_stars), f"{q.fwhm:.2f}",
                     f"{q.ellipticity:.2f}", f"{q.score:.0f}", verdict]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if not q.accepted:
                    item.setForeground(Qt.red)
                self.table.setItem(r, c, item)
        n_ok = sum(1 for q in self.state.qualities if q.accepted)
        self.summary.setText(f"{n_ok}/{len(self.state.qualities)} frames accepted for stacking.")

    def _show_frame(self, row, *_):
        if 0 <= row < len(self.state.qualities):
            q = self.state.qualities[row]
            try:
                img = AstroImage.from_fits(q.path)
                self.canvas.set_image(img.data, keep_view=row > 0)
            except Exception:
                pass

    def _set_accept(self, accepted: bool):
        row = self.table.currentRow()
        if 0 <= row < len(self.state.qualities):
            q = self.state.qualities[row]
            q.accepted = accepted
            if accepted:
                q.reject_reasons = []
            elif not q.reject_reasons:
                q.reject_reasons = ["rejected by hand"]
            self._fill_table()
            self.table.setCurrentCell(row, 0)

    def reject_current(self):
        self._set_accept(False)

    def accept_current(self):
        self._set_accept(True)

    def prev_frame(self):
        self.table.setCurrentCell(max(0, self.table.currentRow() - 1), 0)

    def next_frame(self):
        self.table.setCurrentCell(
            min(self.table.rowCount() - 1, self.table.currentRow() + 1), 0)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Left:
            self.prev_frame()
        elif key == Qt.Key_Right:
            self.next_frame()
        elif key == Qt.Key_X:
            self.reject_current()
        elif key == Qt.Key_A:
            self.accept_current()
        else:
            super().keyPressEvent(event)
