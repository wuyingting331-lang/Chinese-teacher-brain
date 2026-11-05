from pydantic import BaseModel
from teacher.models import Evidence, Report, SecondDraft, Essay, ScoringConfig


def evidence_errors(value, paragraphs, path=''):
    errors = []
    if isinstance(value, Evidence):
        if value.paragraph_id not in paragraphs:
            errors.append(f'{path}: 段落不存在：{value.paragraph_id}')
        elif value.quote not in paragraphs[value.paragraph_id]:
            errors.append(f'{path}: 引文不属于对应原文：{value.paragraph_id}')
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            errors.extend(evidence_errors(getattr(value, name), paragraphs, f'{path}.{name}'))
    elif isinstance(value, list):
        for i,item in enumerate(value):
            errors.extend(evidence_errors(item, paragraphs, f'{path}[{i}]'))
    return errors


def reference_errors(section,value,essay,path=''):
    errors=[]
    if section in ('structure','tasks'):
        ids=value.paragraph_ids
        if len(ids)!=len(set(ids)):
            errors.append(f'{path}.paragraph_ids: 段落引用不能重复')
        for i,pid in enumerate(ids):
            if pid not in essay.paragraphs:
                errors.append(f'{path}.paragraph_ids[{i}]: 段落不存在：{pid}')
    if section=='expressions' and value.used_in_paragraph_id and value.used_in_paragraph_id not in essay.paragraphs:
        errors.append(f'{path}.used_in_paragraph_id: 段落不存在：{value.used_in_paragraph_id}')
    return errors


def validate_section(name, value, essay, config):
    errors = evidence_errors(value, essay.paragraphs, name)
    if name in ('structure','tasks','expressions'):
        for i,item in enumerate(value):
            errors.extend(reference_errors(name,item,essay,f'{name}[{i}]'))
    if name == 'picture_alignment':
        from teacher.images import valid_confirmation
        if valid_confirmation(essay):
            c = essay.picture_confirmation
            sources = [c.text_requirements,*c.scenes,*c.facts,*c.uncertainties]
            if value is None:
                errors.append('picture_alignment: 缺少确认图意的评价')
            elif any(not q or not any(q in s for s in sources) for q in value.confirmed_quotes):
                errors.append('picture_alignment: 图意引文不属于确认图意')
        elif value is not None:
            errors.append('picture_alignment: 尚未确认图意，不能声称核对图片')
    if name == 'overview':
        if not 0 <= value.score <= config.maximum:
            errors.append('总分超出合法范围')
        weights = {w.name: w.maximum for w in config.weights}
        actual = {s.name: s.score for s in value.subscores}
        if len(actual) != len(value.subscores) or set(actual) != set(weights):
            errors.append('分项不符合评分配置')
        if weights and (sum(actual.values()) != value.score or
                        any(not 0 <= s <= weights.get(n, -1) for n, s in actual.items())):
            errors.append('分项范围或总和不正确')
    if name == 'paragraphs':
        ids = [p.paragraph_id for p in value]
        if ids != list(essay.paragraphs):
            errors.append('逐段点评须按顺序覆盖全部原文段落，不能重复')
    if name == 'language':
        for edit in value:
            if (edit.kind == '可选优化') != (edit.category == '可优化但并非错误'):
                errors.append('可选优化必须与错误类型分开')
            # Invalid/ambiguous offsets deliberately degrade to table-only rendering.
    if name == 'expressions':
        for tip in value:
            paragraph=essay.paragraphs.get(tip.location.paragraph_id,'')
            if tip.source=='原文已有' and tip.expression not in paragraph:
                errors.append('expressions: 标为原文已有的表达必须逐字来自对应原文')
            if tip.example_source=='原文引用' and tip.example not in paragraph:
                errors.append('expressions: 标为原文引用的示例必须逐字来自对应原文')
    return errors


def resolve_evidence(value, paragraphs, path=''):
    """Repair only unique exact cross-paragraph matches; never repair wording."""
    notes = []
    if isinstance(value, Evidence):
        if value.paragraph_id in paragraphs and value.quote in paragraphs[value.paragraph_id]:
            return []
        matches = [pid for pid,text in paragraphs.items() if value.quote in text]
        if len(matches) == 1:
            old = value.paragraph_id
            value.paragraph_id = matches[0]
            notes.append(f'{path}: 唯一逐字匹配，段落定位 {old} → {matches[0]}')
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            notes.extend(resolve_evidence(getattr(value,name),paragraphs,f'{path}.{name}'))
        if notes and hasattr(value,'start'):
            value.start = None
    elif isinstance(value,list):
        for i,item in enumerate(value):
            notes.extend(resolve_evidence(item,paragraphs,f'{path}[{i}]'))
    return notes


def report_errors(report: Report, essay: Essay, config: ScoringConfig):
    from teacher.report_contract import ACTIVE
    errors = []
    if report.essay_version != essay.version:
        errors.append('报告版本与确认原文不同')
    for name in ACTIVE:
        errors.extend(validate_section(name,getattr(report,name),essay,config))
    return errors


def draft_errors(draft: SecondDraft, essay: Essay, report: Report):
    errors = []
    if draft.essay_version != essay.version:
        errors.append('示范二稿版本不符')
    for item in draft.implementation:
        if item.task_number > len(report.tasks) or item.draft_quote not in draft.body:
            errors.append('二稿落实说明没有真实文字证据或任务不存在')
    if any(p.teaching is not None for p in report.paragraphs):
        required={i for i,t in enumerate(report.tasks,1) if t.focus in ('内容发展','结构与衔接','人物变化')}
        implemented={i.task_number for i in draft.implementation}
        if required-implemented:
            errors.append('二稿缺少主要内容修改任务的落实说明')
    return errors
