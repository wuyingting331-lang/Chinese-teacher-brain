import json
import re
from pydantic import ValidationError, TypeAdapter, BaseModel
from teacher.models import Report, SecondDraft
from teacher.validation import validate_section, report_errors, draft_errors, resolve_evidence
from teacher.prompts import SYSTEM, DRAFT
from teacher.report_contract import ACTIVE,SCHEMA_VERSION

SECTIONS = {k:Report.model_fields[k] for k in ACTIVE}


def payload(essay, config, **extra):
    from teacher.images import valid_confirmation
    data=essay.model_dump()
    if not valid_confirmation(essay):
        data['picture_confirmation']=None
    return json.dumps(dict(essay=data, essay_version=essay.version,
                          report_schema_version=SCHEMA_VERSION,
                          paragraphs=essay.paragraphs, config=config.model_dump(),
                          source_snippets={pid:[s for s in re.split(r'(?<=[。！？；，])',text) if s.strip()][:40]
                                           for pid,text in essay.paragraphs.items()},
                          picture_checked=valid_confirmation(essay), **extra), ensure_ascii=False)


class GenerationFailure(ValueError):
    def __init__(self, errors, partial, corrections=None, request_id=''):
        super().__init__('；'.join(errors))
        self.errors = errors
        self.partial = partial
        self.corrections = corrections or []
        self.request_id = request_id


def checked_parts(candidate, essay, config, fields=None, corrections=None):
    data = candidate.model_dump() if isinstance(candidate, BaseModel) else candidate
    valid, errors = {}, []
    if not isinstance(data, dict):
        return {}, ['结果必须是对象']
    if data.get('essay_version') != essay.version:
        return {}, ['报告版本与确认原文不同']
    for name in (fields if fields is not None else SECTIONS):
        field = SECTIONS[name]
        try:
            value = TypeAdapter(field.rebuild_annotation()).validate_python(data.get(name))
            notes = resolve_evidence(value,essay.paragraphs,name)
            if corrections is not None:
                corrections.extend(notes)
            issues = validate_section(name, value, essay, config)
            if issues:
                errors.extend(issues)
            else:
                valid[name] = value
        except (ValidationError, ValueError):
            errors.append(f'{name}: 栏目结构不完整或格式错误')
    return valid, errors


def serialized(parts):
    return {k:TypeAdapter(type(v)).dump_python(v,mode='json') for k,v in parts.items()}


def generate_report(client, essay, config, existing=None, resume=None, comparisons=None,target_score=None,calibration_cases=None,full_generation=False):
    if target_score is not None and not 1 <= target_score <= config.maximum:
        raise ValueError('修改目标超出满分范围')
    from teacher.report_flow import run
    report,state=run(client,essay,config,existing=existing,resume=resume,comparisons=comparisons,target_score=target_score,calibration_cases=calibration_cases,full_generation=full_generation)
    client.generation_diagnostics=state['diagnostics']
    client.generation_state=state
    return report


def generate_draft(client, essay, config, report,target_score=None,state=None):
    errors = report_errors(report, essay, config)
    if errors:
        raise GenerationFailure(errors, {})
    from teacher.draft_flow import run
    return run(client,essay,config,report,target_score,state)
