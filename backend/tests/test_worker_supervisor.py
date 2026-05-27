import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.worker_supervisor import WorkerSupervisor


def test_is_structured_complete_accepts_closeout_source():
    sup = WorkerSupervisor()
    sup.register_task("T1")
    sup.mark_completed("T1", "closeout summary", source="closeout")

    assert sup.is_structured_complete("T1") is True


def test_is_structured_complete_accepts_worker_complete_source():
    sup = WorkerSupervisor()
    sup.register_task("T1")
    sup.mark_completed("T1", "worker summary", source="worker.complete")

    assert sup.is_structured_complete("T1") is True


def test_is_structured_complete_rejects_other_sources():
    sup = WorkerSupervisor()
    sup.register_task("T1")
    sup.mark_completed("T1", "auto summary", source="auto")
    assert sup.is_structured_complete("T1") is False

    sup.register_task("T2")
    sup.mark_completed("T2", "failed summary", source="failed")
    assert sup.is_structured_complete("T2") is False
