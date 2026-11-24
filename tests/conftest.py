import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_path(name: str) -> Path:
    return FIXTURES / name


def load_json(name: str):
    return json.loads(fixture_path(name).read_text(encoding="utf-8"))
