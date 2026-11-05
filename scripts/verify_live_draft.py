"""One draft generation plus at most one repair, using the prior synthetic integration record."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from verify_live_recovery import BoundedClient
from teacher.client import settings
from teacher.models import Record
from teacher.service import generate_draft, GenerationFailure
from teacher.render import markdown_draft


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import tomllib
    secrets_path=ROOT/'.streamlit/secrets.toml'
    secrets=tomllib.loads(secrets_path.read_text(encoding='utf-8')) if secrets_path.exists() else {}
    key,model=settings(secrets)
    out=ROOT/'data/integration/draft-recovery'; out.mkdir(parents=True,exist_ok=True)
    r=Record.model_validate_json((ROOT/'data/integration/flow-recovery/record.json').read_text(encoding='utf-8'))
    before=r.report.model_dump()
    result=dict(time_utc=datetime.now(timezone.utc).isoformat(),model=model,
                material='prior_synthetic_six_paragraph_integration_not_user_original',api_calls=0)
    c=None
    if not key or not model:
        result['limitation']='API configuration unavailable'
    else:
        c=BoundedClient(key,model)
        try:
            r.second_draft=generate_draft(c,r.essay,r.config,r.report,state=r.draft_state)
        except GenerationFailure:
            result['complete']=False
        except Exception as error:
            result['failure_type']=type(error).__name__
        result.update(api_calls=c.calls,responses=c.history)
    result.update(complete=bool(r.second_draft),body_status=r.draft_state.get('body_status'),
        notes_status=r.draft_state.get('notes_status'),errors=r.draft_state.get('errors',[]),
        implementation_count=len(r.second_draft.implementation) if r.second_draft else 0,
        report_unchanged=r.report.model_dump()==before)
    (out/'record.json').write_text(r.model_dump_json(indent=2),encoding='utf-8')
    if r.second_draft: (out/'draft.md').write_text(markdown_draft(r),encoding='utf-8')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
