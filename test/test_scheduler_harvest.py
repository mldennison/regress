from queue import Empty
from unittest.mock import MagicMock

from regress import job, job_result, job_status, scheduler


class DummyStatus:
    def find_resources(self, _job_resources):
        return []

    def consume(self, _resources):
        return True


def _dead_worker_job():
    test_job = job()
    test_job.name = "harvest_fail"
    test_job.status = job_status.SETUP
    test_job.result = job_result.INCOMPLETE
    proc = MagicMock()
    proc.is_alive.return_value = False
    result_queue = MagicMock()
    result_queue.get.side_effect = Empty()
    return test_job, proc, result_queue


def test_harvest_exception_marks_job_completed_failed():
    sch = scheduler()
    test_job, proc, result_queue = _dead_worker_job()
    sch._inflight[id(test_job)] = (test_job, proc, result_queue)

    sch._harvest()

    assert test_job.status == job_status.COMPLETED
    assert test_job.result == job_result.FAILED
    assert sch._inflight == {}
    proc.join.assert_called_once()


def test_harvest_exception_does_not_reschedule_job(monkeypatch):
    sch = scheduler()
    test_job, proc, result_queue = _dead_worker_job()
    sch._inflight[id(test_job)] = (test_job, proc, result_queue)

    def fail_if_started(*_args, **_kwargs):
        raise AssertionError("failed harvest should not launch a new worker")

    monkeypatch.setattr("regress.multiprocessing.Process", fail_if_started)

    scheduled, skipped, complete = sch.schedule_jobs([test_job], DummyStatus())

    assert test_job.status == job_status.COMPLETED
    assert test_job.result == job_result.FAILED
    assert complete == [test_job]
    assert scheduled == []
    assert skipped == []
    assert sch._inflight == {}
