"""One report order and reference policy for complete/partial screen and Markdown."""
from datetime import datetime
from html import escape
import re
from zoneinfo import ZoneInfo
from pydantic import TypeAdapter
from teacher.diagnostics import SECTION_LABELS,diagnostic
from teacher.report_contract import RETIRED,health
from teacher.report_view import (REPORT_ORDER,example_paragraphs,example_text,paragraph_notices,
    tasks_view,structure_row,language_view,expression_reference,draft_display_blocks,implementation_reference)


def local_time(timestamp):
    try:
        return datetime.fromisoformat(timestamp).astimezone(ZoneInfo('Asia/Singapore')).strftime('%Y-%m-%d %H:%M +08:00')
    except (ValueError,TypeError):
        return '时间未知'


def safe(text):
    return escape(str(text),quote=True)


def md(value):
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~-])',r'\\\1',safe(value)).replace('\n','<br>')


def annotated_paragraph(text,edits):
    candidates=[]
    for e in edits:
        start,q=e.start,e.evidence.quote
        if e.kind=='明确错误' and start is not None and start>=0 and text[start:start+len(q)]==q:
            candidates.append((start,start+len(q),e.replacement))
    result=[]
    cursor=0
    for start,end,replacement in sorted(candidates):
        if start<cursor:
            continue
        result += [safe(text[cursor:start]),'<del>'+safe(text[start:end])+'</del>','<ins>'+safe(replacement)+'</ins>']
        cursor=end
    result.append(safe(text[cursor:]))
    return '<div class="original">'+''.join(result)+'</div>'


def evidence_text(evidence):
    return '；'.join(f'{e.paragraph_id}「{e.quote}」' for e in evidence)


def diagnostic_rows(record):
    if record.diagnostics:
        return record.diagnostics
    result=[]
    for issue in record.incomplete_errors:
        section=issue.split(':',1)[0].split('[',1)[0].split('.',1)[0]
        if section not in SECTION_LABELS:
            section='overview'
        match=re.search(r'P\d+',issue)
        result.append(diagnostic(section,issue.split(':',1)[0],'LEGACY_DETAILS_UNAVAILABLE',
            match.group() if match else None,repair_count=None))
    return result


def readable_issue(issue):
    section=issue.split(':',1)[0].split('[',1)[0]
    label=SECTION_LABELS.get(section,'报告')
    match=re.search(r'P(\d+)',issue)
    return label+'：'+(f'第{int(match.group(1))}段的引用与原文不一致。' if match else '尚未完成，请查看校验技术细节。')


def report_data(record):
    from teacher.service import SECTIONS
    from teacher.report_flow import section_values,item_type,LISTS
    if record.report:
        return {s:getattr(record.report,s) for s in SECTIONS},set()
    raw=section_values(record.partial_state) if record.partial_state else record.partial_sections
    values={}
    for name,value in raw.items():
        if name not in SECTIONS:
            continue
        annotation=item_type(name) if name in LISTS else SECTIONS[name].rebuild_annotation()
        values[name]=[TypeAdapter(annotation).validate_python(x) for x in value] if name in LISTS else TypeAdapter(annotation).validate_python(value)
    if record.partial_state:
        unfinished={s['section'] for s in record.partial_state['slots'].values() if s['status']!='valid'}
    else:
        unfinished=set(SECTIONS)-set(values)
        for issue in record.incomplete_errors:
            name=issue.split(':',1)[0].split('[',1)[0].split('.',1)[0]
            if name in SECTIONS:
                unfinished.add(name)
        if 'structure_overview' not in raw and not any(x.startswith('structure_overview') for x in record.incomplete_errors):
            unfinished.discard('structure_overview')
    unfinished.difference_update(RETIRED)
    return values,unfinished


def report_health(record):
    values,unfinished=report_data(record)
    result=health(values,unfinished,record.essay)
    from teacher.diagnostics import response_failure_messages
    result['messages']+=response_failure_messages(diagnostic_rows(record))
    return result


