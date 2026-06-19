from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.services.docx_formatter.domain.finding import Finding


class AnalyzeRule(ABC):
    @abstractmethod
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        raise NotImplementedError


class FixRule(ABC):
    @abstractmethod
    def fix(self, doc: Any, config: dict[str, Any]) -> int:
        raise NotImplementedError
