from copy import deepcopy
from unittest.mock import Mock
import pytest
from pydantic import ValidationError
from teacher.demo import demo_record
from teacher.models import ScoringConfig, Weight, Essay, Evidence, LanguageEdit, SecondDraft, Implementation
from teacher.render import annotated_paragraph, markdown_report
from teacher.service import generate_report, generate_draft, GenerationFailure
from teacher.storage import save, load_all
from teacher.validation import report_errors, evidence_errors, draft_errors


def test_config():
    assert ScoringConfig().weights == []
    with pytest.raises(ValidationError):
        ScoringConfig(weights=[Weight(name='内容',maximum=20)])
    with pytest.raises(ValidationError):
        ScoringConfig(maximum=0)


@pytest.mark.parametrize('score',[-1,41])
def test_score_range(score):
    r=demo_record()
    r.report.overview.score=score
    assert report_errors(r.report,r.essay,r.config)


def test_subscores():
    from teacher.models import Subscore
    r=demo_record()
    r.report.overview.subscores=[Subscore(name='内容',score=20)]
    assert report_errors(r.report,r.essay,r.config)
    r.config.weights=[Weight(name='内容',maximum=20),Weight(name='表达',maximum=20)]
    r.report.overview.subscores=[Subscore(name='内容',score=20),Subscore(name='表达',score=7)]
    assert not report_errors(r.report,r.essay,r.config)
    r.report.overview.subscores[1].score=8
    assert report_errors(r.report,r.essay,r.config)


def test_quotes_and_ids():
    e=Essay(title='题',body='他笑了。他笑了。\n我也笑了。')
    assert not evidence_errors(Evidence(paragraph_id='P001',quote='他笑了。'),e.paragraphs)
    assert evidence_errors(Evidence(paragraph_id='P002',quote='他笑了。'),e.paragraphs)
    assert evidence_errors(Evidence(paragraph_id='P999',quote='他笑了。'),e.paragraphs)


def test_repeated_phrase_only_one_position():
    edit=LanguageEdit(evidence=Evidence(paragraph_id='P001',quote='他笑了。'),kind='明确错误',category='病句',
                      replacement='他微笑了。',reason='测试定位',start=4)
    text='他笑了。他笑了。'
    html=annotated_paragraph(text,[edit])
    assert html.count('<del>')==1
    assert html.startswith('<div class="original">他笑了。<del>')
    edit.start=None
    assert '<del>' not in annotated_paragraph(text,[edit])
    edit.start=1
    assert '<del>' not in annotated_paragraph(text,[edit])


def test_optional_not_rendered_as_error():
    r=demo_record()
    edit=r.report.language[0]
    edit.start=0
    assert '<del>' not in annotated_paragraph(edit.evidence.quote,[edit])
    edit.category='病句'
    assert report_errors(r.report,r.essay,r.config)


def test_version_and_original_immutable():
    r=demo_record()
    changed=r.essay.model_copy(update={'title':'新题目'})
    assert changed.version != r.essay.version
    assert report_errors(r.report,changed,r.config)
    with pytest.raises(ValidationError):
        r.essay.body='覆盖'
    assert list(r.essay.paragraphs)==['P001','P002','P003']


def test_storage_roundtrip_and_corruption(tmp_path):
    r=demo_record()
    save(r,tmp_path)
    save(r,tmp_path)
    assert len(list(tmp_path.glob('*.json')))==1
    (tmp_path/'broken.json').write_text('{bad',encoding='utf-8')
    records,warnings=load_all(tmp_path)
    assert records==[r] and len(warnings)==1
    assert not list(tmp_path.glob('*.tmp'))


def test_storage_invalid_and_failed_atomic_write(tmp_path,monkeypatch):
    import teacher.storage as storage
    r=demo_record()
    save(r,tmp_path)
    original=(tmp_path/f'{r.id}.json').read_bytes()
    monkeypatch.setattr(storage.os,'replace',Mock(side_effect=OSError('disk')))
    with pytest.raises(OSError):
        save(r,tmp_path)
    assert (tmp_path/f'{r.id}.json').read_bytes()==original
    assert not list(tmp_path.glob('*.tmp'))
    r.id='../escape'
    with pytest.raises(ValueError):
        save(r,tmp_path)


def test_invalid_structured_response_bounded_repair():
    r=demo_record()
    broken=r.report.model_dump()
    broken['overview']['score']=99
    fake=Mock()
    fake.generate.return_value=broken
    with pytest.raises(GenerationFailure) as exc:
        generate_report(fake,r.essay,r.config)
    assert fake.generate.call_count==2
    assert 'overview' not in exc.value.partial
    assert 'paragraphs' in exc.value.partial
    assert r.essay.body==demo_record().essay.body


def test_repair_success_and_missing_sections():
    r=demo_record()
    fake=Mock()
    fake.generate.side_effect=[{'essay_version':r.essay.version},r.report]
    assert generate_report(fake,r.essay,r.config)==r.report.model_copy(update={'content_summary':None,'expression_summary':None})
    assert fake.generate.call_count==2


def test_bad_quote_repair():
    r=demo_record()
    bad=deepcopy(r.report)
    bad.overview.content.evidence[0].quote='编造引文'
    fake=Mock()
    fake.generate.side_effect=[bad,r.report]
    assert generate_report(fake,r.essay,r.config)==r.report.model_copy(update={'content_summary':None,'expression_summary':None})


def test_html_safety():
    text='<script>alert("x")</script> & **正文**'
    html=annotated_paragraph(text,[])
    assert '<script>' not in html and '&lt;script&gt;' in html and '&amp;' in html
    r=demo_record()
    r.report.paragraphs[0].example=text
    r.report.paragraphs[0].example_paragraphs=[text]
    output=markdown_report(r)
    assert '<script>' not in output and '&lt;script&gt;' in output


def test_second_draft_evidence():
    r=demo_record()
    d=SecondDraft(essay_version=r.essay.version,body='我们把彩纸重新贴好。',
                  implementation=[Implementation(task_number=i,draft_quote='重新贴好',explanation='模拟任务落实说明') for i in (1,2,3)],optional_additions=[])
    assert not draft_errors(d,r.essay,r.report)
    d.implementation[0].draft_quote='编造证据'
    assert draft_errors(d,r.essay,r.report)
    fake=Mock()
    fake.generate.return_value=d
    with pytest.raises(GenerationFailure):
        generate_draft(fake,r.essay,r.config,r.report)
    assert fake.generate.call_count==2


def test_missing_image_warning():
    r=demo_record()
    r.essay=r.essay.model_copy(update={'kind':'看图作文'})
    assert '尚未核对图意' in markdown_report(r)


def test_sdk_adapter_no_paid_call():
    from teacher.client import ModelClient
    from teacher.models import Report
    client=ModelClient('fake-test-key','configured-model')
    client.client=Mock()
    from types import SimpleNamespace
    client.client.responses.create.return_value=SimpleNamespace(status='completed',output=[],
        output_text=demo_record().report.model_dump_json(),_request_id='req-offline')
    assert client.generate(Report,'system','payload')
    args=client.client.responses.create.call_args.kwargs
    assert args['model']=='configured-model' and args['store'] is False and args['text']['format']['type']=='json_schema'
