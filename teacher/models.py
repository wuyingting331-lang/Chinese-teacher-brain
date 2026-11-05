import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Weight(Model):
    name: str
    maximum: int = Field(gt=0)


class Picture(Model):
    model_config = ConfigDict(extra='forbid', frozen=True)
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    extension: Literal['png', 'jpg', 'webp']
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PictureReading(Model):
    text_requirements: str
    scenes: list[str] = Field(min_length=1)
    facts: list[str]
    uncertainties: list[str]


class ConfirmedPicture(Model):
    model_config = ConfigDict(extra='forbid', frozen=True)
    image_version: str
    text_requirements: str
    scenes: tuple[str, ...]
    facts: tuple[str, ...]
    uncertainties: tuple[str, ...]
    method: Literal['模型识别后人工确认', '手动填写']


class ScoringConfig(Model):
    name: str = ''
    maximum: int = Field(default=40, gt=0)
    version: str = 'teaching-40-v1'
    nature: str = '暂定教学参考评分'
    source: str = '项目方案 v1.0；未提供经核实的正式评分表'
    bands: list[str] = Field(default_factory=list)
    weights: list[Weight] = Field(default_factory=list)
    principles: list[str] = Field(default_factory=list)
    calibration_set: str | None = None

    @model_validator(mode='after')
    def check_weights(self):
        if self.weights and (sum(w.maximum for w in self.weights) != self.maximum or
                             len({w.name for w in self.weights}) != len(self.weights)):
            raise ValueError('分项满分之和必须等于总分，且名称不能重复')
        return self


class Essay(Model):
    model_config = ConfigDict(extra='forbid', frozen=True)
    name: str = ''
    grade: Literal['小五', '小六'] = '小六'
    title: str = Field(min_length=1)
    kind: Literal['看图作文', '命题作文'] = '命题作文'
    requirements: str = ''
    draft: Literal['一稿', '二稿'] = '一稿'
    body: str = Field(min_length=1)
    pictures: tuple[Picture, ...] = ()
    picture_confirmation: ConfirmedPicture | None = None

    @property
    def version(self):
        data = self.model_dump()
        # Preserve existing text-only record hashes (v1 compatibility).
        if not self.pictures and self.picture_confirmation is None:
            data.pop('pictures')
            data.pop('picture_confirmation')
        return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    @property
    def paragraphs(self):
        # A nonblank physical line is a paragraph; blank separators remain in body.
        return {f'P{i:03d}': p for i, p in enumerate(
            [s for s in re.split(r'\r\n|\r|\n', self.body) if s.strip()], 1)}

    @model_validator(mode='after')
    def nonblank(self):
        if not self.title.strip() or not self.body.strip():
            raise ValueError('题目与正文不能为空')
        return self


class Evidence(Model):
    paragraph_id: str
    quote: str = Field(min_length=1)


class Judgment(Model):
    text: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    scope: Literal['整体叙事', '局部描写', '语言规范', '内容发展', '其他'] = '其他'
    reasoning: str = ''


class Subscore(Model):
    name: str
    score: int


class Overview(Model):
    level: Judgment | None = None  # Legacy expanded judgments are not regenerated.
    score: int
    subscores: list[Subscore]
    content: Judgment
    expression: Judgment
    comment: str = Field(min_length=1)
    strengths: list[Judgment] = Field(min_length=2, max_length=5)
    problems: list[Judgment] = Field(default_factory=list, max_length=2)
    higher_level_gap: Judgment | None = None


class Structure(Model):
    role: str
    summary: str = ''  # overview, never presented as a verbatim quotation
    evidence: list[Evidence] = Field(default_factory=list)
    effect: str = ''
    action: str = ''
    paragraph_ids: list[str] = Field(default_factory=list)
    problem: str = ''
    adjustments: list[Literal['保留', '压缩', '扩写', '拆段', '合并', '移位', '补过渡']] = Field(default_factory=list)
    arrangement: str = ''

    @model_validator(mode='after')
    def has_layout_guidance(self):
        modern=bool(self.paragraph_ids and self.problem.strip() and self.adjustments and self.arrangement.strip())
        legacy=bool(self.evidence and self.effect.strip() and self.action.strip())
        if not (modern or legacy):
            raise ValueError('结构建议须有完整布局字段，或保留旧版证据、评语与修改动作')
        return self


class ParagraphIssue(Model):
    category: Literal['语序与表达', '情节与因果', '人物描写', '详略与衔接']
    detail: str = Field(min_length=1)


class RevisionMove(Model):
    location: str = Field(min_length=1, description='在本段哪句前后修改；引用须逐字保留')
    action: str = Field(min_length=1, description='具体增删重组步骤；表达重组须列意思顺序，内容发展须交代观察、想法、行动或变化')
    reason: str = Field(min_length=1)


class IntegratedExpression(Model):
    expression: str = Field(min_length=1)
    placement: str = Field(min_length=1)
    sentence: str = Field(min_length=1)
    effect: str = Field(min_length=1)


