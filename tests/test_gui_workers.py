"""FnWorker unit tests — run offscreen; call .run() synchronously so the
thread's job logic is exercised without spinning up a real QThread event
loop. Skipped if PySide6 is absent."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from umbra_noctis.gui.workers import FnWorker  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_success_emits_succeeded_with_return_value(app):
    def job():
        return 42

    worker = FnWorker(job, wants_progress=False, wants_log=False)
    results = []
    failures = []
    worker.succeeded.connect(results.append)
    worker.failed.connect(failures.append)
    worker.run()

    assert results == [42]
    assert failures == []


def test_progress_adapts_two_and_three_arg_signatures(app):
    def job(progress=None):
        progress(1, 10)          # 2-arg form
        progress("stage", 5, 10)  # 3-arg form
        return "done"

    worker = FnWorker(job, wants_progress=True, wants_log=False)
    seen = []
    worker.progressed.connect(lambda stage, done, total: seen.append((stage, done, total)))
    results = []
    worker.succeeded.connect(results.append)
    worker.run()

    assert seen == [("", 1, 10), ("stage", 5, 10)]
    assert results == ["done"]


def test_exception_emits_failed_and_does_not_escape_run(app):
    def job():
        raise ValueError("boom")

    worker = FnWorker(job, wants_progress=False, wants_log=False)
    failures = []
    worker.failed.connect(failures.append)
    successes = []
    worker.succeeded.connect(successes.append)

    worker.run()  # must not raise — the exception is caught inside run()

    assert successes == []
    assert len(failures) == 1
    assert "boom" in failures[0]
    assert "ValueError" in failures[0]


def test_log_kwarg_only_injected_when_wanted(app):
    calls = []

    def job(log=None):
        log("hello")
        return None

    worker = FnWorker(job, wants_progress=False, wants_log=True)
    worker.logged.connect(calls.append)
    worker.run()

    assert calls == ["hello"]
