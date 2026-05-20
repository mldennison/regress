import sys

import pytest

import ak_regress
import regress


@pytest.fixture(autouse=True)
def deterministic_test_mode(monkeypatch):
    monkeypatch.setattr(regress, "test_mode", 1)
    monkeypatch.setattr(regress.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ak_regress.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ak_regress.random, "choice", lambda _choices: regress.job_result.SUCCESS)
    monkeypatch.setattr(sys, "argv", ["ak-regress-test"])
