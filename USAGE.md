# Using Dowsel

Three features, one tally file. Every transcript below is real output from
`python3 dowsel.py ...` (the `dowsel` command on PATH behaves identically).

---

## 1. Peg tallies - `dowsel peg`

Record how many joinery pegs of a given diameter and spacing you need, label the
tally, read back the total, and remove a tally when the job is done. Every tally
carries an id, printed when you add it.

### Empty state

```
$ dowsel peg list

dowsel · peg tallies
──────────────────────────────────────────────────────────

  No peg tallies yet
  Add one:  dowsel peg add 8 --diameter 10 --spacing 20

  State: .dowsel.json
```

### Add a tally

```
$ dowsel peg add 8 --diameter 10 --spacing 20 --label "Oak frame, north wall"

dowsel · peg tallies
──────────────────────────────────────────────────────────

  + peg tally 1 added
    label: Oak frame, north wall
    8 pegs · 10 mm diameter · 20 mm spacing
    remove with: dowsel peg remove 1

  Total pegs: 8 across 1 tally
  State: .dowsel.json
```

`COUNT` is a positive whole number; `--diameter` and `--spacing` are positive
numbers of millimetres (decimals are fine: `--diameter 12.5`). `--label` is
optional - it is what you will recognise the tally by later:

```
$ dowsel peg add 6 --diameter 8 --spacing 18

  + peg tally 3 added
    6 pegs · 8 mm diameter · 18 mm spacing
    remove with: dowsel peg remove 3
```

### List every tally and the total

```
$ dowsel peg list

dowsel · peg tallies
──────────────────────────────────────────────────────────

  ID   LABEL                   COUNT   DIAMETER   SPACING
  ───────────────────────────────────────────────────────
   1   Oak frame, north wall       8      10 mm     20 mm
   2   Pine trestle                4    12.5 mm     20 mm
   3   (none)                      6       8 mm     18 mm

  Total pegs: 18 across 3 tallies
  State: .dowsel.json
```

`dowsel peg show` is the same command under an alias. Long labels are elided on
screen (`...`) so the columns stay lined up; the stored label is always complete.

### Remove a tally

```
$ dowsel peg remove 2

dowsel · peg tallies
──────────────────────────────────────────────────────────

  - peg tally 2 removed
    Pine trestle
    4 pegs · 12.5 mm diameter · 20 mm spacing

  Total pegs: 14 across 2 tallies
  State: .dowsel.json
```

`rm` and `delete` are aliases. The total is recomputed from what is left, and an
id is never reused, so a printed id always addresses the tally you saw in
`dowsel peg list`.

An id that is not there is refused and nothing is written:

```
$ dowsel peg remove 99
dowsel: error: no peg tally with id 99
dowsel: hint: run 'dowsel peg list' to see the ids, then 'dowsel peg remove <id>'

$ dowsel peg remove abc
dowsel: error: id must be an integer (got 'abc')
```

### Refused input

Zero, negative and malformed values are rejected before anything is stored, with
exit code `2` and the message on stderr:

```
$ dowsel peg add 0 --diameter 10 --spacing 20
dowsel: error: count must be positive (got 0)
dowsel: hint: count is a whole number of pegs: dowsel peg add 8 --diameter 10 --spacing 20

$ dowsel peg add 8 --diameter abc --spacing 20
dowsel: error: diameter must be a number (got 'abc')
dowsel: hint: diameter is a positive number of millimetres, e.g. --diameter 10

$ dowsel peg add 8 --diameter 10 --spacing -10
dowsel: error: spacing must be positive (got -10)
dowsel: hint: spacing is a positive number of millimetres, e.g. --spacing 20
```

A rejected tally never reaches `.dowsel.json`.

---

## 2. End-grain boards - `dowsel grain`

Record which way the end-grain runs on a board, so layout marks stay square.

### Empty state

```
$ dowsel grain show

dowsel · end-grain boards
──────────────────────────────────────────────────────────

  No boards yet
  Set one:  dowsel grain set Oak --direction north

  State: .dowsel.json
```

### Record a board

```
$ dowsel grain set Oak --direction north

dowsel · end-grain boards
──────────────────────────────────────────────────────────

  + board 1 saved
    Oak: north

  End-grain runs north; keep layout marks square to it.
  State: .dowsel.json
```

