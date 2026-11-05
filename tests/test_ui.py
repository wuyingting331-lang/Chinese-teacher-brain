from pathlib import Path
from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]/'app.py'


def button(at,label):
    return next(x for x in at.button if x.label==label)


def test_no_key_demo_and_stale_report(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('OPENAI_MODEL',raising=False)
    at=AppTest.from_file(str(APP)).run()
    assert not at.exception
    button(at,'打开离线演示').click().run()
    assert not at.exception
    r=at.session_state.record
    old_version=r.essay.version
    assert r.demo and r.report
    assert button(at,'评分与批改').disabled
    at.text_input(key='edit_title').set_value('更改后的题目').run()
    assert not at.exception
    assert any('旧版本' in x.value for x in at.warning)
    assert at.session_state.record.essay.version==old_version
    button(at,'确认原文').click().run()
    assert not at.exception
    assert at.session_state.record.report is None
    assert at.session_state.record.essay.version!=old_version
    button(at,'保存已确认记录').click().run()
    assert not at.exception
    button(at,'保存已确认记录').click().run()
    assert len(list((Path(at.session_state['_private_data_root'])/'records').glob('*.json')))==1
    button(at,'新建作文').click().run()
    button(at,'重新打开').click().run()
    assert not at.exception
    assert at.text_input(key='edit_title').value=='更改后的题目'


def test_score_once_and_failure_retry(monkeypatch,tmp_path):
    from unittest.mock import Mock
    from teacher.demo import demo_record
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('fake-key','configured-model'))
    monkeypatch.setattr('teacher.client.ModelClient',lambda *args:object())
    def fixed(client,essay,config,**kwargs):
        report=demo_record().report
        report.essay_version=essay.version
        return report
    generate=Mock(side_effect=[TimeoutError('secret must never display'),None])
    monkeypatch.setattr('teacher.service.generate_report',generate)
    at=AppTest.from_file(str(APP)).run()
    button(at,'打开离线演示').click().run()
    at.text_input(key='edit_title').set_value('学生习作').run()
    button(at,'确认原文').click().run()
    original=at.session_state.record.essay.body
    button(at,'评分与批改').click().run()
    assert not at.exception and not at.session_state.busy
    assert at.session_state.record.essay.body==original
    assert at.session_state.record.report is None
    assert all('secret' not in e.value for e in at.error)
    generate.side_effect=fixed
    button(at,'评分与批改').click().run()
    assert not at.exception and at.session_state.record.report
    assert button(at,'评分与批改').disabled
    at.run()
    assert generate.call_count==2


def test_busy_disables_submission(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    at=AppTest.from_file(str(APP)).run()
    button(at,'打开离线演示').click().run()
    at.session_state.busy=True
    at.run()
    assert button(at,'评分与批改').disabled
    assert button(at,'确认原文').disabled
    assert button(at,'新建作文').disabled


def test_picture_manual_confirmation_and_text_edit_invalidation(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    at=AppTest.from_file(str(APP)).run()
    at.selectbox(key='edit_kind').select('看图作文').run()
    assert not at.exception
    assert button(at,'识别题目与图意').disabled
    at.text_input(key='edit_title').set_value('合作').run()
    at.text_area(key='edit_body').set_value('我们布置课室。').run()
    at.text_area(key='topic_text').set_value('请看图写故事。').run()
    at.text_area(key='topic_scene_0').set_value('两人合作布置课室。').run()
    at.text_area(key='topic_facts').set_value('墙上有彩纸。').run()
    button(at,'确认题目与图意').click().run()
    assert not at.exception
    button(at,'确认原文').click().run()
    r=at.session_state.record
    assert r.essay.picture_confirmation.method=='手动填写'
    assert r.essay.picture_confirmation.scenes==('两人合作布置课室。',)
    at.text_area(key='topic_scene_0').set_value('一人扶椅子，另一人贴彩纸。').run()
    assert any('尚未重新确认' in w.value for w in at.warning)
    assert any('旧版本' in w.value for w in at.warning)
    assert button(at,'评分与批改').disabled


def test_picture_reorder_history_preview_and_missing(monkeypatch,tmp_path):
    import io
    from PIL import Image
    import teacher.images as images
    from teacher.models import Essay,Record
    from teacher.storage import save
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(images,'ROOT',tmp_path/'data/images')
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    def image(color):
        buffer=io.BytesIO()
        Image.new('RGB',(64,64),color).save(buffer,format='PNG')
        return images.ingest(buffer.getvalue(),color+'.png')
    a,b=image('red'),image('blue')
    c=images.confirmed([a,b],'题',['红图','蓝图'],[],[],'手动填写')
    record=Record(essay=Essay(title='图片题',kind='看图作文',body='作文',pictures=(a,b),picture_confirmation=c))
    save(record)
    at=AppTest.from_file(str(APP))
    at.session_state['_private_data_root']=str(tmp_path/'data')
    at.run()
    button(at,'重新打开').click().run()
    assert not at.exception
    assert at.session_state.record.essay.pictures==(a,b)
    next(x for x in at.button if x.key=='pic_down_0').click().run()
    assert not at.exception
    assert at.session_state.edit_pictures==(b,a)
    assert any('旧版本' in w.value for w in at.warning)
    images.original_path(a).unlink()
    at.run()
    assert not at.exception
    assert any('缺失或损坏' in w.value for w in at.warning)


def test_identification_button_uses_model_and_preserves_order(monkeypatch,tmp_path):
    from unittest.mock import Mock
    import io
    from PIL import Image
    import teacher.images as images
    from teacher.models import Essay,Record,PictureReading
    from teacher.storage import save
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(images,'ROOT',tmp_path/'data/images')
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('fake','configured-model'))
    monkeypatch.setattr('teacher.image_ui.ModelClient',lambda *args:object())
    buffer=io.BytesIO()
    Image.new('RGB',(64,64)).save(buffer,format='PNG')
    p=images.ingest(buffer.getvalue(),'a.png')
    save(Record(essay=Essay(title='题目图片',body='正文',kind='看图作文',pictures=(p,))))
    identify=Mock(return_value=PictureReading(text_requirements='题目文字',scenes=['图中一人在走路'],facts=['有一个人'],uncertainties=['关系未知']))
    monkeypatch.setattr('teacher.image_ui.identify',identify)
    at=AppTest.from_file(str(APP))
    at.session_state['_private_data_root']=str(tmp_path/'data')
    at.run()
    button(at,'重新打开').click().run()
    button(at,'识别题目与图意').click().run()
    assert not at.exception and not at.session_state.busy
    assert identify.call_count==1 and identify.call_args.args[1]==[p]
    assert at.text_area(key='topic_text').value=='题目文字'
    at.run()
    assert identify.call_count==1
    button(at,'确认题目与图意').click().run()
    button(at,'确认原文').click().run()
    assert at.session_state.record.essay.picture_confirmation.method=='模型识别后人工确认'