def failed_note(record,section):
    events=[e for e in diagnostic_rows(record) if e['section_id']==section and e['status'] in ('failed','stopped')]
    numbers=sorted({int(m.group(1))+1 for e in events if (m:=re.search(r'\[(\d+)\]',e['path']))})
    label='、'.join(f'第{i}项' for i in numbers)
    return label+'尚未完成，已验证条目继续保留。' if label else '本栏尚未完成，已验证内容继续保留。'


def item_numbers(record,section,count):
    slots=[s for s in record.partial_state.get('slots',{}).values()
           if s['section']==section and s['status']=='valid' and s['index'] is not None]
    if len(slots)==count:
        return [s['index']+1 for s in sorted(slots,key=lambda s:s['index'])]
    return list(range(1,count+1))


def judgment(label,value,with_evidence=False):
    if value is None:
        return ''
    result=f'**{label}**：{md(value.text)}'
    if value.reasoning:
        result+=' '+md(value.reasoning)
    ids='、'.join(dict.fromkeys(e.paragraph_id for e in value.evidence))
    return result+('（'+md(ids)+'）' if ids else '')


def calibration_markdown(record):
    if record.calibration is None:
        return ''
    lines=[]
    for case in record.calibration.case_checks:
        if 'reference_score' not in case:
            continue
        verified=case.get('status')=='已确认同稿'
        label='用户参考样本分数（已核对同稿）' if verified else '用户报告的参考分数（'+case.get('status','待核对')+'）'
        limits={w.name:w.maximum for w in record.config.weights}
        parts='，'.join(str(x['name'])+str(x['score'])+'/'+str(limits.get(x['name'],'?')) for x in case.get('reference_subscores',[]))
        lines.append(md(f'{case.get("label","参照样例")} · {label}：{parts}，总分{case["reference_score"]}/{case["maximum"]}。'))
        if not verified:
            lines.append('尚无可用的同稿精确校准；参考数字不作为本次作文已获评分。')
        elif record.report:
            lines.append(f'系统独立评分与参考相差{record.report.overview.score-case["reference_score"]:+d}分；保留独立判断。')
    if record.calibration.review:
        r=record.calibration.review
        lines.append('一致性检查 · '+md(r.verdict)+'：'+md(r.explanation))
    elif record.calibration.status=='一致性检查未完成':
        lines.append('参考评分一致性检查尚未完成；独立评分已保留。')
    return '\n\n'.join(lines)


def paragraph_comments(p):
    if p.teaching is None:
        return [(label,text) for label,text in [('本段优点',p.strength),('主要问题',p.problem),('修改建议',p.advice),
                ('本段示范修改 · '+p.example_kind,example_text(p))] if text]
    t=p.teaching
    rows=[('本段作用与优点',t.role+'\n'+p.strength)]
    rows.append(('最影响质量的问题','\n'.join(x.category+'：'+x.detail for x in t.issues) or p.problem or '本段未列出主要问题。'))
    if not (t.reorder or t.develop or t.expressions) and p.advice:
        rows.append(('怎样修改',p.advice))
    for label,moves in [('怎样修改 · 理顺表达',t.reorder),('怎样修改 · 发展内容',t.develop)]:
        if moves:
            rows.append((label,'\n\n'.join(x.location+'：'+x.action+'\n原因：'+x.reason for x in moves)))
    if t.expressions:
        entries=[]
        canonical=example_text(p)
        for x in t.expressions:
            entry=x.expression+' · '+x.placement+'\n作用：'+x.effect
            if x.expression not in canonical and x.sentence not in canonical:
                entry+='\n融入示例：'+x.sentence
            entries.append(entry)
        rows.append(('怎样修改 · 词句融入','\n\n'.join(entries)))
    if t.uncertainties:
        rows.append(('待确认处','\n'.join(t.uncertainties)))
    rows.append(('本段示范修改 · '+t.example_scope,example_text(p)))
    if t.invented_details:
        rows.append(('示范中新拟的局部细节（非原文事实）','；'.join(t.invented_details)))
    if p.example_kind=='可选扩写（新拟补充）':
        rows.append(('示范性质',p.example_kind))
    rows.append(('为什么这样改更好',t.why_better))
    if t.success_checks:
        rows.append(('修改自查','\n'.join(t.success_checks)))
    return rows