class ParagraphTeaching(Model):
    role: str = Field(min_length=1)
    issues: list[ParagraphIssue]
    reorder: list[RevisionMove]
    develop: list[RevisionMove]
    expressions: list[IntegratedExpression] = Field(max_length=3)
    example_scope: Literal['几句过渡示范', '完整示范段', '拆成2—3段的完整示范', '保留原段']
    invented_details: list[str] = Field(description='示范中新拟的局部细节，非原文事实；可选新增情节不得写进保留原意示范')
    why_better: str = Field(min_length=1)
    is_key: bool = False
    uncertainties: list[str] = Field(default_factory=list)
    success_checks: list[str] = Field(default_factory=list)


class ParagraphReview(Model):
    paragraph_id: str
    strength: str = Field(min_length=1)
    problem: str = ''
    advice: str = ''
    example: str = ''  # Historical string; new generation uses example_paragraphs only.
    example_paragraphs: list[str] = Field(default_factory=list)
    example_kind: Literal['保留原意的局部示范', '保留原意的完整示范（含新拟细节）', '可选扩写（新拟补充）'] = '保留原意的局部示范'
    teaching: ParagraphTeaching | None = None  # Old records have no invented teaching content.

    @model_validator(mode='after')
    def has_example(self):
        if not self.example.strip() and not self.example_paragraphs:
            raise ValueError('示范内容不能为空')
        if any(not p.strip() or '\n' in p or '\r' in p for p in self.example_paragraphs):
            raise ValueError('示范数组每项须为一个非空自然段；分段请使用多个数组项')
        return self


class LanguageEdit(Model):
    evidence: Evidence
    kind: Literal['明确错误', '表达含混', '可选优化']
    category: Literal['错别字', '指代错误', '表达残缺', '病句', '搭配', '标点', '表达不清', '可优化但并非错误']
    replacement: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    start: int | None  # zero-based Python character offset; null means table only


class ExpressionTip(Model):
    expression: str = Field(min_length=1)
    technique: str = ''
    location: Evidence
    reason: str
    example: str
    source: Literal['教学建议（新拟示例）', '原文已有']
    example_kind: Literal['保留原意的局部示范', '可选扩写（新拟补充）'] = '保留原意的局部示范'
    example_source: Literal['原文引用', '教学新拟'] | None = None
    used_in_paragraph_id: str | None = None


class Balance(Model):
    strength: Judgment
    weakness: Judgment
    existing_actions: list[Evidence] = Field(default_factory=list)


class Task(Model):
    location: Evidence | None = None
    problem: str = ''
    action: str = ''
    done: str = ''
    example: str = ''
    focus: Literal['内容发展', '结构与衔接', '人物变化', '语言规范', '其他'] = '其他'
    title: str = ''
    paragraph_ids: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def has_instruction(self):
        if not (self.title.strip() and self.paragraph_ids) and not (self.location and self.action.strip()):
            raise ValueError('任务须有简短标题与段落引用，或旧版定位及动作')
        return self


class PictureAlignment(Model):
    relevance: str = Field(min_length=1)
    reasonable_additions: str = Field(min_length=1)
    deviations: str = Field(min_length=1)
    confirmed_quotes: list[str] = Field(min_length=1)


class Report(Model):
    essay_version: str
    corrections: list[str] = Field(default_factory=list)
    picture_alignment: PictureAlignment | None = None
    overview: Overview
    structure: list[Structure] = Field(min_length=1)
    structure_overview: str = ''
    paragraphs: list[ParagraphReview] = Field(min_length=1)
    language: list[LanguageEdit]
    expressions: list[ExpressionTip] = Field(max_length=10)
    content_summary: Balance | None = None
    expression_summary: Balance | None = None
    tasks: list[Task] = Field(min_length=3, max_length=5)


class Implementation(Model):
    task_number: int = Field(ge=1)
    draft_quote: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class SecondDraft(Model):
    essay_version: str
    body: str = Field(min_length=1)
    implementation: list[Implementation] = Field(min_length=1)
    optional_additions: list[str]
    invented_details: list[str] = Field(default_factory=list)


class CalibrationReview(Model):
    case_id: str
    verdict: Literal['基本一致', '存在有依据的分歧', '需人工复核'] = '需人工复核'
    explanation: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class CalibrationAudit(Model):
    status: Literal['未核对', '无可用同稿样例', '一致性检查未完成', '已完成一致性检查'] = '未核对'
    case_checks: list[dict] = Field(default_factory=list)
    review: CalibrationReview | None = None


class Record(Model):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    essay: Essay
    config: ScoringConfig = Field(default_factory=ScoringConfig)
    prompt_version: str = 'psle-v1'
    report_schema_version: str = 'legacy'
    model_name: str = ''
    demo: bool = False
    target_score: int | None = Field(default=None, ge=1)
    calibration: CalibrationAudit | None = None
    completed_tasks: list[int] = Field(default_factory=list)
    report: Report | None = None
    second_draft: SecondDraft | None = None
    draft_state: dict = Field(default_factory=dict)
    partial_sections: dict = Field(default_factory=dict)
    incomplete_errors: list[str] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)
    partial_state: dict = Field(default_factory=dict)
    diagnostics: list[dict] = Field(default_factory=list)
    generation_versions: list[str] = Field(default_factory=list)
    backup_images: str = '仅含图片关联和确认图意，不含原图；请自行保留上传的原图。云端会话存储不是永久备份。'

    @model_validator(mode='after')
    def check_target(self):
        if self.target_score is not None and self.target_score > self.config.maximum:
            raise ValueError('修改目标不能超过满分')
        return self
