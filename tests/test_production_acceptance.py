from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def _load_acceptance_module():
    root = Path(__file__).resolve().parents[3]
    script_path = root / "scripts" / "production_acceptance.py"
    spec = importlib.util.spec_from_file_location("production_acceptance", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load production_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProductionAcceptanceScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.acceptance = _load_acceptance_module()

    def test_report_status_fails_when_any_check_fails(self) -> None:
        report = self.acceptance.AcceptanceReport(started_at="2026-06-16T00:00:00Z")
        report.add("one", "OK", "passed")
        report.add("two", "FAIL", "blocked")

        self.assertTrue(report.failed)
        self.assertEqual(report.to_dict()["status"], "FAIL")

    def test_forbidden_word_mutation_patterns_match_only_assignments(self) -> None:
        patterns = self.acceptance.FORBIDDEN_WORD_MUTATION_PATTERNS

        self.assertRegex("paragraph.text = 'bad'", patterns["paragraph.text assignment"])
        self.assertRegex("run.text = 'bad'", patterns["run.text assignment"])
        self.assertNotRegex("paragraph.text.strip()", patterns["paragraph.text assignment"])
        self.assertNotRegex("run.text.strip()", patterns["run.text assignment"])


if __name__ == "__main__":
    unittest.main()
