"""YAML から診断設定を読み込むローダー。モジュールレベルキャッシュ。"""

import yaml
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "diagnostic_config.yaml"
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            _cache = yaml.safe_load(f)
    return _cache


def get_candidate_hints() -> dict[str, str]:
    return _load()["candidate_hints"]
