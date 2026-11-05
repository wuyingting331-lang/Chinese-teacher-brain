"""Streamlit entry point: python -m streamlit run app.py."""
import logging
import streamlit as st
from teacher.family_auth import require_login

st.set_page_config(page_title='华文作文小老师', page_icon='✍️', layout='wide')
require_login(st)

from teacher.runtime_paths import bind_session

bind_session(st.session_state)

from teacher.client import ModelClient, settings, friendly_error
from teacher.demo import demo_record
from teacher.models import Essay, Record
from teacher.render import show_report, annotated_paragraph, local_time
from teacher.service import generate_report, generate_draft, GenerationFailure
from teacher.storage import save, load_all
from teacher.prompts import VERSION
from teacher.config import scoring_profiles
from teacher.calibration import prepare_audit,review_consistency
from teacher.models import CalibrationAudit
from teacher.report_contract import SCHEMA_VERSION
from teacher.image_ui import picture_editor, restore_picture_editor
from teacher.images import valid_confirmation
from teacher.private_media import private_download

# Upgrade an existing browser session after a code reload without touching editor text.
if st.session_state.get('record') is not None:
    previous_record=st.session_state.record
    st.session_state.record=Record.model_validate(previous_record.model_dump())

st.markdown('''<style>
.original {color:#171717;background:#fff;padding:1.2rem;border-left:3px solid #d5c6aa;
white-space:pre-wrap;line-height:1.95;font-size:1.1rem;border-radius:4px;}
.original del,.original ins {color:#b42323;} .original ins {margin-left:.25em;}
@media(max-width:700px){[data-testid="stHorizontalBlock"]{flex-direction:column;}
[data-testid="stColumn"]{width:100%!important;flex:1 1 100%!important;}}
</style>''', unsafe_allow_html=True)


def install(record):
    st.session_state.record = record
    st.session_state.pop('schema_adaptation',None)
    for key in list(st.session_state):
        if key.startswith('checklist_'):
            st.session_state.pop(key,None)
    st.session_state.scoring_profile = record.config.version
    st.session_state.goal_enabled = record.target_score is not None
    st.session_state.goal_score = record.target_score or (36 if record.config.maximum==40 else record.config.maximum)
    for k,v in record.essay.model_dump().items():
        if k not in ('pictures','picture_confirmation'):
            st.session_state['edit_'+k] = v
    restore_picture_editor(st,record.essay)
    st.session_state.pop('partial',None)
    st.session_state.pop('operation_error',None)
    st.session_state.pop('validation_comparisons',None)
    st.session_state.busy = False


def fail(error):
    # Do not log exception messages, API payloads, keys or student text.
    logging.getLogger('teacher').warning('operation_failed type=%s', type(error).__name__)
    st.error(friendly_error(error))


st.title('华文作文小老师')
st.caption('PSLE 普通华文 · 小五／小六 · 先读懂故事，再把重点写具体')
try:
    secrets = dict(st.secrets)
except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
    secrets = {}
key, model = settings(secrets)
st.session_state.vision_model = secrets.get('OPENAI_VISION_MODEL','')
busy = st.session_state.get('busy', False)
try:
    profiles = {c.version:c for c in scoring_profiles()}
    previous=st.session_state.get('record')
    if previous:
        profiles[previous.config.version]=previous.config
except (OSError, ValueError):
    st.error('评分配置无法读取或校验失败，请检查 config 下的评分配置。')
    st.stop()


def queue_operation(kind):
    from teacher.family_auth import authenticated,configured_password
    if not authenticated(st.session_state,configured_password(st)):
        return
    if st.session_state.get('busy'):
        return
    r = st.session_state.get('record')
    try:
        values={k:st.session_state['edit_'+k] for k in Essay.model_fields if k not in ('pictures','picture_confirmation')}
        picture_mode=values['kind']=='看图作文'
        edited = Essay(**values,pictures=st.session_state.get('edit_pictures',()) if picture_mode else (),
                       picture_confirmation=st.session_state.get('effective_picture_confirmation') if picture_mode else None)
    except (ValueError, KeyError):
        return
    if not r or r.demo or edited.version != r.essay.version or not key or not model:
        return
    selected_goal=int(st.session_state.goal_score) if st.session_state.get('goal_enabled') else None
    if selected_goal != r.target_score:
        return
    if st.session_state.scoring_profile != r.config.version:
        return
    if (kind == 'score' and r.report) or (kind == 'draft' and (not r.report or r.second_draft)):
        return
    if kind=='calibration' and not r.report:
        return
    if kind=='score' and r.partial_state and r.partial_state.get('format_version')==SCHEMA_VERSION and not any(s['status']=='failed' for s in r.partial_state.get('slots',{}).values()):
        return
    st.session_state.busy = True
    st.session_state.pending = (kind, r.id, r.essay.version)


