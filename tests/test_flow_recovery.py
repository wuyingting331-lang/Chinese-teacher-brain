"""Exercise actual SDK response boundary, incremental validation, merge, AppTest and export."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from hierarchy_sample import hierarchy_record
from teacher.client import ModelClient,ResponseFailure
from teacher.models import Record
from teacher.report_contract import SCHEMA_VERSION,RETIRED
from teacher.report_flow import GeneratedReport,SchemaVersionMismatch,section_values,active_errors
from teacher.report_migration import seed_from_legacy
from teacher.render import markdown_report,report_health,report_data
from teacher.service import generate_report,GenerationFailure,serialized
from teacher.storage import save,load_all


def fixed_response():
    r=hierarchy_record()
    raw=r.report.model_dump(exclude=RETIRED)
    ending=raw['structure'].pop()
    for pid in ('P005','P006'):
        row=deepcopy(ending); row['paragraph_ids']=[pid]
        raw['structure'].append(row)
    GeneratedReport.model_validate(raw)
    return r,raw


def response(raw,request_id='req-offline',status='completed'):
    return SimpleNamespace(status=status,_request_id=request_id,output=[],
        output_text=json.dumps(raw,ensure_ascii=False),incomplete_details=SimpleNamespace(reason='max_output_tokens'))


def sdk_client(*outputs):
    c=ModelClient('fake-offline-key','unchanged-configured-model')
    c.client=Mock(); c.client.responses.create.side_effect=list(outputs)
    return c


def partial_record(r,error):
    r.report=None; r.report_schema_version=SCHEMA_VERSION
    r.partial_state=error.state; r.diagnostics=error.diagnostics
    r.partial_sections=serialized(error.partial); r.incomplete_errors=error.errors
    return r


def ui(monkeypatch,tmp_path,r):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('teacher.client.settings',lambda secrets:('',''))
    monkeypatch.setattr('teacher.demo.demo_record',lambda:r)
    at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run()
    at.sidebar.button[0].click().run()
    assert not at.exception
    return at


def test_full_json_boundary_has_all_six_reviews_and_all_required_columns(monkeypatch,tmp_path):
    r,raw=fixed_response()
    c=sdk_client(response(raw))
    r.report=generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    r.report_schema_version=SCHEMA_VERSION
    h=report_health(r)
    assert h['complete'] and h['paragraphs']==6 and h['structure']==6 and h['tasks']==5
    assert c.client.responses.create.call_count==1
    assert not RETIRED.intersection(GeneratedReport.model_fields)
    at=ui(monkeypatch,tmp_path,r)
    assert not any('本段点评尚未完成' in e.value for e in at.info)
    assert len([x for x in at.markdown if x.value.startswith('### P')])==6
    for i in range(1,7):
        assert len([x for x in at.markdown if x.value.startswith(f'## {i}.')])==1
        assert f'## {i}.' in markdown_report(r)
    assert '不完整批改报告' not in markdown_report(r)


def test_old_whole_parse_failure_is_reproduced_but_five_reviews_now_survive(monkeypatch,tmp_path):
    r,raw=fixed_response(); bad=deepcopy(raw)
    bad['paragraphs'][3]['example_paragraphs']=[' '.join(bad['paragraphs'][3]['example_paragraphs'])]
    with pytest.raises(ValidationError):
        GeneratedReport.model_validate(bad)  # This formerly discarded the whole response.
    c=sdk_client(response(bad,'req-first'),response({'essay_version':r.essay.version,'paragraphs__3':bad['paragraphs'][3]},'req-repair'))
    with pytest.raises(GenerationFailure) as caught:
        generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    error=caught.value; values=section_values(error.state)
    assert len(values['paragraphs'])==5 and len(values['structure'])==6
    assert values['structure_overview']==raw['structure_overview']
    assert len(values['language'])==3 and len(values['expressions'])==2 and len(values['tasks'])==5
    assert {x['item_id'] for x in active_errors(error.state)}=={'P004'}
    r=partial_record(r,error)
    at=ui(monkeypatch,tmp_path,r)
    assert len([x for x in at.info if '本段点评尚未完成' in x.value])==1
    assert any('5/6段' in x.value and 'P004' in x.value for x in at.info)
    assert '5/6段' in markdown_report(r)
    assert not any('内容综合意见' in x.value or '表达综合意见' in x.value for x in at.info)
    save(r,tmp_path/'records')
    assert load_all(tmp_path/'records')[0][0].partial_state==r.partial_state
    assert c.last_exchange['api_request_id']=='req-repair'


def test_p004_quote_failure_keeps_other_language_and_all_reviews_then_merges():
    r,raw=fixed_response(); bad=deepcopy(raw)
    row=deepcopy(raw['language'][0])
    row.update(evidence=dict(paragraph_id='P004',quote='不存在的原句'),replacement='照顾妹妹')
    bad['language'].append(row)
    good=deepcopy(row); good['evidence']['quote']='我关掉电脑陪着她'
    c=sdk_client(response(bad),response({'essay_version':r.essay.version,'language__3':good},'req-fixed'))
    result=generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    assert len(result.paragraphs)==6 and len(result.language)==4 and len(result.structure)==6
    assert result.overview.model_dump()==raw['overview']
    assert not active_errors(c.generation_state)
    request=json.loads(c.client.responses.create.call_args.kwargs['input'][1]['content'])
    assert request['generate_only']==['language__3']


def test_failed_repair_cannot_overwrite_valid_score_or_valid_reviews():
    r,raw=fixed_response(); bad=deepcopy(raw)
    bad['paragraphs'][3]['teaching']['role']=''
    repair={'essay_version':r.essay.version,'paragraphs__3':bad['paragraphs'][3],'overview':dict(raw['overview'],score=40)}
    c=sdk_client(response(bad),response(repair))
    with pytest.raises(GenerationFailure) as caught:
        generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    values=section_values(caught.value.state)
    assert values['overview']==raw['overview']
    assert values['paragraphs']==[p for p in raw['paragraphs'] if p['paragraph_id']!='P004']
    assert caught.value.partial['paragraphs']


def test_out_of_order_rows_are_associated_by_id_not_list_position():
    r,raw=fixed_response(); raw['paragraphs']=list(reversed(raw['paragraphs']))
    c=sdk_client(response(raw))
    result=generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    assert [p.paragraph_id for p in result.paragraphs]==list(r.essay.paragraphs)


def test_missing_six_is_reported_as_six_not_two_error_paths(monkeypatch,tmp_path):
    r,raw=fixed_response()
    c=sdk_client(response({'essay_version':r.essay.version,'overview':raw['overview']}),
                 response({'essay_version':r.essay.version}))
    with pytest.raises(GenerationFailure) as caught:
        generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    r=partial_record(r,caught.value)
    at=ui(monkeypatch,tmp_path,r)
    assert any('0/6段' in x.value and '（6段）' in x.value for x in at.info)
    assert len([x for x in at.info if '本段点评尚未完成' in x.value])==6
    assert report_health(r)['missing_paragraph_ids']==list(r.essay.paragraphs)


def test_legacy_record_can_read_but_never_enters_new_repair_directly(tmp_path):
    r,raw=fixed_response()
    c=sdk_client(response(raw))
    generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    old=deepcopy(c.generation_state); old['format_version']='single-outline-v1'
    r.report=None; r.partial_state=old; r.partial_sections=section_values(old)
    assert report_data(r)[0]['paragraphs']
    with pytest.raises(SchemaVersionMismatch):
        generate_report(c,r.essay,r.config,resume=old)
    current,seed,path=seed_from_legacy(r,tmp_path/'snapshots')
    assert path.exists() and current.id!=r.id and not current.partial_state
    assert seed['overview']['score']==raw['overview']['score']
    assert set(seed)=={'overview'} and current.report_schema_version==SCHEMA_VERSION


def test_input_version_mismatch_is_rejected_before_api():
    r,raw=fixed_response(); c=sdk_client(response(raw))
    generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    changed=r.essay.model_copy(update={'body':r.essay.body+'改动'})
    with pytest.raises(ValueError,match='原文'):
        generate_report(c,changed,r.config,resume=c.generation_state)
    assert c.client.responses.create.call_count==1


@pytest.mark.parametrize('status,output,text,code',[
    ('incomplete',[], '{}','RESPONSE_INCOMPLETE'),
    ('completed',[SimpleNamespace(content=[SimpleNamespace(type='refusal')])],'','MODEL_REFUSAL'),
    ('completed',[],'{"broken":','JSON_DECODE_ERROR')])
def test_response_statuses_are_distinguished_and_request_ids_not_stale(status,output,text,code):
    r,raw=fixed_response()
    resp=response(raw,'req-current',status); resp.output=output; resp.output_text=text
    c=sdk_client(resp); c.last_request_id='req-stale'
    with pytest.raises(ResponseFailure) as caught:
        c.generate_raw(GeneratedReport,'system','{}')
    assert caught.value.code==code and c.last_request_id=='req-current'
    assert c.last_exchange['response_status']==status


def test_optional_teaching_field_absence_does_not_discard_other_columns():
    r,raw=fixed_response()
    raw['paragraphs'][3]['teaching'].pop('uncertainties')
    c=sdk_client(response(raw))
    result=generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    assert len(result.paragraphs)==6 and len(result.tasks)==5


def test_explicit_newlines_are_normalized_without_inventing_split_positions():
    r,raw=fixed_response()
    expected=list(raw['paragraphs'][3]['example_paragraphs'])
    raw['paragraphs'][3]['example_paragraphs']=['\n\n'.join(expected)]
    c=sdk_client(response(raw))
    result=generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    assert result.paragraphs[3].example_paragraphs==expected
    assert c.generation_state['exchanges'][0]['valid_counts']['paragraphs']==6
    assert c.generation_state['exchanges'][0]['complete'] is True


def test_request_failure_has_metadata_and_is_not_automatically_retried(tmp_path):
    r,raw=fixed_response()
    c=sdk_client(RuntimeError('private_exception_body'))
    with pytest.raises(RuntimeError):
        generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    assert c.client.responses.create.call_count==1
    assert c.last_exchange['response_status']=='request_failed'
    log=(tmp_path/'diagnostics/generation.jsonl').read_text(encoding='utf-8')
    assert 'private_exception_body' not in log and 'fake-offline-key' not in log
    assert 'request_failed' in log


def test_retired_failed_slots_never_trigger_requests_or_block_completion():
    r,raw=fixed_response(); c=sdk_client(response(raw))
    generate_report(c,r.essay,r.config,full_generation=True,calibration_cases=[])
    state=deepcopy(c.generation_state)
    for name in RETIRED:
        state['slots'][name]=dict(section=name,index=None,status='failed',value=None,repair_count=0)
    no_requests=sdk_client()
    result=generate_report(no_requests,r.essay,r.config,resume=state,calibration_cases=[])
    assert len(result.paragraphs)==6
    no_requests.client.responses.create.assert_not_called()
