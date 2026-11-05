import json
from copy import deepcopy
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
from teacher.service import generate_draft, GenerationFailure
from teacher.models import Record
from teacher.render import markdown_report
from hierarchy_sample import hierarchy_record


def raw_draft(r):
    return dict(essay_version=r.essay.version,body='我摘下耳机，呼喊妹妹。我低下头，想起她的哭声。',
        implementation=[dict(task_number=i,draft_quote='我摘下耳机，呼喊妹妹。',explanation='补上行动与反应。') for i in range(1,len(r.report.tasks)+1)],
        optional_additions=[],invented_details=['呼喊的动作为新拟细节。'])


def client(*responses):
    c=Mock(); c.generate.side_effect=responses
    return c


@pytest.fixture(autouse=True)
def isolate_logs(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_normal_and_shared_quote_allowed():
    r=hierarchy_record(); raw=raw_draft(r); state={}
    c=client(raw)
    d=generate_draft(c,r.essay,r.config,r.report,state=state)
    assert d.body==raw['body'] and state['errors']==[] and c.generate.call_count==1
    assert state['notes_status']=='valid'


def test_body_preserved_only_notes_retried_then_cleared():
    r=hierarchy_record(); report=r.report.model_dump(); raw=raw_draft(r)
    bad=deepcopy(raw); bad['implementation'][0]['draft_quote']='来自计划而不在二稿里的话'
    c=client(bad,{'implementation':bad['implementation']}); state={}
    with pytest.raises(GenerationFailure):
        generate_draft(c,r.essay,r.config,r.report,state=state)
    assert state['body_status']=='valid' and state['notes_status']=='failed'
    assert state['errors'][0]['code']=='DRAFT_QUOTE_MISMATCH'
    assert state['errors'][0]['path']=='implementation[0].draft_quote'
    assert c.generate.call_args.args[0].__name__=='DraftNotes'
    request=json.loads(c.generate.call_args.args[2])
    assert request['validated_draft']['body']==raw['body']
    assert 'report' not in request and 'source_snippets' not in request and 'essay' not in request
    assert r.report.model_dump()==report
    retry=client({'implementation':raw['implementation'],'body':'不能覆盖正文'})
    d=generate_draft(retry,r.essay,r.config,r.report,state=state)
    assert d.body==raw['body'] and state['errors']==[] and state['notes_status']=='valid'
    assert 'unverified_implementation' not in state


def test_body_parse_failure_shows_unverified_not_complete():
    r=hierarchy_record(); raw=raw_draft(r); raw['essay_version']='wrong'
    state={}
    with pytest.raises(GenerationFailure):
        generate_draft(client(raw,raw),r.essay,r.config,r.report,state=state)
    assert state['body_status']=='failed' and state['errors'][0]['code']=='VERSION_MISMATCH'
    assert state['unverified_body']==raw['body'] and 'body' not in state


def ui(record):
    script='''import streamlit as st
from teacher.models import Record
from teacher.render import show_second_draft
r=Record.model_validate(st.session_state.r)
show_second_draft(st,r)
'''
    at=AppTest.from_string(script)
    at.session_state.r=record.model_dump()
    return at.run()


def test_actual_ui_partial_body_and_saved_state():
    r=hierarchy_record(); raw=raw_draft(r); raw['implementation']=[]
    with pytest.raises(GenerationFailure):
        generate_draft(client(raw,raw),r.essay,r.config,r.report,state=r.draft_state)
    restored=Record.model_validate_json(r.model_dump_json())
    at=ui(restored)
    assert not at.exception
    assert any('只重试落实说明' in x.value for x in at.warning)
    assert any(x.value==raw['body'] for x in at.text)
    assert '修改落实说明未完成' in markdown_report(restored)
    restored.draft_state['body_status']='failed'; restored.draft_state['unverified_body']=raw['body']
    at=ui(restored)
    assert not at.exception and any(x.label=='未验证草稿' for x in at.expander)


def test_parse_missing_implementation_does_not_discard_body():
    r=hierarchy_record(); raw=raw_draft(r); del raw['implementation']
    state={}
    with pytest.raises(GenerationFailure):
        generate_draft(client(raw,{}),r.essay,r.config,r.report,state=state)
    assert state['body_status']=='valid'
    assert any(e['path']=='implementation' and e['code']=='SCHEMA_PARSE_ERROR' for e in state['errors'])


def test_real_client_raw_boundary_and_successful_notes_repair():
    from test_flow_recovery import sdk_client, response
    r=hierarchy_record(); raw=raw_draft(r); bad=deepcopy(raw)
    bad['implementation'][0]['draft_quote']='这句话只在计划里'
    c=sdk_client(response(bad),response({'implementation':raw['implementation']},'req-notes'))
    state={}
    d=generate_draft(c,r.essay,r.config,r.report,state=state)
    assert d.body==raw['body'] and state['errors']==[]
    assert c.client.responses.create.call_count==2
    assert state['exchanges'][-1]['api_request_id']=='req-notes'
    assert state['exchanges'][-1]['parse_status']=='json_decoded'


def test_incomplete_response_is_not_reported_as_quote_failure():
    from test_flow_recovery import sdk_client, response
    r=hierarchy_record()
    first=response({}); first.status='incomplete'
    second=response({}); second.status='incomplete'
    c=sdk_client(first,second); state={}
    with pytest.raises(GenerationFailure):
        generate_draft(c,r.essay,r.config,r.report,state=state)
    assert state['errors'][0]['code']=='RESPONSE_INCOMPLETE'
    assert state['errors'][0]['path']=='response'
    assert state['body_status']=='failed'
