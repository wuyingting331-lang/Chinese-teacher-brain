"""Item-preserving report generation and bounded, inspectable repairs."""
from copy import deepcopy
from typing import get_args, get_origin, Literal
from uuid import uuid4
import re
from pydantic import BaseModel, TypeAdapter, ValidationError, create_model, Field, model_validator
from teacher.models import Report, Model, Evidence, ParagraphReview, ParagraphTeaching, Task, Overview, Judgment, ExpressionTip, CalibrationAudit, Structure, Balance
from teacher.validation import evidence_errors, resolve_evidence, validate_section, reference_errors
from teacher.diagnostics import diagnostic, from_issue, persist, persist_exchange
from teacher.report_contract import ACTIVE,RETIRED,SCHEMA_VERSION

FIELDS={k:Report.model_fields[k] for k in ACTIVE}
LISTS={k for k,v in FIELDS.items() if get_origin(v.annotation) is list}
MINIMUM={'structure':1,'language':0,'expressions':0,'tasks':3}
MAXIMUM={'expressions':10,'tasks':5}
MAX_REPAIRS=3
REPAIR_GUIDANCE={
    'EXAMPLE_PARAGRAPH_COUNT_MISMATCH':'本段标注拆成2—3段，example_paragraphs必须返回2或3个独立自然段字符串；不能只返回一项或把换行塞进一项。',
    'QUOTE_MISMATCH':'Evidence必须逐字取自对应原文，保留原错字；多个已有动作分别用短Evidence，不能合并概述。',
    'RETAINED_EXPRESSION_NOT_ORIGINAL':'原文已有只用于实际逐字出现的词句；若表达是教学建议，应诚实标为教学建议（新拟示例），例句另设example_source=教学新拟。定位Evidence仍须精确。',
    'EXAMPLE_NOT_ORIGINAL':'若例句本来是教学示范，将example_source设教学新拟；只有真实原句才标原文引用。不要把新拟例句塞进Evidence。',
    'CLEAR_ERROR_AS_OPTIONAL':'将指代、用字与残缺拆成明确纠错，心理动作发展另列可选提升；局部修复单项时只处理该项，不改其他有效条目。',
}

# Persistence accepts legacy missing fields; new model requests require the new teaching contract.
GeneratedTeaching=create_model('GeneratedTeaching',__base__=ParagraphTeaching,is_key=(bool,...))
class GeneratedParagraph(ParagraphReview):
    teaching: GeneratedTeaching
    problem: Literal[''] = ''
    advice: Literal[''] = ''
    example: Literal[''] = ''
    example_paragraphs: list[str] = Field(min_length=1)

    @model_validator(mode='after')
    def actual_split(self):
        if self.teaching.example_scope=='拆成2—3段的完整示范' and len(self.example_paragraphs) not in (2,3):
            raise ValueError('分段标签与实际示范段落数组不符')
        return self


GeneratedTask=create_model('GeneratedTask',__base__=Task,
    title=(str,Field(min_length=1)),paragraph_ids=(list[str],Field(min_length=1)),
    location=(type(None),None),problem=(Literal[''],''),action=(Literal[''],''),done=(Literal[''],''),example=(Literal[''],''),
    focus=(Task.model_fields['focus'].annotation,...))
GeneratedStructure=create_model('GeneratedStructure',__base__=Structure,
    paragraph_ids=(list[str],Field(min_length=1)),problem=(str,Field(min_length=1)),
    adjustments=(Structure.model_fields['adjustments'].annotation,Field(min_length=1)),arrangement=(str,Field(min_length=1)),
    summary=(Literal[''],''),effect=(Literal[''],''),action=(Literal[''],''),evidence=(list[Evidence],Field(default_factory=list,max_length=0)))
LegacyStructureRepair=create_model('LegacyStructureRepair',__base__=Structure,
    evidence=(list[Evidence],Field(min_length=1)),effect=(str,Field(min_length=1)),action=(str,Field(min_length=1)))
class GeneratedExpression(ExpressionTip):
    example_source: Literal['原文引用','教学新拟']
    used_in_paragraph_id: str | None

    @model_validator(mode='after')
    def no_duplicate_example(self):
        if self.used_in_paragraph_id and self.example:
            raise ValueError('已引用逐段示范的词句，不再另存一份示例正文')
        return self
