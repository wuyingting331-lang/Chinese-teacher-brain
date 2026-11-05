import json
import os
import re
import tempfile
from pathlib import Path
from pydantic import ValidationError
from teacher.models import Record
from teacher.validation import report_errors, draft_errors, evidence_errors
from teacher.runtime_paths import data_path


def validate_record(record):
    if not re.fullmatch(r'[a-f0-9]{32}', record.id):
        raise ValueError('非法记录ID')
    if record.report and report_errors(record.report, record.essay, record.config):
        raise ValueError('记录中的报告校验失败')
    if record.second_draft and (not record.report or draft_errors(record.second_draft, record.essay, record.report)):
        raise ValueError('记录中的二稿校验失败')
    if record.calibration and record.calibration.review and evidence_errors(record.calibration.review,record.essay.paragraphs):
        raise ValueError('校准一致性说明的引文校验失败')
    if record.partial_sections and not record.partial_state:
        from teacher.service import checked_parts, SECTIONS
        from teacher.report_contract import RETIRED
        if not set(record.partial_sections).issubset(set(SECTIONS)|RETIRED):
            raise ValueError('不完整记录含未知栏目')
        current={k:v for k,v in record.partial_sections.items() if k in SECTIONS}
        from pydantic import TypeAdapter
        from teacher.report_flow import LISTS,item_type
        from teacher.validation import reference_errors,validate_section
        for name,raw in current.items():
            if name in LISTS:
                for row in raw:
                    value=TypeAdapter(item_type(name)).validate_python(row)
                    if evidence_errors(value,record.essay.paragraphs,name) or reference_errors(name,value,record.essay,name):
                        raise ValueError('历史部分条目引用校验失败')
                    if name=='paragraphs' and value.paragraph_id not in record.essay.paragraphs:
                        raise ValueError('历史部分段落不存在')
            else:
                value=TypeAdapter(SECTIONS[name].rebuild_annotation()).validate_python(raw)
                if validate_section(name,value,record.essay,record.config):
                    raise ValueError('不完整记录含未通过校验的栏目')
    if record.partial_state:
        from teacher.report_flow import checked_state
        checked_state(record.partial_state,record.essay,record.config)


def save(record, directory=None):
    validate_record(record)
    directory = Path(directory) if directory is not None else data_path('records')
    directory.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, suffix='.tmp', delete=False) as f:
            temp = f.name
            f.write(record.model_dump_json(indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, directory / f'{record.id}.json')
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def load_all(directory=None):
    records, warnings = [], []
    directory = Path(directory) if directory is not None else data_path('records')
    try:
        paths = list(directory.glob('*.json'))
    except OSError:
        return [], ['无法读取历史记录目录，请检查访问权限。']
    for path in paths:
        try:
            record = Record.model_validate_json(path.read_text(encoding='utf-8'))
            validate_record(record)
            records.append(record)
        except (OSError, ValueError, ValidationError, json.JSONDecodeError):
            warnings.append(f'已跳过损坏或不可读取的记录：{path.name}')
    return sorted(records, key=lambda r: r.created_at, reverse=True), warnings
