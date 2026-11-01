# Almaz's stoppage and restart clues

`possession/dead_ball.py` adds movement-based clues to the existing event tags.
It returns Azamat's `PriorData`, ready for Belek and Isken's state machine.
The state machine still decides the final H, A, D, or X labels.

This is an untuned first version. It can suggest that play is stopped or live;
it cannot establish the referee's decision from tracking alone.

## How the guys call it

Once this branch is merged, run in the existing team environment:

```python
from possession.data import load_match
from possession.dead_ball import build_priors

match = load_match()
priors = build_priors(match)
```

`load_match()` uses MTAH_DATA_DIR and needs the tactical ATD XML and TXT files.
The tagging XML is used when available. No video or homography is needed.
`build_priors()` itself only uses already loaded data and opens no files.

When Beks provides `FeatureData`, pass it as well:

```python
priors = build_priors(match, features=features, config=config)
```

`features` is Beks's result and `config` is the shared settings dictionary.
The detector only uses the existing `team_evidence` and `team_reliability`
fields. It assumes no new feature names in Beks's dictionaries. The frame
numbers must match exactly. Features are optional, so this work can be tested
before Beks's module is finished.

Read the results with the same frame index:

```python
for frame in match.frame:
    stop_or_live_clue = priors.dead_evidence[frame]
    weight = priors.dead_reliability[frame]
    possible_restart = priors.restart_evidence[frame]
    # Combine these with team clues in the state machine.
```

| Result | Meaning |
|---|---|
| `dead_evidence = 0.9`, weight 0.5 | Supporting clues for stopped play |
| `dead_evidence = 0.1`, weight 0.5 | Supporting clues for live play |
| `dead_evidence = 0.5`, weight 0 | No opinion; ignore this clue |
| `restart_evidence = 0` | No restart clue |
| `restart_evidence = 0.5` | The original set-piece tag covers this frame |
| `restart_evidence = 0.75` | Motion was confirmed after a recently observed stop |

These numbers are starting strengths, not measured probabilities. A restart
value already includes its strength; there is no separate restart-weight field.
The new movement-based restart is one pulse per confirmed stop. The original
weaker tag window is preserved, so restart_evidence may stay at 0.5 around it.

## How stopped-play evidence is built

The ball must be observed, have a usable speed, and remain slow for 0.6 seconds.
It must also have at least one supporting clue:

- A set-piece tag covers this time; or
- The ball is at least 0.5 metres outside the pitch.

Only then does the detector suggest stopped play. A stationary ball in the
middle of the pitch without a supporting tag gives no opinion. A tag without
usable ball observations also gives no stopped-play opinion.

This can miss genuine stoppages and can mistake a live pause inside an
approximate tag window for stopped play. It is a conservative starting rule,
not proof that the ball is dead.

## How live-play and restart evidence is built

The ball must be observed inside the pitch and move at least 2 m/s for 0.2
seconds. It also needs either:

- A confirmed stop within the previous 3 seconds; or
- Beks's team clue with weight at least 0.5 and strongest team support at least
  0.75. This is extra supporting evidence, not independent ground truth.

The first option can produce a stronger restart pulse. The second supports live
play but does not invent a restart without an observed stop. A new confirmed
stop is required before another movement-based restart can be emitted.

The detector does not guess which team takes an unknown-team throw-in.
It keeps Almaz's existing team hints and confidence weights.

## Handling bad or missing data

- A missing ball is not evidence of stopped play. It clears local confirmation
  counters and old stop context; a restart is not inferred across an unseen gap.
- Missing raw speed can be estimated from two adjacent observed positions in
  the same half. The first observation alone then gives no speed.
- When raw speed and position-based speed both exist, both must support slow
  or fast movement. Disagreement gives no affirmative slow/moving clue.
- A supplied speed or position jump above 45 m/s is rejected. Positions more
  than 10 metres beyond any pitch side are rejected. These are adjustable tracking
  checks, not claims about football's physical limits.
- Every counter resets at a half change, including direct first-to-second-half
  changes. No history crosses an excluded frame.
- Outside the supplied half masks, all clues are neutral and restart support
  is zero. The final decoder still writes X there.
- The function checks shared input types and frame alignment. Inputs are not
  changed, and the output is checked by the existing PriorData constructor.

No team possession state is maintained here. Only short confirmation counters
and recent-stop context are used to filter evidence. If support ends, the
output returns to neutral rather than claiming the stop continues indefinitely.

## Timing matters for the state machine

Durations use `max(1, ceil(seconds * fps))` consecutive frames. Stop/live clues
begin at the confirmation frame. The detector does not edit earlier frames.

Belek and Isken should account for this existing delay before adding another
persistence requirement. These clues can be wrong; their final decoder still
needs its own documented transition policy. No particular accuracy improvement
has been measured.

## Settings

Pass the full pipeline dictionary. This module reads only its own sections and
leaves other owners' settings alone:

```python
config = {
    "dead_ball": {
        "enabled": True,
        "stationary_speed_mps": 0.5,
        "moving_speed_mps": 2.0,
        "max_ball_speed_mps": 45.0,
        "outside_margin_m": 0.5,
        "position_margin_m": 10.0,
        "stop_duration_s": 0.6,
        "motion_duration_s": 0.2,
        "restart_context_s": 3.0,
        "evidence_weight": 0.5,
    },
    "tagging": {"team_reliability": 0.5, "restart_strength": 0.5},
}
```

`evidence_weight` is the weight of the inferred dead/live clues. The confirmed
restart pulse has strength 0.75. Setting evidence_weight to zero or enabled to
false disables movement-based inference and keeps just tagging within the half
masks. Invalid settings and unknown options inside these sections fail clearly.

These defaults were not trained or tuned on match labels. Do not select them
using the public five-minute answer file. Improving them needs allowed evidence
and documented reasoning.

## Debugging

The existing tagging reason bits stay unchanged: 1 conflict, 2 unknown team,
4 set-piece window. New bits are:

| Constant | Bit | Meaning |
|---|---|---|
| STOP_TAG_AND_STILL | 8 | Confirmed slow ball with a set-piece tag |
| STOP_OUTSIDE_AND_STILL | 16 | Confirmed slow ball outside the pitch |
| LIVE_MOTION | 32 | Confirmed movement with supporting context |
| CONFIRMED_RESTART | 64 | First confirmed movement after this stop |
| UNUSABLE_BALL | 128 | No usable ball observation/speed at this frame |

Use bitwise checks because several reasons can apply:

```python
from possession.dead_ball import CONFIRMED_RESTART

frame = 100  # Example frame, not a special match rule.
restart_here = bool(priors.diagnostic_flags[frame] & CONFIRMED_RESTART)
```

## Tests and remaining checks

```bash
python -m unittest discover -s tests -v
```

The full suite passed 97 tests, including 33 new cases for this module. Tests use
invented inputs only. They cover false stops, missing data, speed disagreement,
restart pulses, half independence, frame rates, invalid inputs, and full-length
output. No competition data or public answer file was used in this work.

Testing used an approved temporary environment with the team's locked packages
on Python 3.15. The team's Python 3.12 environment needs its own run. No project
environment, pyenv configuration, dependency lock, evaluator, or baseline changed.

Still needed: review with Beks and Belek/Isken, a local real-data run by an
authorised team member, complete pipeline integration, and allowed accuracy
validation. Tracking cannot always distinguish live pauses, ball retrieval during
stoppages, or erroneous positions. Keep detailed real-data outputs local and out
of Git and hosted AI chats.