def detailed_comments(p,tasks):
    rows=paragraph_comments(p)
    existing='\n'.join(value for _,value in rows)
    # Preserve operational depth of old tasks once, next to the corresponding paragraph.
    for task in tasks:
        if task.title or not task.location or task.location.paragraph_id!=p.paragraph_id:
            continue
        for label,value in [('历史任务补充步骤',task.action),('修改自查',task.done)]:
            if value and value not in existing:
                rows.append((label,value))
                existing+='\n'+value
    return rows


def example_markdown(p,original):
    return '\n\n'.join('保留原段，见本段原文。' if text==original else md(text) for text in example_paragraphs(p))


def basis_markdown(record,values,unfinished):
    lines=['评分配置：'+md(record.config.name or record.config.version),md(record.config.source),
           '版本：'+md(record.config.version)+'；提示词：'+md(record.prompt_version)]
    o=values.get('overview')
    if o:
        lines += [judgment('内容评分依据',o.content),judgment('表达评分依据',o.expression)]
    if calibration_markdown(record):
        lines.append(calibration_markdown(record))
    if record.calibration:
        for case in record.calibration.case_checks:
            if case.get('source'):
                lines.append('样例来源：'+md(case['source']))
            lines += [md(x) for x in case.get('limitations',[])]
    if any(s.get('section') in RETIRED for s in record.partial_state.get('slots',{}).values()):
        lines.append('历史格式的附加诊断保留在记录备份中，不作为当前报告的必需栏目。')
    from teacher.images import valid_confirmation
    if record.essay.kind=='看图作文' and not valid_confirmation(record.essay):
        lines.append('尚未核对图意，不能确认符合图片要求。')
    if valid_confirmation(record.essay):
        c=record.essay.picture_confirmation
        lines += ['确认图意方式：'+md(c.method),md(c.text_requirements)]
        if values.get('picture_alignment'):
            p=values['picture_alignment']
            lines += [md(p.relevance),'合理补充：'+md(p.reasonable_additions),'偏离图意：'+md(p.deviations)]
    if 'picture_alignment' in unfinished:
        lines.append('图意评价：'+failed_note(record,'picture_alignment'))
    return '\n\n'.join(x for x in lines if x)


