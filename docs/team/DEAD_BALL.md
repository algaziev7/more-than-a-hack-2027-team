# Almaz's stoppage and restart clues

## Kickoff signal proposal for PR #18 (E2/E4 review required)

E3 proposes `CONFIRMED_KICKOFF = 256` in the existing `diagnostic_flags`.
It means an observed centre settlement followed by sustained departure and
bounded endpoint control, within a `SET PIECES` / `Type=Kick Off (Start)`
window. It is distinct from generic live movement and ordinary restarts.
E2 should use this bit alone to open an awaiting period; generic numeric
priors retain their existing meanings. No shared dataclass or signature changes
are proposed. This semantic addition needs Belek/Beks review before merge.
The E2 consumer change belongs in PR #18 and is not implemented here.

### Implemented E3 candidate

`build_priors` now emits that bit once per qualifying settlement/departure
episode, at confirmation, without changing the numeric priors, the ordinary
restart flags, or final labels. `summarize_prior_diagnostics` adds
`event_counts.confirmed_kickoffs`. The detector does not read period policies;
E2 owns deciding when a period requires this evidence.

The complete episode must lie inside a start-kickoff tag window. Type and code
matching ignore case and surrounding/repeated whitespace. Missing tags,
conflicting Type variants, and `Kick Off (After Goal)` do not qualify. Duplicate
windows do not strengthen the signal. A tag alone cannot confirm anything.

The candidate requires:

- `ceil(stop_duration_s * fps)` observed slow frames within
  `kickoff_centre_radius_m` of the pitch centre (default 1 m).
- At least `ceil(motion_duration_s * fps)` observed moving frames, departure
  beyond that centre region, and displacement of `kickoff_departure_m` from
  the last settled position (default 1.5 m).
- E4 control using the existing reliability >= 0.5 and team support >= 0.75
  cutoffs, within `kickoff_control_window_s` (default 1 s) of the motion onset
  and confirmation, or at reception. Control need not persist throughout a pass.
- Confirmation within `restart_context_s` of the last observed settlement.
  Sustained stillness at the centre refreshes settlement. A new confirmed stop
  at reception prevents a late kickoff pulse.

The new 1 m / 1.5 m bounds separate a local settlement region from a clear
departure; the 1 s control window bounds stale corroboration. These are explicit
engineering hypotheses, not settings chosen from the competition match or
labels. They require owner review and remain unvalidated on real inputs.

Kickoff confirmation alone tolerates up to
`floor(kickoff_max_missing_gap_s * fps)` missing frames in total during pending
confirmation (default 0.2 s). Missing frames emit no kickoff bit and contribute
no observed support. Reacquisition must have credible cross-gap displacement;
without raw speed this endpoint displacement can support an observed reacquired
frame, but never fills unseen frames. Conflicting supplied speed cannot count
as motion. Excessive total missing time, rejected positions/speeds, half changes,
and lost tag context clear the episode. Ordinary live-motion gap behavior is
unchanged; this fixes the kickoff-specific failure without changing other stops.

The defaults deliberately fail closed when tags, settlement, or control are
missing. This may miss the real kickoff. Centre settlement followed by a
controlled pre-match repositioning can still resemble a kickoff; geometry and
automatic tags cannot establish the referee's decision. No real-match accuracy
claim follows from synthetic success.

### E2 integration required before claiming a half-start fix

Belek should consume `priors.diagnostic_flags & CONFIRMED_KICKOFF` while awaiting
the period's first possession (None flags mean no confirmation). Generic
`exit_dead_ok` must not open or refresh this gate. On an accepted kickoff,
clear the stop latch, discard pre-opening team support, and anchor the earliest
first-possession boundary at that confirmation frame. This matters when missing
ball frames prevent generic live evidence: the new bit is sufficient opening
proof even if numeric dead/live priors are neutral. A confirmed stop must still
cancel an opening. Keep normal dwell, expiry, and ordinary stop behavior after
the first possession. Disabled E3 must not silently bypass an awaiting period;
that behavior in PR #18 differs from the original agreed fail-closed policy.

