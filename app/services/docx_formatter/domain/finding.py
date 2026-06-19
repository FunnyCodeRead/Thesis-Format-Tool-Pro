from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Finding:
    type: str
    severity: str
    location: str
    message: str
    current_value: str | None = None
    expected_value: str | None = None
    suggestion: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
