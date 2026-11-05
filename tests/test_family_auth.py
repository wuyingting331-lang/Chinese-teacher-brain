from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import base64
import json
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from teacher import family_auth as auth

APP=Path(__file__).resolve().parents[1]/'app.py'
PASSWORD='only-a-synthetic-test-password-家'


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(st,'secrets',{'FAMILY_PASSWORD':PASSWORD})
    monkeypatch.setattr(auth,'_failures',deque())


def login(at,password=PASSWORD):
    at.text_input(key='_family_password').set_value(password)
    next(x for x in at.button if x.label=='登录').click().run()
    return at


def test_unconfigured_and_blank_are_fail_closed(monkeypatch):
    for config in ({},{'FAMILY_PASSWORD':''},{'FAMILY_PASSWORD':'   '},{'FAMILY_PASSWORD':123}):
        monkeypatch.setattr(st,'secrets',config)
        at=AppTest.from_file(str(APP)).run()
        assert not at.exception
        assert any('应用已锁定' in x.value for x in at.error)
        assert not at.text_area and not at.get('file_uploader') and not at.get('bidi_component')
        assert not at.button and not at.sidebar.button
        assert '_private_data_root' not in at.session_state


def test_unauthenticated_does_not_load_business_or_call_api(monkeypatch):
    calls=[]
    monkeypatch.setattr('teacher.storage.load_all',lambda: calls.append('records'))
    monkeypatch.setattr('teacher.config.scoring_profiles',lambda: calls.append('profiles'))
    monkeypatch.setattr('teacher.client.ModelClient',Mock(side_effect=AssertionError('must not call')))
    at=AppTest.from_file(str(APP)).run()
    assert not at.exception and not calls
    assert [x.label for x in at.text_input]==['家庭密码']
    assert not at.text_area and not at.get('file_uploader') and not at.get('bidi_component')
    assert '_private_data_root' not in at.session_state
    login(at,'wrong')
    assert not at.exception and not calls
    assert any('密码不正确' in x.value for x in at.error)
    assert PASSWORD not in str(at.session_state)
    assert not at.session_state.get('_family_password','')


def test_success_logout_erases_data_files_and_requires_login_again(monkeypatch):
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    a=AppTest.from_file(str(APP)).run(); login(a)
    assert not a.exception and auth.authenticated(a.session_state,PASSWORD)
    assert PASSWORD not in str(a.session_state)
    next(x for x in a.button if x.label=='打开离线演示').click().run()
    next(x for x in a.button if x.label=='保存已确认记录').click().run()
    root=Path(a.session_state['_private_data_root'])
    (root/'images').mkdir(exist_ok=True)
    (root/'images'/'test-upload').write_bytes(b'synthetic-image')
    (root/'diagnostics').mkdir(exist_ok=True)
    (root/'diagnostics'/'test-log').write_text('synthetic')
    assert list((root/'records').glob('*.json'))
    a.session_state.pending=('draft','old','old')
    next(x for x in a.button if x.label=='退出家庭登录').click().run()
    assert not a.exception
    assert 'record' not in a.session_state and 'pending' not in a.session_state
    assert '_private_data_root' not in a.session_state and '_family_token' not in a.session_state
    assert not root.exists()
    assert not a.text_area and not a.get('bidi_component') and not a.get('file_uploader')
    login(a)
    assert not a.exception and 'record' not in a.session_state
    assert Path(a.session_state['_private_data_root'])!=root


def test_password_rotation_revokes_previous_login(monkeypatch):
    at=AppTest.from_file(str(APP)).run(); login(at)
    next(x for x in at.button if x.label=='打开离线演示').click().run()
    root=Path(at.session_state['_private_data_root'])
    monkeypatch.setattr(st,'secrets',{'FAMILY_PASSWORD':'a-different-synthetic-password'})
    at.run()
    assert not at.exception and not at.text_area and not root.exists()
    assert '_family_token' not in at.session_state and 'record' not in at.session_state