E2/E4 review this semantic addition and jointly test their decoder change at
25 and 50 fps: stationary wait, approach-centre-and-settle, actual departure,
missing ball, repeated false openings, expiry, late boundaries, disabled E3,
unknown team, and mixed period policies. E3's standalone tests cannot establish
that the existing PR #18 consumes the new bit: it currently does not.

### Local diagnostic recipe (human terminal only)

If the yes/no check returns no confirmations, run this in a separate local
terminal with the actual prediction config:

```bash
python scripts/diagnose_kickoff.py --config configs/input-v1.json
```

The command uses the detector's actual gates with optional counters, writes
`runs/kickoff-gates.json` plus a readable `runs/kickoff-summary.txt`, and prints
no match diagnostics. Open the summary locally and share only half 2's stage
and optional settlement-detail category, never the report or counts.
Stages distinguish absent start-tag context, no usable
ball, no confirmed centre settlement, no sustained subsequent motion, no clear
departure, no endpoint control, and a contradictory confirmed stop. The counts
include reset causes (missing budget, rejected observation, context loss,
episode expiry and motion pause) to inspect privately. An earliest unmet stage
is a diagnostic lead, not proof of the real-match cause. Thresholds and labels
are unchanged. `enabled: false` means the config disabled motion inference.

When settlement is missing, the report distinguishes no observed ball near the
centre, observed but unusable centre positions/speeds, centre observations that
fail stillness, and fragmented slow support. A diagnostic-only lookback using
the existing `restart_context_s` also checks for slow centre observations just
before the start-tag window, within the same half. `SLOW_CENTRE_SEEN_BEFORE_TAG`
is evidence outside the required context, not proof it belongs to this kickoff.
It never supplies settlement evidence or changes detections. This helps test
whether requiring the full settlement inside a tag window is an unsuitable
assumption, without expanding a radius, speed threshold or tag window to fit
this match.

To distinguish centre observations before the tag from observation gaps around
a published kickoff, pass `--check-frame` to the diagnostic command. This input
is used only by `summarize_kickoff_coverage`, after normal inference has finished;
it never enters detector settings or changes predictions. The readable summary
then gives tag coverage, pre-tag centre coverage within the same continuous
period, ball observation at the check, and coverage in a surrounding window
using the existing `restart_context_s`. A missing sample at the check does not
prove the kick itself was unobserved, and nearby observations do not establish
the referee's decision. Inspect counts privately and share only categories.

Run the following on the E3 branch with the same config as the reported PR #18
run. It writes the opening flags, nearby centre distances, and start-tag
coverage into an ignored local file. Do not run it through hosted AI tools,
paste its output into chat, or commit the report. Enter the published kickoff
only for the coverage check; it is never passed into `build_priors`.
`first_generic_signal` reconstructs the first PR #18 opening predicate for
each awaiting half; it is not a kickoff classification. Inspect the distance
sequence locally to distinguish approach/settlement from departure.

