"""App sessions use private ephemeral directories; command-line tools retain local data/."""
from contextvars import ContextVar
from pathlib import Path
import tempfile
import shutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_session_root = ContextVar('teacher_session_data_root', default=None)


def bind_session(state):
    if '_private_data_root' not in state:
        state['_private_data_root'] = tempfile.mkdtemp(prefix='chinese-teacher-session-')
    _session_root.set(Path(state['_private_data_root']))


def data_path(*parts):
    return (_session_root.get() or Path('data')).joinpath(*parts)


def session_root():
    return _session_root.get()


def clear_session_files(state):
    """Only delete an app-created direct child of the OS temporary directory."""
    raw=state.get('_private_data_root')
    _session_root.set(None)
    if not raw:
        return True
    try:
        candidate=Path(raw)
        target=candidate.resolve()
        base=Path(tempfile.gettempdir()).resolve()
        if candidate.is_symlink() or target.parent!=base or not target.name.startswith('chinese-teacher-session-'):
            return False
        if target.exists():
            shutil.rmtree(target)
        return True
    except (OSError,ValueError,TypeError):
        return False
