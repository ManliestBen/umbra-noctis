"""Workflow pages 3–5: Stack, Process, Export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..calib.masters import build_master
from ..core.ops import OPS, apply_op, ensure_ops_loaded
from ..export.summary import acquisition_caption
from ..export.writers import export_image, save_comparison
from ..library import Library, resolve_target
from ..recipes.auto import AUTO_RECIPE_STEPS
from ..recipes.recipe import Recipe
from ..stack.integrate import integrate
from .canvas import ImageCanvas
from .pages_data import _header
from .state import AppState
from .workers import FnWorker

_STAGE_LABELS = {
    "linear": "Linear (before stretch)",
    "stretch": "Stretch",
    "nonlinear": "After stretch",
    "geometry": "Geometry",
    "cosmetic": "Cosmetic / repair",
}


class StackPage(QWidget):
    """Step 3 — calibrate, register, and integrate the accepted frames."""

    stacking_done = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.worker = None

        lay = QVBoxLayout(self)
        lay.addLayout(_header(
            "3 · Stack",
            "The accepted frames are dark-calibrated, registered (rotation-aware, "
            "so alt-az sessions are fine), outlier pixels like satellite trails "
            "are rejected, and everything is combined into one deep image. "
            "Defaults are tuned for Dwarf 3 data — just press Stack."))

        opts = QGroupBox("Options")
        form = QFormLayout(opts)
        self.sigma = QDoubleSpinBox()
        self.sigma.setRange(1.0, 10.0)
        self.sigma.setValue(3.0)
        self.sigma.setToolTip("Pixel rejection threshold. Lower = more aggressive "
                              "satellite/hot-pixel removal (3.0 is right for most data).")
        self.best = QSpinBox()
        self.best.setRange(10, 100)
        self.best.setValue(90)
        self.best.setSuffix(" %")
        self.best.setToolTip("After auto-rejection, keep only this fraction of the "
                             "best frames by quality score.")
        self.drizzle = QComboBox()
        self.drizzle.addItems(["1× (off)", "1.5×", "2×"])
        self.drizzle.setToolTip("Integrate onto a finer pixel grid. Needs many "
                                "well-dithered frames; try it on 50+ sub sessions.")
        self.dark_label = QLabel("(searching…)")
        form.addRow("Rejection sigma", self.sigma)
        form.addRow("Keep best", self.best)
        form.addRow("Drizzle", self.drizzle)
        form.addRow("Master dark", self.dark_label)
        lay.addWidget(opts)

        self.stack_btn = QPushButton("Stack frames")
        self.stack_btn.setObjectName("primary")
        self.stack_btn.clicked.connect(self.run_stack)
        lay.addWidget(self.stack_btn)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        split = QSplitter(Qt.Horizontal)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Stacking log will appear here…")
        split.addWidget(self.log)
        self.canvas = ImageCanvas()
        split.addWidget(self.canvas)
        split.setSizes([380, 720])
        lay.addWidget(split, 1)

        self.next_btn = QPushButton("Continue to processing  →")
        self.next_btn.setObjectName("primary")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self.stacking_done.emit)
        lay.addWidget(self.next_btn, 0, Qt.AlignRight)

    def on_enter(self):
        s = self.state.dark_session
        self.dark_label.setText(
            f"auto-matched: {s.path.name}" if s else
            "none found — statistical hot-pixel removal will be used")

    def run_stack(self):
        if not self.state.session:
            return
        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            return
        accepted_qualities = [q for q in self.state.qualities if q.accepted] \
            if self.state.qualities else []
        accepted = [q.path for q in accepted_qualities] \
            if self.state.qualities else list(self.state.session.lights)
        if len(accepted) < 2:
            QMessageBox.warning(self, "Not enough frames",
                                "Need at least 2 accepted frames to stack.")
            return
        master_dark = None
        if self.state.dark_session:
            master_dark = build_master(self.state.dark_session.lights)
        self.stack_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.log.clear()

        drizzle = {0: 1.0, 1: 1.5, 2: 2.0}[self.drizzle.currentIndex()]
        self.worker = FnWorker(
            integrate, accepted, master_dark=master_dark,
            rejection_sigma=self.sigma.value(),
            best_fraction=self.best.value() / 100.0,
            quality_filter=False,  # user already graded by hand
            qualities=accepted_qualities or None,  # reuse the Grade page's scores
            drizzle=drizzle)
        self.worker.progressed.connect(self._progress)
        self.worker.logged.connect(self.log.appendPlainText)
        self.worker.succeeded.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _progress(self, stage, done, total):
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self.progress.setFormat(f"{stage} %v/%m")

    def _done(self, result):
        self.state.stacked = result.image
        self.state.reset_edits()
        self.stack_btn.setEnabled(True)
        self.stack_btn.setText("Re-stack")
        self.progress.setVisible(False)
        self.canvas.set_image(result.image.data)
        self.log.appendPlainText(
            f"\nDone: {result.n_used} frames stacked, "
            f"{100 * result.rejected_pixel_fraction:.2f}% of pixel samples rejected.")
        self.next_btn.setEnabled(True)

    def _failed(self, tb):
        self.stack_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.log.appendPlainText("STACKING FAILED:\n" + tb)


class ProcessPage(QWidget):
    """Step 4 — the darkroom: apply any operation, see it instantly, undo freely."""

    processing_done = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        ensure_ops_loaded()
        self.state = state
        self.worker = None
        self._param_widgets = {}
        self._before = None

        lay = QVBoxLayout(self)
        lay.addLayout(_header(
            "4 · Process",
            "Pick a tool on the left, tune its settings, press Apply. The preview "
            "always shows the current state (with a display autostretch while the "
            "data is linear). Recommended order: work top-to-bottom through the "
            "Linear tools, then Stretch, then After-stretch. Everything is "
            "undoable and recorded."))

        split = QSplitter(Qt.Horizontal)

        # ---- left: tool tree + params
        left = QWidget()
        ll = QVBoxLayout(left)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        for stage, label in _STAGE_LABELS.items():
            top = QTreeWidgetItem([label])
            top.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for spec in sorted((s for s in OPS.values() if s.stage == stage),
                               key=lambda s: s.name):
                child = QTreeWidgetItem([spec.label])
                child.setData(0, Qt.UserRole, spec.name)
                child.setToolTip(0, (spec.doc.splitlines() or [""])[0])
                top.addChild(child)
            top.setExpanded(stage == "linear")
        self.tree.currentItemChanged.connect(self._tool_selected)
        ll.addWidget(self.tree, 2)

        self.doc_label = QLabel("Select a tool to see what it does.")
        self.doc_label.setObjectName("pageHint")
        self.doc_label.setWordWrap(True)
        ll.addWidget(self.doc_label)

        self.param_box = QGroupBox("Settings")
        self.param_form = QFormLayout(self.param_box)
        param_scroll = QScrollArea()
        param_scroll.setWidgetResizable(True)
        param_scroll.setWidget(self.param_box)
        ll.addWidget(param_scroll, 1)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply_current)
        ll.addWidget(self.apply_btn)

        self.auto_btn = QPushButton("✨ Auto-process (do everything for me)")
        self.auto_btn.setToolTip("Runs the standard chain: gradient removal, color "
                                  "balance, denoise, GHS stretch, vibrance.")
        self.auto_btn.clicked.connect(self.apply_auto_chain)
        ll.addWidget(self.auto_btn)
        split.addWidget(left)

        # ---- center: canvas
        center = QWidget()
        cl = QVBoxLayout(center)
        self.canvas = ImageCanvas()
        cl.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        self.stretch_toggle = QCheckBox("Display autostretch")
        self.stretch_toggle.setChecked(True)
        self.stretch_toggle.toggled.connect(self.canvas.set_autostretch)
        self.before_btn = QPushButton("Hold for before")
        self.before_btn.pressed.connect(self._show_before)
        self.before_btn.released.connect(self._show_after)
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(self.canvas.fit)
        one_btn = QPushButton("1:1")
        one_btn.clicked.connect(self.canvas.zoom_1_1)
        for w in (self.stretch_toggle, self.before_btn, fit_btn, one_btn):
            controls.addWidget(w)
        controls.addStretch(1)
        cl.addLayout(controls)
        split.addWidget(center)

        # ---- right: history
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("History"))
        self.history = QListWidget()
        rl.addWidget(self.history, 1)
        undo_btn = QPushButton("Undo last step")
        undo_btn.clicked.connect(self.undo)
        reset_btn = QPushButton("Reset to stack")
        reset_btn.clicked.connect(self.reset)
        save_recipe_btn = QPushButton("Save steps as recipe…")
        save_recipe_btn.clicked.connect(self.save_recipe)
        for b in (undo_btn, reset_btn, save_recipe_btn):
            rl.addWidget(b)
        split.addWidget(right)

        split.setSizes([320, 660, 220])
        lay.addWidget(split, 1)

        self.next_btn = QPushButton("Continue to export  →")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self.processing_done.emit)
        lay.addWidget(self.next_btn, 0, Qt.AlignRight)

    # -------------------------------------------------------------- lifecycle
    def on_enter(self):
        if self.state.current is not None:
            self.canvas.set_image(self.state.current.data)
            self._refresh_history()

    # ---------------------------------------------------------------- tools
    def _tool_selected(self, item, _prev):
        self._param_widgets.clear()
        while self.param_form.rowCount():
            self.param_form.removeRow(0)
        if item is None or item.data(0, Qt.UserRole) is None:
            self.apply_btn.setEnabled(False)
            return
        spec = OPS[item.data(0, Qt.UserRole)]
        self.doc_label.setText(spec.doc or spec.label)
        for p in spec.params:
            w = self._make_param_widget(p)
            if w is not None:
                w.setToolTip(p.doc)
                self.param_form.addRow(p.name, w)
                self._param_widgets[p.name] = (p, w)
        self.apply_btn.setEnabled(self.state.current is not None)
        self.apply_btn.setText(f"Apply {spec.label}")

    @staticmethod
    def _make_param_widget(p):
        if p.kind == "float":
            w = QDoubleSpinBox()
            w.setRange(p.lo if p.lo is not None else -1e6,
                       p.hi if p.hi is not None else 1e6)
            w.setDecimals(3)
            has_bounds = p.lo is not None and p.hi is not None
            w.setSingleStep(((p.hi - p.lo) / 50) if has_bounds else 0.1)
            w.setValue(float(p.default or 0))
            return w
        if p.kind == "int":
            w = QSpinBox()
            w.setRange(int(p.lo) if p.lo is not None else -10**6,
                       int(p.hi) if p.hi is not None else 10**6)
            w.setValue(int(p.default or 0))
            return w
        if p.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(p.default))
            return w
        if p.kind == "choice":
            w = QComboBox()
            w.addItems(list(p.choices))
            if p.default in p.choices:
                w.setCurrentText(str(p.default))
            return w
        w = QLineEdit(str(p.default or ""))
        return w

    def _collect_params(self):
        params = {}
        for name, (p, w) in self._param_widgets.items():
            if p.kind == "float":
                params[name] = w.value()
            elif p.kind == "int":
                params[name] = w.value()
            elif p.kind == "bool":
                params[name] = w.isChecked()
            elif p.kind == "choice":
                params[name] = w.currentText()
            else:
                params[name] = w.text()
        return params

    # --------------------------------------------------------------- actions
    def apply_current(self):
        item = self.tree.currentItem()
        if item is None or self.state.current is None:
            return
        op_name = item.data(0, Qt.UserRole)
        params = self._collect_params()
        self._run_ops([(op_name, params)])

    def apply_auto_chain(self):
        if self.state.current is None:
            return
        self._run_ops([(s["op"], s["params"]) for s in AUTO_RECIPE_STEPS])

    def _run_ops(self, steps):
        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            return
        self.apply_btn.setEnabled(False)
        self.auto_btn.setEnabled(False)
        img = self.state.current

        def job(progress=None, log=None):
            out = img
            for i, (name, params) in enumerate(steps):
                if log:
                    log(f"{name}…")
                out = apply_op(out, name, **params)
                if progress:
                    progress("process", i + 1, len(steps))
            return out

        self.worker = FnWorker(job)
        self.worker.succeeded.connect(self._ops_done)
        self.worker.failed.connect(self._ops_failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _ops_done(self, img):
        self.state.push_edit(img)
        self.canvas.set_image(img.data, keep_view=True)
        self._refresh_history()
        self.apply_btn.setEnabled(True)
        self.auto_btn.setEnabled(True)

    def _ops_failed(self, tb):
        self.apply_btn.setEnabled(True)
        self.auto_btn.setEnabled(True)
        QMessageBox.warning(self, "Operation failed", tb.splitlines()[-1])

    def undo(self):
        img = self.state.undo()
        if img is not None:
            self.canvas.set_image(img.data, keep_view=True)
        self._refresh_history()

    def reset(self):
        self.state.reset_edits()
        if self.state.current is not None:
            self.canvas.set_image(self.state.current.data, keep_view=True)
        self._refresh_history()

    def save_recipe(self):
        if self.state.current is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save recipe", "my-recipe.json",
                                              "Recipe (*.json)")
        if path:
            Recipe.from_history(self.state.current, Path(path).stem).save(path)

    def _refresh_history(self):
        self.history.clear()
        if self.state.current is not None:
            for h in self.state.current.history:
                if h["op"] in OPS:
                    self.history.addItem(OPS[h["op"]].label)
                else:
                    self.history.addItem(h["op"])

    def _show_before(self):
        base = self.state.edits[0] if self.state.edits else self.state.stacked
        if base is not None:
            self._before = True
            self.canvas.set_image(base.data, keep_view=True)

    def _show_after(self):
        if self.state.current is not None:
            self.canvas.set_image(self.state.current.data, keep_view=True)


class ExportPage(QWidget):
    """Step 5 — save the result, with a ready-to-post caption."""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state

        lay = QVBoxLayout(self)
        lay.addLayout(_header(
            "5 · Export",
            "Save your finished image. TIFF (16-bit) keeps full quality for "
            "further editing; JPEG is for sharing. The caption below is "
            "generated from your session metadata — paste it straight into "
            "Reddit, AstroBin, or Instagram."))

        row = QHBoxLayout()
        self.export_btn = QPushButton("Export image…")
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self.export)
        self.compare_btn = QPushButton("Export before/after comparison…")
        self.compare_btn.clicked.connect(self.export_comparison)
        row.addWidget(self.export_btn)
        row.addWidget(self.compare_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self.caption = QPlainTextEdit()
        self.caption.setReadOnly(False)
        self.caption.setMaximumHeight(150)
        lay.addWidget(QLabel("Shareable caption (editable):"))
        lay.addWidget(self.caption)

        self.canvas = ImageCanvas()
        lay.addWidget(self.canvas, 1)
        self.status = QLabel("")
        self.status.setObjectName("pageHint")
        lay.addWidget(self.status)

    def on_enter(self):
        if self.state.current is not None:
            self.canvas.set_image(self.state.current.data)
        if self.state.session:
            n_used = self.state.stacked.meta.get("n_stacked") if self.state.stacked else None
            self.caption.setPlainText(
                acquisition_caption([self.state.session], n_used))

    def export(self):
        if self.state.current is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export image", "final.jpg",
            "JPEG (*.jpg);;16-bit TIFF (*.tif);;PNG (*.png);;FITS (*.fits)")
        if not path:
            return
        out = export_image(self.state.current, path)
        self.status.setText(f"Exported {out}")
        self._record_output(out)

    def _record_output(self, out: Path) -> None:
        """Catalog the export in the library — never let a library failure
        (locked db, permissions, ...) block a successful export."""
        if not self.state.session:
            return
        try:
            lib = Library()
            sid, _ = lib.import_session(self.state.session)
            target = resolve_target(self.state.session.target)["canonical"]
            lib.add_output(target=target, name=Path(out).stem, path=out, session_id=sid)
        except Exception as exc:
            self.status.setText(f"Exported {out}  (library not updated: {exc})")

    def export_comparison(self):
        if self.state.current is None or self.state.stacked is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export comparison", "before-after.jpg", "JPEG (*.jpg)")
        if not path:
            return
        out = save_comparison(self.state.stacked, self.state.current, path)
        self.status.setText(f"Exported {out}")
