"""Explicitly authorized bounded integration: same configured model, synthetic anonymous essay, <=2 calls."""
import json
from pathlib import Path
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))

from hierarchy_sample import hierarchy_record
from teacher.client import ModelClient,settings,ResponseFailure
from teacher.service import generate_report,GenerationFailure,serialized
from teacher.render import report_health,markdown_report
from teacher.report_contract import SCHEMA_VERSION
from teacher.prompts import VERSION


class BoundedClient(ModelClient):
    def __init__(self,key,model):
        super().__init__(key,model)
        self.calls=0
        self.history=[]

    def generate_raw(self,*args,**kwargs):
        if self.calls>=2:
            raise ResponseFailure('INTEGRATION_BUDGET_EXHAUSTED')
        self.calls+=1
        print(json.dumps({'event':'request_started','call':self.calls}),flush=True)
        try:
            return super().generate_raw(*args,**kwargs)
        finally:
            self.history.append(dict(self.last_exchange))
            print(json.dumps({'event':'request_finished','call':self.calls,**self.last_exchange}),flush=True)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    key,model=settings()
    try:
        import tomllib
        path=ROOT/'.streamlit'/'secrets.toml'
        secrets=tomllib.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not key or not model:
            key,model=settings(secrets)
    except (OSError,ValueError):
        pass
    directory=ROOT/'data'/'integration'/'flow-recovery'
    directory.mkdir(parents=True,exist_ok=True)
    r=hierarchy_record()
    # The fixed response and its placeholder score are never sent as input or used as a seed.
    r.report=None
    r.demo=False  # This is a real model response on a clearly labelled synthetic essay.
    r.prompt_version=VERSION
    r.target_score=None
    r.model_name=model
    r.report_schema_version=SCHEMA_VERSION
    result={'time_utc':datetime.now(timezone.utc).isoformat(),'schema_version':SCHEMA_VERSION,
            'material':'synthetic_anonymous_six_paragraph_test_not_user_original',
            'model':model,'api_calls':0,'maximum_api_calls':2,'live_api':False}
    client=None
    if not key or not model:
        result['limitation']='OPENAI_API_KEY or OPENAI_MODEL is not configured'
    else:
        client=BoundedClient(key,model)
        try:
            r.report=generate_report(client,r.essay,r.config,calibration_cases=[],full_generation=True)
            result['live_api']=True
            result['score']=r.report.overview.score
            result['subscores']=[x.model_dump() for x in r.report.overview.subscores]
            result['state_exchanges']=client.generation_state.get('exchanges',[])
        except GenerationFailure as error:
            result['live_api']=any(x.get('response_status')=='completed' for x in client.history)
            r.partial_state=error.state
            r.partial_sections=serialized(error.partial)
            r.incomplete_errors=error.errors
            r.diagnostics=error.diagnostics
            result['state_exchanges']=error.state.get('exchanges',[])
            overview=error.partial.get('overview')
            if overview:
                result['score']=overview.score
                result['subscores']=[x.model_dump() for x in overview.subscores]
            result['errors']=[{k:e.get(k) for k in ('section_id','path','item_id','paragraph_id','code','status')}
                              for e in error.diagnostics if e.get('status') in ('failed','stopped')]
        except Exception as error:
            result['failure_type']=type(error).__name__
            result['http_status']=getattr(error,'status_code',None)
            result['failure_code']=getattr(error,'code',None)
        result['api_calls']=client.calls
        result['responses']=client.history
    result['health']=report_health(r)
    result['complete']=result['health']['complete']
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if key:
        text=text.replace(key,'[REDACTED]')
    (directory/'result.json').write_text(text,encoding='utf-8')
    if r.report or r.partial_state:
        (directory/'record.json').write_text(r.model_dump_json(indent=2),encoding='utf-8')
        (directory/'report.md').write_text(markdown_report(r),encoding='utf-8')
    print(text,flush=True)


if __name__=='__main__':
    main()
