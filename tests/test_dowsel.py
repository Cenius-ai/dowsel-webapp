"""Behavioural tests for Dowsel.

Every test drives the real command line in a throwaway working directory, so the
assertions describe exactly what a woodworker sees at the bench. Run with
``pytest`` or ``python -m unittest discover -s tests``.
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


class CliTestCase(unittest.TestCase):
    """Base class: a fresh working directory and a helper to run the CLI."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)

    def run_cli(self, *args: str, expect: "int | None" = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop("DOWSEL_STATE_FILE", None)
        env["NO_COLOR"] = "1"          # keep assertions free of ANSI escapes
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

    @staticmethod
    def output(result: subprocess.CompletedProcess) -> str:
        return f"{result.stdout}{result.stderr}"

    @property
    def state_file(self) -> Path:
        return self.workdir / ".dowsel.json"

    def read_state(self) -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def add_tally(self, count: str, diameter: str = "10", spacing: str = "20") -> None:
        self.run_cli(
            "peg", "add", count, "--diameter", diameter, "--spacing", spacing, expect=0
        )


class HelpTest(CliTestCase):
    def test_help_lists_every_subcommand_and_exits_zero(self) -> None:
        result = self.run_cli("--help", expect=0)
        for command in ("peg", "grain", "kerf"):
            self.assertIn(command, result.stdout)
        self.assertIn("dowsel peg add", result.stdout)  # worked examples are part of help

    def test_no_arguments_prints_usage_and_exits_zero(self) -> None:
        result = self.run_cli(expect=0)
        self.assertIn("usage: dowsel", result.stdout)
        for command in ("peg", "grain", "kerf"):
            self.assertIn(command, result.stdout)

    def test_each_group_without_a_subcommand_prints_its_help(self) -> None:
        for group, expected in (("peg", "add"), ("grain", "set"), ("kerf", "clear")):
            with self.subTest(group=group):
                result = self.run_cli(group, expect=0)
                self.assertIn(group, result.stdout)
                self.assertIn(expected, result.stdout)

    def test_version_flag(self) -> None:
        result = self.run_cli("--version", expect=0)
        self.assertRegex(result.stdout.strip(), r"^dowsel \d+\.\d+\.\d+$")

    def test_subcommand_help_shows_the_flags(self) -> None:
        result = self.run_cli("peg", "add", "--help", expect=0)
        self.assertIn("--diameter", result.stdout)
        self.assertIn("--spacing", result.stdout)
        self.assertIn("--label", result.stdout)

    def test_peg_help_lists_remove(self) -> None:
        result = self.run_cli("peg", "--help", expect=0)
        self.assertIn("remove", result.stdout)
        self.assertIn("add", result.stdout)
        self.assertIn("list", result.stdout)

    def test_module_imports_without_side_effects(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "import dowsel; print(dowsel.__version__)"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "1.0.0")


class OutputHygieneTest(CliTestCase):
    def test_results_go_to_stdout_and_errors_to_stderr(self) -> None:
        listed = self.run_cli("peg", "list", expect=0)
        self.assertIn("No peg tallies yet", listed.stdout)
        self.assertEqual(listed.stderr, "")

        rejected = self.run_cli("peg", "add", "0", "--diameter", "10", "--spacing", "20")
        self.assertEqual(rejected.stdout, "")
        self.assertIn("count must be positive", rejected.stderr)

    def test_no_ansi_escapes_when_output_is_not_a_terminal(self) -> None:
        result = self.run_cli("peg", "list", expect=0)
        self.assertNotIn("\x1b[", result.stdout)

    def test_no_color_flag_is_accepted(self) -> None:
        result = self.run_cli("peg", "list", "--no-color", expect=0)
        self.assertNotIn("\x1b[", result.stdout)


class PegTallyTest(CliTestCase):
    def test_empty_list_invites_the_add_command(self) -> None:
        result = self.run_cli("peg", "list", expect=0)
        self.assertIn("No peg tallies yet", result.stdout)
        self.assertIn("dowsel peg add", result.stdout)

    def test_add_confirms_and_exits_zero(self) -> None:
        result = self.run_cli(
            "peg", "add", "8", "--diameter", "10", "--spacing", "20", expect=0
        )
        self.assertIn("added", result.stdout)
        self.assertIn("8 pegs", result.stdout)
        self.assertIn("10 mm diameter", result.stdout)
        self.assertIn("20 mm spacing", result.stdout)

    def test_second_tally_is_stored_alongside_the_first(self) -> None:
        self.add_tally("8")
        self.add_tally("4")
        state = self.read_state()
        self.assertEqual([tally["count"] for tally in state["peg_tallies"]], [8, 4])

    def test_list_shows_both_tallies_and_the_total(self) -> None:
        self.add_tally("8")
        self.add_tally("4")
        result = self.run_cli("peg", "list", expect=0)
        self.assertEqual(result.stdout.count("10 mm"), 2)   # both rows, diameter column
        self.assertIn("Total pegs: 12", result.stdout)
        self.assertIn("across 2 tallies", result.stdout)

    def test_show_is_an_alias_for_list(self) -> None:
        self.add_tally("3")
        listed = self.run_cli("peg", "list", expect=0).stdout
        shown = self.run_cli("peg", "show", expect=0).stdout
        self.assertEqual(listed, shown)

    def test_decimal_diameter_and_spacing_are_kept(self) -> None:
        self.add_tally("6", diameter="12.5", spacing="0.75")
        state = self.read_state()
        self.assertEqual(state["peg_tallies"][0]["diameter_mm"], 12.5)
        self.assertEqual(state["peg_tallies"][0]["spacing_mm"], 0.75)
        self.assertIn("12.5 mm", self.run_cli("peg", "list", expect=0).stdout)

    def test_count_rejects_zero_negative_and_malformed(self) -> None:
        cases = {
            "0": "count must be positive",
            "-3": "count must be positive",
            "abc": "count must be an integer",
        }
        for count, message in cases.items():
            with self.subTest(count=count):
                result = self.run_cli(
                    "peg", "add", count, "--diameter", "10", "--spacing", "20"
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, self.output(result))

    def test_diameter_rejects_zero_negative_and_malformed(self) -> None:
        cases = {
            "0": "diameter must be positive",
            "-5": "diameter must be positive",
            "abc": "diameter must be a number",
        }
        for diameter, message in cases.items():
            with self.subTest(diameter=diameter):
                result = self.run_cli(
                    "peg", "add", "8", "--diameter", diameter, "--spacing", "20"
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, self.output(result))

    def test_spacing_rejects_zero_negative_and_malformed(self) -> None:
        cases = {
            "0": "spacing must be positive",
            "-10": "spacing must be positive",
            "abc": "spacing must be a number",
        }
        for spacing, message in cases.items():
            with self.subTest(spacing=spacing):
                result = self.run_cli(
                    "peg", "add", "8", "--diameter", "10", "--spacing", spacing
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, self.output(result))

    def test_rejected_input_never_touches_the_state_file(self) -> None:
        self.run_cli("peg", "add", "0", "--diameter", "10", "--spacing", "20")
        self.assertFalse(self.state_file.exists())

    def test_validation_errors_use_their_own_exit_code(self) -> None:
        self.assertEqual(
            self.run_cli("peg", "add", "0", "--diameter", "10", "--spacing", "20").returncode,
            2,
        )

    def test_state_is_plain_json_with_the_documented_shape(self) -> None:
        self.add_tally("8")
        state = self.read_state()
        self.assertEqual(state["version"], 1)
        self.assertEqual(state["boards"], [])
        self.assertIsNone(state["kerf"])
        self.assertEqual(state["next_tally_id"], 2)
        self.assertEqual(
            state["peg_tallies"],
            [
                {
                    "id": 1,
                    "label": "",
                    "count": 8,
                    "diameter_mm": 10.0,
                    "spacing_mm": 20.0,
                }
            ],
        )


class GrainBoardTest(CliTestCase):
    def test_empty_show_invites_the_set_command(self) -> None:
        result = self.run_cli("grain", "show", expect=0)
        self.assertIn("No boards yet", result.stdout)
        self.assertIn("dowsel grain set", result.stdout)

    def test_set_confirms_and_exits_zero(self) -> None:
        result = self.run_cli("grain", "set", "Oak", "--direction", "north", expect=0)
        self.assertIn("saved", result.stdout)
        self.assertIn("Oak: north", result.stdout)

    def test_show_lists_every_board_as_species_and_direction(self) -> None:
        self.run_cli("grain", "set", "Oak", "--direction", "north", expect=0)
        self.run_cli("grain", "set", "Pine", "--direction", "south", expect=0)
        result = self.run_cli("grain", "show", expect=0)
        self.assertIn("Oak: north", result.stdout)
        self.assertIn("Pine: south", result.stdout)
        self.assertIn("2 boards recorded", result.stdout)

    def test_empty_species_is_rejected(self) -> None:
        result = self.run_cli("grain", "set", "", "--direction", "north")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("species is required", self.output(result))

    def test_whitespace_only_species_is_rejected(self) -> None:
        result = self.run_cli("grain", "set", "   ", "--direction", "north")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("species is required", self.output(result))

    def test_species_is_trimmed_before_storing(self) -> None:
        self.run_cli("grain", "set", "  Oak  ", "--direction", "north", expect=0)
        self.assertEqual(
            self.read_state()["boards"], [{"species": "Oak", "direction": "north"}]
        )

    def test_rejected_board_never_touches_the_state_file(self) -> None:
        self.run_cli("grain", "set", "", "--direction", "north")
        self.assertFalse(self.state_file.exists())


class KerfReminderTest(CliTestCase):
    def test_empty_show_prints_no_reminder_and_invites_set(self) -> None:
        result = self.run_cli("kerf", "show", expect=0)
        self.assertIn("No kerf reminder set", result.stdout)
        self.assertIn("dowsel kerf set", result.stdout)

    def test_set_confirms_and_exits_zero(self) -> None:
        result = self.run_cli("kerf", "set", "0.5", expect=0)
        self.assertIn("saved", result.stdout)

    def test_show_prints_kerf_and_half_kerf_offset(self) -> None:
        self.run_cli("kerf", "set", "0.5", expect=0)
        result = self.run_cli("kerf", "show", expect=0)
        self.assertIn("Kerf: 0.5 mm", result.stdout)
        self.assertIn("Half-kerf offset: 0.25 mm", result.stdout)

    def test_half_kerf_offset_of_an_odd_width(self) -> None:
        self.run_cli("kerf", "set", "3", expect=0)
        result = self.run_cli("kerf", "show", expect=0)
        self.assertIn("Kerf: 3 mm", result.stdout)
        self.assertIn("Half-kerf offset: 1.5 mm", result.stdout)

    def test_invalid_kerf_is_rejected(self) -> None:
        cases = {
            "0": "kerf must be positive",
            "-0.5": "kerf must be positive",
            "abc": "kerf must be a number",
        }
        for kerf, message in cases.items():
            with self.subTest(kerf=kerf):
                result = self.run_cli("kerf", "set", kerf)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, self.output(result))

    def test_clearing_restores_the_empty_state(self) -> None:
        self.run_cli("kerf", "set", "0.5", expect=0)
        self.run_cli("kerf", "clear", expect=0)
        result = self.run_cli("kerf", "show", expect=0)
        self.assertIn("No kerf reminder set", result.stdout)
        self.assertIn("dowsel kerf set", result.stdout)
        self.assertIsNone(self.read_state()["kerf"])

    def test_setting_again_replaces_the_previous_width(self) -> None:
        self.run_cli("kerf", "set", "0.5", expect=0)
        self.run_cli("kerf", "set", "2.4", expect=0)
        result = self.run_cli("kerf", "show", expect=0)
        self.assertIn("Kerf: 2.4 mm", result.stdout)
        self.assertIn("Half-kerf offset: 1.2 mm", result.stdout)


