"""Anonymous Chinese examples: errors are simulated, never paid model calls."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
from teacher.demo import demo_record
from teacher.models import LanguageEdit,Evidence
from teacher.service import generate_report,GenerationFailure,serialized
from teacher.report_flow import section_values,active_errors,MAX_REPAIRS
from teacher.diagnostics import grouped_messages
from teacher.render import markdown_report,section_markdown,report_data
from teacher.storage import save,load_all


def broken_report():
    r=demo_record()
    r.demo=False
    good=r.report.model_copy(deep=True)
    # This ordinary Chinese sample has no student identifiers.
    edit=LanguageEdit(evidence=Evidence(paragraph_id='P002',quote='我扶着椅子'),kind='可选优化',
                      category='可优化但并非错误',replacement='我稳稳地扶住椅子',reason='动作更具体',start=None)
    good.language=[edit,edit.model_copy(deep=True),edit.model_copy(deep=True)]
    broken=good.model_copy(deep=True)
    broken.language[1].evidence.quote='我稳稳地扶着椅子'  # polished, not original
    broken.language[2].evidence.quote='我牢牢地扶着椅子'  # same section, second error
    broken.tasks[1].location.quote='我们终于完成了任务。'  # nonexistent sentence
    broken.structure[0].evidence[0].paragraph_id='P003'  # unique original is P001
    return r,good,broken


def failed_generation():
    r,good,broken=broken_report()
    fake=Mock()
    # Return the whole bad report from mock repair too; engine reads only targets.
    fake.generate.return_value=broken
    with pytest.raises(GenerationFailure) as caught:
        generate_report(fake,r.essay,r.config)
    return r,good,broken,caught.value,fake


def partial_record():
    r,good,broken,error,fake=failed_generation()
    r.report=None
    r.partial_sections=serialized(error.partial)
    r.partial_state=error.state
    r.incomplete_errors=error.errors
    r.diagnostics=error.diagnostics
    r.corrections=error.corrections
    return r,good,error,fake


def test_anonymous_reproduction_classification_and_dedup():
    r,good,broken,error,fake=failed_generation()
    events=active_errors(error.state)
    assert len(events)==3
    assert {e['section_id'] for e in events}=={'language','tasks'}
    assert {e['path'] for e in events}=={'language[1].evidence','language[2].evidence','tasks[1].location'}
    assert all(e['code']=='QUOTE_MISMATCH' and e['repair_count']==1 and e['status']=='failed' for e in events)
    assert all(e['paragraph_id'] in ('P002','P003') for e in events)
    messages=grouped_messages(error.diagnostics)
    assert len(messages)==2 and '语言修改' in messages[0] and '二稿计划' in messages[1]
    assert any('P003 → P001' in note for note in error.corrections)
    assert any(e['code']=='QUOTE_RELOCATED' and e['status']=='corrected' and e['paragraph_id']=='P001'
               for e in error.diagnostics)
    values=section_values(error.state)
    assert values['language']==[good.language[0].model_dump()]
    assert len(values['tasks'])==2
    assert values['structure'][0]['evidence'][0]['paragraph_id']=='P001'


def test_item_only_request_and_merge_preserves_score_and_valid_rows():
    r,good,broken,error,fake=failed_generation()
    schema,system,payload=fake.generate.call_args.args
    request=json.loads(payload)
    assert set(schema.model_fields)=={'essay_version','language__1','language__2','tasks__1'}
    assert 'language__0' in request['validated_items']
    assert request['paragraphs']==r.essay.paragraphs
    assert request['repair_errors'][0]['code']=='QUOTE_MISMATCH'
    assert request['candidate_comparisons'][0]['original_paragraph']
    repair=Mock()
    repair.generate.return_value={'essay_version':r.essay.version,
                                   'language__1':good.language[1].model_dump(),
                                   'language__2':good.language[2].model_dump(),
                                   'tasks__1':good.tasks[1].model_dump(),
                                   'overview':{'score':40}}  # unsolicited overwrite ignored
    result=generate_report(repair,r.essay,r.config,resume=error.state)
    assert result.overview==good.overview and result.language==good.language and result.tasks==good.tasks
    assert repair.generate.call_count==1
    assert not [e for e in repair.generation_diagnostics if e['status'] in ('failed','stopped')]
    assert any(e['status']=='repaired' and e['repair_count']==2 for e in repair.generation_diagnostics)


def test_stop_after_bounded_manual_repairs():
    r,good,broken,error,fake=failed_generation()
    state=error.state
    while any(s['status']=='failed' for s in state['slots'].values()):
        again=Mock()
        again.generate.return_value=broken
        with pytest.raises(GenerationFailure) as caught:
            generate_report(again,r.essay,r.config,resume=state)
        assert again.generate.call_count==1
        state=caught.value.state
    assert all(e['status']=='stopped' and e['repair_count']==MAX_REPAIRS for e in active_errors(state))
    never=Mock()
    with pytest.raises(GenerationFailure):
        generate_report(never,r.essay,r.config,resume=state)
    never.generate.assert_not_called()
    assert all('上限' in m for m in grouped_messages(state['diagnostics']))


def test_partial_storage_keeps_valid_entries_and_safe_diagnostics(tmp_path):
    r,good,error,fake=partial_record()
    save(r,tmp_path)
    loaded,warnings=load_all(tmp_path)
    assert not warnings
    values,_=report_data(loaded[0])
    assert values['language']==[good.language[0]] and len(values['tasks'])==2
    # Failed candidate text never reaches saved state/diagnostics.
    backup=(tmp_path/f'{r.id}.json').read_text(encoding='utf-8')
    assert '我稳稳地扶着椅子' not in backup
    assert any(d['candidate_quote']=='我稳稳地扶着椅子' for d in error.details)


def test_formal_partial_markdown_not_recursive_fields():
    r,good,error,fake=partial_record()
    text=markdown_report(r)
    assert '不完整批改报告' in text
    assert '|学生原句|问题类型|建议修改|修改原因|' in text
    assert '总分：27/40' in text
    assert '## 2. 故事结构与详略建议' in text and '## 6. 二稿执行清单' in text
    assert '**第' not in text and '第2项' in text
    assert '**分项**' not in text and '图意核对' not in text
    assert '**paragraph_id**' not in text and '**evidence**' not in text
    assert '我稳稳地扶着椅子' not in text
    assert '- [ ] 任务3' in text and '- [ ] 任务2' not in text


def test_streamlit_partial_layout_and_dedup(monkeypatch,tmp_path):
    r,good,error,fake=partial_record()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    save(r)
    at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'))
    at.session_state['_private_data_root']=str(tmp_path/'data')
    at.run()
    next(x for x in at.button if x.label=='重新打开').click().run()
    assert not at.exception
    assert any('语言修改仍有未通过' in x.value for x in at.info)
    assert any('二稿清单尚无完整' in x.value for x in at.info)
    contents='\n'.join(x.value for x in at.markdown)
    assert '|学生原句|问题类型|建议修改|修改原因|' in contents
    assert '<div class="original">' in contents
    assert len(at.get('column'))>=6
    assert '## 4. 语言修改表（不完整）' in contents
    assert '**分项**' not in contents and '图意核对' not in contents


def test_teaching_checks_reject_technique_as_expression_and_new_language_error():
    from teacher.report_flow import quality_issues
    r=demo_record()
    tip=r.report.expressions[0]
    tip.expression='强化心理描写'
    tip.example='我带上耳机。'
    codes={code for _,code in quality_issues('expressions',tip,r.essay,'expressions[0]')}
    assert codes=={'EXPRESSION_NOT_CONCRETE','EXAMPLE_LANGUAGE_ERROR'}


def test_missing_required_entries_cannot_be_completed_by_dropping_rows():
    r,good,broken=broken_report()
    bad=broken.model_dump()
    bad['tasks']=bad['tasks'][:1]
    fake=Mock()
    fake.generate.return_value=bad
    with pytest.raises(GenerationFailure) as error:
        generate_report(fake,r.essay,r.config)
    assert any(e['section_id']=='tasks' and e['code'].startswith('SCHEMA_') for e in active_errors(error.value.state))
    assert len(section_values(error.value.state)['tasks'])==1


def test_streamlit_success_clears_partial_state_and_messages(monkeypatch,tmp_path):
    r,good,error,_=partial_record()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('fake-key','configured-model'))
    client=Mock()
    client.generate.return_value={'essay_version':r.essay.version,
                                  'language__1':good.language[1].model_dump(),
                                  'language__2':good.language[2].model_dump(),
                                  'tasks__1':good.tasks[1].model_dump()}
    monkeypatch.setattr('teacher.client.ModelClient',lambda *args:client)
    save(r)
    at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'))
    at.session_state['_private_data_root']=str(tmp_path/'data')
    at.run()
    next(x for x in at.button if x.label=='重新打开').click().run()
    next(x for x in at.button if x.label=='修复未完成栏目').click().run()
    assert not at.exception
    result=at.session_state.record
    assert result.report and not result.partial_state and not result.incomplete_errors and not result.partial_sections
    assert not [e for e in result.diagnostics if e['status'] in ('failed','stopped')]
    assert not [x for x in at.warning if '报告不完整' in x.value]
    assert not [x for x in at.info if '有效条目已保留' in x.value]
    at.run()
    assert client.generate.call_count==1


def test_motivation_context_and_action_evidence():
    from teacher.report_flow import quality_issues
    from teacher.models import Essay
    r=demo_record()
    essay=Essay(title='责任',body='我不想离开电脑，索性戴上耳机。\n我关掉电脑，给妹妹换尿布，又坐在一旁陪她。')
    edit=LanguageEdit(evidence=Evidence(paragraph_id='P001',quote='索性戴上耳机'),kind='可选优化',
                      category='可优化但并非错误',replacement='我只好把耳机戴上',reason='示例',start=None)
    assert any(code=='MOTIVATION_CHANGED' for _,code in quality_issues('language',edit,essay,'language[0]'))
    from teacher.models import Balance,Judgment
    balance=Balance(strength=Judgment(text='有实际补救行动',evidence=[Evidence(paragraph_id='P002',quote='我关掉电脑，给妹妹换尿布，又坐在一旁陪她。')],scope='内容发展',reasoning='关电脑、换尿布和陪伴都是动作，不只是心理发誓'),
                    weakness=Judgment(text='后续坚持可进一步交代',evidence=[Evidence(paragraph_id='P002',quote='又坐在一旁陪她')]),
                    existing_actions=[Evidence(paragraph_id='P002',quote='我关掉电脑，给妹妹换尿布，又坐在一旁陪她。')])
    from teacher.validation import evidence_errors
    assert not evidence_errors(balance,essay.paragraphs)


def test_sdk_schema_failure_keeps_precise_field_path_without_input(caplog):
    from pydantic import ValidationError
    from teacher.models import Report
    r=demo_record()
    broken=r.report.model_dump()
    broken['language'][0]['evidence']['quote']=''
    with pytest.raises(ValidationError) as parsed:
        Report.model_validate(broken)
    fake=Mock()
    fake.generate.side_effect=parsed.value
    with pytest.raises(GenerationFailure) as caught:
        generate_report(fake,r.essay,r.config)
    diagnostics=active_errors(caught.value.state)
    assert any(e['path']=='language[0].evidence.quote' and e['code']=='SCHEMA_STRING_TOO_SHORT' for e in diagnostics)
    assert r.essay.body not in caplog.text
