"""Shared family password gate, with server-side session state and bounded attempts."""
from collections import deque
import hashlib
import hmac
import math
import secrets
import threading
import time

_TOKEN_KEY=secrets.token_bytes(32)
SESSION_LIMIT=5
COOLDOWN=60
INSTANCE_LIMIT=20
WINDOW=300
_failures=deque()
_lock=threading.Lock()


def configured_password(st):
    try:
        value=st.secrets.get('FAMILY_PASSWORD','')
    except (FileNotFoundError,st.errors.StreamlitSecretNotFoundError):
        return ''
    return value if isinstance(value,str) and value.strip() else ''


def password_token(password):
    return hmac.new(_TOKEN_KEY,password.encode('utf-8'),hashlib.sha256).hexdigest()


def authenticated(state,password):
    token=state.get('_family_token')
    return bool(password and isinstance(token,str) and hmac.compare_digest(token,password_token(password)))


def remaining_wait(state,now):
    with _lock:
        while _failures and _failures[0]<=now-WINDOW:
            _failures.popleft()
        instance_until=_failures[0]+WINDOW if len(_failures)>=INSTANCE_LIMIT else now
    return max(0,math.ceil(max(state.get('_login_blocked_until',now),instance_until)-now))


def clear_private_session(st):
    from teacher.runtime_paths import clear_session_files
    failed=not clear_session_files(st.session_state)
    # Clear uploads and legacy native media references for this session only.
    from streamlit import runtime
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    ctx=get_script_run_ctx(suppress_warning=True)
    if runtime.exists() and ctx is not None:
        rt=runtime.get_instance()
        try:
            rt.uploaded_file_mgr.remove_session_files(ctx.session_id)
            rt.media_file_mgr.clear_session_refs(ctx.session_id)
            rt.media_file_mgr.remove_orphaned_files()
            rt.media_file_mgr.remove_orphaned_files()
        except (AttributeError,OSError,RuntimeError):
            failed=True
    for key in list(st.session_state):
        del st.session_state[key]
    if failed:
        st.session_state['_cleanup_failed']=True


def attempt_login(st):
    candidate=st.session_state.pop('_family_password','')
    password=configured_password(st)
    now=time.monotonic()
    wait=remaining_wait(st.session_state,now)
    if not password:
        return
    if wait:
        st.session_state['_login_message']=f'尝试过于频繁，请等待约{wait}秒后重试。'
        return
    if isinstance(candidate,str) and hmac.compare_digest(candidate.encode('utf-8'),password.encode('utf-8')):
        st.session_state['_family_token']=password_token(password)
        for key in ('_login_message','_login_failures','_login_blocked_until'):
            st.session_state.pop(key,None)
        return
    with _lock:
        _failures.append(now)
    count=st.session_state.get('_login_failures',0)+1
    if count>=SESSION_LIMIT:
        st.session_state['_login_failures']=0
        st.session_state['_login_blocked_until']=now+COOLDOWN
        st.session_state['_login_message']='连续输错5次，请等待60秒后重试。'
    else:
        st.session_state['_login_failures']=count
        st.session_state['_login_message']=f'密码不正确，本轮还可尝试{SESSION_LIMIT-count}次。'


def require_login(st):
    password=configured_password(st)
    if authenticated(st.session_state,password):
        st.sidebar.button('退出家庭登录',on_click=clear_private_session,args=(st,))
        return
    if st.session_state.get('_family_token') or any(k in st.session_state for k in ('record','edit_body','edit_pictures','pending','pending_vision')):
        clear_private_session(st)
    st.title('华文作文小老师 · 家庭登录')
    if st.session_state.get('_cleanup_failed'):
        st.warning('会话内容已清除，但临时文件清理未全部完成；请管理员检查服务器。')
    if not password:
        st.error('尚未配置家庭密码，应用已锁定。请管理员在 Streamlit Secrets 中设置顶层 FAMILY_PASSWORD（非空字符串）。')
        st.stop()
    st.caption('使用家庭共用密码进入。这不是独立账号系统；登录状态仅在当前会话有效。')
    wait=remaining_wait(st.session_state,time.monotonic())
    if wait:
        st.warning(f'登录暂时受限，请等待约{wait}秒，之后点击登录重试。')
    if st.session_state.get('_login_message'):
        st.error(st.session_state['_login_message'])
    with st.form('family_login',clear_on_submit=True):
        st.text_input('家庭密码',type='password',key='_family_password')
        st.form_submit_button('登录',on_click=attempt_login,args=(st,))
    st.stop()