class JsonOutputTest(CliTestCase):
    """The machine-readable contract, mirroring the /api endpoints in the plan."""

    def test_peg_list_json_reports_tallies_and_total(self) -> None:
        self.add_tally("8")
        self.add_tally("4")
        payload = json.loads(self.run_cli("peg", "list", "--json", expect=0).stdout)
        self.assertEqual(payload["total_pegs"], 12)
        self.assertEqual(payload["tally_count"], 2)
        self.assertEqual(payload["tallies"][0]["count"], 8)

    def test_peg_add_json_reports_the_stored_tally(self) -> None:
        payload = json.loads(
            self.run_cli(
                "peg", "add", "8", "--diameter", "10", "--spacing", "20", "--json", expect=0
            ).stdout
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["total_pegs"], 8)
        self.assertEqual(payload["tally"]["diameter_mm"], 10.0)

    def test_grain_show_json_lists_boards(self) -> None:
        self.run_cli("grain", "set", "Oak", "--direction", "north", expect=0)
        payload = json.loads(self.run_cli("grain", "show", "--json", expect=0).stdout)
        self.assertEqual(payload["boards"], [{"species": "Oak", "direction": "north"}])
        self.assertEqual(payload["board_count"], 1)

    def test_kerf_json_reports_kerf_and_half_kerf(self) -> None:
        self.run_cli("kerf", "set", "0.5", expect=0)
        payload = json.loads(self.run_cli("kerf", "show", "--json", expect=0).stdout)
        self.assertEqual(payload, {"kerf_mm": 0.5, "half_kerf_mm": 0.25})

    def test_kerf_json_after_clear_is_null(self) -> None:
        self.run_cli("kerf", "set", "0.5", expect=0)
        cleared = json.loads(self.run_cli("kerf", "clear", "--json", expect=0).stdout)
        self.assertTrue(cleared["cleared"])
        shown = json.loads(self.run_cli("kerf", "show", "--json", expect=0).stdout)
        self.assertIsNone(shown["kerf_mm"])


