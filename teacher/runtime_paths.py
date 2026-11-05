"""App sessions use private ephemeral directories; command-line tools retain local data/."""
from contextvars import ContextVar
from pathlib import Path
import tempfile

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