def section_markdown(record):
    values,unfinished=report_data(record)
    def title(text,sections):
        return '## '+text+('（不完整）' if unfinished.intersection(sections) else '')
    tasks=values.get('tasks',[])
    task_refs=tasks_view(tasks,item_numbers(record,'tasks',len(tasks)))
    blocks={}
    lines=[title('1. 得分与整体评价',{'overview'})]
    o=values.get('overview')
    if o:
        limits={w.name:w.maximum for w in record.config.weights}
        parts=[f'{s.name}{s.score}/{limits[s.name]}' for s in o.subscores if s.name in limits]
        lines += ['**系统本次独立评分：'+md('，'.join(parts)+('，' if parts else ''))+f'总分：{o.score}/{record.config.maximum}**',
                  md(record.config.nature),md(o.comment),'**两个优点**']
        lines += ['- '+md(x.text) for x in o.strengths[:2]]
    else:
        lines.append('评分尚未通过校验，不显示未经验证的分数或总体评语。')
    lines += ['**三个提升重点**']
    lines += ['- '+md('、'.join(t.paragraph_ids)+'：'+t.title) for t in task_refs[:3]]
    if 'tasks' in unfinished:
        lines.append('提升重点：'+failed_note(record,'tasks'))
    if record.target_score is not None:
        lines.append(f'二稿目标：{record.target_score}/{record.config.maximum}，仅用于修改计划，不影响原稿评分，也不保证考试分数。')
    if 'picture_alignment' in unfinished:
        lines.append('部分校验尚未完成，详见“评分依据”。')
    blocks['overview']='\n\n'.join(lines)
    blocks['basis']=basis_markdown(record,values,unfinished)

    lines=[title('2. 故事结构与详略建议',{'structure','structure_overview'})]
    fallback=('全篇布局判断尚未完成，以下保留已验证的结构建议。' if 'structure_overview' in unfinished else
              '旧记录未单列全篇布局判断，以下保留原有结构建议，不补造分析。')
    lines.append(md(values.get('structure_overview') or fallback))
    table=['|原文位置与作用|当前结构或详略问题|调整动作|具体安排及目的|','|---|---|---|---|']
    table += ['|'+'|'.join(md(x) for x in structure_row(s))+'|' for s in values.get('structure',[])]
    lines.append('\n'.join(table))
    for name in ('structure','structure_overview'):
        if name in unfinished:
            lines.append(SECTION_LABELS[name]+'：'+failed_note(record,name))
    blocks['structure']='\n\n'.join(lines)

    reviews={p.paragraph_id:p for p in values.get('paragraphs',[])}
    lines=[title('3. 逐段修改指导',{'paragraphs'})]
    for pid,text in record.essay.paragraphs.items():
        p=reviews.get(pid)
        marked=' · 重点修改' if p and p.teaching and p.teaching.is_key else ''
        lines += ['### '+pid+marked,'**原文**\n\n'+md(text)]
        if not p:
            lines.append('本段点评尚未完成，原文已保留。')
            continue
        for label,value in detailed_comments(p,tasks):
            lines.append('**'+md(label)+'**\n\n'+(example_markdown(p,text) if label.startswith('本段示范修改') else md(value)))
        lines += [md(note) for note in paragraph_notices(p)]
    if 'paragraphs' in unfinished:
        lines.append(failed_note(record,'paragraphs'))
    blocks['paragraphs']='\n\n'.join(lines)

    language=values.get('language',[])
    table=['|学生原句|问题类型|建议修改|修改原因|','|---|---|---|---|']
    for i,e in language_view(language,record.essay.paragraphs,item_numbers(record,'language',len(language))):
        pid=e.evidence.paragraph_id
        quote=e.evidence.quote
        replacement=e.replacement
        p=reviews.get(pid)
        if p and (replacement==example_text(p) or replacement in example_paragraphs(p)):
            replacement='见'+pid+'本段示范'
        if quote==record.essay.paragraphs.get(pid):
            quote='整段原文见逐段指导'
            if p and e.kind=='可选优化':
                replacement='整段提升以'+pid+'本段示范为准；历史原建议保留在JSON记录'
        table.append('|'+'|'.join(md(x) for x in [f'条目{i} · '+pid+'：'+quote,e.kind+'／'+e.category,
                                                       replacement,e.reason])+'|')
    lines=[title('4. 语言修改表',{'language'}),'\n'.join(table)]
    if 'language' in unfinished:
        lines.append(failed_note(record,'language'))
    elif not language:
        lines.append('本栏未列出需要修改的语言条目。')
    blocks['language']='\n\n'.join(lines)

    lines=[title('5. 词句提升',{'expressions'})]
    for source,label in [('原文已有','原文中值得保留的表达'),('教学建议（新拟示例）','可融入本篇的提升表达')]:
        tips=[t for t in values.get('expressions',[]) if t.source==source]
        if not tips:
            continue
        lines += ['**'+label+'**']
        for t in tips:
            expression=t.expression if t.expression!=record.essay.paragraphs.get(t.location.paragraph_id) else '整段表达（见原文）'
            lines.append('- '+md(expression)+' · '+md(t.location.paragraph_id)+'：'+md(t.reason))
            ref=expression_reference(t,reviews)
            if ref:
                lines.append('已用于'+md(ref)+'本段示范，见逐段指导。')
            elif t.example and t.example!=record.essay.paragraphs.get(t.location.paragraph_id):
                lines.append(('原文例句：' if t.example_source=='原文引用' else '融入本篇的句子（教学新拟）：')+md(t.example))
    if 'expressions' in unfinished:
        lines.append(failed_note(record,'expressions'))
    elif not values.get('expressions'):
        lines.append('本次没有额外列出词句，不为凑数新增表达。')
    blocks['expressions']='\n\n'.join(lines)

    lines=[title('6. 二稿执行清单',{'tasks'})]
    lines += ['- ['+('x' if t.number in record.completed_tasks else ' ')+'] '+md(f'任务{t.number} · '+ '、'.join(t.paragraph_ids)+'：'+t.title) for t in task_refs]
    if 'tasks' in unfinished:
        lines.append(failed_note(record,'tasks'))
    blocks['checklist']='\n\n'.join(lines)
    return blocks


