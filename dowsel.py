#!/usr/bin/env python3
"""Dowsel - timber joinery peg tally, end-grain direction boards, saw kerf reminder.

One file, standard library only. State is a single JSON document in the current
working directory (``.dowsel.json``), so separate invocations share it. Set
``DOWSEL_STATE_FILE`` to point somewhere else.

The tally document is read as UTF-8 text and parsed as JSON data with
``json.loads``; every field is type-checked before it reaches the model, so a
hand-edited or corrupted file can only ever produce a clear error message.

Design tokens (committed direction: calm-precise / terminal dark / mono):
    accent      oklch(0.58 0.12 199) == #008f95  -> ANSI truecolor below
    surface     the host terminal (dark by default)
    chrome      box-drawing rules, aligned columns, no borders or panels
    signal      words carry the meaning; colour only reinforces it
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

__version__ = "1.0.0"

APP_NAME = "dowsel"
STATE_FILENAME = ".dowsel.json"
STATE_ENV_VAR = "DOWSEL_STATE_FILE"
STATE_VERSION = 1
RULE_WIDTH = 58
LABEL_WIDTH = 30

EXIT_OK = 0
EXIT_STATE = 1
EXIT_INVALID = 2

# --- design tokens ---------------------------------------------------------
ACCENT_RGB = (0x00, 0x8F, 0x95)  # #008f95 == oklch(0.58 0.12 199)
_ANSI_RESET = "\x1b[0m"
_ANSI_BOLD = "\x1b[1m"
_ANSI_DIM = "\x1b[2m"
_ANSI_ACCENT = "\x1b[38;2;{};{};{}m".format(*ACCENT_RGB)


class DowselError(Exception):
    """Base class for failures that carry a user-facing message."""


class ValidationError(DowselError):
    """The user typed something the tool refuses. Exit code 2."""


class StateError(DowselError):
    """The on-disk state could not be read or written. Exit code 1."""


# --- data model ------------------------------------------------------------
@dataclass(frozen=True)
class PegTally:
    tally_id: int
    label: str
    count: int
    diameter_mm: float
    spacing_mm: float

    def to_dict(self) -> "dict[str, object]":
        return {
            "id": self.tally_id,
            "label": self.label,
            "count": self.count,
            "diameter_mm": self.diameter_mm,
            "spacing_mm": self.spacing_mm,
        }

    def facts(self, dot: str) -> str:
        """The one-line description shared by add, list and remove."""
        return (
            f"{self.count} pegs {dot} {format_mm(self.diameter_mm)} mm diameter "
            f"{dot} {format_mm(self.spacing_mm)} mm spacing"
        )


@dataclass(frozen=True)
class GrainBoard:
    species: str
    direction: str

    def to_dict(self) -> "dict[str, str]":
        return {"species": self.species, "direction": self.direction}


@dataclass
class State:
    peg_tallies: "list[PegTally]"
    boards: "list[GrainBoard]"
    kerf_mm: "float | None"
    next_tally_id: int = 1

    def to_payload(self) -> "dict[str, object]":
        return {
            "version": STATE_VERSION,
            "next_tally_id": self.next_tally_id,
            "peg_tallies": [tally.to_dict() for tally in self.peg_tallies],
            "boards": [board.to_dict() for board in self.boards],
            "kerf": None if self.kerf_mm is None else {"kerf_mm": self.kerf_mm},
        }

    def total_pegs(self) -> int:
        return sum(tally.count for tally in self.peg_tallies)

    def tally_count_label(self) -> str:
        count = len(self.peg_tallies)
        return f"{count} {'tally' if count == 1 else 'tallies'}"

    def find_tally(self, tally_id: int) -> "int | None":
        """Position of the tally with this id, or None - never a silent match."""
        for position, tally in enumerate(self.peg_tallies):
            if tally.tally_id == tally_id:
                return position
        return None


def empty_state() -> State:
    return State(peg_tallies=[], boards=[], kerf_mm=None)


# --- validation ------------------------------------------------------------
def parse_positive_int(raw: str, field: str) -> int:
    """Return a positive integer, or raise ValidationError naming the field."""
    try:
        value = int((raw or "").strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be an integer (got {raw!r})") from None
    if value <= 0:
        raise ValidationError(f"{field} must be positive (got {value})")
    return value


def parse_positive_float(raw: str, field: str) -> float:
    """Return a positive finite number, or raise ValidationError naming the field."""
    try:
        value = float((raw or "").strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a number (got {raw!r})") from None
    if not math.isfinite(value):
        raise ValidationError(f"{field} must be a finite number (got {raw!r})")
    if value <= 0:
        raise ValidationError(f"{field} must be positive (got {format_mm(value)})")
    return value


def parse_required_text(raw: str, field: str) -> str:
    """Return trimmed text, refusing an empty value."""
    text = (raw or "").strip()
    if not text:
        raise ValidationError(f"{field} is required and cannot be empty")
    return text


# --- formatting ------------------------------------------------------------
def format_mm(value: float) -> str:
    """Render millimetres without noise: 10.0 -> '10', 0.25 -> '0.25'."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if not text or (text == "0" and value != 0):
        return f"{value:g}"
    return text