class StateFileTest(CliTestCase):
    def test_corrupt_state_file_fails_loudly_without_a_traceback(self) -> None:
        self.state_file.write_text("{not json", encoding="utf-8")
        result = self.run_cli("peg", "list")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not valid JSON", self.output(result))
        self.assertNotIn("Traceback", self.output(result))

    def test_stored_non_positive_tally_is_reported_as_a_state_error(self) -> None:
        self.state_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "peg_tallies": [{"count": 0, "diameter_mm": 10, "spacing_mm": 20}],
                }
            ),
            encoding="utf-8",
        )
        result = self.run_cli("peg", "list")
        self.assertEqual(result.returncode, 1)
        self.assertIn("count must be a positive number", self.output(result))

    def test_state_file_can_be_relocated_with_the_environment_variable(self) -> None:
        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["DOWSEL_STATE_FILE"] = "bench/dowsel-state.json"
        subprocess.run(
            [sys.executable, str(CLI), "peg", "add", "5", "--diameter", "8", "--spacing", "16"],
            cwd=str(self.workdir),
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        relocated = self.workdir / "bench" / "dowsel-state.json"
        self.assertTrue(relocated.is_file())
        self.assertFalse(self.state_file.exists())
        stored = json.loads(relocated.read_text(encoding="utf-8"))
        self.assertEqual(stored["peg_tallies"][0]["count"], 5)

    def test_the_three_features_share_one_state_file(self) -> None:
        self.add_tally("8")
        self.run_cli("grain", "set", "Ash", "--direction", "east", expect=0)
        self.run_cli("kerf", "set", "1.2", expect=0)
        state = self.read_state()
        self.assertEqual(len(state["peg_tallies"]), 1)
        self.assertEqual(state["boards"], [{"species": "Ash", "direction": "east"}])
        self.assertEqual(state["kerf"], {"kerf_mm": 1.2})


class TerminalEncodingTest(CliTestCase):
    """Output encoding belongs to the terminal, so it must never abort a run."""

    def run_with_encoding(self, encoding: str, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop("DOWSEL_STATE_FILE", None)
        env["NO_COLOR"] = "1"
        env["PYTHONIOENCODING"] = encoding
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=str(self.workdir),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_non_ascii_species_survives_an_ascii_terminal(self) -> None:
        saved = self.run_with_encoding("ascii", "grain", "set", "Ch\u00eane", "--direction", "north")
        self.assertEqual(saved.returncode, 0, msg=saved.stderr)
        self.assertNotIn("Traceback", saved.stderr)

        shown = self.run_with_encoding("ascii", "grain", "show")
        self.assertEqual(shown.returncode, 0, msg=shown.stderr)
        self.assertNotIn("Traceback", shown.stderr)
        self.assertIn("north", shown.stdout)

        # the glyph may be escaped on the way out, but the stored name stays exact
        self.assertEqual(self.read_state()["boards"][0]["species"], "Ch\u00eane")

    def test_ascii_terminal_falls_back_to_ascii_rules_and_dots(self) -> None:
        result = self.run_with_encoding("ascii", "peg", "list")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("\u2500", result.stdout)
        self.assertIn("-", result.stdout)

    def test_utf8_terminal_keeps_the_box_drawing(self) -> None:
        result = self.run_with_encoding("utf-8", "peg", "list")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("\u2500", result.stdout)


if __name__ == "__main__":
    unittest.main()