def report_body(record,blocks=None):
    blocks=blocks or section_markdown(record)
    lines=[]
    for key in REPORT_ORDER:
        lines.append(blocks[key])
        if key=='overview':
            lines.append('<details>\n<summary>评分依据</summary>\n\n'+blocks['basis']+'\n\n</details>')
    return '\n\n'.join(lines)


def incomplete_markdown(record):
    return '## 不完整批改报告\n\n'+report_body(record)


def markdown_report(record):
    lines=['# '+md(record.essay.title),'**演示数据，不是真实评分**' if record.demo else '**作文批改报告**',
           '原文版本：'+record.essay.version,'创建时间：'+local_time(record.created_at)]
    status=report_health(record)
    if not status['complete'] and (record.report or record.partial_sections or record.partial_state or record.incomplete_errors):
        lines += ['## 不完整批改报告']+status['messages']
    if record.report or record.partial_sections or record.partial_state or record.incomplete_errors:
        lines += [report_body(record)]
    else:
        lines += ['## 确认原文']+[f'**{pid}**\n\n'+md(text) for pid,text in record.essay.paragraphs.items()]
    if record.second_draft:
        d=record.second_draft
        values,_=report_data(record)
        lines += ['## 示范二稿','模型示范不代表学生独立完成，不承诺考试分数。相同段落引用上方原段或提升示范；完整稿可单独下载。',
                  '\n\n'.join(md(x) for x in draft_display_blocks(record,values.get('paragraphs',[]))),'### 修改落实说明']
        lines += [f'任务{i.task_number} · '+md(implementation_reference(record,i,values.get('paragraphs',[])) or '「'+i.draft_quote+'」')+'：'+md(i.explanation) for i in d.implementation]
        if d.invented_details:
            lines += ['### 示范中新拟的局部细节（非原文事实）']+[md(x) for x in d.invented_details]
        if d.optional_additions:
            lines += ['### 可选新增情节（未写入正文）']+[md(x) for x in d.optional_additions]
    if not record.second_draft and record.draft_state:
        state=record.draft_state
        lines += ['## 示范二稿（未完成）']
        if state.get('body_status')=='valid':
            lines += ['正文已通过结构与版本校验；修改落实说明未完成。',md(state['body']['body'])]
        else:
            lines += ['正文尚未通过校验。']
        lines += [md(e['reason']) for e in state.get('errors',[])]
    lines += [md(record.backup_images)]
    return '\n\n'.join(lines)


def markdown_draft(record):
    if not record.second_draft:
        return ''
    d=record.second_draft
    blocks=[p for p in re.split(r'\r\n|\r|\n',d.body) if p.strip()]
    lines=['# '+md(record.essay.title)+' · 提升示范二稿',
           '模型辅助示范，不代表学生独立完成，不承诺考试分数。']+[md(p) for p in blocks]
    if d.invented_details:
        lines += ['## 新拟局部细节']+[md(x) for x in d.invented_details]
    if d.optional_additions:
        lines += ['## 未采用的可选情节']+[md(x) for x in d.optional_additions]
    return '\n\n'.join(lines)