```bash
python - <<'PY'
import json
from dataclasses import replace
from pathlib import Path
import numpy as np
from scripts.predict import load_config
from possession.data import load_match
from possession.features import build_features
from possession.dead_ball import (
    build_priors, _kickoff_context, LIVE_MOTION, CONFIRMED_RESTART,
    CONFIRMED_KICKOFF,
)
from possession.state_machine import StateMachineConfig, _decisive_state_per_frame

config = load_config("configs/input-v1.json")
match = load_match(config=config)
features = build_features(match, config)
priors = build_priors(match, features, config)
settings = replace(StateMachineConfig(**config.get("state_machine", {})), fps=match.fps)
_, _, generic, _ = _decisive_state_per_frame(features, priors, settings)
context = _kickoff_context(match.events, len(match.frame))
centre = np.asarray(match.pitch_m)/2
distance = np.linalg.norm(match.ball_xy_m-centre, axis=1)
report = []
for half in (1, 2):
    found = np.flatnonzero(generic & (match.half == half))
    opening = int(found[0]) if len(found) else None
    item = {"half": half, "first_generic_signal": opening,
            "kickoff_confirmations": np.flatnonzero(
                (priors.diagnostic_flags & CONFIRMED_KICKOFF != 0)
                & (match.half == half)).tolist()}
    if opening is not None:
        flags = int(priors.diagnostic_flags[opening])
        item.update(live_motion=bool(flags & LIVE_MOTION),
                    restart_pulse=bool(flags & CONFIRMED_RESTART),
                    start_tag_covers_opening=bool(context[opening]))
        nearby = range(max(0, opening-int(2*match.fps)),
                       min(len(match.frame), opening+int(2*match.fps)+1))
        item["nearby_centre_distances_m"] = [
            {"frame": i, "distance": float(distance[i]) if np.isfinite(distance[i]) else None}
            for i in nearby if match.half[i] == half]
    report.append(item)
# Optional check only. Never insert this value into detector settings.
import os
check_frame = os.environ.get("MTAH_KICKOFF_CHECK_FRAME")
coverage = None if check_frame is None else bool(context[int(check_frame)])
path = Path("runs/kickoff-diagnostic.json")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({"periods": report, "start_tag_covers_check_frame": coverage},
                           indent=2, allow_nan=False) + "\n", encoding="utf-8")
print("Diagnostic saved locally; inspect it outside hosted AI tools.")
PY
```

The report checks tag coverage at the opening and, optionally, at the published
kickoff. It does not assert that the whole intervening wait is covered. Inspect
the tag windows locally if those two checks differ or the signal is missing.
Share only the qualitative conclusion with Belek. Never choose thresholds to
make a detected boundary coincide with the published kickoff.

`possession/dead_ball.py` adds movement-based clues to the existing event tags.
It returns Azamat's `PriorData`, ready for Belek and Isken's state machine.
The state machine still decides the final H, A, D, or X labels.

## Bounded missing-observation support (review candidate)

Set `dead_ball.max_missing_gap_s` to enable bounded tolerance; the default is
0, preserving the original consecutive-observation policy described below.
The synthetic candidate uses 0.2 s. This is an engineering hypothesis, not a
selected competition setting. Compare it locally against 0 with otherwise
identical inputs/config using the aggregate diagnostic recipe below.

For the candidate run, insert this before building features/priors in that recipe:

```python
config.setdefault("dead_ball", {})["max_missing_gap_s"] = 0.2
```

Save baseline and candidate totals separately locally; use 0 for the baseline.

The detector still requires `ceil(stop_duration_s * fps)` observed supporting
frames. Missing observations emit neutral dead/live evidence and never advance
confirmation. A pending stop run may retain its support through at most
`floor(max_missing_gap_s * fps)` missing frames **in total**, including repeated
gaps; exceeding that budget resets the run and restart context. Thus intermittent
observations cannot accumulate indefinitely toward a new confirmation. Confirmation
clears the cumulative budget. A confirmed stop tolerates repeated gaps, each no
longer than that same limit, provided every reacquired observation still supports
the stop. With no pending stop run, retained restart context also uses only the
per-gap limit and still expires according to the wall-clock `restart_context_s`.

On reacquisition, displacement from the last usable position must also fit the
stationary-speed bound over elapsed time to retain pending stop support. A
stationary observation at a new location starts fresh support. Implausible
cross-gap displacement clears restart context too. This check does not impute
positions or claim the unseen trajectory was stationary. Rejected observed
samples always reset context; tolerance applies only to actually missing balls.
Live-motion dwell always resets on a gap, and half changes reset everything.

Selection argument: dropping all evidence at a single occlusion makes confirmed
stops depend strongly on uninterrupted detection. Retaining a bounded amount of
observed support addresses that failure while preserving the evidence count,
requiring fresh motion confirmation, and bounding stale support. The risk is
an unseen brief restart/stop within the gap; endpoint checks cannot rule it out.
Review this tradeoff with E2/E4 before enabling it in a frozen submission.
Long unobserved stoppages and still balls lacking contextual support remain
unresolved. More D frames alone do not establish better predictions.