def shorten(text: str, limit: int = LABEL_WIDTH) -> str:
    """Keep the table columns lined up: a long label is elided, never wrapped."""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


class Painter:
    """ANSI painter that stays silent when colour is off or unsupported."""

    def __init__(self, enabled: bool, unicode_ok: bool = True) -> None:
        self.enabled = enabled
        self.unicode_ok = unicode_ok

    def accent(self, text: str) -> str:
        return self._wrap(text, _ANSI_ACCENT)

    def bold(self, text: str) -> str:
        return self._wrap(text, _ANSI_BOLD)

    def dim(self, text: str) -> str:
        return self._wrap(text, _ANSI_DIM)

    def _wrap(self, text: str, code: str) -> str:
        return f"{code}{text}{_ANSI_RESET}" if self.enabled else text

    @property
    def rule(self) -> str:
        return "\u2500" if self.unicode_ok else "-"

    @property
    def dot(self) -> str:
        return "\u00b7" if self.unicode_ok else "-"


@dataclass
class Context:
    path: Path
    painter: Painter


def render_page(title: str, body: "list[str]", painter: Painter) -> str:
    lines = [
        f"{painter.accent(APP_NAME)} {painter.dim(painter.dot)} {title}",
        painter.dim(painter.rule * RULE_WIDTH),
        "",
        *body,
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_table(
    header: "tuple[str, ...]",
    rows: "list[tuple[str, ...]]",
    alignment: str,
    painter: Painter,
) -> "list[str]":
    """Aligned monospace columns: header, a rule, then one line per row."""
    table = [header, *rows]
    widths = [max(len(row[index]) for row in table) for index in range(len(header))]

    def format_row(row: "tuple[str, ...]") -> str:
        cells = [
            cell.rjust(widths[index]) if alignment[index] == "r" else cell.ljust(widths[index])
            for index, cell in enumerate(row)
        ]
        return "  " + "   ".join(cells).rstrip()

    header_line = format_row(header)
    return [
        painter.bold(header_line),
        "  " + painter.dim(painter.rule * (len(header_line) - 2)),
        *(format_row(row) for row in rows),
    ]


def emit_json(payload: object) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)  # output only, never input
    sys.stdout.write("\n")


def print_page(text: str) -> None:
    sys.stdout.write(text)


def print_error(message: str, hint: "str | None" = None) -> None:
    print(f"{APP_NAME}: error: {message}", file=sys.stderr)
    if hint:
        print(f"{APP_NAME}: hint: {hint}", file=sys.stderr)


# --- persistence -----------------------------------------------------------
def state_path() -> Path:
    configured = os.environ.get(STATE_ENV_VAR, "").strip()
    return Path(configured or STATE_FILENAME).expanduser()


