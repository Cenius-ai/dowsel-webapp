# Installing Dowsel

Dowsel is one Python file with no runtime dependencies. Setup is one command and
it exits; the tool is started separately (it is a CLI, not a server).

## Prerequisites (already on the machine - this project never installs them)

| Requirement | Why | Check |
| --- | --- | --- |
| Python 3.8+ | runs `dowsel.py` | `python3 --version` |
| `pip` (for `python3`) | installs the one declared dependency | `python3 -m pip --version` |

No system packages, compilers or services are needed. `install.sh` never calls
`apt`, `apk`, `yum`, `brew`, `sudo` or `systemctl`.

## Package manager

**pip**, driven by the committed `requirements.txt`. There is exactly one
declared dependency - `pytest`, the test runner - because the product itself
imports only the Python standard library. With no runtime dependency tree there
is nothing to lock beyond that single pin, which is why the tree carries
`requirements.txt` and not a generated lockfile.

## Step 1 - install

```bash
bash install.sh
```

What it does, in order:

1. checks the interpreter is Python 3.8+ (fails loudly otherwise)
2. refreshes `pip`/`setuptools`/`wheel` (best effort - an offline machine with a
   working pip still finishes)
3. installs `requirements.txt` (skipped when `pytest` is already importable)
4. installs the optional `dowsel` console command (`pip install -e .`, no build
   isolation, so it works offline; a locked-down site-packages only prints a note
   and you use `python3 dowsel.py` instead)
5. imports the module and runs `--version` as a loud self-check

It is idempotent: running it twice is safe. It does **not** start the tool.

## Step 2 - seed demo data

Not applicable, deliberately. Dowsel stores exactly what you type and nothing
else: there is no user table and no demo content to seed, and the empty states
are themselves the invitation (`No peg tallies yet` / `Add one: dowsel peg add ...`).
The state file is created on first write.

If you want a populated bench to look at, run the tour - it fills a temporary
state file with realistic tallies, boards and a 0.5 mm kerf and then removes it:

```bash
bash demo.sh
```

## Step 3 - run in dev

```bash
python3 dowsel.py --help
python3 dowsel.py peg add 8 --diameter 10 --spacing 20
python3 dowsel.py peg list
```

`DOWSEL_STATE_FILE` relocates the JSON state file (default `.dowsel.json` in the
current directory). No other configuration is required, and there is no `.env`
to create.

## Step 4 - test

```bash
python3 -m pytest
```

73 behavioural tests, all driven through the real command line in throwaway
directories. No network, no external services, no interactive prompts.

## Uninstall

```bash
python3 -m pip uninstall dowsel       # only if you installed the console command
rm .dowsel.json                       # your tally file, if you want it gone
```

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `dowsel: command not found` | The console command was not installed; use `python3 dowsel.py ...` from the project directory |
| `dowsel: error: .dowsel.json is not valid JSON (line 3: ...)` | The state file was edited or truncated by hand; repair it or delete it to start fresh |
| `dowsel: error: count must be positive (got 0)` | Validation is doing its job - a tally needs at least one peg |
| Colours missing | Expected in pipes and redirects; they appear only on a terminal, and `NO_COLOR` / `--no-color` turn them off |
| Box characters or timber names look escaped | The terminal's encoding cannot represent them; the value is stored exactly and only the glyph on screen is escaped |
