"""Umbra Noctis desktop application: a guided 5-step workflow.

Library → Grade → Stack → Process → Export, with free navigation once a step
has data. Dark theme by default; View menu offers a red night-vision mode.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog,
                               QHBoxLayout, QLabel, QListWidget, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from .. import __app_name__, __version__
from .pages_data import GradePage, LibraryPage
from .pages_process import ExportPage, ProcessPage, StackPage
from .state import AppState
from .theme import DARK_QSS, RED_NIGHT_QSS

_STEPS = ["1 · Library", "2 · Grade", "3 · Stack", "4 · Process", "5 · Export"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__} — ex umbra noctis, in solem")
        self.resize(1360, 860)
        self.state = AppState()

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(190)
        side_lay = QVBoxLayout(sidebar)
        side_lay.setContentsMargins(0, 16, 0, 16)
        title = QLabel("  UMBRA\n  NOCTIS")
        title.setObjectName("pageTitle")
        side_lay.addWidget(title)
        side_lay.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for i, label in enumerate(_STEPS):
            btn = QPushButton(label)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, idx=i: self.goto(idx))
            self.nav_group.addButton(btn, i)
            side_lay.addWidget(btn)
            self.nav_buttons.append(btn)
        side_lay.addStretch(1)
        version = QLabel(f"  v{__version__}")
        version.setObjectName("pageHint")
        side_lay.addWidget(version)
        layout.addWidget(sidebar)

        # ---- pages
        self.stack_widget = QStackedWidget()
        self.library_page = LibraryPage(self.state)
        self.grade_page = GradePage(self.state)
        self.stack_page = StackPage(self.state)
        self.process_page = ProcessPage(self.state)
        self.export_page = ExportPage(self.state)
        for page in (self.library_page, self.grade_page, self.stack_page,
                     self.process_page, self.export_page):
            wrapper = QWidget()
            wl = QVBoxLayout(wrapper)
            wl.setContentsMargins(24, 20, 24, 16)
            wl.addWidget(page)
            self.stack_widget.addWidget(wrapper)
        layout.addWidget(self.stack_widget, 1)
        self.setCentralWidget(root)

        # flow signals
        self.library_page.session_chosen.connect(lambda: self.goto(1))
        self.grade_page.grading_done.connect(lambda: self.goto(2))
        self.stack_page.stacking_done.connect(lambda: self.goto(3))
        self.process_page.processing_done.connect(lambda: self.goto(4))

        self._build_menu()
        self.goto(0)
        self.statusBar().showMessage(
            "Welcome. Open a folder of Dwarf 3 data — or create a practice "
            "session — to begin.")

    # ------------------------------------------------------------------ nav
    def goto(self, index: int):
        # guard: later steps need earlier data
        if index >= 1 and self.state.session is None:
            self._nudge(0, "Pick a session first (double-click one in the Library).")
            return
        if index >= 3 and self.state.stacked is None and index != 3:
            self._nudge(2, "Stack the session first.")
            return
        self.stack_widget.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        page = (self.library_page, self.grade_page, self.stack_page,
                self.process_page, self.export_page)[index]
        if hasattr(page, "on_enter"):
            page.on_enter()

    def _nudge(self, index: int, message: str):
        self.statusBar().showMessage(message, 5000)
        self.stack_widget.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)

    # ----------------------------------------------------------------- menu
    def _build_menu(self):
        m_file = self.menuBar().addMenu("&File")
        open_act = QAction("&Open data folder…", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self.library_page.open_folder)
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence.Quit)
        quit_act.triggered.connect(self.close)
        m_file.addAction(open_act)
        m_file.addSeparator()
        m_file.addAction(quit_act)

        m_view = self.menuBar().addMenu("&View")
        self.red_mode = QAction("Red night-vision mode", self, checkable=True)
        self.red_mode.toggled.connect(
            lambda on: QApplication.instance().setStyleSheet(
                RED_NIGHT_QSS if on else DARK_QSS))
        m_view.addAction(self.red_mode)

        m_help = self.menuBar().addMenu("&Help")
        about = QAction("&About", self)
        about.triggered.connect(self._about)
        guide = QAction("&Guide", self)
        guide.setShortcut(QKeySequence.HelpContents)
        guide.triggered.connect(self._show_guide)
        docs = QAction("Where are the docs?", self)
        docs.triggered.connect(lambda: QMessageBox.information(
            self, "Documentation",
            "The full guide is built in: Help → Guide (or `umbra guide` "
            "in a terminal).\n\nThe repository also ships\n"
            "USER_GUIDE.md — every feature explained\n"
            "PROCESSING_TUTORIAL.md — step-by-step walkthrough\n"
            "GUI_TOUR.md — this app, screen by screen\n\n"
            "https://github.com/ManliestBen/umbra-noctis"))
        m_help.addAction(guide)
        m_help.addAction(docs)
        m_help.addAction(about)

    def _show_guide(self):
        from ..guide import render, topics
        dlg = QDialog(self)
        dlg.setWindowTitle("Umbra Noctis — Guide")
        dlg.resize(880, 640)
        layout = QHBoxLayout(dlg)
        topic_list = QListWidget()
        topic_list.setMaximumWidth(240)
        viewer = QTextBrowser()
        viewer.setOpenExternalLinks(True)
        keys = []
        for key, title in topics():
            keys.append(key)
            topic_list.addItem(title)
        topic_list.currentRowChanged.connect(
            lambda row: viewer.setMarkdown(render(keys[row])) if row >= 0 else None)
        topic_list.setCurrentRow(0)
        layout.addWidget(topic_list)
        layout.addWidget(viewer, stretch=1)
        dlg.exec()

    def _about(self):
        QMessageBox.about(
            self, "About Umbra Noctis",
            f"<b>{__app_name__}</b> v{__version__}<br>"
            "Post-processing for the DwarfLab Dwarf 3 smart telescope.<br><br>"
            "<i>Ex umbra noctis, in solem</i> — out of the shadow of night, "
            "into the sun.")


def run_gui():
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setStyleSheet(DARK_QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