with st.sidebar:
    st.header('学习档案')
    if st.button('打开离线演示', width='stretch', disabled=busy):
        install(demo_record())
        st.rerun()
    if st.button('新建作文', width='stretch', disabled=busy):
        st.session_state.pop('record',None)
        st.session_state.pop('schema_adaptation',None)
        st.session_state.pop('goal_enabled',None)
        st.session_state.pop('goal_score',None)
        st.session_state.pop('scoring_profile',None)
        for field in Essay.model_fields:
            st.session_state.pop('edit_'+field,None)
        restore_picture_editor(st,Essay(title='新作文',body='待填写'))
        st.session_state.pop('partial',None)
        st.session_state.pop('operation_error',None)
        st.rerun()
    records,warnings = load_all()
    for warning in warnings:
        st.warning(warning)
    if records:
        chosen = st.selectbox('已保存记录', list(range(len(records))),
                              format_func=lambda i: f'{records[i].essay.title} · {local_time(records[i].created_at)} · {records[i].id[:6]}',
                              disabled=busy)
        if st.button('重新打开', disabled=busy):
            install(records[chosen])
            st.rerun()
    else:
        st.caption('还没有已保存的记录。')
    st.caption('记录与图片仅保存在当前会话的临时目录，不与其他会话共享。重新连接或云端重启后可能无法恢复，请及时下载 JSON 和报告，并自行保留原图。')
    if not key or not model:
        st.info('真实评分需要配置 OPENAI_API_KEY 与 OPENAI_MODEL。可在 .env 或 Streamlit secrets 中填写。离线演示无需联网。')

if 'scoring_profile' not in st.session_state:
    st.session_state.scoring_profile=next(iter(profiles))
selected_profile=st.selectbox('教学参考评分配置',list(profiles),key='scoring_profile',
                            format_func=lambda version:profiles[version].name or version,disabled=busy)
scoring_config=profiles[selected_profile]
st.caption(scoring_config.nature+' · '+scoring_config.source)
st.subheader('1. 填写与核对作文')
a,b,c = st.columns(3)
with a:
    name = st.text_input('学生姓名（可选）', key='edit_name', disabled=busy)
    grade = st.selectbox('年级',['小六','小五'], key='edit_grade', disabled=busy)
with b:
    title = st.text_input('作文题目', key='edit_title', disabled=busy)
    kind = st.selectbox('题型',['命题作文','看图作文'], key='edit_kind', disabled=busy)
with c:
    draft = st.selectbox('稿次',['一稿','二稿'], key='edit_draft', disabled=busy)
requirements = st.text_area('题目要求或图片内容的文字说明', key='edit_requirements', height=90, disabled=busy)
pictures, picture_confirmation = picture_editor(st,key,model,busy) if kind=='看图作文' else ((),None)
body = st.text_area('作文正文（每段换行，保留原有字词和标点）', key='edit_body',height=260, disabled=busy)
st.session_state.setdefault('goal_enabled',True)
st.session_state.setdefault('goal_score',36 if scoring_config.maximum==40 else scoring_config.maximum)
if not 1<=st.session_state.goal_score<=scoring_config.maximum:
    st.session_state.goal_score=36 if scoring_config.maximum==40 else scoring_config.maximum
goal_enabled = st.checkbox('设置修改目标分数', key='goal_enabled', disabled=busy)
goal_score = st.number_input('修改目标分数', min_value=1, max_value=scoring_config.maximum,
                             step=1, key='goal_score', disabled=busy or not goal_enabled)
target_score = int(goal_score) if goal_enabled else None
st.caption('目标仅用于制定修改计划。原稿独立评分，不为迎合目标抬分；不保证修改稿在真实考试获得该分数。未提供正式评分表时，仍为暂定教学参考评分。')
current = None
try:
    current = Essay(name=name,grade=grade,title=title,kind=kind,requirements=requirements,draft=draft,body=body,
                    pictures=pictures,picture_confirmation=picture_confirmation)
except ValueError:
    st.caption('填写题目与正文后，即可确认原文。')
record = st.session_state.get('record')
same = bool(current and record and current.version == record.essay.version and
            target_score == record.target_score and scoring_config==record.config)
