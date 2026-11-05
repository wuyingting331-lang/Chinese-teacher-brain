"""Keep simulated API diagnostics out of the user's real request history."""
import pytest


@pytest.fixture(autouse=True)
def isolate_generation_diagnostics(monkeypatch,tmp_path):
    from teacher.diagnostics import persist,persist_exchange
    monkeypatch.setattr('teacher.report_flow.persist',lambda events:persist(events,tmp_path/'diagnostics'))
    monkeypatch.setattr('teacher.report_flow.persist_exchange',lambda event:persist_exchange(event,tmp_path/'diagnostics'))
