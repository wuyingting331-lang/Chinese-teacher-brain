"""Safe, structured diagnostics. Detailed candidate comparisons stay in session."""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

SECTION_LABELS = {
    'overview':'评分与总体评价', 'structure':'故事结构与详略', 'paragraphs':'逐段批改',
    'structure_overview':'全篇布局判断',
    'language':'语言修改', 'expressions':'好词好句', 'content_summary':'内容综合意见',
    'expression_summary':'表达综合意见', 'tasks':'二稿计划', 'picture_alignment':'图意评价',
}


def diagnostic(section, path, code, paragraph_id=None, repair_count=0, status='failed', request_id=''):
    return dict(section_id=section, path=path, code=code, paragraph_id=paragraph_id,
                item_id=paragraph_id or path,repair_count=repair_count, status=status, request_id=request_id)


def from_issue(section, issue, fallback, repair_count=0, request_id=''):
    paragraph = re.search(r'P\d+',issue)
    path = issue.split(':',1)[0] if ':' in issue else fallback
    code = ('QUOTE_MISMATCH' if '引文不属于' in issue else
            'PARAGRAPH_NOT_FOUND' if '段落不存在' in issue else
            'SCORE_INVALID' if '分' in issue else 'SECTION_INVALID')
    return diagnostic(section,path,code,paragraph.group() if paragraph else None,repair_count,request_id=request_id)


def persist(events, directory=None):
    from teacher.runtime_paths import data_path
    directory=Path(directory) if directory is not None else data_path('diagnostics')
    """Allow-list fields so original text and exception payloads cannot reach logs."""
    keys=('section_id','path','code','paragraph_id','item_id','repair_count','status','request_id','api_request_id')
    for event in events:
        safe={k:event.get(k) for k in keys}
        logging.getLogger('teacher.validation').warning(
            'category=%s path=%s paragraph_id=%s request_id=%s repair_count=%s status=%s',
            safe['code'],safe['path'],safe['paragraph_id'],safe['request_id'],safe['repair_count'],safe['status'])
        try:
            directory.mkdir(parents=True,exist_ok=True)
            with (directory/'validation.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),**safe),ensure_ascii=False)+'\n')
        except OSError:
            logging.getLogger('teacher').warning('diagnostic_write_failed')


def grouped_messages(events):
    from teacher.report_contract import RETIRED
    groups={}
    for e in events:
        if e['section_id'] in RETIRED or e.get('status') not in ('failed','stopped'):
            continue
        groups.setdefault(e['section_id'],[]).append(e)
    result=[]
    for section,items in groups.items():
        ids=sorted({e['paragraph_id'] for e in items if e.get('paragraph_id')})
        positions='、'.join('第'+str(int(p[1:]))+'段' for p in ids if re.fullmatch(r'P\d+',p))
        suffix='；已达修复上限，请人工检查后重新确认原文。' if any(e['status']=='stopped' for e in items) else '；有效条目已保留，可点击“修复未完成栏目”。'
        result.append(f'{SECTION_LABELS.get(section,section)}：{len({e["path"] for e in items})}处未完成'+
                      (f'（{positions}）' if positions else '')+suffix)
    return result


def response_failure_messages(events):
    from teacher.report_contract import ACTIVE
    descriptions={
        'RESPONSE_INCOMPLETE':'模型响应未完成，本批结果未计为完整；已验证内容仍保留。',
        'MODEL_REFUSAL':'模型返回拒绝信息，本批没有生成完整指导。',
        'JSON_DECODE_ERROR':'模型返回无法解码为完整JSON；没有用默认内容替代。',
        'RESPONSE_FAILED':'模型服务返回失败状态；已验证内容仍保留。',
        'MODEL_REQUEST_FAILED':'模型请求失败；没有覆盖已经验证的结果。',
        'VERSION_MISMATCH':'返回版本与确认原文不一致，本批结果没有合并。',
        'SCHEMA_PARSE_ERROR':'该批次发生结构解析失败；旧格式部分记录需按当前契约重新生成指导。',
    }
    codes={e.get('code') for e in events if e.get('section_id') in ACTIVE and e.get('status') in ('failed','stopped')}
    return [message for code,message in descriptions.items() if code in codes]


def persist_exchange(event,directory=None):
    """Response/parse/completeness metadata only; no prompts, response text or credentials."""
    keys=('schema_version','request_id','api_request_id','response_status','parse_status','incomplete_reason',
          'error_type','http_status','validation_status','valid_counts','complete_sections','complete')
    from teacher.runtime_paths import data_path
    directory=Path(directory) if directory is not None else data_path('diagnostics')
    try:
        directory.mkdir(parents=True,exist_ok=True)
        with (directory/'generation.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({k:event.get(k) for k in keys},ensure_ascii=False)+'\n')
    except OSError:
        logging.getLogger('teacher').warning('generation_metadata_write_failed')
