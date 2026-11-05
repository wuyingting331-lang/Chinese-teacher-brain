"""Structural contracts and references, not keyword/length proxies for teaching quality."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from markdown_it import MarkdownIt
from streamlit.testing.v1 import AppTest

from hierarchy_sample import hierarchy_record
from teacher.demo import demo_record
from teacher.models import Record,ParagraphReview,LanguageEdit,SecondDraft
from teacher.render import markdown_report,markdown_draft,section_markdown,md,report_data,paragraph_comments
from teacher.report_flow import GeneratedReport,GeneratedParagraph,GeneratedExpression,checked_state,initial_state,ingest_section,check_slot
from teacher.report_view import REPORT_ORDER,example_paragraphs,example_text,language_view,tasks_view
from teacher.service import generate_report,GenerationFailure
from teacher.storage import save,load_all
from teacher.validation import report_errors,evidence_errors,reference_errors


def test_new_generation_has_one_task_set_and_canonical_example_arrays():
    r=hierarchy_record()
    generated=GeneratedReport.model_validate(r.report.model_dump(exclude={'content_summary','expression_summary'}))
    assert 'content_summary' not in type(generated).model_fields and 'expression_summary' not in type(generated).model_fields
    assert len(generated.overview.strengths)==2 and generated.overview.problems==[]
    assert generated.overview.level is None and generated.overview.higher_level_gap is None
    assert 'priority_tasks' not in type(generated).model_fields and 'focus_paragraph' not in type(generated).model_fields
    assert all(not p.example and p.example_paragraphs for p in generated.paragraphs)
    assert all(t.title and t.paragraph_ids and not any([t.problem,t.action,t.done,t.example,t.location]) for t in generated.tasks)
    assert not report_errors(generated,r.essay,r.config)
    assert not evidence_errors(generated,r.essay.paragraphs)


def test_report_order_and_original_example_once_in_export():
    r=hierarchy_record()
    exported=markdown_report(r)
    positions=[exported.index(f'## {i}.') for i in range(1,7)]
    assert positions==sorted(positions)
    assert list(k for k in section_markdown(r) if k!='basis')==list(REPORT_ORDER)
    for original in r.essay.paragraphs.values():
        assert exported.count(md(original))==1
    for p in r.report.paragraphs:
        for block in example_paragraphs(p):
            assert exported.count(md(block))==1
    assert '重点段落提升' not in exported and '完整二稿计划与补充意见' not in exported
    assert exported.count('## 2. 故事结构与详略建议')==1
    assert exported.count('## 3. 逐段修改指导')==1
    p4=r.report.paragraphs[3]
    assert '\n\n'.join(md(x) for x in p4.example_paragraphs) in exported
    assert '### P004 · 重点修改' in exported


def test_overview_checklist_are_references_without_long_teaching_copies():
    r=hierarchy_record()
    blocks=section_markdown(r)
    refs=tasks_view(r.report.tasks)
    for t in refs[:3]:
        assert t.title in blocks['overview'] and t.title in blocks['checklist']
    assert '本段示范修改' not in blocks['overview'] and '完成标准' not in blocks['checklist']
    for original in r.essay.paragraphs.values():
        assert md(original) not in blocks['overview'] and md(original) not in blocks['checklist']
    for p in r.report.paragraphs:
        for block in p.example_paragraphs:
            assert md(block) not in blocks['overview'] and md(block) not in blocks['checklist']
    assert blocks['checklist'].count('- [ ]')==len(refs)


def test_layout_table_fields_and_combined_references_render_as_table():
    r=hierarchy_record()
    section=section_markdown(r)['structure']
    assert md(r.report.structure_overview) in section
    parser=MarkdownIt().enable('table')
    html=parser.render(section)
    assert html.count('<th>')==4 and html.count('<td>')==4*len(r.report.structure)
    for row in r.report.structure:
        assert '、'.join(row.paragraph_ids) in section
        assert md(row.problem) in section and md(row.arrangement) in section
        for operation in row.adjustments:
            assert operation in section
    assert 'P005、P006' in section
    assert '本段示范修改' not in section


def test_generation_rejects_split_label_without_real_paragraphs():
    raw=hierarchy_record().report.paragraphs[3].model_dump()
    raw['example_paragraphs']=[' '.join(raw['example_paragraphs'])]
    with pytest.raises(ValidationError,match='分段标签'):
        GeneratedParagraph.model_validate(raw)
    raw['example_paragraphs']=['第一段\n第二段','第三段']
    with pytest.raises(ValidationError,match='自然段'):
        GeneratedParagraph.model_validate(raw)
    raw['example_paragraphs']=['第一段','第二段']
    assert len(GeneratedParagraph.model_validate(raw).example_paragraphs)==2


def test_legacy_single_string_scope_warning_and_score_unchanged(tmp_path):
    r=hierarchy_record()
    raw=r.model_dump()
    raw.pop('completed_tasks')
    raw['report'].pop('structure_overview')
    for p in raw['report']['paragraphs']:
        p['example']=' '.join(p.pop('example_paragraphs'))
    # All new structure fields absent: old advice is adapted, not manufactured.
    for row in raw['report']['structure']:
        row['action']=row['arrangement']
        row['effect']=row['problem']
        row['evidence']=[dict(paragraph_id=pid,quote=r.essay.paragraphs[pid]) for pid in row['paragraph_ids']]
        for key in ('paragraph_ids','problem','adjustments','arrangement'):
            row.pop(key)
    old=Record.model_validate(raw)
    score=old.report.overview.model_dump()
    output=markdown_report(old)
    assert '没有保存对应分段' in output and '旧记录未单列全篇布局判断' in output
    assert old.report.overview.model_dump()==score
    save(old,tmp_path)
    records,warnings=load_all(tmp_path)
    assert records==[old] and not warnings


def test_old_partial_state_adapts_missing_layout_field_without_hiding_failures():
    r=demo_record()
    state=initial_state(r.essay)
    for name in list(state['slots']):
        ingest_section(state,name,getattr(r.report,name),r.essay,r.config,[])
    del state['slots']['structure_overview']
    state['format_version']='single-outline-v1'
    state['slots']['content_summary']=dict(section='content_summary',index=None,status='failed',value=None,repair_count=1)
    restored=checked_state(state,r.essay,r.config)
    assert restored['slots']['structure_overview']['status']=='valid'
    assert restored['slots']['structure_overview']['value']==''
    r.report=None; r.partial_state=restored; r.incomplete_errors=['content_summary: QUOTE_MISMATCH']
    values,unfinished=report_data(r)
    assert 'content_summary' not in unfinished and 'structure_overview' not in unfinished
    output=markdown_report(r)
    assert '历史格式的附加诊断' in output and '旧记录未单列' in output
    assert '内容综合意见' not in output


def test_identical_character_correction_long_short_overlap_is_one_row():
    r=hierarchy_record()
    short=r.report.language[0]
    long=short.model_copy(deep=True)
    long.evidence.quote='我嫌她烦，就推了他一下。'
    long.replacement='我嫌她烦，就推了她一下。'
    rows=language_view([long,short,r.report.language[1]],r.essay.paragraphs)
    assert len(rows)==2 and rows[0][1].evidence.quote==short.evidence.quote
    r.report.language=[long,short,r.report.language[1]]
    assert MarkdownIt().enable('table').render(section_markdown(r)['language']).count('<td>')==8


def test_same_words_at_different_offsets_and_different_changes_are_preserved():
    quote='推了他一下'
    paragraph='他推了他一下，后来又推了他一下。'
    first=LanguageEdit(evidence=dict(paragraph_id='P001',quote=quote),replacement='推了她一下',
        kind='明确错误',category='指代错误',reason='第一处',start=paragraph.index(quote))
    second=first.model_copy(deep=True); second.start=paragraph.rindex(quote)
    third=first.model_copy(deep=True); third.replacement='推了它一下'
    assert len(language_view([first,second,third],{'P001':paragraph}))==3


def test_expression_only_refers_to_canonical_paragraph_example():
    r=hierarchy_record()
    section=section_markdown(r)['expressions']
    assert '已用于P004本段示范' in section
    for p in r.report.paragraphs:
        for block in p.example_paragraphs:
            assert md(block) not in section
    raw=r.report.expressions[0].model_dump()
    raw['example']='另外一份重复句子'
    with pytest.raises(ValidationError,match='不再另存'):
        GeneratedExpression.model_validate(raw)


def test_new_task_structure_and_expression_refs_are_validated():
    r=hierarchy_record()
    for section,value in [('tasks',r.report.tasks[0]),('structure',r.report.structure[0])]:
        bad=value.model_copy(deep=True); bad.paragraph_ids=['P999']
        assert reference_errors(section,bad,r.essay,section)
    tip=r.report.expressions[0].model_copy(deep=True); tip.used_in_paragraph_id='P999'
    assert reference_errors('expressions',tip,r.essay,'expressions')


def test_streamlit_single_original_and_example_blocks_and_checklist(monkeypatch,tmp_path):
    r=hierarchy_record()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    monkeypatch.setattr('teacher.demo.demo_record',lambda:r)
    app=Path(__file__).resolve().parents[1]/'app.py'
    at=AppTest.from_file(str(app)).run()
    at.sidebar.button[0].click().run()
    assert not at.exception
    markdowns=[e.value for e in at.markdown]
    texts=[e.value for e in at.text]
    for original in r.essay.paragraphs.values():
        assert sum(s.count(original) for s in markdowns)==1
    for p in r.report.paragraphs:
        for block in p.example_paragraphs:
            assert texts.count(block)==1
    assert [x.label for x in at.expander]==['评分依据']
    for i in range(1,7):
        assert len([s for s in markdowns if s.startswith(f'## {i}.')])==1
    checkbox=next(c for c in at.checkbox if str(c.key).startswith('checklist_'))
    checkbox.check().run()
    assert not at.exception and at.session_state.record.completed_tasks==[1]
    assert '- [x] 任务1' in markdown_report(at.session_state.record)
    assert at.session_state.record.report.overview.score==r.report.overview.score
    at.sidebar.button[0].click().run()
    assert not at.exception and at.session_state.record.completed_tasks==[]


def test_failed_new_layout_field_remains_visible_and_repairable():
    r=hierarchy_record()
    broken=r.report.model_dump()
    broken['structure'][0]['paragraph_ids']=['P999']
    client=Mock(); client.generate.return_value=broken
    with pytest.raises(GenerationFailure) as caught:
        generate_report(client,r.essay,r.config,calibration_cases=[])
    r.report=None; r.partial_state=caught.value.state; r.incomplete_errors=caught.value.errors
    output=markdown_report(r)
    assert '故事结构与详略建议（不完整）' in output and '第1项尚未完成' in output
    assert 'P999' not in section_markdown(r)['structure']
    r.partial_state['slots']['structure_overview'].update(status='failed',value=None)
    assert '全篇布局判断尚未完成' in section_markdown(r)['structure']


def test_retained_original_is_referenced_instead_of_printed_again():
    r=demo_record()
    assert r.report.paragraphs[0].example_paragraphs==[r.essay.paragraphs['P001']]
    output=markdown_report(r)
    assert output.count(md(r.essay.paragraphs['P001']))==1
    assert '保留原段，见本段原文' in output


def test_retired_summaries_are_not_current_required_columns():
    r=demo_record()
    state=initial_state(r.essay)
    ingest_section(state,'content_summary',r.report.content_summary.model_dump(),r.essay,r.config,[])
    assert 'content_summary' not in state['slots']
    assert r.report.content_summary is not None  # Historical source remains intact.


def test_same_exact_correction_with_conflicting_legacy_categories_is_not_duplicated():
    r=hierarchy_record()
    first=r.report.language[0]
    second=first.model_copy(update={'category':'病句'})
    rows=language_view([first,second],r.essay.paragraphs)
    assert len(rows)==1 and '分类不一致，待核对' in rows[0][1].reason
    assert first.reason!=rows[0][1].reason  # Source record is not rewritten.


def test_optional_draft_reuses_existing_full_examples_by_reference():
    r=hierarchy_record()
    p=r.report.paragraphs[3]
    body=example_text(p)
    r.second_draft=SecondDraft(essay_version=r.essay.version,body=body,optional_additions=[],
        implementation=[dict(task_number=1,draft_quote=p.example_paragraphs[0],explanation='此处落实外部提醒与担忧的衔接。')])
    report=markdown_report(r)
    standalone=markdown_draft(r)
    for block in p.example_paragraphs:
        assert report.count(md(block))==1
        assert standalone.count(md(block))==1
    assert '沿用P004提升示范第1段' in report
    assert r.second_draft.body==body


def test_successful_new_generation_roundtrip_uses_the_same_guidance_and_tasks():
    r=hierarchy_record()
    client=Mock(); client.generate.return_value=GeneratedReport.model_validate(r.report.model_dump(exclude={'content_summary','expression_summary'}))
    result=generate_report(client,r.essay,r.config,target_score=36,calibration_cases=[])
    assert result.overview.score==r.report.overview.score
    assert result.paragraphs[3].example_paragraphs==r.report.paragraphs[3].example_paragraphs
    assert result.tasks==r.report.tasks and result.content_summary is None and result.expression_summary is None
    assert not report_errors(result,r.essay,r.config)


def test_failed_legacy_structure_cannot_drop_its_required_quotes():
    r=demo_record()
    state=initial_state(r.essay)
    ingest_section(state,'structure',[r.report.structure[0]],r.essay,r.config,[])
    candidate=r.report.structure[0].model_dump()
    candidate['evidence']=[]
    check_slot(state,'structure__0',candidate,r.essay,r.config,[],repair=True)
    assert state['slots']['structure__0']['status']=='failed'
