"""Plumbing tests use artificial scores; no test prescribes the student's score."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from markdown_it import MarkdownIt
from streamlit.testing.v1 import AppTest
import streamlit as st

from teacher.calibration import CalibrationCase,check_case,prepare_audit,load_cases,save_case
from teacher.config import load_scoring,LEGACY_PATH
from teacher.demo import demo_record
from teacher.models import Essay,Record,Subscore,ExpressionTip,LanguageEdit,CalibrationReview
from teacher.render import markdown_report,section_markdown
from teacher.report_flow import quality_issues,generation_issues,comparison_details,active_errors
from teacher.service import generate_report,GenerationFailure
from teacher.storage import save,load_all
from teacher.validation import report_errors,evidence_errors,validate_section


def reference_record(content=14,expression=15):
    r=demo_record()
    r.config=load_scoring()
    r.report.overview.subscores=[Subscore(name='内容',score=content),Subscore(name='表达',score=expression)]
    r.report.overview.score=content+expression
    return r


def verified_case(r,score=18):
    return CalibrationCase(id='anonymous-artificial-case',set_id=r.config.calibration_set,
        label='人工测试样例，非用户作文',source='离线测试人工构造，不是实际参考评分',
        reference_score=score,reference_subscores=[dict(name='内容',score=score//2),dict(name='表达',score=score-score//2)],
        maximum=40,reference_title=r.essay.title,reference_body=r.essay.body,
        reference_paragraphs=r.essay.paragraphs,reference_feedback='人工构造的参照说明，仅验证版本匹配与分数隔离。')


def test_new_profile_preserves_legacy_and_has_no_invented_bands():
    config=load_scoring(); legacy=load_scoring(LEGACY_PATH)
    assert config.name=='作文小老师参考评分 v1'
    assert config.maximum==40 and [(w.name,w.maximum) for w in config.weights]==[('内容',20),('表达',20)]
    assert config.calibration_set and not config.bands
    assert not legacy.weights and legacy.version=='teaching-40-v1'
    assert '用户' in config.source and '未经核实' not in config.name


@pytest.mark.parametrize('content,expression',[(8,10),(14,15),(19,18)])
def test_subscore_sum_and_ranges(content,expression):
    r=reference_record(content,expression)
    assert not report_errors(r.report,r.essay,r.config)
    r.report.overview.score+=1
    assert validate_section('overview',r.report.overview,r.essay,r.config)
    r.report.overview.score=21+expression
    r.report.overview.subscores[0].score=21
    assert validate_section('overview',r.report.overview,r.essay,r.config)


def test_legacy_config_and_new_fields_roundtrip(tmp_path):
    r=demo_record()
    raw=r.model_dump()
    for key in ('name','principles','calibration_set'):
        raw['config'].pop(key)
    raw.pop('calibration')
    for p in raw['report']['paragraphs']:
        p['teaching'].pop('is_key')
    for e in raw['report']['expressions']:
        e.pop('example_source')
    restored=Record.model_validate(raw)
    assert restored.calibration is None and not restored.config.weights
    assert restored.essay.version==r.essay.version and restored.report.overview.score==r.report.overview.score
    save(restored,tmp_path)
    records,warnings=load_all(tmp_path)
    assert records==[restored] and not warnings


def test_retained_expression_and_invented_example_are_independent():
    r=demo_record()
    tip=ExpressionTip(expression='重新',source='原文已有',
        location=dict(paragraph_id='P002',quote='我扶着椅子'),reason='结合本段配合过程。',
        example='我扶稳椅子，小明重新调整彩纸的位置。',example_source='教学新拟')
    assert not quality_issues('expressions',tip,r.essay,'expressions[0]')
    assert not validate_section('expressions',[tip],r.essay,r.config)
    assert not evidence_errors(tip,r.essay.paragraphs)
    tip.example_source='原文引用'
    assert quality_issues('expressions',tip,r.essay,'expressions[0]')==[('expressions[0].example','EXAMPLE_NOT_ORIGINAL')]
    assert validate_section('expressions',[tip],r.essay,r.config)
    assert comparison_details(tip,r.essay,'expressions[0]')[0]['path']=='expressions[0].example'
    tip.example_source='教学新拟'
    tip.location.quote='我稳稳地扶着椅子'
    assert evidence_errors(tip,r.essay.paragraphs)  # Exact student evidence is still required.


def test_clear_errors_are_split_from_optional_development():
    body='我觉得妹妹真令人讨厌并推了他一下。她哭了，我把耳机带上，继续玩游。'
    essay=Essay(title='人工纠错测试',body=body)
    combined=LanguageEdit(evidence=dict(paragraph_id='P001',quote=body),kind='可选优化',
        category='可优化但并非错误',replacement='我不耐烦地推开妹妹，索性戴上耳机继续玩游戏。',reason='整段错误分类示例',start=None)
    assert ('language[0].kind','CLEAR_ERROR_AS_OPTIONAL') in generation_issues('language',combined,essay,'language[0]')
    for quote,replacement,category in [('推了他一下','推了她一下','指代错误'),('把耳机带上','把耳机戴上','错别字'),('玩游','玩游戏','表达残缺')]:
        edit=LanguageEdit(evidence=dict(paragraph_id='P001',quote=quote),replacement=replacement,
            kind='明确错误',category=category,reason='具体纠错',start=None)
        assert not evidence_errors(edit,essay.paragraphs)
        assert not generation_issues('language',edit,essay,'language[0]')
    combined.evidence.quote='我觉得妹妹真令人讨厌'
    assert not generation_issues('language',combined,essay,'language[0]')


def test_new_example_defects_blocked_without_invalidating_historical_record(tmp_path):
    r=demo_record()
    r.report.paragraphs[0].example='买什么东西！因为尿布湿疹起了红点。'
    r.report.paragraphs[0].example_paragraphs=[r.report.paragraphs[0].example]
    issues=generation_issues('paragraphs',r.report.paragraphs[0],r.essay,'paragraphs[0]')
    assert {code for _,code in issues}=={'INVENTED_DIALOGUE_MEANING','UNSUPPORTED_MEDICAL_WORDING'}
    save(r,tmp_path)  # Old reports remain readable; new generation has stronger checks.
    assert load_all(tmp_path)[0]==[r]


def test_exact_version_includes_title_paragraphs_and_typos():
    r=reference_record(); case=verified_case(r)
    assert check_case(case,r.essay,r.config)['status']=='已确认同稿'
    for changed in [r.essay.model_copy(update={'title':'不同题目'}),
                    r.essay.model_copy(update={'body':r.essay.body.replace('椅子','椅了')}),
                    r.essay.model_copy(update={'body':r.essay.body.replace('\n','\n\n',1)})]:
        assert check_case(case,changed,r.config)['status']=='版本不一致'
    case.reference_paragraphs['P002']='另一段'
    assert check_case(case,r.essay,r.config)['status']=='版本不一致'


def test_pending_reference_is_not_treated_as_verified(tmp_path):
    r=reference_record()
    cases,warnings=load_cases(private=tmp_path)
    assert len(cases)==1 and not warnings and cases[0].reference_body is None
    audit,verified=prepare_audit(r.essay,r.config,cases)
    assert audit.status=='无可用同稿样例' and not verified
    client=Mock(); client.generate.return_value=r.report
    report=generate_report(client,r.essay,r.config,target_score=36,calibration_cases=cases)
    assert report==r.report.model_copy(update={'content_summary':None,'expression_summary':None}) and client.generate.call_count==2
    assert all('verified_reference' not in json.loads(call.args[2]) for call in client.generate.call_args_list)
    assert client.calibration_audit.case_checks[0]['status']=='待核对'


@pytest.mark.parametrize('reference_score',[18,34])
def test_independent_score_then_consistency_without_target_or_score_overwrite(reference_score,tmp_path):
    r=reference_record(); case=verified_case(r,reference_score)
    requests=[]
    def respond(schema,system,request):
        data=json.loads(request); requests.append(data)
        if schema is CalibrationReview:
            return dict(case_id=case.id,explanation='分歧来自对配合过程发展程度的判断不同；保留独立分项。',
                evidence=[dict(paragraph_id='P002',quote='我们重新贴好')])
        raw=r.report.model_dump()
        if len(requests)>1:
            raw['overview']['score']=40  # Unrequested changes must be ignored.
        return raw
    client=Mock(); client.generate.side_effect=respond
    report=generate_report(client,r.essay,r.config,target_score=36,calibration_cases=[case])
    assert report.overview==r.report.overview
    assert len(requests)==3
    assert requests[0]['generate_only']==['overview'] and 'verified_reference' not in requests[0] and 'teaching_goal' not in requests[0]
    assert requests[1]['independent_assessment']['score']==r.report.overview.score
    assert requests[1]['verified_reference']['reference_score']==reference_score and 'teaching_goal' not in requests[1]
    assert requests[2]['teaching_goal']['target_score']==36
    assert client.calibration_audit.status=='已完成一致性检查'
    r.report=report; r.calibration=client.calibration_audit
    save(r,tmp_path)
    assert load_all(tmp_path)[0]==[r]
    output=markdown_report(r)
    assert '系统本次独立评分' in output and '用户参考样本分数' in output and '相差' in output


def test_failed_consistency_preserves_independent_score_and_reports_incomplete_audit():
    r=reference_record(); case=verified_case(r)
    def respond(schema,system,request):
        if schema is CalibrationReview:
            return dict(case_id=case.id,explanation='模拟错误引用',evidence=[dict(paragraph_id='P002',quote='原文没有的示范句')])
        return r.report
    client=Mock(); client.generate.side_effect=respond
    result=generate_report(client,r.essay,r.config,calibration_cases=[case])
    assert result.overview==r.report.overview and client.generate.call_count==4
    assert client.calibration_audit.status=='一致性检查未完成' and client.calibration_audit.review is None


def test_real_button_markdown_payload_is_written_and_parsed(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    captured={}
    original=st.download_button
    def download(label,data,*args,**kwargs):
        if kwargs.get('mime')=='text/markdown':
            captured['payload']=data
        return original(label,data,*args,**kwargs)
    monkeypatch.setattr(st,'download_button',download)
    app=Path(__file__).resolve().parents[1]/'app.py'
    at=AppTest.from_file(str(app)).run()
    next(b for b in at.button if b.label=='打开离线演示').click().run()
    assert not at.exception
    path=tmp_path/'actual-download-payload.md'
    path.write_text(captured['payload'],encoding='utf-8')
    actual=path.read_text(encoding='utf-8')
    assert '|学生原句|问题类型|建议修改|修改原因|\n|---|---|---|---|\n|' in actual
    assert '\\|---' not in actual
    html=MarkdownIt('commonmark',{'html':True}).enable('table').render(actual)
    assert '<table>' in html and '<thead>' in html and '<tbody>' in html
    assert [x.label for x in at.expander]==['评分依据']
    positions=[actual.index(f'## {i}.') for i in range(1,7)]
    assert positions==sorted(positions) and positions[0]<actual.index('<details>')<positions[1]


def test_markdown_table_escapes_cells_without_breaking_rows():
    r=demo_record()
    r.report.language[0].reason='包含竖线|、换行\n以及星号*的说明'
    output=section_markdown(r)['language']
    rendered=MarkdownIt().enable('table').render(output)
    assert rendered.count('<td>')==4 and '<br>' in rendered


def test_new_profile_selection_does_not_mutate_history(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    app=Path(__file__).resolve().parents[1]/'app.py'
    at=AppTest.from_file(str(app)).run()
    assert at.selectbox(key='scoring_profile').value==load_scoring().version
    next(b for b in at.button if b.label=='打开离线演示').click().run()
    old=at.session_state.record.model_copy(deep=True)
    assert at.selectbox(key='scoring_profile').value==old.config.version
    at.selectbox(key='scoring_profile').select(load_scoring().version).run()
    assert not at.exception and at.session_state.record==old
    assert any('旧版本' in w.value for w in at.warning)
    next(b for b in at.button if b.label=='确认原文').click().run()
    assert at.session_state.record.config.version==load_scoring().version
    assert at.session_state.record.report is None and at.session_state.record.calibration.status=='无可用同稿样例'


def test_four_failed_field_shapes_repaired_without_disabling_quotes():
    # These are artificial candidates, not reconstructed raw replies from the user's log.
    from test_teaching_upgrade import teaching_record
    r=teaching_record()
    good=r.report.model_copy(deep=True)
    good.expressions=demo_record().report.expressions[:5]
    good.content_summary.existing_actions=[dict(paragraph_id='P004',quote='我关掉电脑陪着她')]
    from teacher.models import Evidence
    good.content_summary.existing_actions=[Evidence.model_validate(x) for x in good.content_summary.existing_actions]
    bad=good.model_copy(deep=True)
    for i in (0,2,4):
        bad.expressions[i].source='原文已有'
    bad.content_summary.existing_actions[0].quote='我关掉电脑，陪着妹妹。'
    client=Mock(); client.generate.return_value=bad
    with pytest.raises(GenerationFailure) as caught:
        generate_report(client,r.essay,r.config)
    events=active_errors(caught.value.state)
    assert {e['path'] for e in events}=={
        'expressions[0].expression','expressions[2].expression','expressions[4].expression'}
    retry=Mock(); retry.generate.return_value=good
    result=generate_report(retry,r.essay,r.config,resume=caught.value.state)
    assert result.overview==good.overview and not evidence_errors(result,r.essay.paragraphs)
    assert not [e for e in retry.generation_diagnostics if e['status'] in ('failed','stopped')]
    assert retry.generate.call_count==1
    schema,_,request=retry.generate.call_args.args
    assert set(schema.model_fields)=={'essay_version','expressions__0','expressions__2','expressions__4'}
    assert json.loads(request)['source_snippets']['P004']


def test_private_reference_storage_and_feedback_version(tmp_path):
    r=reference_record(); case=verified_case(r)
    before=check_case(case,r.essay,r.config)
    save_case(case,tmp_path)
    cases,warnings=load_cases(catalog=tmp_path/'empty',private=tmp_path)
    assert not warnings and cases==[case]
    assert cases[0].reference_body==r.essay.body
    case.reference_feedback='新的参考判断说明，不能复用旧的一致性说明。'
    after=check_case(case,r.essay,r.config)
    assert before['text_version']==after['text_version'] and before['reference_version']!=after['reference_version']
    invalid=case.model_dump(); invalid['id']='../outside'
    with pytest.raises(ValueError):
        save_case(invalid,tmp_path)