GeneratedOverview=create_model('GeneratedOverview',__base__=Overview,strengths=(list[Judgment],Field(min_length=2,max_length=2)),
    level=(type(None),None),problems=(list[Judgment],Field(default_factory=list,max_length=0)),higher_level_gap=(type(None),None))
GeneratedReport=create_model('GeneratedReport',__base__=Model,essay_version=(str,...),corrections=(list[str],Field(default_factory=list)),
    picture_alignment=(Report.model_fields['picture_alignment'].rebuild_annotation(),...),language=(Report.model_fields['language'].rebuild_annotation(),...),
    overview=(GeneratedOverview,...),expressions=(list[GeneratedExpression],Field(max_length=10)),
    structure=(list[GeneratedStructure],Field(min_length=1)),structure_overview=(str,Field(min_length=1)),
    paragraphs=(list[GeneratedParagraph],Field(min_length=1)),tasks=(list[GeneratedTask],Field(min_length=3,max_length=5)))


class SchemaVersionMismatch(ValueError):
    pass


def request_annotation(section,index):
    if section=='structure_overview':
        from typing import Annotated
        return Annotated[str,Field(min_length=1)]
    if section=='overview':
        return GeneratedOverview
    if section=='expressions':
        return GeneratedExpression if index is not None else list[GeneratedExpression]
    if section in ('paragraphs','tasks','structure'):
        item={'paragraphs':GeneratedParagraph,'tasks':GeneratedTask,'structure':GeneratedStructure}[section]
        if index is not None:
            return item
        from typing import Annotated
        return Annotated[list[item],Field(min_length=3 if section=='tasks' else 1,
                                          **({'max_length':5} if section=='tasks' else {}))]
    return FIELDS[section].rebuild_annotation() if index is None else item_type(section)


def target_annotation(state,key,slot):
    section,index=slot['section'],slot['index']
    if section in state.get('legacy_required_summaries',[]):
        return Balance
    if section in ('content_summary','expression_summary') and state.get('format_version')=='single-outline-v1':
        return type(None)
    if section=='structure' and key in state.get('legacy_required_structures',[]) and not state.get('strict_contract'):
        if index is not None:
            return LegacyStructureRepair
        from typing import Annotated
        return Annotated[list[LegacyStructureRepair],Field(min_length=1)]
    return request_annotation(section,index)


def dump(value):
    return TypeAdapter(type(value)).dump_python(value,mode='json')


def item_type(section):
    return get_args(FIELDS[section].annotation)[0]


def slot_key(section,index=None):
    return section if index is None else f'{section}__{index}'


def initial_state(essay,existing=None):
    state={'essay_version':essay.version,'request_id':uuid4().hex,'slots':{},'empty_lists':[],
           'diagnostics':[],'corrections':[],'format_version':SCHEMA_VERSION,'expected_paragraph_ids':list(essay.paragraphs),'legacy_required_summaries':[],
           'legacy_required_structures':[]}
    for section in FIELDS:
        state['slots'][section]={'section':section,'index':None,'status':'failed','value':None,'repair_count':0}
    from teacher.images import valid_confirmation
    if not valid_confirmation(essay):
        state['slots']['picture_alignment'].update(status='valid',value=None)
    return state


def comparison_details(value,essay,path):
    result=[]
    if isinstance(value,Evidence):
        if evidence_errors(value,essay.paragraphs,path):
            result.append(dict(path=path,paragraph_id=value.paragraph_id,candidate_quote=value.quote,
                               original_paragraph=essay.paragraphs.get(value.paragraph_id,'【段落不存在】'),
                               exact_matching_paragraphs=[p for p,t in essay.paragraphs.items() if value.quote in t]))
    elif isinstance(value,BaseModel):
        if isinstance(value,ExpressionTip):
            original=essay.paragraphs.get(value.location.paragraph_id,'')
            for field,should_check in [('expression',value.source=='原文已有'),('example',value.example_source=='原文引用')]:
                candidate=getattr(value,field)
                if should_check and candidate not in original:
                    result.append(dict(path=path+'.'+field,paragraph_id=value.location.paragraph_id,
                        candidate_quote=candidate,original_paragraph=original,
                        exact_matching_paragraphs=[p for p,t in essay.paragraphs.items() if candidate in t]))
        for name in type(value).model_fields:
            result.extend(comparison_details(getattr(value,name),essay,path+'.'+name))
    elif isinstance(value,list):
        for i,item in enumerate(value):
            result.extend(comparison_details(item,essay,f'{path}[{i}]'))
    return result


