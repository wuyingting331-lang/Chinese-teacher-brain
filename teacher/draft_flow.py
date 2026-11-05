"""Independent, resumable body and implementation validation. Never mutates reports."""
import json
from pathlib import Path
from pydantic import Field, ValidationError
from teacher.models import Model, Implementation, SecondDraft
from teacher.prompts import DRAFT_SYSTEM, DRAFT


class DraftBody(Model):
    essay_version: str
    body: str = Field(min_length=1)
    optional_additions: list[str]
    invented_details: list[str] = Field(default_factory=list)


class DraftNotes(Model):
    implementation: list[Implementation] = Field(min_length=1)


def issue(code, path, reason):
    return dict(code=code, path=path, reason=reason)


def note_errors(items, body, report):
    errors=[]
    for n,item in enumerate(items):
        if item.task_number > len(report.tasks):
            errors.append(issue('TASK_NOT_FOUND',f'implementation[{n}].task_number','对应任务不存在。'))
        if item.draft_quote not in body:
            errors.append(issue('DRAFT_QUOTE_MISMATCH',f'implementation[{n}].draft_quote','落实证据未逐字出现在本次二稿中。'))
    if any(p.teaching is not None for p in report.paragraphs):
        required={i for i,t in enumerate(report.tasks,1) if t.focus in ('内容发展','结构与衔接','人物变化')}
        for number in sorted(required-{i.task_number for i in items}):
            errors.append(issue('IMPLEMENTATION_MISSING',f'implementation.task_{number}','主要内容任务缺少落实说明。'))
    return errors


def parse_errors(error, prefix=''):
    return [issue('SCHEMA_PARSE_ERROR',prefix+'.'.join(map(str,e['loc'])), '字段缺失或类型不正确：'+e['type']) for e in error.errors()]


def run(client,essay,config,report,target_score=None,state=None):
    from teacher.service import payload, GenerationFailure
    state=state if state is not None else {}
    if state and state.get('essay_version')!=essay.version:
        raise GenerationFailure(['二稿状态与确认原文版本不一致，请重新生成。'],{})
    state.setdefault('essay_version',essay.version)
    state.setdefault('exchanges',[])
    if state.get('body_status')=='valid':
        saved=DraftBody.model_validate(state.get('body'))
        if saved.essay_version!=essay.version or not saved.body.strip():
            raise GenerationFailure(['已保存二稿正文版本或内容无效，请重新生成。'],{})
    for attempt in range(2):
        notes_only=state.get('body_status')=='valid'
        schema=DraftNotes if notes_only else SecondDraft
        request=payload(essay,config,report=report.model_dump(),teaching_goal=target_score,
            validated_draft=state.get('body') if notes_only else None,repair_errors=state.get('errors',[]))
        instruction=DRAFT+'\n同一二稿引文可以支持多项相关任务；证据只从实际二稿复制，不从原文或计划复制。'
        if notes_only:
            instruction+='\n只返回implementation，依据validated_draft正文补全说明；不要改写正文。'
            # No original snippets or earlier paragraph examples compete with the actual draft.
            request=json.dumps(dict(essay_version=essay.version,validated_draft=state['body'],
                tasks=[dict(task_number=i,title=t.title,focus=t.focus,paragraph_ids=t.paragraph_ids)
                       for i,t in enumerate(report.tasks,1)],repair_errors=state.get('errors',[])),ensure_ascii=False)
        errors=[]
        try:
            raw=(client.generate_raw(schema,DRAFT_SYSTEM+instruction,request) if callable(getattr(type(client),'generate_raw',None))
                 else client.generate(schema,DRAFT_SYSTEM+instruction,request))
            if isinstance(raw,Model): raw=raw.model_dump()
            if not isinstance(raw,dict): raise ValueError('JSON_NOT_OBJECT')
            if not notes_only:
                state['unverified_body']=raw.get('body') if isinstance(raw.get('body'),str) else ''
                try:
                    body=DraftBody.model_validate({k:raw[k] for k in DraftBody.model_fields if k in raw})
                    if body.essay_version!=essay.version:
                        errors.append(issue('VERSION_MISMATCH','essay_version','二稿版本与确认原文不一致。'))
                    elif not body.body.strip():
                        errors.append(issue('BODY_EMPTY','body','正文只有空白。'))
                    else:
                        state['body']=body.model_dump()
                        state['body_status']='valid'
                except ValidationError as error:
                    errors.extend(parse_errors(error))
            if state.get('body_status')=='valid':
                try:
                    notes=DraftNotes.model_validate({'implementation':raw.get('implementation')})
                    errors.extend(note_errors(notes.implementation,state['body']['body'],report))
                    if errors:
                        state['unverified_implementation']=notes.model_dump()['implementation']
                    if not errors:
                        result=SecondDraft(**state['body'],implementation=notes.implementation)
                        state.update(notes_status='valid',errors=[],implementation=notes.model_dump()['implementation'])
                        state.pop('unverified_implementation',None)
                        return result
                except ValidationError as error:
                    errors.extend(parse_errors(error))
        except Exception as error:
            if isinstance(error,ValidationError): errors.extend(parse_errors(error))
            else: errors.append(issue(getattr(error,'code','MODEL_REQUEST_FAILED'),'response','模型响应或JSON解析失败，已保留此前有效正文。'))
        finally:
            exchange=getattr(client,'last_exchange',{})
            state['exchanges'].append(dict(exchange) if isinstance(exchange,dict) else {})
            try:
                from teacher.runtime_paths import data_path
                p=data_path('diagnostics','draft.jsonl'); p.parent.mkdir(parents=True,exist_ok=True)
                metadata={k:state['exchanges'][-1].get(k) for k in ('response_status','parse_status','api_request_id','incomplete_reason','error_type','http_status')}
                with p.open('a',encoding='utf-8') as f:
                    f.write(json.dumps(dict(essay_version=essay.version,errors=errors,body_status=state.get('body_status','failed'),notes_status=state.get('notes_status','failed'),exchange=metadata),ensure_ascii=False)+'\n')
            except OSError: pass
        state['errors']=errors
        state['notes_status']='failed'
        if state.get('body_status')!='valid': state['body_status']='failed'
    failure=GenerationFailure([e['reason'] for e in state['errors']],{})
    failure.draft_state=state
    raise failure