def test_per_session_and_instance_rate_limits(monkeypatch):
    clock=[100.0]
    monkeypatch.setattr(auth,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    fake=SimpleNamespace(secrets={'FAMILY_PASSWORD':PASSWORD},session_state={})
    for _ in range(5):
        fake.session_state['_family_password']='bad'
        auth.attempt_login(fake)
    assert auth.remaining_wait(fake.session_state,100)==60
    fake.session_state['_family_password']=PASSWORD
    auth.attempt_login(fake)
    assert not auth.authenticated(fake.session_state,PASSWORD)
    clock[0]=161
    fake.session_state['_family_password']=PASSWORD
    auth.attempt_login(fake)
    assert auth.authenticated(fake.session_state,PASSWORD)
    auth._failures.clear()
    for _ in range(20):
        other=SimpleNamespace(secrets=fake.secrets,session_state={'_family_password':'bad'})
        auth.attempt_login(other)
    assert auth.remaining_wait({},161)>0
    assert auth.remaining_wait({},462)==0


def test_login_is_not_shared_between_browser_sessions(monkeypatch):
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    a=AppTest.from_file(str(APP)).run(); login(a)
    b=AppTest.from_file(str(APP)).run()
    assert not b.exception and not b.text_area
    assert '_family_token' not in b.session_state
    root=Path(a.session_state['_private_data_root'])
    login(b)
    other_root=Path(b.session_state['_private_data_root'])
    assert other_root!=root
    next(x for x in a.button if x.label=='退出家庭登录').click().run()
    b.run()
    assert other_root.exists() and b.text_area and not b.exception


def test_native_media_is_not_registered_and_download_payload_is_exact(monkeypatch):
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    native=Mock(side_effect=AssertionError('must not register public media'))
    monkeypatch.setattr(st,'download_button',native)
    monkeypatch.setattr(st,'image',native)
    from teacher import private_media
    captured=[]
    original=private_media._MEDIA
    def capture(**kwargs):
        captured.append(kwargs['data'])
        return original(**kwargs)
    monkeypatch.setattr(private_media,'_MEDIA',capture)
    at=AppTest.from_file(str(APP)).run()
    assert not captured
    login(at)
    next(x for x in at.button if x.label=='打开离线演示').click().run()
    assert not at.exception and not native.called
    payload=next(x for x in reversed(captured) if x.get('mime')=='application/json')
    data=json.loads(base64.b64decode(payload['payload']))
    assert data['essay']['body']==at.session_state.record.essay.body
    assert PASSWORD not in json.dumps(data)


def test_cleanup_refuses_paths_outside_app_temp_scope(tmp_path):
    from teacher.runtime_paths import clear_session_files
    sentinel=tmp_path/'keep'; sentinel.mkdir()
    assert not clear_session_files({'_private_data_root':str(sentinel)})
    assert sentinel.exists()


def test_unconfigured_clears_stale_pre_gate_business_state(monkeypatch):
    from teacher.demo import demo_record
    from teacher.runtime_paths import bind_session, _session_root
    state={}; token=_session_root.set(None)
    try:
        bind_session(state); root=Path(state['_private_data_root'])
    finally:
        _session_root.reset(token)
    monkeypatch.setattr(st,'secrets',{})
    at=AppTest.from_file(str(APP))
    at.session_state['_private_data_root']=str(root)
    at.session_state['record']=demo_record()
    at.session_state['pending']=('draft','stale','stale')
    at.run()
    assert not at.exception and not root.exists()
    assert 'record' not in at.session_state and 'pending' not in at.session_state
    assert not at.get('bidi_component') and not at.text_area


def test_logout_clears_only_current_runtime_media_and_uploads(monkeypatch):
    from streamlit import runtime
    from streamlit.runtime import scriptrunner
    rt=SimpleNamespace(uploaded_file_mgr=Mock(),media_file_mgr=Mock())
    monkeypatch.setattr(runtime,'exists',lambda:True)
    monkeypatch.setattr(runtime,'get_instance',lambda:rt)
    monkeypatch.setattr(scriptrunner,'get_script_run_ctx',lambda **kwargs:SimpleNamespace(session_id='current-session'))
    fake=SimpleNamespace(session_state={'record':'synthetic','pending':'synthetic','_family_token':'synthetic'})
    auth.clear_private_session(fake)
    assert fake.session_state=={}
    rt.uploaded_file_mgr.remove_session_files.assert_called_once_with('current-session')
    rt.media_file_mgr.clear_session_refs.assert_called_once_with('current-session')