def quality_issues(section,value,essay,path):
    """Small explicit checks; semantic teaching quality still needs human review."""
    issues=[]
    if section=='expressions' and value.expression.strip() in {
        '强化心理描写','细化环境描写','增加动作描写','加强心理描写','心理描写','环境描写'}:
        issues.append((path+'.expression','EXPRESSION_NOT_CONCRETE'))
    if section=='expressions' and value.source=='原文已有':
        if value.expression not in essay.paragraphs.get(value.location.paragraph_id,''):
            issues.append((path+'.expression','RETAINED_EXPRESSION_NOT_ORIGINAL'))
    if section=='expressions' and value.example_source=='原文引用' and value.example not in essay.paragraphs.get(value.location.paragraph_id,''):
        issues.append((path+'.example','EXAMPLE_NOT_ORIGINAL'))
    texts=[]
    if section=='language':
        texts=[(path+'.replacement',value.replacement)]
        context=essay.paragraphs.get(value.evidence.paragraph_id,'')
        if any(x in context for x in ('索性','故意','不想','懒得','逃避','不以为然')) and re.search(r'只好[^。！？]*(?:[戴带][^。！？]*耳机|耳机[^。！？]*[戴带])',value.replacement):
            issues.append((path+'.replacement','MOTIVATION_CHANGED'))
    if section in ('paragraphs','expressions'):
        from teacher.report_view import example_text
        text=example_text(value) if section=='paragraphs' else value.example
        texts=[(path+'.example',text)]
        pid=value.paragraph_id if section=='paragraphs' else value.location.paragraph_id
        context=essay.paragraphs.get(pid,'')
        if any(x in context for x in ('索性','故意','不想','懒得','逃避','不以为然')) and re.search(r'只好[^。！？]*(?:[戴带][^。！？]*耳机|耳机[^。！？]*[戴带])',text):
            issues.append((path+'.example','MOTIVATION_CHANGED'))
    for p,text in texts:
        if '带上耳机' in text:
            issues.append((p,'EXAMPLE_LANGUAGE_ERROR'))
    def judgments(v,p):
        if isinstance(v,BaseModel):
            if hasattr(v,'text') and hasattr(v,'evidence') and '结构杂乱' in v.text:
                if all(e.quote.strip() in ('但却从来不以为然','但却从来不以为然。') for e in v.evidence):
                    issues.append((p+'.evidence','EVIDENCE_CONTEXT_INSUFFICIENT'))
            for n in type(v).model_fields:
                judgments(getattr(v,n),p+'.'+n)
        elif isinstance(v,list):
            for i,x in enumerate(v):
                judgments(x,f'{p}[{i}]')
    judgments(value,path)
    return issues


def generation_issues(section,value,essay,path):
    """Specific known defects in new replies; do not retroactively invalidate old records."""
    issues=[]
    if section=='language' and value.kind!='明确错误' and re.search(r'带上耳机|把耳机带上|玩游(?!戏)',value.evidence.quote):
        issues.append((path+'.kind','CLEAR_ERROR_AS_OPTIONAL'))
    if section in ('paragraphs','expressions','language'):
        field='replacement' if section=='language' else 'example'
        from teacher.report_view import example_text
        text=example_text(value) if section=='paragraphs' else getattr(value,field)
        if '因为尿布湿疹起了红点' in text:
            issues.append((path+'.'+field,'UNSUPPORTED_MEDICAL_WORDING'))
        pid=value.paragraph_id if section=='paragraphs' else (value.location.paragraph_id if section=='expressions' else value.evidence.paragraph_id)
        source=essay.paragraphs.get(pid,'')
        if '买什么东西！' in text and '买什么东西！' not in source:
            issues.append((path+'.'+field,'INVENTED_DIALOGUE_MEANING'))
        if '真烦我买东西' in source and re.search(r'买什么(?:东西)?[？?！!]',text):
            issues.append((path+'.'+field,'AMBIGUOUS_DIALOGUE_REINTERPRETED'))
        if '大腿' in source and '红疹' in source and re.search(r'小腿[^。！？]*红[疹点]|红[疹点][^。！？]*小腿',text):
            issues.append((path+'.'+field,'BODY_LOCATION_CHANGED'))
    return issues


