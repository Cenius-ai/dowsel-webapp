"""A peg tally carries a label, is printed with an id, and can be removed.

These tests pin the two plan points that the CLI surface has to prove: the id
printed by `peg add` addresses the same tally in `peg list`, and `peg remove`
takes it out of the store so it no longer appears.
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


class PegLabelAndRemoveTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)

    def run_cli(self, *args: str, expect: "int | None" = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop("DOWSEL_STATE_FILE", None)
        env["NO_COLOR"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=str(self.workdir),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if expect is not None:
            self.assertEqual(
                result.returncode,
                expect,
                msg=f"command {args} exited {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
        return result

    @property
    def state_file(self) -> Path:
        return self.workdir / ".dowsel.json"

    def read_state(self) -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def add(self, count: str, label: "str | None" = None) -> int:
        args = ["peg", "add", count, "--diameter", "10", "--spacing", "20"]
        if label is not None:
            args += ["--label", label]
        self.run_cli(*args, expect=0)
        return self.read_state()["peg_tallies"][-1]["id"]

    # --- label and id ----------------------------------------------------
    def test_label_is_stored_with_the_tally(self) -> None:
        self.add("8", "Oak frame, north wall")
        tally = self.read_state()["peg_tallies"][0]
        self.assertEqual(tally["label"], "Oak frame, north wall")
        self.assertEqual(tally["id"], 1)

    def test_label_is_optional(self) -> None:
        self.add("8")
        self.assertEqual(self.read_state()["peg_tallies"][0]["label"], "")

    def test_label_is_trimmed_before_storing(self) -> None:
        self.add("8", "  Pine trestle  ")
        self.assertEqual(self.read_state()["peg_tallies"][0]["label"], "Pine trestle")

    def test_adding_prints_the_id_it_stored(self) -> None:
        result = self.run_cli(
            "peg", "add", "8", "--diameter", "10", "--spacing", "20",
            "--label", "Oak frame", expect=0,
        )
        self.assertIn("peg tally 1 added", result.stdout)
        self.assertIn("label: Oak frame", result.stdout)
        self.assertEqual(self.read_state()["peg_tallies"][0]["id"], 1)

    def test_printed_id_addresses_the_tally_in_the_list(self) -> None:
        tally_id = self.add("8", "Oak frame")
        listed = self.run_cli("peg", "list", expect=0)
        self.assertIn("ID", listed.stdout)
        self.assertIn("LABEL", listed.stdout)
        self.assertIn(str(tally_id), listed.stdout)
        self.assertIn("Oak frame", listed.stdout)

    def test_ids_increase_and_stay_unique(self) -> None:
        first = self.add("8")
        second = self.add("4")
        third = self.add("2")
        self.assertEqual([first, second, third], [1, 2, 3])
        ids = [tally["id"] for tally in self.read_state()["peg_tallies"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_unlabelled_tally_still_lists(self) -> None:
        self.add("8")
        listed = self.run_cli("peg", "list", expect=0)
        self.assertIn("(none)", listed.stdout)
        self.assertIn("Total pegs: 8", listed.stdout)

    def test_a_long_label_is_elided_on_screen_but_stored_whole(self) -> None:
        long_label = "North wall of the oak frame, second bay, upper rail"
        self.add("8", long_label)
        listed = self.run_cli("peg", "list", expect=0)
        self.assertIn("...", listed.stdout)
        self.assertNotIn(long_label, listed.stdout)
        self.assertEqual(self.read_state()["peg_tallies"][0]["label"], long_label)

    # --- remove ----------------------------------------------------------
    def test_removing_a_tally_drops_it_from_the_list(self) -> None:
        first = self.add("8", "Oak frame")
        second = self.add("4", "Pine trestle")
        removed = self.run_cli("peg", "remove", str(second), expect=0)
        self.assertIn(f"peg tally {second} removed", removed.stdout)
        self.assertIn("Pine trestle", removed.stdout)
        self.assertIn("Total pegs: 8", removed.stdout)

        listed = self.run_cli("peg", "list", expect=0)
        self.assertIn("Oak frame", listed.stdout)
        self.assertNotIn("Pine trestle", listed.stdout)
        self.assertNotIn(f" {second} ", listed.stdout)
        self.assertEqual(
            [tally["id"] for tally in self.read_state()["peg_tallies"]], [first]
        )

    def test_removal_persists_across_invocations(self) -> None:
        self.add("8")
        target = self.add("4")
        self.run_cli("peg", "remove", str(target), expect=0)
        # a separate process, a separate read of the same file
        self.assertEqual(len(self.read_state()["peg_tallies"]), 1)
        self.assertIn("Total pegs: 8", self.run_cli("peg", "list", expect=0).stdout)

    def test_removing_the_last_tally_returns_to_the_empty_state(self) -> None:
        target = self.add("8")
        self.run_cli("peg", "remove", str(target), expect=0)
        listed = self.run_cli("peg", "list", expect=0)
        self.assertIn("No peg tallies yet", listed.stdout)
        self.assertIn("dowsel peg add", listed.stdout)

    def test_rm_is_an_alias_for_remove(self) -> None:
        target = self.add("8")
        self.run_cli("peg", "rm", str(target), expect=0)
        self.assertEqual(self.read_state()["peg_tallies"], [])

    def test_an_unknown_id_is_refused_and_changes_nothing(self) -> None:
        self.add("8")
        before = self.state_file.read_bytes()
        result = self.run_cli("peg", "remove", "99")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no peg tally with id 99", result.stderr)
        self.assertIn("dowsel peg list", result.stderr)   # tells the user how to find an id
        self.assertEqual(self.state_file.read_bytes(), before)

    def test_a_malformed_id_is_refused(self) -> None:
        self.add("8")
        for bad, message in (
            ("abc", "id must be an integer"),
            ("0", "id must be positive"),
            ("-2", "id must be positive"),
        ):
            with self.subTest(tally_id=bad):
                result = self.run_cli("peg", "remove", bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, f"{result.stdout}{result.stderr}")
        self.assertEqual(len(self.read_state()["peg_tallies"]), 1)

    def test_an_id_is_not_reused_after_a_removal(self) -> None:
        first = self.add("8")
        second = self.add("4")
        self.run_cli("peg", "remove", str(second), expect=0)
        third = self.add("2")
        self.assertGreater(third, second)
        self.assertEqual(
            [tally["id"] for tally in self.read_state()["peg_tallies"]], [first, third]
        )

    def test_remove_json_reports_what_went_and_the_new_total(self) -> None:
        self.add("8", "Oak frame")
        target = self.add("4", "Pine trestle")
        payload = json.loads(self.run_cli("peg", "remove", str(target), "--json", expect=0).stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["removed"]["id"], target)
        self.assertEqual(payload["removed"]["label"], "Pine trestle")
        self.assertEqual(payload["total_pegs"], 8)
        self.assertEqual(payload["tally_count"], 1)

    def test_remove_is_double_click_safe(self) -> None:
        target = self.add("8")
        self.run_cli("peg", "remove", str(target), expect=0)
        # the second attempt finds nothing and must not corrupt the file
        echo = self.run_cli("peg", "remove", str(target))
        self.assertEqual(echo.returncode, 2)
        self.assertIn("No peg tallies yet", self.run_cli("peg", "list", expect=0).stdout)


if __name__ == "__main__":
    unittest.main()
