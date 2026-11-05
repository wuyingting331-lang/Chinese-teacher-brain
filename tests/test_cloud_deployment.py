import io
from pathlib import Path
from PIL import Image
from streamlit.testing.v1 import AppTest
from teacher.demo import demo_record
from teacher.storage import save, load_all
from teacher.images import ingest, original_path, model_bytes
from teacher.runtime_paths import bind_session, data_path, _session_root

APP=Path(__file__).resolve().parents[1]/'app.py'


def test_private_paths_isolate_records_and_identical_images(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    token=_session_root.set(None)
    try:
        first={'_private_data_root':str(tmp_path/'session-a')}
        second={'_private_data_root':str(tmp_path/'session-b')}
        bind_session(first)
        r=demo_record(); save(r)
        b=io.BytesIO(); Image.new('RGB',(64,64),'red').save(b,format='PNG')
        p=ingest(b.getvalue(),'a.png'); a_path=original_path(p)
        assert a_path.is_file() and load_all()[0][0].id==r.id
        bind_session(second)
        assert load_all()==([],[]) and not original_path(p).exists()
        ingest(b.getvalue(),'b.png')
        assert original_path(p)!=a_path and model_bytes(p)
        assert data_path('diagnostics').parent==Path(second['_private_data_root'])
        bind_session(first)
        assert load_all()[0][0].id==r.id and original_path(p)==a_path
    finally:
        _session_root.reset(token)


def test_two_real_ui_sessions_do_not_share_saved_records(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    # A legacy shared record must not show up in either browser's history.
    r=demo_record(); save(r,tmp_path/'data/records')
    a=AppTest.from_file(str(APP)).run()
    b=AppTest.from_file(str(APP)).run()
    assert not a.exception and not b.exception
    assert a.session_state['_private_data_root']!=b.session_state['_private_data_root']
    assert not any(x.label=='已保存记录' for x in a.selectbox)
    next(x for x in a.button if x.label=='打开离线演示').click().run()
    next(x for x in a.button if x.label=='保存已确认记录').click().run()
    a.run(); b.run()
    assert any(x.label=='已保存记录' for x in a.selectbox)
    assert not any(x.label=='已保存记录' for x in b.selectbox)
    assert not b.exception


def test_streamlit_top_level_secrets_and_required_assets(monkeypatch):
    from teacher.client import settings
    from teacher.config import scoring_profiles
    monkeypatch.setattr('teacher.client.load_dotenv',lambda:None)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('OPENAI_MODEL',raising=False)
    assert settings({'OPENAI_API_KEY':'fake-test-key','OPENAI_MODEL':'configured-model'})==('fake-test-key','configured-model')
    assert scoring_profiles()
    assert (APP.parent/'teacher/prompts.py').is_file()
    assert (APP.parent/'config/calibration/user_reference_pending.json').is_file()