def check_slot(state,key,raw,essay,config,details,repair=False,generated=False,revalidate=False):
    slot=state['slots'][key]
    if slot['status']=='valid' and not revalidate:
        return
    section,index=slot['section'],slot['index']
    path=section if index is None else f'{section}[{index}]'
    count=slot['repair_count']
    issues=[]
    try:
        if generated and section=='paragraphs' and isinstance(raw,dict):
            blocks=raw.get('example_paragraphs')
            if isinstance(blocks,list) and blocks and all(isinstance(x,str) for x in blocks) and any('\n' in x or '\r' in x for x in blocks):
                raw=dict(raw,example_paragraphs=[p for block in blocks for p in re.split(r'\r\n|\r|\n',block) if p.strip()])
                state['diagnostics'].append(dict(diagnostic(section,path+'.example_paragraphs','EXPLICIT_BREAKS_NORMALIZED',
                    slot.get('item_id'),count,status='corrected',request_id=state['request_id']),target=key))
        annotation=FIELDS[section].rebuild_annotation() if index is None else item_type(section)
        if state.get('strict_contract'):
            annotation=request_annotation(section,index)
        if section in state.get('legacy_required_summaries',[]):
            annotation=Balance
        if section=='structure' and key in state.get('legacy_required_structures',[]) and not state.get('strict_contract'):
            annotation=LegacyStructureRepair if index is not None else list[LegacyStructureRepair]
        value=TypeAdapter(annotation).validate_python(raw)
        notes=resolve_evidence(value,essay.paragraphs,path)
        state['corrections'].extend(notes)
        for note in notes:
            match=re.search(r'→ (P\d+)',note)
            state['diagnostics'].append(dict(diagnostic(section,note.split(':',1)[0],'QUOTE_RELOCATED',
                match.group(1) if match else None,count,status='corrected',request_id=state['request_id']),target=key))
        details.extend(comparison_details(value,essay,path))
        if index is None:
            errors=validate_section(section,value,essay,config)
        else:
            errors=evidence_errors(value,essay.paragraphs,path)
            errors.extend(reference_errors(section,value,essay,path))
            if section=='language':
                if (value.kind=='可选优化')!=(value.category=='可优化但并非错误'):
                    issues.append(diagnostic(section,path+'.category','EDIT_KIND_CONFLICT',repair_count=count))
            if section=='paragraphs':
                expected=slot.get('item_id') or (list(essay.paragraphs)[index] if index<len(essay.paragraphs) else None)
                if value.paragraph_id!=expected:
                    issues.append(diagnostic(section,path+'.paragraph_id','PARAGRAPH_ORDER_INVALID',value.paragraph_id,count))
        issues.extend(from_issue(section,e,path,count) for e in errors)
        if section=='structure_overview' and state.get('format_version')==SCHEMA_VERSION and not str(value).strip():
            issues.append(diagnostic(section,path,'REQUIRED_CONTENT_MISSING',repair_count=count))
        if index is not None and section in ('language','expressions','paragraphs') or section in ('overview','content_summary','expression_summary'):
            issues.extend(diagnostic(section,p,code,repair_count=count) for p,code in quality_issues(section,value,essay,path))
        if generated and index is not None:
            issues.extend(diagnostic(section,p,code,repair_count=count) for p,code in generation_issues(section,value,essay,path))
    except ValidationError as exc:
        value=None
        for e in exc.errors(include_input=False,include_url=False):
            node=raw
            pid=slot.get('item_id')
            for part in e['loc']:
                if isinstance(node,dict) and re.fullmatch(r'P\d+',str(node.get('paragraph_id',''))):
                    pid=node['paragraph_id']
                try:
                    node=node[part]
                except (KeyError,TypeError,IndexError):
                    break
            suffix=''.join(f'[{x}]' if isinstance(x,int) else '.'+str(x) for x in e['loc'])
            code='EXAMPLE_PARAGRAPH_COUNT_MISMATCH' if e['type']=='value_error' and '分段标签' in e['msg'] else 'SCHEMA_'+e['type'].upper()
            issues.append(diagnostic(section,path+suffix,code,pid,repair_count=count))
    except (ValueError,TypeError):
        value=None
        issues.append(diagnostic(section,path,'SCHEMA_INVALID',repair_count=count))
    # A prior failure's final status is retained rather than left looking active.
    for e in state['diagnostics']:
        if e.get('target')==key and e['status'] in ('failed','stopped'):
            e['status']='superseded' if issues else 'repaired'
            if not issues:
                e['repair_count']=count
    if issues:
        if value is not None:
            reference=getattr(value,'evidence',None) or getattr(value,'location',None)
            known_pid=reference.paragraph_id if isinstance(reference,Evidence) else getattr(value,'paragraph_id',None)
            for e in issues:
                if not e.get('paragraph_id') and known_pid:
                    e['paragraph_id']=known_pid
        slot.update(value=None,status='stopped' if count>=MAX_REPAIRS else 'failed')
        for e in issues:
            e.update(target=key,item_id=slot.get('item_id') or key,request_id=state['request_id'],status=slot['status'])
        state['diagnostics'].extend(issues)
    else:
        slot.update(value=dump(value),status='valid')
        if repair:
            state['diagnostics'].append(dict(diagnostic(section,path,'VALIDATED',repair_count=count,
                                                        status='repaired',request_id=state['request_id']),target=key))