def _number(raw: object, field: str, where: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise StateError(f"{where}: {field} must be a number")
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise StateError(f"{where}: {field} must be a positive number")
    return value


def _whole_number(raw: object, field: str, where: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise StateError(f"{where}: {field} must be a positive whole number")
    return raw


def _state_from_payload(payload: "dict[str, object]", path: Path) -> State:
    where = str(path)
    tallies_raw = payload.get("peg_tallies", [])
    boards_raw = payload.get("boards", [])
    kerf_raw = payload.get("kerf")
    if not isinstance(tallies_raw, list) or not isinstance(boards_raw, list):
        raise StateError(f"{where}: 'peg_tallies' and 'boards' must be lists")

    tallies: "list[PegTally]" = []
    for index, item in enumerate(tallies_raw, start=1):
        label = f"{where}: peg tally {index}"
        if not isinstance(item, dict):
            raise StateError(f"{label} must be an object")
        # A file written before ids and labels existed still loads: the id
        # defaults to the row position and the label to empty.
        tally_id = _whole_number(item.get("id", index), "id", label)
        raw_label = item.get("label", "")
        if raw_label is None:
            raw_label = ""
        if not isinstance(raw_label, str):
            raise StateError(f"{label}: label must be text")
        count = _number(item.get("count"), "count", label)
        if count != int(count):
            raise StateError(f"{label}: count must be a whole number")
        tallies.append(
            PegTally(
                tally_id=tally_id,
                label=raw_label.strip(),
                count=int(count),
                diameter_mm=_number(item.get("diameter_mm"), "diameter_mm", label),
                spacing_mm=_number(item.get("spacing_mm"), "spacing_mm", label),
            )
        )

    boards: "list[GrainBoard]" = []
    for index, item in enumerate(boards_raw, start=1):
        label = f"{where}: board {index}"
        if not isinstance(item, dict):
            raise StateError(f"{label} must be an object")
        species = item.get("species")
        direction = item.get("direction")
        if not isinstance(species, str) or not species.strip():
            raise StateError(f"{label}: species must be a non-empty string")
        if not isinstance(direction, str) or not direction.strip():
            raise StateError(f"{label}: direction must be a non-empty string")
        boards.append(GrainBoard(species=species.strip(), direction=direction.strip()))

    kerf_mm: "float | None" = None
    if kerf_raw is not None:
        if not isinstance(kerf_raw, dict):
            raise StateError(f"{where}: 'kerf' must be an object or null")
        kerf_mm = _number(kerf_raw.get("kerf_mm"), "kerf_mm", where)

    highest_id = max((tally.tally_id for tally in tallies), default=0)
    next_tally_id = highest_id + 1
    stored_next = payload.get("next_tally_id")
    if (
        isinstance(stored_next, int)
        and not isinstance(stored_next, bool)
        and stored_next > highest_id
    ):
        next_tally_id = stored_next  # never hand out an id that is already in use

    return State(
        peg_tallies=tallies,
        boards=boards,
        kerf_mm=kerf_mm,
        next_tally_id=next_tally_id,
    )


def load_state(path: Path) -> State:
    """Read and parse the tally document.

    The file is read as UTF-8 text and parsed with ``json.loads`` - plain JSON
    data only. Nothing a tally file contains can construct an object, resolve a
    tag, or run code; fields are then type-checked in ``_state_from_payload``.
    """
    if not path.exists():
        return empty_state()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StateError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise StateError(
            f"{path} is not UTF-8 text (byte {exc.start}); "
            "repair it or delete it to start fresh"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StateError(
            f"{path} is not valid JSON (line {exc.lineno}: {exc.msg}); "
            "repair it or delete it to start fresh"
        ) from exc
    if not isinstance(payload, dict):
        raise StateError(f"{path} must contain a JSON object")
    return _state_from_payload(payload, path)


def save_state(path: Path, state: State) -> None:
    """Write the whole document atomically, so a crash never truncates it."""
    directory = path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handle_fd, temporary = tempfile.mkstemp(
            prefix=".dowsel-", suffix=".tmp", dir=str(directory)
        )
    except OSError as exc:
        raise StateError(f"cannot write {path}: {exc.strerror or exc}") from exc
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            json.dump(state.to_payload(), handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass  # already gone; the write error below is the one worth reporting
        raise StateError(f"cannot write {path}: {exc.strerror or exc}") from exc


# --- commands: peg ---------------------------------------------------------
def cmd_peg_add(args: argparse.Namespace, ctx: Context) -> int:
    count = parse_positive_int(args.count, "count")
    diameter = parse_positive_float(args.diameter, "diameter")
    spacing = parse_positive_float(args.spacing, "spacing")
    label = (args.label or "").strip()

    state = load_state(ctx.path)
    tally = PegTally(
        tally_id=state.next_tally_id,
        label=label,
        count=count,
        diameter_mm=diameter,
        spacing_mm=spacing,
    )
    state.peg_tallies.append(tally)
    state.next_tally_id = tally.tally_id + 1
    save_state(ctx.path, state)

    total = state.total_pegs()
    if args.json:
        emit_json(
            {
                "ok": True,
                "tally": tally.to_dict(),
                "tally_count": len(state.peg_tallies),
                "total_pegs": total,
            }
        )
        return EXIT_OK

    body = [f"  {ctx.painter.accent('+')} peg tally {tally.tally_id} added"]
    if tally.label:
        body.append(f"    label: {tally.label}")
    body.extend(
        [
            f"    {tally.facts(ctx.painter.dot)}",
            f"    remove with: dowsel peg remove {tally.tally_id}",
            "",
            f"  Total pegs: {total} across {state.tally_count_label()}",
            f"  State: {ctx.path}",
        ]
    )
    print_page(render_page("peg tallies", body, ctx.painter))
    return EXIT_OK


def cmd_peg_list(args: argparse.Namespace, ctx: Context) -> int:
    state = load_state(ctx.path)
    total = state.total_pegs()
    if args.json:
        emit_json(
            {
                "tallies": [tally.to_dict() for tally in state.peg_tallies],
                "tally_count": len(state.peg_tallies),
                "total_pegs": total,
            }
        )
        return EXIT_OK

    if not state.peg_tallies:
        body = [
            "  No peg tallies yet",
            "  Add one:  dowsel peg add 8 --diameter 10 --spacing 20",
            "",
            f"  State: {ctx.path}",
        ]
        print_page(render_page("peg tallies", body, ctx.painter))
        return EXIT_OK

    rows = [
        (
            str(tally.tally_id),
            shorten(tally.label) if tally.label else "(none)",
            str(tally.count),
            f"{format_mm(tally.diameter_mm)} mm",
            f"{format_mm(tally.spacing_mm)} mm",
        )
        for tally in state.peg_tallies
    ]
    body = [
        *render_table(
            ("ID", "LABEL", "COUNT", "DIAMETER", "SPACING"), rows, "rlrrr", ctx.painter
        ),
        "",
        f"  Total pegs: {total} across {state.tally_count_label()}",
        f"  State: {ctx.path}",
    ]
    print_page(render_page("peg tallies", body, ctx.painter))
    return EXIT_OK


def cmd_peg_remove(args: argparse.Namespace, ctx: Context) -> int:
    tally_id = parse_positive_int(args.tally_id, "id")

    state = load_state(ctx.path)
    position = state.find_tally(tally_id)
    if position is None:
        raise ValidationError(f"no peg tally with id {tally_id}")
    removed = state.peg_tallies.pop(position)
    save_state(ctx.path, state)

    total = state.total_pegs()
    if args.json:
        emit_json(
            {
                "ok": True,
                "removed": removed.to_dict(),
                "tally_count": len(state.peg_tallies),
                "total_pegs": total,
            }
        )
        return EXIT_OK

    body = [f"  {ctx.painter.accent('-')} peg tally {removed.tally_id} removed"]
    if removed.label:
        body.append(f"    {removed.label}")
    body.extend(
        [
            f"    {removed.facts(ctx.painter.dot)}",
            "",
            f"  Total pegs: {total} across {state.tally_count_label()}",
            f"  State: {ctx.path}",
        ]
    )
    print_page(render_page("peg tallies", body, ctx.painter))
    return EXIT_OK


# --- commands: grain -------------------------------------------------------
def cmd_grain_set(args: argparse.Namespace, ctx: Context) -> int:
    species = parse_required_text(args.species, "species")
    direction = parse_required_text(args.direction, "direction")

    state = load_state(ctx.path)
    state.boards.append(GrainBoard(species=species, direction=direction))
    save_state(ctx.path, state)

    index = len(state.boards)
    board = state.boards[-1]
    if args.json:
        emit_json({"ok": True, "board": board.to_dict(), "board_count": index})
        return EXIT_OK

    body = [
        f"  {ctx.painter.accent('+')} board {index} saved",
        f"    {board.species}: {board.direction}",
        "",
        f"  End-grain runs {board.direction}; keep layout marks square to it.",
        f"  State: {ctx.path}",
    ]
    print_page(render_page("end-grain boards", body, ctx.painter))
    return EXIT_OK


def cmd_grain_show(args: argparse.Namespace, ctx: Context) -> int:
    state = load_state(ctx.path)
    if args.json:
        emit_json(
            {
                "boards": [board.to_dict() for board in state.boards],
                "board_count": len(state.boards),
            }
        )
        return EXIT_OK

    if not state.boards:
        body = [
            "  No boards yet",
            "  Set one:  dowsel grain set Oak --direction north",
            "",
            f"  State: {ctx.path}",
        ]
        print_page(render_page("end-grain boards", body, ctx.painter))
        return EXIT_OK

    rows = [
        (str(index), f"{board.species}: {board.direction}")
        for index, board in enumerate(state.boards, start=1)
    ]
    plural = "board" if len(state.boards) == 1 else "boards"
    body = [
        *render_table((" #", "BOARD"), rows, "rl", ctx.painter),
        "",
        f"  {len(state.boards)} {plural} recorded",
        f"  State: {ctx.path}",
    ]
    print_page(render_page("end-grain boards", body, ctx.painter))
    return EXIT_OK


# --- commands: kerf --------------------------------------------------------
def half_of(kerf_mm: float) -> float:
    """The half-kerf offset, kept clean of binary float dust (0.5 -> 0.25)."""
    return round(kerf_mm / 2, 6)


def _kerf_payload(kerf_mm: "float | None") -> "dict[str, float | None]":
    return {
        "kerf_mm": kerf_mm,
        "half_kerf_mm": None if kerf_mm is None else half_of(kerf_mm),
    }


def _kerf_body(kerf_mm: float) -> "list[str]":
    half = half_of(kerf_mm)
    return [
        f"  Kerf: {format_mm(kerf_mm)} mm",
        f"  Half-kerf offset: {format_mm(half)} mm",
        "",
        f"  Offset the fence {format_mm(half)} mm past the line "
        "so the blade cuts on the waste side.",
    ]


def cmd_kerf_set(args: argparse.Namespace, ctx: Context) -> int:
    kerf = parse_positive_float(args.width, "kerf")

    state = load_state(ctx.path)
    state.kerf_mm = kerf
    save_state(ctx.path, state)

    if args.json:
        emit_json({"ok": True, **_kerf_payload(kerf)})
        return EXIT_OK

    body = [
        f"  {ctx.painter.accent('+')} kerf reminder saved",
        "",
        *_kerf_body(kerf),
        f"  State: {ctx.path}",
    ]
    print_page(render_page("saw kerf reminder", body, ctx.painter))
    return EXIT_OK


def cmd_kerf_show(args: argparse.Namespace, ctx: Context) -> int:
    state = load_state(ctx.path)
    if args.json:
        emit_json(_kerf_payload(state.kerf_mm))
        return EXIT_OK

    if state.kerf_mm is None:
        body = [
            "  No kerf reminder set",
            "  Set one:  dowsel kerf set 0.5",
            "",
            f"  State: {ctx.path}",
        ]
        print_page(render_page("saw kerf reminder", body, ctx.painter))
        return EXIT_OK

    body = [*_kerf_body(state.kerf_mm), f"  State: {ctx.path}"]
    print_page(render_page("saw kerf reminder", body, ctx.painter))
    return EXIT_OK


def cmd_kerf_clear(args: argparse.Namespace, ctx: Context) -> int:
    state = load_state(ctx.path)
    had_kerf = state.kerf_mm is not None
    state.kerf_mm = None
    save_state(ctx.path, state)

    if args.json:
        emit_json({"ok": True, "cleared": had_kerf, **_kerf_payload(None)})
        return EXIT_OK

    status = "kerf reminder cleared" if had_kerf else "no kerf reminder was set"
    body = [
        f"  {ctx.painter.accent('-')} {status}",
        "",
        "  No kerf reminder set",
        "  Set one:  dowsel kerf set 0.5",
        "",
        f"  State: {ctx.path}",
    ]
    print_page(render_page("saw kerf reminder", body, ctx.painter))
    return EXIT_OK


# --- argument parsing ------------------------------------------------------
EPILOG = """\
examples:
  dowsel peg add 8 --diameter 10 --spacing 20   record a peg tally
  dowsel peg add 4 --diameter 10 --spacing 20 --label "Pine trestle"
                                                record a labelled tally
  dowsel peg list                               list tallies, ids and the peg total
  dowsel peg remove 2                           remove a peg tally by id
  dowsel grain set Oak --direction north        record a board's end-grain direction
  dowsel grain show                             list recorded boards
  dowsel kerf set 0.5                           remember a 0.5 mm saw kerf
  dowsel kerf show                              show kerf and half-kerf offset
  dowsel kerf clear                             forget the kerf reminder

state:
  everything is stored in .dowsel.json in the current directory;
  set DOWSEL_STATE_FILE to use another file. Errors go to stderr and
  exit non-zero: 1 for an unreadable state file, 2 for invalid input.
"""


def _common_flags() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON on stdout instead of a table",
    )
    common.add_argument(
        "--no-color",
        action="store_true",
        help="never emit ANSI colour (NO_COLOR is honoured too)",
    )
    return common


def build_parser() -> "tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]":
    common = _common_flags()
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Dowsel - timber joinery peg tally, end-grain boards and saw kerf reminder.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"{APP_NAME} {__version__}"
    )

    groups = parser.add_subparsers(dest="command", metavar="{peg,grain,kerf}")
    group_parsers: "dict[str, argparse.ArgumentParser]" = {}

    # peg ------------------------------------------------------------------
    peg = groups.add_parser(
        "peg",
        parents=[common],
        help="timber joinery peg tallies",
        description="Record timber joinery peg tallies, list them and total the pegs.",
    )
    peg_sub = peg.add_subparsers(dest="peg_command", metavar="{add,list,remove}")
    peg_add = peg_sub.add_parser(
        "add",
        parents=[common],
        help="add a peg tally (count, diameter, spacing)",
        description=(
            "Add one peg tally. count is a positive whole number of pegs; "
            "diameter and spacing are positive numbers of millimetres. "
            "The tally is given an id, printed on success and shown by 'peg list'."
        ),
    )
    peg_add.add_argument("count", metavar="COUNT", help="number of pegs (positive integer)")
    peg_add.add_argument(
        "--diameter", metavar="MM", required=True, help="peg diameter in millimetres"
    )
    peg_add.add_argument(
        "--spacing", metavar="MM", required=True, help="peg spacing in millimetres"
    )
    peg_add.add_argument(
        "--label",
        metavar="TEXT",
        default="",
        help="what this tally is for, e.g. 'Oak frame, north wall'",
    )
    peg_add.set_defaults(func=cmd_peg_add)
    peg_list = peg_sub.add_parser(
        "list",
        aliases=["show"],
        parents=[common],
        help="list all tallies, their ids and the total peg count",
        description=(
            "List every peg tally with its id, label, count, diameter and spacing, "
            "then the total pegs."
        ),
    )
    peg_list.set_defaults(func=cmd_peg_list)
    peg_remove = peg_sub.add_parser(
        "remove",
        aliases=["rm", "delete"],
        parents=[common],
        help="remove a peg tally by id",
        description="Remove one peg tally by its id. Ids are shown by 'dowsel peg list'.",
    )
    peg_remove.add_argument("tally_id", metavar="ID", help="id of the tally to remove")
    peg_remove.set_defaults(func=cmd_peg_remove)
    group_parsers["peg"] = peg

    # grain ----------------------------------------------------------------
    grain = groups.add_parser(
        "grain",
        parents=[common],
        help="end-grain direction boards",
        description="Record the end-grain direction of a board and review the boards set.",
    )
    grain_sub = grain.add_subparsers(dest="grain_command", metavar="{set,show}")
    grain_set = grain_sub.add_parser(
        "set",
        parents=[common],
        help="record a board's species and end-grain direction",
        description="Record one board: the species and the direction its end-grain runs.",
    )
    grain_set.add_argument("species", metavar="SPECIES", help="timber species, e.g. Oak")
    grain_set.add_argument(
        "--direction", metavar="DIR", required=True, help="end-grain direction, e.g. north"
    )
    grain_set.set_defaults(func=cmd_grain_set)
    grain_show = grain_sub.add_parser(
        "show",
        parents=[common],
        help="list every board with its species and direction",
        description="List every recorded board as 'species: direction'.",
    )
    grain_show.set_defaults(func=cmd_grain_show)
    group_parsers["grain"] = grain

    # kerf -----------------------------------------------------------------
    kerf = groups.add_parser(
        "kerf",
        parents=[common],
        help="saw kerf reminder with the half-kerf offset",
        description="Remember a saw kerf width and read back the half-kerf offset.",
    )
    kerf_sub = kerf.add_subparsers(dest="kerf_command", metavar="{set,show,clear}")
    kerf_set = kerf_sub.add_parser(
        "set",
        parents=[common],
        help="remember a saw kerf width in millimetres",
        description="Store the saw kerf width (a positive number of millimetres).",
    )
    kerf_set.add_argument("width", metavar="MM", help="kerf width in millimetres")
    kerf_set.set_defaults(func=cmd_kerf_set)
    kerf_show = kerf_sub.add_parser(
        "show",
        parents=[common],
        help="show the kerf width and half-kerf offset",
        description="Show the stored kerf width and its half-kerf offset.",
    )
    kerf_show.set_defaults(func=cmd_kerf_show)
    kerf_clear = kerf_sub.add_parser(
        "clear",
        parents=[common],
        help="forget the kerf reminder",
        description="Remove the stored kerf reminder.",
    )
    kerf_clear.set_defaults(func=cmd_kerf_clear)
    group_parsers["kerf"] = kerf

    return parser, group_parsers


HINTS = {
    "count": "count is a whole number of pegs: dowsel peg add 8 --diameter 10 --spacing 20",
    "diameter": "diameter is a positive number of millimetres, e.g. --diameter 10",
    "spacing": "spacing is a positive number of millimetres, e.g. --spacing 20",
    "id": "run 'dowsel peg list' to see the ids, then 'dowsel peg remove <id>'",
    "species": "name the timber species: dowsel grain set Oak --direction north",
    "direction": "name the end-grain direction, e.g. --direction north",
    "kerf": "kerf is a positive number of millimetres, e.g. dowsel kerf set 0.5",
}


def _hint_for(message: str) -> "str | None":
    if message.startswith("no peg tally with id "):
        return HINTS["id"]
    for field, hint in HINTS.items():
        if message.startswith(f"{field} "):
            return hint
    return None


def _stream_supports_unicode(stream: object) -> bool:
    encoding = (getattr(stream, "encoding", "") or "").lower()
    if not encoding:
        return False
    try:
        "\u2500\u00b7".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _make_streams_resilient() -> None:
    """Escape what the terminal's encoding cannot carry instead of crashing.

    A species name such as "Ch\u00eane" (or any non-ASCII timber name) on an
    ASCII or cp1252 console would otherwise end the run with a UnicodeEncodeError
    traceback - output encoding is not user input to validate, it is a property
    of the terminal, so degrade the glyph, never the run.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (ValueError, OSError):
            continue  # not reconfigurable (captured/redirected); default stands


def _color_enabled(no_color_flag: bool) -> bool:
    if no_color_flag or os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _make_context(args: argparse.Namespace) -> Context:
    painter = Painter(
        enabled=_color_enabled(getattr(args, "no_color", False)),
        unicode_ok=_stream_supports_unicode(sys.stdout),
    )
    return Context(path=state_path(), painter=painter)


def main(argv: "list[str] | None" = None) -> int:
    _make_streams_resilient()
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser, group_parsers = build_parser()

    if not arguments:
        parser.print_help()
        return EXIT_OK

    try:
        args = parser.parse_args(arguments)
    except SystemExit as exc:  # argparse handled --help/--version or a usage error
        return int(exc.code or EXIT_OK)

    handler = getattr(args, "func", None)
    if handler is None:
        group = group_parsers.get(getattr(args, "command", ""))
        (group or parser).print_help()
        return EXIT_OK

    context = _make_context(args)
    try:
        return handler(args, context)
    except ValidationError as exc:
        message = str(exc)
        print_error(message, _hint_for(message))
        return EXIT_INVALID
    except StateError as exc:
        print_error(str(exc))
        return EXIT_STATE


def run_cli() -> int:
    """Console-script entry point: never raises on ordinary failures."""
    try:
        return main()
    except BrokenPipeError:  # a pager or `head` closed the pipe; not an error
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        return EXIT_OK
    except KeyboardInterrupt:
        print(f"\n{APP_NAME}: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(run_cli())
