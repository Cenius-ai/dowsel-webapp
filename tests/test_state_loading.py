"""The tally file is parsed as plain JSON data - never through a stream reader.

These tests pin the safe-loading contract: a `.dowsel.json` produced by anything
other than Dowsel (hand edits, binary junk, a JSON array) is refused with a clear
message and exit code 1 - never a traceback, never anything but data. A file
written before tallies had ids and labels still loads and gets ids assigned.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI = PROJECT_ROOT / "dowsel.py"


class StateLoadingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.state_file = self.workdir / ".dowsel.json"

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop("DOWSEL_STATE_FILE", None)
        env["NO_COLOR"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=str(self.workdir),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_binary_state_file_is_reported_not_crashed(self) -> None:
        self.state_file.write_bytes(b"\x80\x81\xfe\xff not text at all")
        result = self.run_cli("peg", "list")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not UTF-8 text", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_non_json_bytes_are_refused_as_data(self) -> None:
        self.state_file.write_bytes(b"\x80\x04\x95\x10\x00\x00\x00\x00\x00\x00\x00}\x94.")
        result = self.run_cli("peg", "list")
        self.assertEqual(result.returncode, 1)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_json_array_is_rejected(self) -> None:
        self.state_file.write_text('["pegs"]', encoding="utf-8")
        result = self.run_cli("peg", "list")
        self.assertEqual(result.returncode, 1)
        self.assertIn("must contain a JSON object", result.stderr)

    def test_an_empty_file_is_reported_as_invalid_json(self) -> None:
        self.state_file.write_text("", encoding="utf-8")
        result = self.run_cli("peg", "list")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not valid JSON", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_unknown_keys_from_a_hand_edit_are_ignored(self) -> None:
        self.state_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "peg_tallies": [],
                    "boards": [],
                    "kerf": None,
                    "workbench_note": "for the oak frame",
                }
            ),
            encoding="utf-8",
        )
        result = self.run_cli("peg", "list")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("No peg tallies yet", result.stdout)

    def test_a_file_from_before_ids_and_labels_still_loads(self) -> None:
        self.state_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "peg_tallies": [
                        {"count": 8, "diameter_mm": 10.0, "spacing_mm": 20.0},
                        {"count": 4, "diameter_mm": 12.5, "spacing_mm": 20.0},
                    ],
                    "boards": [{"species": "Oak", "direction": "north"}],
                    "kerf": {"kerf_mm": 0.5},
                }
            ),
            encoding="utf-8",
        )
        listed = self.run_cli("peg", "list")
        self.assertEqual(listed.returncode, 0, msg=listed.stderr)
        self.assertIn("Total pegs: 12", listed.stdout)

        # the old rows get ids in file order, and the next add continues the series
        added = self.run_cli("peg", "add", "2", "--diameter", "9", "--spacing", "15")
        self.assertEqual(added.returncode, 0, msg=added.stderr)
        self.assertIn("peg tally 3 added", added.stdout)

    def test_a_written_tally_reads_back_unchanged(self) -> None:
        added = self.run_cli("peg", "add", "7", "--diameter", "9.5", "--spacing", "30")
        self.assertEqual(added.returncode, 0, msg=added.stderr)
        listed = self.run_cli("peg", "list")
        self.assertEqual(listed.returncode, 0, msg=listed.stderr)
        self.assertIn("Total pegs: 7", listed.stdout)
        self.assertIn("9.5 mm", listed.stdout)

    def test_state_file_is_left_untouched_by_a_read(self) -> None:
        added = self.run_cli("peg", "add", "7", "--diameter", "9.5", "--spacing", "30")
        self.assertEqual(added.returncode, 0, msg=added.stderr)
        before = self.state_file.read_bytes()
        self.run_cli("peg", "list")
        self.assertEqual(self.state_file.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
