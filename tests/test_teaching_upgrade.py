import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from teacher.demo import demo_record
from teacher.models import Essay, Record, ExpressionTip, Task, SecondDraft
from teacher.render import markdown_report, paragraph_comments
from teacher.report_flow import quality_issues,GeneratedParagraph,GeneratedTask
from teacher.service import generate_report, generate_draft
from teacher.validation import evidence_errors, draft_errors
from teaching_sample import p004_review
from teacher.report_view import example_text


def teaching_record():
    r=demo_record()
    body=list(r.essay.paragraphs.values())+['敲门声响了。我开门看见警察。警察提醒我去找妹妹。我找到妹妹。警察离开后，我替她换尿布，看见大腿上有红疹。我关掉电脑陪着她。']
    r.essay=Essay(title='一次教训（人工测试文本）',body='\n'.join(body))
    r.report.essay_version=r.essay.version
    r.report.paragraphs.append(p004_review())
    r.target_score=36
    r.report.tasks[0]=Task(location=dict(paragraph_id='P004',quote='我找到妹妹'),problem='转折跳跃',
        action='警察交代后写想起妹妹、呼喊寻找，再接照顾，拆成三段。',
        example='刚才还听见她哭，现在怎么没有声音了？我连忙回头喊：“妹妹！”',
        done='三个阶段连接清楚，原有补救行动全部保留。',focus='内容发展')
    r.report.expressions=[ExpressionTip(expression='关掉电脑',location=dict(paragraph_id='P004',quote='我关掉电脑陪着她。'),
        reason='实际补救行动值得保留。',example='我关掉电脑陪着她。',source='原文已有'),
        ExpressionTip(expression='心里一紧',location=dict(paragraph_id='P004',quote='我找到妹妹'),
        reason='担忧引出照顾动作。',example='看到妹妹脸上的泪痕，我心里一紧，赶紧走过去抱起她。',source='教学建议（新拟示例）')]
    return r


def test_old_record_roundtrip_preserves_version_and_missing_teaching():
    r=demo_record()
    old=r.model_dump()
    old.pop('target_score')
    for p in old['report']['paragraphs']:
        p.pop('teaching')
    for t in old['report']['tasks']:
        t.pop('example'); t.pop('focus')
    old['report']['expressions']=[t for t in old['report']['expressions'] if t['source']!='原文已有']
    restored=Record.model_validate(old)
    assert restored.target_score is None and restored.essay.version==r.essay.version
    assert all(p.teaching is None for p in restored.report.paragraphs)
    text=markdown_report(restored)
    assert '动作具体' in text and '为什么这样改更好' not in text
    assert '原文中值得保留的表达' not in text  # No fabricated legacy analysis.
    assert Record.model_validate_json(restored.model_dump_json())==restored


def test_new_fields_validation_and_screen_export_parity(monkeypatch,tmp_path):
    r=teaching_record()
    r.second_draft=SecondDraft(essay_version=r.essay.version,body=example_text(p004_review()),
        implementation=[dict(task_number=1,draft_quote='我加快脚步去找她',explanation='落实寻找与担忧的衔接。')],
        optional_additions=['可选坦白方案未写入正文。'],invented_details=['脚步和内心话为新拟具体化细节。'])
    assert not evidence_errors(r.report,r.essay.paragraphs)
    text=markdown_report(r)
    for label,value in paragraph_comments(r.report.paragraphs[-1]):
        assert label in text
    assert '原文中值得保留的表达' in text and '可融入本篇的提升表达' in text
    assert '已用于P004本段示范' in text and '修改自查' in text and '36/40' in text
    assert '评价维度：' not in text and '判断说明：' not in text
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('teacher.demo.demo_record',lambda:r)
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    app=Path(__file__).resolve().parents[1]/'app.py'
    at=AppTest.from_file(str(app)).run()
    next(b for b in at.button if b.label=='打开离线演示').click().run()
    assert not at.exception
    screen='\n'.join(x.value for x in at.markdown)+'\n'+'\n'.join(x.value for x in at.text)
    for label,_ in paragraph_comments(r.report.paragraphs[-1]):
        assert label in screen
    assert r.essay.paragraphs['P004'] in screen
    assert '沿用P004提升示范第1段' in screen and '落实寻找与担忧的衔接' in screen
    assert '沿用P004提升示范第1段' in text
    assert at.get('bidi_component')  # Downloads are browser-only; no public /media URL.
    assert '脚步和内心话为新拟具体化细节' in text
    at.number_input(key='goal_score').set_value(35).run()
    assert next(b for b in at.button if b.label=='确认原文').disabled is False
    assert at.session_state.record.target_score==36
    bad=p004_review().model_dump()
    bad['teaching']['issues'][0]['category']='随便一个类别'
    with pytest.raises(ValidationError):
        type(p004_review()).model_validate(bad)