def ingest_section(state,section,raw,essay,config,details,repair_count=0,generated=False):
    if section in RETIRED:
        return
    if section=='paragraphs':
        state['slots'].pop(section,None)
        rows={}
        for row in raw if isinstance(raw,list) else []:
            row=row.model_dump() if isinstance(row,BaseModel) else row
            if isinstance(row,dict):
                rows.setdefault(row.get('paragraph_id'),[]).append(row)
        for i,pid in enumerate(essay.paragraphs):
            key=slot_key(section,i)
            if state['slots'].get(key,{}).get('status')=='valid':
                continue
            state['slots'][key]=dict(section=section,index=i,item_id=pid,status='failed',value=None,repair_count=repair_count)
            candidates=rows.get(pid,[])
            check_slot(state,key,candidates[0] if len(candidates)==1 else None,essay,config,details,generated=generated)
            if len(candidates)!=1:
                for event in state['diagnostics']:
                    if event.get('target')==key and event['status'] in ('failed','stopped'):
                        event.update(code='PARAGRAPH_MISSING' if not candidates else 'PARAGRAPH_DUPLICATED',paragraph_id=pid,item_id=pid)
        for pid in set(rows)-set(essay.paragraphs):
            state['diagnostics'].append(dict(diagnostic(section,'paragraphs.'+str(pid),'UNEXPECTED_PARAGRAPH_REJECTED',status='corrected',request_id=state['request_id']),item_id=pid))
        return
    if section in ('content_summary','expression_summary') and raw is not None:
        required=state.setdefault('legacy_required_summaries',[])
        if section not in required:
            required.append(section)
    if section in LISTS and isinstance(raw,list):
        require_legacy_structure=section=='structure' and section in state.get('legacy_required_structures',[])
        state['slots'].pop(section,None)
        minimum=len(essay.paragraphs) if section=='paragraphs' else MINIMUM.get(section,0)
        if not raw and minimum==0:
            state['empty_lists'].append(section)
        for i in range(max(len(raw),minimum)):
            key=slot_key(section,i)
            if state['slots'].get(key,{}).get('status')=='valid':
                continue
            row=raw[i].model_dump() if i<len(raw) and isinstance(raw[i],BaseModel) else (raw[i] if i<len(raw) else None)
            if section=='structure' and not state.get('strict_contract') and (require_legacy_structure or isinstance(row,dict) and row.get('evidence')):
                required=state.setdefault('legacy_required_structures',[])
                if key not in required:
                    required.append(key)
            state['slots'][key]=dict(section=section,index=i,status='failed',value=None,repair_count=repair_count)
            check_slot(state,key,raw[i] if i<len(raw) else None,essay,config,details,generated=generated)
        if len(raw)>MAXIMUM.get(section,len(essay.paragraphs) if section=='paragraphs' else len(raw)):
            key=section+'__limit'
            state['slots'][key]=dict(section=section,index=None,status='stopped',value=None,repair_count=MAX_REPAIRS)
            state['diagnostics'].append(dict(diagnostic(section,section,'TOO_MANY_ITEMS',repair_count=MAX_REPAIRS,
                                                        status='stopped',request_id=state['request_id']),target=key))
    else:
        if section not in state['slots']:
            state['slots'][section]=dict(section=section,index=None,status='failed',value=None,repair_count=0)
        check_slot(state,section,raw,essay,config,details,generated=generated)