def show_report(st,record,show_health=True):
    values,unfinished=report_data(record)
    if show_health:
        for message in report_health(record)['messages']:
            st.warning(message)
    blocks=section_markdown(record)
    st.subheader(record.essay.title)
    for section in REPORT_ORDER:
        if section=='paragraphs':
            st.markdown(blocks[section].split('\n\n',1)[0])
            show_paragraphs(st,record,values)
            if 'paragraphs' in unfinished:
                st.info(failed_note(record,'paragraphs'))
        elif section=='checklist':
            st.markdown(blocks[section].split('\n\n',1)[0])
            tasks=values.get('tasks',[])
            for task in tasks_view(tasks,item_numbers(record,'tasks',len(tasks))):
                key=f'checklist_{record.id}_{task.number}'
                st.session_state.setdefault(key,task.number in record.completed_tasks)
                checked=st.checkbox(f'任务{task.number} · '+ '、'.join(task.paragraph_ids)+'：'+task.title,
                    key=key,disabled=st.session_state.get('busy',False))
                record.completed_tasks=sorted((set(record.completed_tasks)|{task.number}) if checked else (set(record.completed_tasks)-{task.number}))
            if 'tasks' in unfinished:
                st.info(failed_note(record,'tasks'))
        else:
            st.markdown(blocks[section])
        if section=='overview':
            with st.expander('评分依据'):
                st.markdown(blocks['basis'])
    show_second_draft(st,record)


def show_paragraphs(st,record,values):
    st.caption('左侧为确认原文；右侧为修改指导。语言纠错集中列在语言修改表。')
    reviews={p.paragraph_id:p for p in values.get('paragraphs',[])}
    for pid,text in record.essay.paragraphs.items():
        p=reviews.get(pid)
        st.markdown('### '+pid+(' · 重点修改' if p and p.teaching and p.teaching.is_key else ''))
        left,right=st.columns([1.2,1],gap='large')
        with left:
            st.markdown('**原文**')
            st.markdown(annotated_paragraph(text,[]),unsafe_allow_html=True)
        with right:
            if not p:
                st.info('本段点评尚未完成，原文已保留。')
            else:
                for label,value in detailed_comments(p,values.get('tasks',[])):
                    st.markdown('**'+label+'**')
                    if label.startswith('本段示范修改'):
                        for block in example_paragraphs(p):
                            st.text('保留原段，见本段原文。' if block==text else block)
                    else:
                        st.text(value)
                for note in paragraph_notices(p):
                    st.warning(note)
        st.divider()


def show_second_draft(st,record):
    state=record.draft_state
    if not record.second_draft and state:
        st.subheader('示范二稿')
        if state.get('body_status')=='valid':
            st.warning('二稿正文已通过结构与版本校验；修改落实说明未完成，请点击“只重试落实说明”。人物、事件与结局仍需人工核对。')
            st.text(state['body']['body'])
            st.download_button('下载二稿正文（说明未完成）',state['body']['body'],file_name=f'{record.id}-body.txt')
        else:
            st.warning('二稿正文尚未通过校验，请点击“重新生成示范二稿”。')
            if state.get('unverified_body'):
                with st.expander('未验证草稿'):
                    st.text(state['unverified_body'])
        for error in state.get('errors',[]):
            st.info(error['reason'])
        with st.expander('二稿技术详情'):
            st.json(dict(errors=state.get('errors',[]),exchanges=state.get('exchanges',[])))
            if state.get('unverified_implementation'):
                st.caption('以下是未通过校验的说明候选，不能作为已落实证据。')
                st.json(state['unverified_implementation'])
    if record.second_draft:
        d=record.second_draft
        st.subheader('示范二稿')
        st.caption('模型示范不代表学生独立完成，不承诺考试分数。相同段落引用上方原段或提升示范。')
        values,_=report_data(record)
        for block in draft_display_blocks(record,values.get('paragraphs',[])):
            st.text(block)
        st.download_button('下载完整示范二稿',markdown_draft(record),file_name=f'{record.id}-draft.md',mime='text/markdown',
                           disabled=st.session_state.get('busy',False))
        st.markdown('**修改落实说明**')
        for item in d.implementation:
            ref=implementation_reference(record,item,values.get('paragraphs',[])) or '「'+item.draft_quote+'」'
            st.text(f'任务{item.task_number} · {ref}：{item.explanation}')
        if d.invented_details:
            st.caption('新拟局部细节（非原文事实）：'+'；'.join(d.invented_details))
        if d.optional_additions:
            st.caption('未采用的可选新增情节：'+'；'.join(d.optional_additions))