busy = st.session_state.get('busy',False)
if record and not same:
    st.warning('作文、评分配置或修改目标已改变。下方报告仍对应已确认的旧版本，请重新确认后生成新报告。')
if st.button('确认原文', disabled=not current or busy or same, type='primary'):
    st.session_state.pop('schema_adaptation',None)
    st.session_state.record = Record(essay=current, config=scoring_config, prompt_version=VERSION, model_name=model,
                                    target_score=target_score,calibration=prepare_audit(current,scoring_config)[0],report_schema_version=SCHEMA_VERSION)
    st.session_state.pop('partial',None)
    st.session_state.pop('operation_error',None)
    st.session_state.pop('validation_comparisons',None)
    st.rerun()
record = st.session_state.get('record')
if not record:
    st.info('填写作文并点击“确认原文”，再开始评分；也可打开离线演示查看完整页面。')
    st.stop()
same = bool(current and current.version == record.essay.version and target_score == record.target_score and scoring_config==record.config)
if record.demo:
    st.warning('演示数据：固定的离线报告及分数，仅用于检查页面，不是真实评分或模型调用结果。')
st.caption(f'确认原文版本：{record.essay.version[:12]}')
if record.essay.kind == '看图作文' and not valid_confirmation(record.essay):
    st.warning('尚未核对图意。本次只能分析文章本身，不能确认符合图片要求。')
has_report=bool(record.report or record.partial_sections or record.partial_state or record.incomplete_errors)
if not has_report:
    with st.expander('查看已确认原文（独立保存）', expanded=True):
        st.text(record.essay.title)
        for pid,text in record.essay.paragraphs.items():
            st.caption(pid)
            st.markdown(annotated_paragraph(text,[]),unsafe_allow_html=True)


def run_operation(operation):
    st.session_state.busy = True
    try:
        with st.spinner('老师正在阅读与核对，请稍候……'):
            operation()
    except GenerationFailure as error:
        if hasattr(error,'draft_state'):
            record.draft_state=error.draft_state
            st.session_state.pop('operation_error',None)
            return
        st.session_state.partial = dict(version=record.essay.version, sections=error.partial, errors=error.errors)
        if not record.report:
            from teacher.service import serialized
            record.partial_sections=serialized(error.partial)
            record.incomplete_errors=error.errors
            record.corrections.extend(error.corrections)
            record.partial_state=getattr(error,'state',{})
            record.diagnostics=getattr(error,'diagnostics',[])
            if record.partial_state.get('calibration'):
                record.calibration=CalibrationAudit.model_validate(record.partial_state['calibration'])
        st.session_state.validation_comparisons=getattr(error,'details',[])
        if record.report:
            st.session_state.operation_error='示范二稿未通过校验，已保留批改报告，请重试。'
        else:
            st.session_state.pop('operation_error',None)
    except Exception as error:
        st.session_state.operation_error = friendly_error(error)
        fail(error)
    finally:
        st.session_state.busy = False


def score():
    global record
    seed=None
    if ((record.partial_state and record.partial_state.get('format_version')!=SCHEMA_VERSION) or
        (record.partial_sections and not record.partial_state)):
        from teacher.report_migration import seed_from_legacy
        record,seed,snapshot=seed_from_legacy(record)
        st.session_state.record=record
        st.session_state.pop('validation_comparisons',None)
        st.session_state.schema_adaptation='历史原记录已独立备份；只保留重新核验通过的原评分，指导按当前schema重新生成。'
    record.generation_versions=list(dict.fromkeys([*record.generation_versions,record.prompt_version,VERSION]))
    record.prompt_version=VERSION
    client=ModelClient(key,model)
    if seed:
        result=generate_report(client,record.essay,record.config,existing=seed,target_score=record.target_score)
    elif record.partial_state:
        result = generate_report(client,record.essay,record.config,resume=record.partial_state,
                                 comparisons=st.session_state.get('validation_comparisons'),target_score=record.target_score)
    elif record.partial_sections:
        result = generate_report(client,record.essay,record.config,existing=record.partial_sections,target_score=record.target_score)
    else:
        result = generate_report(client,record.essay,record.config,target_score=record.target_score)
    record.report = result
    record.report_schema_version=SCHEMA_VERSION
    audit=getattr(client,'calibration_audit',None)
    if isinstance(audit,CalibrationAudit):
        record.calibration=audit
    record.model_name = model
    record.second_draft = None
    record.draft_state = {}
    record.partial_sections={}
    record.incomplete_errors=[]
    record.partial_state={}
    diagnostics=getattr(client,'generation_diagnostics',[])
    record.diagnostics=diagnostics if isinstance(diagnostics,list) else []
    record.corrections.extend(result.corrections)
    st.session_state.pop('partial',None)
    st.session_state.pop('validation_comparisons',None)