Synthetic verification: 53 E3 tests pass, including thirteen gap-policy tests.
No restricted-data experiment or public-label tuning was performed.

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

### Totals-only coverage diagnostics (2026-11-10)

`summarize_prior_diagnostics(match, features, config)` runs the same inference
with aggregate counters, then compares it with control corroboration disabled.
It returns JSON-compatible totals and shares only. It does not return frame
IDs, positions, tags, paths, metadata, or labels. The existing `build_priors`
signature, shared contracts, thresholds, and outputs are unchanged.

Run this **locally**, from the branch checkout in the team environment. Use the
same config as the prediction being investigated (replace the example config
path if needed). Do not run restricted-data commands through hosted AI tools.

```bash
python - <<'PY'
import json
from pathlib import Path
from possession.data import load_match
from possession.features import build_features
from possession.dead_ball import summarize_prior_diagnostics
from scripts.predict import load_config

config = load_config("configs/input-v1.json")
match = load_match(config=config)
features = build_features(match, config)
report = summarize_prior_diagnostics(match, features, config)
Path("runs").mkdir(exist_ok=True)
Path("runs/prior-coverage.json").write_text(
    json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
print("Totals saved locally to runs/prior-coverage.json")
PY
```

Interpret `frame_counts` and `graded_frame_shares` together: **all frame shares
use graded frames**, including `usable_without_confirmed_stop_frames`, which
answers E2's requested coverage question. These four disjoint buckets sum to
`ball_usable_frames` when motion inference is enabled:

1. `usable_not_still_frames`: usable speed does not meet stillness rules.
2. `still_without_stop_context_frames`: still, but neither a restart tag nor
   sufficient outside-pitch distance supports a stop.
3. `stop_candidate_below_dwell_frames`: supporting still observations have not
   yet reached the consecutive dwell requirement. This includes the warm-up
   of successful runs, so it is not a count of failed stops.
4. `confirmed_stop_frames`: supporting still observations after confirmation.

`ball_missing_frames` and `ball_observed_unusable_frames` separate absence
from rejected observations. `event_counts` counts incomplete stop runs reset
by unusable ball, loss of supporting stillness/context, or a half change.
A run left incomplete at end of input is not counted as reset. These counts
explain gates, not the number of actual referee stoppages missed.

`confirmed_stop_run_share_followed_by_live` uses **confirmed stop runs** as its
denominator. It counts runs whose retained context later produces one confirmed
restart pulse within the configured context lifetime. It bridges only tolerated
gaps, never halftime, and is not an accuracy or cancellation rate. A new confirmed run
replaces the preceding context. `confirmed_stop_frames_overwritten_by_live`
is a **structural invariant check**, not a measured coverage-loss mechanism.
It counts simultaneous stop/live flags and must be zero: configuration validation
requires stationary speed < moving speed, making their conditions disjoint.
Later live evidence does not erase earlier stop evidence in E3.

`without_control_comparison.changed_stop_frames` should also be zero. E4's
team evidence only corroborates the live branch; it cannot change E3's stop
candidate or dwell. Additional live frames can still clear pending D support
or end D sooner **in the decoder**, which can reduce final D labels without
reducing prior stop coverage. A decoder comparison must be done separately
by E2 with identical inputs/config/code. No decoder changes are made here.

When motion inference is disabled, motion-gate counters are omitted. Empty
denominators return JSON null. The helper runs priors twice when features are
supplied; it is an opt-in investigation tool, not extra pipeline work.

The strong team hints across tag windows are unchanged. E2's proposed use of
tags only when tracking evidence is unavailable requires E2/E4 review of the
fusion policy; this diagnostic patch does not implement that proposal.

Synthetic follow-up: 40 E3 tests pass, including seven coverage/invariance
tests against E4's actual feature builder. Full suite: 134 discovered, 132 pass,
two real-decoder integration skips because E2 is absent from main. Environment:
Python 3.15.0, existing pinned dependencies. No match run, label inspection,
parameter tuning, or accuracy measurement was performed. The dominant source
of real-match attrition remains unknown until an authorised local run.

### Original implementation evidence

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
