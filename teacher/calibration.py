"""Source-tracked references; unverified texts never become numerical scoring anchors."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import Field, ValidationError, model_validator
from teacher.models import Model, Subscore, CalibrationAudit, CalibrationReview
from teacher.validation import evidence_errors
from teacher.runtime_paths import data_path

CATALOG=Path(__file__).resolve().parents[1]/'config'/'calibration'


class CalibrationCase(Model):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]+$')
    set_id: str
    label: str
    source: str = Field(min_length=1)
    reference_score: int = Field(ge=0)
    reference_subscores: list[Subscore]
    maximum: int = Field(gt=0)
    reference_title: str | None = None
    reference_body: str | None = None
    reference_paragraphs: dict[str,str] = Field(default_factory=dict)
    reference_feedback: str | None = None
    current_report_score_reported: int | None = None
    content_rationale: list[str] = Field(default_factory=list)
    expression_rationale: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_reference_score(self):
        if (self.reference_score>self.maximum or sum(x.score for x in self.reference_subscores)!=self.reference_score
            or len({x.name for x in self.reference_subscores})!=len(self.reference_subscores)
            or any(not 0<=x.score<=self.maximum for x in self.reference_subscores)):
            raise ValueError('参考分项、范围或总分不一致')
        return self


def load_cases(catalog=CATALOG,private=None):
    cases={}
    warnings=[]
    for directory in (Path(catalog),Path(private) if private is not None else data_path('calibration')):
        for path in sorted(directory.glob('*.json')):
            try:
                case=CalibrationCase.model_validate_json(path.read_text(encoding='utf-8'))
                cases[case.id]=case
            except (OSError,ValueError):
                warnings.append('无法读取校准样例：'+path.name)
    return list(cases.values()),warnings


def save_case(case,directory=None):
    """Store supplied reference originals privately, without changing bundled or historical data."""
    case=CalibrationCase.model_validate(case.model_dump() if isinstance(case,CalibrationCase) else case)
    if sum(x.score for x in case.reference_subscores)!=case.reference_score or case.reference_score>case.maximum:
        raise ValueError('参考分项与总分不一致')
    directory=Path(directory) if directory is not None else data_path('calibration')
    directory.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=directory,suffix='.tmp',delete=False) as f:
            temporary=f.name
            f.write(case.model_dump_json(indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary,directory/(case.id+'.json'))
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def text_version(title,body,paragraphs):
    return hashlib.sha256(json.dumps(dict(title=title,body=body,paragraphs=paragraphs),
        ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()


def check_case(case,essay,config):
    missing=[k for k in ('reference_title','reference_body','reference_feedback') if not getattr(case,k)]
    missing+=[] if case.reference_paragraphs else ['reference_paragraphs']
    result=dict(case_id=case.id,label=case.label,source=case.source,reference_score=case.reference_score,
        reference_subscores=[x.model_dump() for x in case.reference_subscores],maximum=case.maximum,
        status='待核对',limitations=list(case.limitations),text_version=None,
        reference_version=hashlib.sha256(json.dumps(case.model_dump(),ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest())
    if missing:
        result['limitations'].append('缺少：'+'、'.join(missing)+'；未确认题目、全文、段落及错字版本一致。')
        return result
    result['text_version']=text_version(case.reference_title,case.reference_body,case.reference_paragraphs)
    exact=(case.reference_title==essay.title and case.reference_body==essay.body and case.reference_paragraphs==essay.paragraphs)
    weights={w.name:w.maximum for w in config.weights}
    legal=(case.maximum==config.maximum and {s.name for s in case.reference_subscores}==set(weights)
           and all(0<=s.score<=weights.get(s.name,-1) for s in case.reference_subscores)
           and sum(s.score for s in case.reference_subscores)==case.reference_score)
    if exact and legal:
        result['status']='已确认同稿'
    else:
        result['status']='版本不一致' if not exact else '评分配置不一致'
        result['limitations'].append('不将此样例作为当前作文的精确分数校准依据。')
    return result


def prepare_audit(essay,config,cases=None):
    if not config.calibration_set:
        return None,[]
    warnings=[]
    if cases is None:
        cases,warnings=load_cases()
    relevant=[c for c in cases if c.set_id==config.calibration_set]
    checks=[check_case(c,essay,config) for c in relevant]
    verified=[c for c,ch in zip(relevant,checks) if ch['status']=='已确认同稿']
    audit=CalibrationAudit(status='一致性检查未完成' if verified else '无可用同稿样例',case_checks=checks)
    if warnings:
        audit.case_checks.append(dict(status='样例读取警告',limitations=warnings))
    return audit,verified


def review_consistency(client,essay,config,overview,audit,verified):
    """Never accepts the revision goal and never returns an altered score."""
    if not verified:
        return audit
    from teacher.service import payload
    from teacher.prompts import CONSISTENCY
    case=verified[0]
    errors=[]
    for _ in range(2):
        request=payload(essay,config,independent_assessment=overview.model_dump(),
            verified_reference=case.model_dump(),score_difference=overview.score-case.reference_score,
            repair_errors=errors)
        try:
            value=client.generate(CalibrationReview,CONSISTENCY,request)
            value=CalibrationReview.model_validate(value.model_dump() if hasattr(value,'model_dump') else value)
            errors=evidence_errors(value,essay.paragraphs,'calibration.review')
            if value.case_id!=case.id:
                errors.append('校准样例标识不一致')
            if not errors:
                return CalibrationAudit(status='已完成一致性检查',case_checks=audit.case_checks,review=value)
        except (ValidationError,ValueError):
            errors=['一致性说明结构或证据校验失败']
        except Exception:
            break  # No automatic retry for network/authentication failures.
    return CalibrationAudit(status='一致性检查未完成',case_checks=audit.case_checks)
