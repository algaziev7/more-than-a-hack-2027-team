# How Belek and Isken use Almaz's tagging code

Almaz's code turns event tags into clues for every video frame. It gives a
possible team, a weight for that clue, and a possible restart around that time.
Belek and Isken combine these with Beks's tracking features to decide possession.

The original tagging code and Azamat's data loader are merged. The adapter
explained here is new work on `almaz/tagging-adapter`; it still needs review
and merge before everyone uses it from main.

## 1. Recommended: use events that Azamat already loaded

Once this branch is available, use these calls in the pipeline:

```python
from possession.data import load_match
from possession.tagging import build_tagging_priors

match = load_match()  # Reads local data using MTAH_DATA_DIR.
priors = build_tagging_priors(match.events, n_frames=len(match.frame))
```

`match` contains the tracking and events. `priors` is Azamat's actual `PriorData`
object, with NumPy arrays in the format the state machine expects. The adapter
handles the conversion and checks the result. No manual conversion is needed.

Load the match and build the clues once at the start. Keep `priors` in memory
and pass it to the state machine. There is no intermediate file to send.

The planned state-machine call is `decode(match, features, priors, config)`.
`features` comes from Beks. That call is a plan, not an implemented function
in this branch.

## 2. Read the clues for the current frame

Inside the state machine, use the same frame number for all inputs:

```python
for frame in match.frame:
    home_hint, away_hint = priors.tag_team_evidence[frame]
    weight = priors.tag_team_reliability[frame]
    restart_hint = priors.restart_evidence[frame]

    # Combine these clues with Beks's features and your previous state.
    # Your state machine decides the final H, A, D, or X label.
```

`PriorData` has no `frame` field: use `match.frame`. For the real match there
are 199,319 entries per field. Entry 100 refers to tactical frame 100.

| Value | Simple meaning |
|---|---|
| Team hint `(1, 0)` | The tags support Barcelona |
| Team hint `(0, 1)` | The tags support Athletic |
| Team hint `(0.5, 0.5)` | No team preference |
| `weight == 0` | Ignore the team clue |
| `weight == 0.5` | Default weight for a usable team clue |
| `restart_hint == 0` | No restart clue from the tags |
| `restart_hint == 0.5` | A restart may happen around this time |

A team hint is not certainty. Always read its weight. These weights are starting
choices, not measured probabilities. Do not turn a restart clue straight into
D: the tag covers a window around the restart, not its exact moment.

## 3. If you already have the old list-based signals

Keep using them and convert once:

```python
from possession.tagging import load_tagging_signals, to_prior_data

signals = load_tagging_signals()
priors = to_prior_data(signals)
```

This path only reads `tactical/BAR-ATH_tactical_smart_tagging.xml`. The recommended
`load_match()` path also needs the tactical ATD XML and TXT files. Set
`MTAH_DATA_DIR` to the parent folder containing `tactical/` before running either.

The old signal loader still works without NumPy. The new adapter and Azamat's
contracts need NumPy, which is already in the team's dependency lock. Use your
agreed team environment; the adapter does not install anything.

## What the adapter does

- Converts the clue lists into NumPy arrays and returns `PriorData`.
- Keeps team columns in H,A order and keeps all diagnostic flags.
- Preserves values and weights; it does not make the clues stronger or change
  the possession rules.
- Checks frame order, lengths, shapes, valid values, and neutral clues where
  the weight is zero. It rejects fractional reason codes instead of rounding them.
- Makes independent copies. Changing the returned arrays does not change the
  original signals, and changing the signals later does not change the arrays.
- Supports an empty event list with neutral clues and a zero-frame test case.

## What is still missing

Actual stoppage detection is later work with Beks's movement features. For now,
`priors.dead_evidence` is always 0.5 and `priors.dead_reliability` is always 0.
That means there is no stopped-play clue from this module yet. The adapter does
not add a new detector.

The later function `build_priors(match, features, config)` is still planned.
`build_tagging_priors()` only provides the current tagging clues in a shared format.

Belek and Isken still handle halftime, ungraded frames, and final labels.

## Existing tagging rules

- Attacking codes that can support a team are BUILD UP, PROGRESSION, ATTACKING
  TRANSITION, CREATING CHANCES, BALL IN FINAL THIRD, BALL IN THE BOX, and LONG BALL.
- Barcelona/FC Barcelona mean H. Atletic Club/Athletic Club mean A.
  Capitalisation and extra spaces do not matter.
- Unknown or missing teams give no team preference. A throw-in with N/A can
  still provide a restart clue.
- SET PIECES provides restart clues, not proof of live team possession.
- Conflicting team hints cancel where they overlap. Repeated tags do not
  increase the weight.
- Defending phases, PLAYERS IN THE BOX, GOALS, and unknown codes give no team
  preference in this version.
- Starts are included and ends are excluded: start 2, end 5 covers frames 2,
  3, and 4. Out-of-range parts are clipped; invalid or reversed times fail.

For debugging, `diagnostic_flags` uses conflict=1, unknown team=2, and restart
window=4. Several flags can be combined. Use constants to check them:

```python
from possession.tagging import TEAM_CONFLICT

has_conflict = bool(priors.diagnostic_flags[100] & TEAM_CONFLICT)
```

## Try an invented example without the dataset

Run this Python code from the repository root in your team environment:

```python
from possession.contracts import PriorData
from possession.tagging import build_tagging_priors

# These events are invented, not labels or extracts from the match.
events = [
    {"code": "BUILD UP", "start_frame": 1, "end_frame": 3,
     "tags": {"Team": "Barcelona"}},
    {"code": "SET PIECES", "start_frame": 3, "end_frame": 5,
     "tags": {"Team": "N/A", "Type": "Throw-in"}},
]
priors = build_tagging_priors(events, n_frames=6)
assert isinstance(priors, PriorData)
assert priors.tag_team_evidence[1].tolist() == [1.0, 0.0]
assert priors.tag_team_reliability[1] == 0.5
assert priors.restart_evidence[3] == 0.5
assert priors.tag_team_reliability[3] == 0.0
assert priors.dead_reliability[3] == 0.0
```

## Tests

In your team environment, run:

```bash
python -m unittest tests.test_tagging tests.test_tagging_adapter tests.test_contracts tests.test_data -v
```

All 54 tests passed. They use invented data, not match files or the public answer
file. The earlier XML helper also ran on Almaz's laptop and produced 199,319
frames. Running successfully does not prove improved possession accuracy.

The defaults remain `TaggingConfig(team_reliability=0.5, restart_strength=0.5)`.
Do not choose settings using the public five-minute answer file. Keep actual
match XML and generated arrays out of Git and hosted AI chats.
