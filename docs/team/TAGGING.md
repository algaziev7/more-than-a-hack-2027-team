# How Belek and Isken use Almaz's tagging code

Almaz's code reads the Smart Tagging XML and gives a clue for each video frame:
which team might have possession, how much weight to give that clue, and whether
there might be a restart around that time.

Belek and Isken use these clues together with Beks's tracking features. Their
state machine makes the final H, A, D, or X decision.

## 1. Get the code and point to your own data

You need `possession/tagging.py`, `possession/__init__.py`, and the existing
starter files. The review branch is `almaz/tagging-v1` in the team repo.
After its pull request is merged, get the code by updating your branch from main.

Each person sets their own data path in their terminal:

```bash
export MTAH_DATA_DIR="/your/path/to/dataset"
```

That folder must contain:

```text
tactical/BAR-ATH_tactical_smart_tagging.xml
```

This module needs no extra packages, videos, or tracking files.

## 2. Load the clues once at the start of your program

Run your program from the repository root:

```python
from possession.tagging import load_tagging_signals

signals = load_tagging_signals()
```

`signals` holds the results in memory. There is no output file to send between
modules. Keep this variable and pass it to your state-machine code. When the
program ends, the results disappear unless your program saves them.

For this match, there are 199,319 entries in each list. Entry 100 describes
frame 100 of the tactical video. Load once, not again for every frame.

## 3. Read the clues inside your frame loop

Add this to the place where your program processes each frame:

```python
for frame in signals.frame:
    home_hint, away_hint = signals.tag_team_evidence[frame]
    weight = signals.tag_team_reliability[frame]
    restart_hint = signals.restart_evidence[frame]

    # Use these values together with Beks's features in your state machine.
    # Your state machine still decides the final possession label.
```

This shows how to read the inputs. The state machine itself is separate work.

| Value | Simple meaning |
|---|---|
| Team hint `(1, 0)` | The tags support Barcelona |
| Team hint `(0, 1)` | The tags support Athletic |
| Team hint `(0.5, 0.5)` | No team preference |
| `weight == 0` | Ignore this team clue |
| `weight == 0.5` | Default weight for a usable team clue |
| `restart_hint == 0` | No restart clue from the tags |
| `restart_hint == 0.5` | A restart may happen around this time |

A `(1, 0)` hint does not mean Barcelona definitely has possession. Read its
weight too. These weights are starting choices, not measured probabilities.

For example, you can soften a team hint before combining it with other inputs:

```python
frame = 100  # Example of reading one frame, not a special rule for this frame.
home_hint, away_hint = signals.tag_team_evidence[frame]
weight = signals.tag_team_reliability[frame]

home_support = 0.5 * (1 - weight) + home_hint * weight
away_support = 0.5 * (1 - weight) + away_hint * weight
```

A Barcelona hint with weight 0.5 gives support values `(0.75, 0.25)`.
A clue with weight 0 gives `(0.5, 0.5)`. These are inputs to your decision logic;
they do not establish a 75% chance of possession.

Do not turn a restart clue straight into `D`. A tag covers a time window around
a restart, so it does not identify the exact moment play stops or resumes.

## 4. If Azamat has already loaded the events

Use those events directly instead of reading the XML again:

```python
from possession.tagging import build_tagging_signals

signals = build_tagging_signals(events, n_frames=199319)
```

`events` must be the list of event dictionaries returned by
`starter.load_smart_tagging.load`, or the same format from Azamat's loader.
Each dictionary has `code`, `start_frame`, `end_frame`, and `tags`.

The outputs are Python lists. If your code uses NumPy, convert them where needed:

```python
import numpy as np

team_hints = np.asarray(signals.tag_team_evidence)  # 199319 rows, 2 columns: H, A
weights = np.asarray(signals.tag_team_reliability)  # One value per frame
```

## What works now and what comes later

- Attacking phases can support the named team. Supported codes are BUILD UP,
  PROGRESSION, ATTACKING TRANSITION, CREATING CHANCES, BALL IN FINAL THIRD,
  BALL IN THE BOX, and LONG BALL.
- Barcelona and FC Barcelona mean H. Atletic Club and Athletic Club mean A.
  Capitalisation and extra spaces do not matter.
- Missing or unknown teams give no team preference. Throw-ins with `N/A` still
  provide a restart clue.
- SET PIECES provides restart clues, even when its team is known. It does not
  establish who has live possession.
- Conflicting team clues cancel where they overlap. Repeated copies of a tag
  do not make it stronger.
- Defending phases, PLAYERS IN THE BOX, GOALS, and unknown event types give no
  team hint in this first version.
- Event starts are included; ends are excluded. For example, start 2 and end 5
  covers frames 2, 3, and 4. Out-of-range parts are removed. Reversed or invalid
  frame numbers cause an error.
- Actual dead-ball detection still needs work with Beks's movement features.
  For now, `dead_evidence` is always 0.5 and `dead_reliability` is always 0,
  which tells the state machine there is no dead-ball evidence from this module.

For debugging, `diagnostic_flags` records conflict=1, unknown team=2, and
restart window=4. Flags can be combined. Check them using the exported constants:

```python
from possession.tagging import TEAM_CONFLICT

has_conflict = bool(signals.diagnostic_flags[100] & TEAM_CONFLICT)
```

Belek and Isken still handle halftime, ungraded frames, and the final labels.

## Check the code

Run from the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_tagging.py' -v
```

All 14 tests use invented events. They need no dataset. Almaz also ran the loader
on his local XML and reported 199,319 output frames. That confirms the module
runs; it does not measure possession accuracy.

The default settings are `TaggingConfig(team_reliability=0.5,
restart_strength=0.5)`. Do not choose settings using the public five-minute
answer file. Keep the actual XML and generated match data local and out of Git
and hosted AI chats.