Both the species and the direction must be non-empty; `--direction` is required.

```
$ dowsel grain set "" --direction north
dowsel: error: species is required and cannot be empty
dowsel: hint: name the timber species: dowsel grain set Oak --direction north
```

### Show the boards

```
$ dowsel grain show

dowsel · end-grain boards
──────────────────────────────────────────────────────────

   #   BOARD
  ──────────
   1   Oak: north
   2   Pine: south

  2 boards recorded
  State: .dowsel.json
```

---

## 3. Saw kerf reminder - `dowsel kerf`

Remember the blade's kerf so the half-kerf offset is always one command away.

### Empty / cleared state

```
$ dowsel kerf show

dowsel · saw kerf reminder
──────────────────────────────────────────────────────────

  No kerf reminder set
  Set one:  dowsel kerf set 0.5

  State: .dowsel.json
```

### Set it

```
$ dowsel kerf set 0.5

dowsel · saw kerf reminder
──────────────────────────────────────────────────────────

  + kerf reminder saved

  Kerf: 0.5 mm
  Half-kerf offset: 0.25 mm

  Offset the fence 0.25 mm past the line so the blade cuts on the waste side.
  State: .dowsel.json
```

### Read it back

```
$ dowsel kerf show

dowsel · saw kerf reminder
──────────────────────────────────────────────────────────

  Kerf: 0.5 mm
  Half-kerf offset: 0.25 mm

  Offset the fence 0.25 mm past the line so the blade cuts on the waste side.
  State: .dowsel.json
```

Setting a new width replaces the old one. `0`, negative and non-numeric widths
are refused with exit code `2`:

```
$ dowsel kerf set -0.5
dowsel: error: kerf must be positive (got -0.5)
dowsel: hint: kerf is a positive number of millimetres, e.g. dowsel kerf set 0.5
```

### Clear it

```
$ dowsel kerf clear

dowsel · saw kerf reminder
──────────────────────────────────────────────────────────

  - kerf reminder cleared

  No kerf reminder set
  Set one:  dowsel kerf set 0.5

  State: .dowsel.json
```

---

## Scripting it

Every subcommand takes `--json`, which prints one object on stdout and no
decoration - ready for `jq` or a shell script:

```
$ dowsel peg list --json
{
  "tallies": [
    {
      "count": 8,
      "diameter_mm": 10.0,
      "id": 1,
      "label": "Oak frame, north wall",
      "spacing_mm": 20.0
    },
    {
      "count": 4,
      "diameter_mm": 12.5,
      "id": 2,
      "label": "Pine trestle",
      "spacing_mm": 20.0
    }
  ],
  "tally_count": 2,
  "total_pegs": 12
}

$ dowsel peg remove 2 --json
{
  "ok": true,
  "removed": {
    "count": 4,
    "diameter_mm": 12.5,
    "id": 2,
    "label": "Pine trestle",
    "spacing_mm": 20.0
  },
  "tally_count": 1,
  "total_pegs": 8
}

$ dowsel kerf show --json
{
  "half_kerf_mm": 0.25,
  "kerf_mm": 0.5
}

$ dowsel grain show --json
{
  "board_count": 2,
  "boards": [
    {
      "direction": "north",
      "species": "Oak"
    },
    {
      "direction": "south",
      "species": "Pine"
    }
  ]
}
```

`dowsel kerf clear --json` reports `ok`, `cleared` and both kerf values, which are
`null` once the reminder is gone.

Exit codes: `0` success, `2` invalid input or unknown id, `1` unreadable or
unwritable state file. Errors always go to stderr, results to stdout, so
`dowsel peg list | grep` stays clean.

Keep several benches apart with the state file variable:

```bash
DOWSEL_STATE_FILE=workshop/.dowsel.json dowsel peg list
```

## Colour

Colour (the `#008f95` accent on the wordmark and the `+` / `-` status glyph) is
emitted only to a terminal. Pipes, redirects, `NO_COLOR=1` and `--no-color` all
produce plain text, and box-drawing characters degrade to ASCII on terminals
that cannot encode them.
