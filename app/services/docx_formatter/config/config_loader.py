from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().parents[6] / "configs" / "school_config.json"


class AnalyzerConfigError(ValueError):
    pass


class ConfigLoader:
    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self.config_path = config_path

    def load_all(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise AnalyzerConfigError(f"School config not found: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as config_file:
            return json.load(config_file)

    def load(self, document_type: str, config_override: dict[str, Any] | None = None) -> dict[str, Any]:
        configs = self.load_all()
        config = configs.get(document_type)

        if not config:
            raise AnalyzerConfigError(f"No school config for document_type: {document_type}")

        if not config_override:
            return config

        if not isinstance(config_override, dict):
            raise AnalyzerConfigError("Template config_json must be a JSON object.")

        return _deep_merge(config, config_override)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