def section_values(state,complete_only=False):
    result={}
    for section in FIELDS:
        slots=[s for s in state['slots'].values() if s['section']==section]
        incomplete=(not slots and section not in state['empty_lists']) or any(s['status']!='valid' for s in slots)
        if complete_only and incomplete:
            continue
        valid=[s for s in slots if s['status']=='valid']
        if any(s['index'] is None for s in valid):
            result[section]=next(s['value'] for s in valid if s['index'] is None)
        elif section in LISTS and (valid or section in state['empty_lists']):
            result[section]=[s['value'] for s in sorted(valid,key=lambda s:s['index'])]
    return result


def active_errors(state):
    return [e for e in state['diagnostics'] if e['section_id'] in ACTIVE and e['status'] in ('failed','stopped')]


def error_strings(state):
    return [f'{e["path"]}: {e["code"]}'+(f'：{e["paragraph_id"]}' if e.get('paragraph_id') else '') for e in active_errors(state)]


def record_exchange(state,client,essay):
    if not isinstance(getattr(client,'last_exchange',None),dict):
        return
    from teacher.report_contract import counts
    complete_values=section_values(state,complete_only=True)
    complete=len(complete_values)==len(FIELDS)
    exchange=dict(client.last_exchange,schema_version=SCHEMA_VERSION,request_id=state['request_id'],
        valid_counts=counts(section_values(state),essay),complete_sections=list(complete_values),
        complete=complete,validation_status='complete' if complete else 'partial')
    state.setdefault('exchanges',[]).append(exchange)
    persist_exchange(exchange)


def checked_state(state,essay,config):
    """Revalidate every persisted valid item before trusting it for rendering/merging."""
    if state.get('essay_version')!=essay.version:
        raise ValueError('局部修复状态不属于当前原文')
    result=deepcopy(state)
    if 'format_version' not in result:
        result['legacy_required_summaries']=[name for name in ('content_summary','expression_summary')
            if any(s['section']==name and s['status']!='valid' for s in result.get('slots',{}).values())]
        result['legacy_required_structures']=[key for key,s in result.get('slots',{}).items() if s['section']=='structure']
    if not any(s['section']=='structure_overview' for s in result.get('slots',{}).values()):
        current=result.get('format_version')==SCHEMA_VERSION
        result['slots']['structure_overview']=dict(section='structure_overview',index=None,status='failed' if current else 'valid',value=None if current else '',repair_count=0)
    for key,slot in list(result.get('slots',{}).items()):
        if slot['section'] in RETIRED:
            continue
        if slot['section'] not in FIELDS or key!=slot_key(slot['section'],slot['index']) and not key.endswith('__limit'):
            raise ValueError('非法修复条目标识')
        if slot['status']=='valid':
            check_slot(result,key,slot['value'],essay,config,[],revalidate=True)
            if result['slots'][key]['status']!='valid':
                raise ValueError('已保存条目不再通过校验')
    return result


