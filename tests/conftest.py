"""Keep simulated API diagnostics out of the user's real request history."""
import pytest


@pytest.fixture(autouse=True)
def business_ui_test_login(monkeypatch,request):
    """Business regressions enter through the real gate; dedicated auth tests never auto-login."""
    if request.module.__name__.endswith('test_family_auth'):
        return
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from teacher import family_auth
    from collections import deque
    test_password='synthetic-test-login-only'
    monkeypatch.setattr(st,'secrets',{'FAMILY_PASSWORD':test_password})
    monkeypatch.setattr(family_auth,'_failures',deque())
    original=AppTest.run
    def run(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        fields=[x for x in self.text_input if x.key=='_family_password']
        if fields and not self.exception:
            fields[0].set_value(test_password)
            next(x for x in self.button if x.label=='登录').click()
            result=original(self,*args,**kwargs)
        return result
    monkeypatch.setattr(AppTest,'run',run)


@pytest.fixture(autouse=True)
def isolate_generation_diagnostics(monkeypatch,tmp_path):
    from teacher.diagnostics import persist,persist_exchange
    monkeypatch.setattr('teacher.report_flow.persist',lambda events:persist(events,tmp_path/'diagnostics'))
    monkeypatch.setattr('teacher.report_flow.persist_exchange',lambda event:persist_exchange(event,tmp_path/'diagnostics'))