st.subheader('2. 评分与批改')
stopped=bool(record.partial_state) and record.partial_state.get('format_version')==SCHEMA_VERSION and not any(s['status']=='failed' for s in record.partial_state.get('slots',{}).values())
st.button('修复未完成栏目' if record.partial_sections or record.partial_state or record.incomplete_errors else '评分与批改',
          type='primary',disabled=busy or not same or not key or not model or bool(record.report) or record.demo or stopped,
          on_click=queue_operation,args=('score',))
if st.session_state.get('operation_error'):
    st.error(st.session_state.operation_error)
if record.partial_sections or record.partial_state or record.incomplete_errors:
    from teacher.render import diagnostic_rows,report_health
    status=report_health(record)
    if not status['complete']:
        st.warning('报告不完整：已验证条目已保留，可保存或下载。只修复失败部分，不覆盖有效内容。')
    for message in status['messages']:
        st.info(message)
    with st.expander('校验技术细节'):
        st.caption('旧记录缺少的路径或修复次数显示为未知，不据此推测原始原因。')
        st.json(diagnostic_rows(record))
        if st.session_state.get('validation_comparisons'):
            st.caption('以下原文与候选引文比对仅保留在当前会话，不写入诊断日志。')
            st.json(st.session_state.validation_comparisons)
        st.json(record.partial_state or record.partial_sections)
if record.corrections:
    with st.expander('已记录的唯一匹配定位修正'):
        st.text('\n'.join(record.corrections))
if record.report or record.partial_sections or record.partial_state or record.incomplete_errors:
    show_report(st,record,show_health=False)
if st.session_state.get('schema_adaptation'):
    st.caption(st.session_state.schema_adaptation)
if record.report:
    if record.diagnostics:
        with st.expander('校验技术细节'):
            st.json(record.diagnostics)
    st.caption('示范二稿由模型辅助生成，不等同于学生独立完成稿，不承诺考试分数。')
    draft_label=('只重试落实说明' if record.draft_state.get('body_status')=='valid' else
                 '重新生成示范二稿' if record.draft_state else '生成示范二稿')
    st.button(draft_label, disabled=busy or not same or not key or not model or record.demo or bool(record.second_draft),
              on_click=queue_operation,args=('draft',))
    if record.calibration and record.calibration.status=='一致性检查未完成':
        st.button('重试参考评分一致性检查',disabled=busy or not same or not key or not model or record.demo,
                  on_click=queue_operation,args=('calibration',))

st.divider()
st.subheader('保存与下载')
if not same:
    st.caption('以下操作保存／下载的是上方已确认的旧版本。编辑框中的改动尚未确认。')
if st.button('保存已确认记录', disabled=busy):
    try:
        save(record)
        st.success(f'已保存记录 {record.id[:8]}；重复点击更新同一记录。')
    except Exception as error:
        fail(error)
from teacher.render import markdown_report
private_download(st,'下载 Markdown 批改报告', markdown_report(record), file_name=f'{record.id}.md',mime='text/markdown', disabled=busy)
private_download(st,'下载 JSON 记录备份',record.model_dump_json(indent=2),file_name=f'{record.id}.json',mime='application/json', disabled=busy)
st.caption('JSON 不包含原始图片；图片只在当前会话临时保留，请自行保存上传的原图。')
pending = st.session_state.pop('pending',None)
if pending:
    kind_requested, record_id, version = pending
    st.session_state.pop('operation_error',None)
    if same and record.id == record_id and record.essay.version == version:
        if kind_requested == 'score':
            run_operation(score)
        elif kind_requested=='draft':
            def second():
                record.second_draft = generate_draft(ModelClient(key,model),record.essay,record.config,record.report,target_score=record.target_score,state=record.draft_state)
            run_operation(second)
        elif kind_requested=='calibration':
            def compare():
                audit,verified=prepare_audit(record.essay,record.config)
                record.calibration=review_consistency(ModelClient(key,model),record.essay,record.config,
                                                       record.report.overview,audit,verified)
            run_operation(compare)
    st.session_state.busy = False
    st.rerun()
