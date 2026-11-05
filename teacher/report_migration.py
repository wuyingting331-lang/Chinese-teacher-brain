"""Explicit read-only legacy adaptation. Only independently revalidated scores may seed a new run."""
from pathlib import Path
from uuid import uuid4
from teacher.models import Record,Overview
from teacher.report_contract import SCHEMA_VERSION
from teacher.validation import validate_section
from teacher.runtime_paths import data_path


def seed_from_legacy(record,directory=None):
    directory=Path(directory) if directory is not None else data_path('legacy_snapshots')
    directory.mkdir(parents=True,exist_ok=True)
    snapshot=directory/(uuid4().hex+'.json')
    snapshot.write_text(record.model_dump_json(indent=2),encoding='utf-8')
    raw=record.report.overview.model_dump() if record.report else None
    if raw is None and record.partial_state:
        slot=record.partial_state.get('slots',{}).get('overview',{})
        if slot.get('status')=='valid':
            raw=slot.get('value')
    if raw is None:
        raw=record.partial_sections.get('overview')
    seed={}
    try:
        overview=Overview.model_validate(raw)
        if not validate_section('overview',overview,record.essay,record.config):
            # No score change. Only retired prose fields are excluded from the new request.
            data=overview.model_dump()
            data.update(level=None,problems=[],higher_level_gap=None,strengths=data['strengths'][:2])
            seed={'overview':data}
    except (ValueError,TypeError):
        pass
    current=Record(essay=record.essay,config=record.config,target_score=record.target_score,
        model_name=record.model_name,report_schema_version=SCHEMA_VERSION,
        generation_versions=[*record.generation_versions,record.prompt_version])
    return current,seed,snapshot