def run(client,essay,config,existing=None,resume=None,comparisons=None,target_score=None,calibration_cases=None,full_generation=False):
    from teacher.service import GenerationFailure, payload
    from teacher.prompts import SYSTEM
    details=list(comparisons or [])
    if existing and set(existing)!={'overview'}:
        raise SchemaVersionMismatch('无完整schema与条目状态的投影不能直接局部修复；请读取历史内容后明确适配，或提供当前partial_state。')
    if resume and resume.get('format_version')!=SCHEMA_VERSION:
        raise SchemaVersionMismatch('历史schema的部分结果只能阅读；需明确适配后重新生成当前指导，不能直接局部修复。')
    state=checked_state(resume,essay,config) if resume else initial_state(essay,existing)
    raw_method=getattr(type(client),'generate_raw',None)
    state['strict_contract']=callable(raw_method)
    fresh=not resume and not existing
    if existing and not resume:
        for section,raw in existing.items():
            if section in FIELDS:
                ingest_section(state,section,raw,essay,config,details)
    from teacher.calibration import prepare_audit,review_consistency
    audit,verified=prepare_audit(essay,config,calibration_cases)
    if audit is not None and state.get('calibration'):
        saved=CalibrationAudit.model_validate(state['calibration'])
        if saved.case_checks==audit.case_checks:
            audit=saved
    calibration_attempted=False
    separate_scoring=not full_generation and (target_score is not None or config.calibration_set is not None)
    if full_generation and target_score is not None:
        raise ValueError('完整联调请求不能携带二稿目标')
    # With a goal, score in a separate request that never receives that goal.
    seeded_score=not resume and existing and set(existing)=={'overview'}
    calls=((3 if separate_scoring else 2) if fresh else (2 if seeded_score else 1))
    guidance_started=False
    for call in range(calls):
        targets={k:s for k,s in state['slots'].items() if s['section'] in FIELDS and s['status']=='failed' and s['repair_count']<MAX_REPAIRS}
        if not targets:
            break
        scoring_only=separate_scoring and state['slots'].get('overview',{}).get('status')=='failed'
        if scoring_only:
            targets={k:s for k,s in targets.items() if s['section']=='overview'}
        first_guidance=fresh and separate_scoring and not guidance_started and not scoring_only
        if first_guidance:
            guidance_started=True
        is_initial=fresh and call==0 and not separate_scoring
        if not scoring_only and audit is not None and audit.status=='一致性检查未完成' and not calibration_attempted:
            overview=TypeAdapter(Overview).validate_python(state['slots']['overview']['value'])
            audit=review_consistency(client,essay,config,overview,audit,verified)
            calibration_attempted=True
        if audit is not None:
            state['calibration']=audit.model_dump()
            client.calibration_audit=audit
        if is_initial:
            schema=GeneratedReport
        else:
            schema=create_model('RepairOnlyFailedItems',__base__=Model,essay_version=(str,...),
                                **{k:(target_annotation(state,k,s),...)
                                   for k,s in targets.items()})
            if not (fresh and call==0 or first_guidance or seeded_score and call==0):
                for s in targets.values():
                    s['repair_count']+=1
        request=payload(essay,config,request_id=state['request_id'],generate_only=list(targets),
                        repair_targets={k:dict(section_id=s['section'],index=s['index'],item_id=s.get('item_id'),repair_count=s['repair_count']) for k,s in targets.items()},
                        repair_errors=active_errors(state),validated_sections=section_values(state),
                        repair_instructions={e['path']:REPAIR_GUIDANCE[e['code']] for e in active_errors(state) if e['code'] in REPAIR_GUIDANCE},
                        candidate_comparisons=details,
                        validated_items={k:s['value'] for k,s in state['slots'].items() if s['status']=='valid'},
                        **({'teaching_goal':dict(target_score=target_score,maximum=config.maximum,
                            purpose='仅制定修改计划；原稿评分已独立完成，禁止改分，不保证考试得分')}
                           if target_score is not None and not scoring_only else {}))
        stop_after_call=False
        try:
            generator=client.generate_raw if callable(raw_method) else client.generate
            candidate=generator(schema,SYSTEM+'\n局部修复时只返回repair_targets对应字段，不返回或改写任何已验证条目。',request)
            raw=candidate.model_dump() if isinstance(candidate,BaseModel) else candidate
            if not isinstance(raw,dict) or raw.get('essay_version')!=essay.version:
                raise ValueError('VERSION_MISMATCH')
            if is_initial:
                state['slots']={}
                for section in FIELDS:
                    ingest_section(state,section,raw.get(section),essay,config,details,generated=True)
            else:
                for key,slot in list(targets.items()):
                    section,index=slot['section'],slot['index']
                    # Legacy full-section replies are read only at the requested slot.
                    value=raw.get(key)
                    if key not in raw and section in raw and not state.get('strict_contract'):
                        if section=='paragraphs' and index is not None:
                            pid=slot.get('item_id') or list(essay.paragraphs)[index]
                            matches=[x for x in raw[section] if isinstance(x,dict) and x.get('paragraph_id')==pid] if isinstance(raw[section],list) else []
                            value=matches[0] if len(matches)==1 else None
                        else:
                            value=raw[section] if index is None else (raw[section][index] if isinstance(raw[section],list) and index<len(raw[section]) else None)
                    if index is None and section in LISTS and isinstance(value,list):
                        count=slot['repair_count']
                        for e in state['diagnostics']:
                            if e.get('target')==key and e['status'] in ('failed','stopped'):
                                e['status']='repaired'
                                e['repair_count']=count
                        ingest_section(state,section,value,essay,config,details,repair_count=count,generated=True)
                    else:
                        check_slot(state,key,value,essay,config,details,repair=True,generated=True)
        except Exception as exc:
            if not isinstance(exc,(ValidationError,ValueError)) and (is_initial or fresh and call==0):
                record_exchange(state,client,essay)
                raise
            code=getattr(exc,'code',None) or ('SCHEMA_PARSE_ERROR' if isinstance(exc,ValidationError) else (
                ('VERSION_MISMATCH' if str(exc)=='VERSION_MISMATCH' else 'RESPONSE_INVALID')
                if isinstance(exc,ValueError) else 'MODEL_REQUEST_FAILED'))
            if not isinstance(exc,(ValidationError,ValueError)):
                code='MODEL_REQUEST_FAILED'
                stop_after_call=True
            for event in state['diagnostics']:
                if event.get('target') in targets and event['status'] in ('failed','stopped'):
                    event['status']='superseded'
            for key,slot in targets.items():
                if state['slots'].get(key,{}).get('status')=='valid':
                    continue
                status='stopped' if slot['repair_count']>=MAX_REPAIRS else 'failed'
                slot['status']=status
                state['diagnostics'].append(dict(diagnostic(slot['section'],key,code,repair_count=slot['repair_count'],
                                                            status=status,request_id=state['request_id']),target=key))
            if 'paragraphs' in state['slots'] and state['slots']['paragraphs']['status']!='valid':
                count=state['slots']['paragraphs']['repair_count']
                ingest_section(state,'paragraphs',None,essay,config,details,repair_count=count)
                for e in state['diagnostics']:
                    if e.get('target')=='paragraphs' and e['status'] in ('failed','stopped'):
                        e['status']='superseded'
            if isinstance(exc,ValidationError):
                for error in exc.errors(include_input=False,include_url=False):
                    loc=list(error['loc'])
                    head=str(loc[0]) if loc else ''
                    key=head if head in targets else next((k for k,s in targets.items() if s['section']==head),None)
                    if key:
                        slot=targets[key]
                        base=slot['section'] if slot['index'] is None else f'{slot["section"]}[{slot["index"]}]'
                        suffix=''.join(f'[{x}]' if isinstance(x,int) else '.'+str(x) for x in loc[1:])
                        state['diagnostics'].append(dict(diagnostic(slot['section'],base+suffix,'SCHEMA_'+error['type'].upper(),
                            repair_count=slot['repair_count'],status=slot['status'],request_id=state['request_id']),target=key))
        # Write final snapshots without candidate text. API request IDs are metadata.
        for event in state['diagnostics']:
            api_id=getattr(client,'last_request_id',None)
            if isinstance(api_id,str):
                event.setdefault('api_request_id',api_id)
        record_exchange(state,client,essay)
        persist(state['diagnostics'])
        if stop_after_call:
            break
        if fresh and scoring_only and call>=1 and state['slots']['overview']['status']!='valid':
            break  # At most one automatic score repair; keep the remaining guidance ungenerated.
        values=section_values(state,complete_only=True)
        if len(values)==len(FIELDS):
            report=Report(essay_version=essay.version,corrections=state['corrections'],**values)
            return report,state
    values=section_values(state,complete_only=True)
    if len(values)==len(FIELDS):
        return Report(essay_version=essay.version,corrections=state['corrections'],**values),state
    error=GenerationFailure(error_strings(state),section_values(state),state['corrections'],state['request_id'])
    error.state=state
    error.diagnostics=state['diagnostics']
    error.details=details
    raise error
