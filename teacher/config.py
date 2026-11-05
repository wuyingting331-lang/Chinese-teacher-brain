from pathlib import Path
from teacher.models import ScoringConfig

CONFIG_DIR = Path(__file__).resolve().parents[1] / 'config'
DEFAULT_PATH = CONFIG_DIR / 'scoring_reference_v1.json'
LEGACY_PATH = CONFIG_DIR / 'scoring.json'


def load_scoring(path=DEFAULT_PATH):
    return ScoringConfig.model_validate_json(Path(path).read_text(encoding='utf-8'))


def scoring_profiles():
    return [load_scoring(DEFAULT_PATH),load_scoring(LEGACY_PATH)]
