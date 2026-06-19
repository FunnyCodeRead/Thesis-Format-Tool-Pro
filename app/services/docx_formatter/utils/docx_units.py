from __future__ import annotations

from typing import Any


def length_to_cm(value: Any) -> float | None:
    if value is None:
        return None
    return float(value.cm)


def length_to_pt(value: Any) -> float | None:
    if value is None:
        return None
    return float(value.pt)


def close(current: float | None, expected: float, tolerance: float) -> bool:
    return current is not None and abs(current - expected) <= tolerance


def format_cm(value: float | None) -> str:
    if value is None:
        return "not set"
    return f"{value:.2f} cm"


def format_pt(value: float | None) -> str:
    if value is None:
        return "not set"
    return f"{value:.1f} pt"


def format_line_spacing(value: Any) -> str:
    if value is None:
        return "not set"
    if isinstance(value, (float, int)):
        return f"{float(value):.2f}"
    return "exact spacing"