@pytest.mark.parametrize('goal',[32,36,39])
def test_target_never_reaches_scoring_and_cannot_overwrite_score(goal):
    r=demo_record()
    requests=[]
    def respond(schema,system,request):
        data=json.loads(request); requests.append(data)
        raw=r.report.model_dump()
        raw['overview']['score']=r.report.overview.score if 'overview' in schema.model_fields else 40
        return raw
    client=Mock(); client.generate.side_effect=respond
    report=generate_report(client,r.essay,r.config,target_score=goal)
    assert len(requests)==2
    assert requests[0]['generate_only']==['overview']
    assert 'teaching_goal' not in requests[0]
    assert requests[1]['teaching_goal']['target_score']==goal
    assert 'overview' not in requests[1]['generate_only']
    assert report.overview==r.report.overview


def test_retained_expression_and_second_draft_content_evidence():
    r=teaching_record()
    for task in r.report.tasks[1:]:
        task.focus='其他'
    tip=r.report.expressions[0]
    assert not quality_issues('expressions',tip,r.essay,'expressions[0]')
    tip.expression='飞奔'
    assert quality_issues('expressions',tip,r.essay,'expressions[0]')
    tip.expression='关掉电脑'
    d=SecondDraft(essay_version=r.essay.version,body=example_text(p004_review()),
        implementation=[dict(task_number=2,draft_quote='我摘下耳机',explanation='局部动作')],optional_additions=[])
    assert any('主要内容修改' in x for x in draft_errors(d,r.essay,r.report))
    d.implementation[0].task_number=1
    assert not draft_errors(d,r.essay,r.report)
    client=Mock(); client.generate.return_value=d
    result=generate_draft(client,r.essay,r.config,r.report,target_score=36)
    assert result==d and json.loads(client.generate.call_args.args[2])['teaching_goal']==36


def test_goal_range_and_original_version_are_independent():
    r=demo_record(); version=r.essay.version
    with pytest.raises(ValidationError):
        Record(essay=r.essay,target_score=41)
    with pytest.raises(ValueError):
        generate_report(Mock(),r.essay,r.config,target_score=41)
    r.target_score=36
    assert r.essay.version==version


def test_generation_schema_requires_new_fields_but_storage_accepts_legacy():
    p=demo_record().report.paragraphs[0].model_dump()
    p.pop('teaching')
    from teacher.models import ParagraphReview
    assert ParagraphReview.model_validate(p).teaching is None
    with pytest.raises(ValidationError):
        GeneratedParagraph.model_validate(p)
    task=demo_record().report.tasks[0].model_dump()
    task.pop('example')
    assert Task.model_validate(task).example==''
    task.pop('title')
    with pytest.raises(ValidationError):
        GeneratedTask.model_validate(task)


def test_partial_legacy_paragraphs_render_without_fabrication():
    r=demo_record()
    values=r.report.model_dump()
    for p in values['paragraphs']:
        p.pop('teaching')
    r.report=None
    r.partial_sections={'paragraphs':values['paragraphs']}
    r.incomplete_errors=['tasks: 尚未完成']
    output=markdown_report(r)
    assert '**原文**' in output and '动作具体' in output
    assert '为什么这样改更好' not in output


def test_goal_guidance_repairs_only_failed_paragraph():
    r=demo_record()
    broken=r.report.model_dump()
    broken['paragraphs'][0]['teaching']['role']=''
    client=Mock(); client.generate.side_effect=[r.report,broken,r.report]
    result=generate_report(client,r.essay,r.config,target_score=36)
    assert result==r.report.model_copy(update={'content_summary':None,'expression_summary':None}) and client.generate.call_count==3
    schema,_,request=client.generate.call_args.args
    assert set(schema.model_fields)=={'essay_version','paragraphs__0'}
    assert json.loads(request)['teaching_goal']['target_score']==36
    assert any(e['section_id']=='paragraphs' and e['status']=='repaired' and e['repair_count']==1
               for e in client.generation_diagnostics)


def test_invalid_score_never_exposes_goal_or_proceeds_to_guidance():
    from teacher.service import GenerationFailure
    r=demo_record()
    bad=r.report.model_dump(); bad['overview']['score']=99
    client=Mock(); client.generate.return_value=bad
    with pytest.raises(GenerationFailure) as caught:
        generate_report(client,r.essay,r.config,target_score=36)
    assert client.generate.call_count==2
    assert all('teaching_goal' not in json.loads(call.args[2]) for call in client.generate.call_args_list)
    assert 'overview' not in caught.value.partial
