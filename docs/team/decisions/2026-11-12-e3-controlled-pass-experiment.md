# Controlled pass as kickoff evidence: synthetic experiment

Owner: Almaz / E3. Branch: `e3/kickoff-confirmation`. Status: **not sufficient
for half-start opening; do not integrate as kickoff confirmation**.

## Hypothesis and implementation

A relative-motion cue may tolerate tracking offset without enlarging the
fixed centre region: settlement -> kick control -> observed ball release
beyond both teams' control radius -> reception control. Start tags supply
context throughout, never a boundary. Existing E3 times/speeds and E4's 3 m
control radius are reused; no setting is selected from competition timing.

`possession/kickoff_pass.py::controlled_pass_candidates` is a standalone
experimental function. It is not called by `build_priors`, the pipeline or E2,
and emits no `CONFIRMED_KICKOFF` bit. No shared contract changes. Spatial
settlement tolerates bounded jitter using the existing stationary-speed/dwell
product as a drift bound. Observed release must persist for the motion dwell.
Gaps never count as evidence; excessive gaps, invalid samples, expired episodes
and half changes clear support. No interpolation or final possession labels.
Reacquisition without a supplied speed may reset this experimental detector;
the short-gap test uses supplied speed. It is not a complete missing-ball solution.

## Synthetic findings

Seven tests pass in `tests/test_kickoff_pass.py`, with 25/50 fps positive cases:

- Controlled passes with fixed coordinate shifts and small tracking jitter
  produce reception-time candidates.
- Accompanied ball motion towards the centre followed by a wait is rejected.
- Stationary waits, missing context, missing settlement, missing reception,
  long gaps, expired episodes and cross-half support are rejected.
- Short gaps are neutral and can preserve bounded observed support.
- **Counterexample:** a controlled preparatory pass towards the centre,
  received and settled there, is accepted. This is a false positive for a
  hypothetical pre-whistle sequence, even though all observations are plausible.

The last test deliberately exposes a limitation; its passing means the
counterexample is reproduced, not that kickoff detection succeeded. Start-tag
context and pass mechanics do not encode referee permission. A true kickoff
and a preparatory pass may have indistinguishable supplied observations.

## Decision and next step

Do not replace the centre gate with this signal or enable it as a hidden
fallback. E2/E4 should review whether an independent live-start cue can be
obtained, or explicitly agree a fallback policy and its error tradeoff. The
fixed-centre candidate in PR #19 remains unresolved on real inputs.

No competition inputs, reports, answer labels or frame-specific constants
were used. This is a synthetic engineering experiment, not an accuracy result.
