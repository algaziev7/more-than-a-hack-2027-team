"""Isken's independent policy, integration and regression checks for E2.

All inputs are invented. Expected boundaries are hand specified or derived by
an offline run-group oracle, never by production fusion/transition helpers.
"""

from copy import deepcopy
from itertools import groupby, product
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from evaluation import possession_metrics as pm
from possession.dead_ball import build_priors
from possession.export import write_submission
from possession.state_machine import decode
from tests.e2_scenarios import TIMING_CASES, evidence_sequence, label_transitions, measure_timing


def grouped_reference(symbols, half, team_required, dead_required, latched_required=None,
                      lookahead=0, period_start=None, window=150, tag_start=None):
    """Independent re-derivation of the decode() policy from its prose description.

    Through 2026-11-08 this was a purely declarative "group runs, check each run's own length,
    suffix-assign from its boundary" oracle, deliberately avoiding production's pending-occurrence
    counter for structural independence. Decision 6 (2026-11-09) broke that: whether an H/A
    observation counts at all now depends on the *current state* and a *dead_confirmed* latch at
    that exact moment, both of which only make sense evaluated in temporal sequence -- a single D
    observation can latch the flag without itself transitioning the state; an R between two
    otherwise-qualifying H observations doesn't break their run (Decision 3: a non-decisive frame
    pauses a pending count, it doesn't reset it) but does clear the latch mid-run. No declarative
    whole-run check can express that without silently becoming wrong in some case (as happened
    twice while developing this update). So this is now a sequential walk, each piece re-derived
    independently from the written policy (not by importing or calling state_machine.decode) --
    less structurally different from production than the original design, but still a second,
    independently-authored implementation of the same prose spec, which is what actually matters
    for catching a transcription or off-by-one error in either one.

    `latched_required` (Decision 6's safety valve, added after a later review demonstrated the
    latch could otherwise pin D indefinitely): while gated, an H/A candidate still accumulates,
    but against this much longer requirement instead of team_required. The moment R lifts the
    gate, any *team*-candidate progress accumulated under that longer requirement is discarded
    (re-derived independently from the same reasoning as production's: letting it carry over
    toward the now-much-shorter team_required would let a long "banked" run of mere proximity
    cash in the instant a single frame of real proof arrives) -- a pending D-candidate, unrelated
    to the gate, is untouched. Defaults to `team_required` (no safety valve distinguishable from
    ordinary gating) when omitted, for callers that don't exercise it.

    R also discards a pending D-candidate (2026-11-10, Almaz's review): confirmed live play
    between two isolated stop observations means they are not one stop. The evidence-age window
    (evidence_window_s, ~150 frames by default) is not modelled: every sequence here is shorter.

    Decision 8 (2026-11-11): a confirmed team change is backdated to the start of its latest
    support run (a gap longer than team_required breaks it), except the latched safety valve; D
    is never backdated.

    Decision 9 (2026-11-11, ported from PR #16): the first team change after an R while in D is
    moved back to that R when its run starts within `lookahead` symbols and no other team symbol
    came in between; a D symbol, a half change or leaving D clears it. 0 disables it.

    Decision 10 (2026-11-12): `period_start` maps half -> "live_at_entry" (default, matching the
    evidence_sequence fixture) or "await_start". Until an await_start half has its first team
    possession, H/A symbols count as nothing unless the gate is open; an R opens it for `window`
    symbols, and a D or `window` symbols without an R close it again, dropping pending team
    support and the restart anchor. `window` is also the evidence window that trims old support
    (as production's evidence_window_s does for both).

    Decision 11 (2026-11-12): an R before `tag_start` (the first Kick Off (Start) tag symbol of
    an awaiting half; None means no tag) neither opens nor refreshes the gate. Single-half use.
    """
    if latched_required is None:
        latched_required = team_required
    labels = ["X"] * len(symbols)
    for half_id, indices in groupby(range(len(symbols)), key=lambda i: half[i]):
        indices = list(indices)
        if half_id == 0:
            continue
        state, dead_confirmed = "D", False
        pending_symbol, pending_count, last_support, support = None, 0, None, []
        restart_at, restart_teams = None, set()
        played = (period_start or {}).get(str(half_id), "live_at_entry") == "live_at_entry"
        awaiting, live_until = not played, -1
        for i in indices:
            symbol = symbols[i]
            if symbol == "D":
                dead_confirmed = True
            elif symbol == "R" and dead_confirmed:
                dead_confirmed = False
                # Only discard a candidate that was actually subject to the gate -- a single D
                # observation can latch dead_confirmed without state ever becoming "D" (it never
                # reached dead_required), so without the state == "D" guard, a later R would
                # wipe an ordinary, never-gated run's progress for no reason.
                if pending_symbol in ("H", "A") and state == "D":
                    pending_symbol, pending_count = None, 0
            if symbol == "R" and pending_symbol == "D":
                pending_symbol, pending_count = None, 0
            if symbol == "D":
                restart_at = None
            elif symbol == "R" and state == "D" and restart_at is None:
                restart_at, restart_teams = i, set()
            elif symbol in "HA" and restart_at is not None:
                restart_teams.add(symbol)

            vote = symbol
            if not played:
                if symbol == "R" and (tag_start is None or i >= tag_start):
                    awaiting, live_until = False, i + window
                elif not awaiting and (symbol == "D" or i > live_until):
                    awaiting = True
                if awaiting:
                    restart_at = None
                    if pending_symbol in ("H", "A"):
                        pending_symbol, pending_count = None, 0
                    if symbol in "HA":
                        vote = "."
            candidate = vote if vote in "HAD" else None
            if candidate is None:
                labels[i] = state
                continue
            if candidate == state:
                pending_symbol, pending_count = None, 0
                labels[i] = state
                continue
            if candidate == pending_symbol:
                if i - last_support > team_required:  # a long unsupported gap breaks the run
                    pending_start = i
                support.append(i)
            else:
                pending_start, support = i, [i]
            last_support = i
            pending_symbol = candidate
            latched = candidate != "D" and state == "D" and dead_confirmed
            backdate = candidate != "D" and not latched
            # Support older than the evidence window (the longer latched window while latched) no
            # longer counts, and the boundary cannot reach before what remains.
            trim = 2 * latched_required if latched else window
            while i - support[0] > trim:
                support.pop(0)
            pending_count, pending_start = len(support), max(pending_start, support[0])
            if candidate == "D":
                required = dead_required
            elif latched:
                required = latched_required
            else:
                required = team_required
            if pending_count >= required:
                # Decision 8: backdate a team change to the run's first supporting symbol (never
                # D, never the latched safety valve). Only paused symbols lie between.
                if backdate:
                    if (restart_at is not None and 0 < pending_start - restart_at <= lookahead
                            and restart_teams <= {candidate}):
                        pending_start = restart_at
                    labels[pending_start:i] = [candidate] * (i - pending_start)
                if candidate != "D":
                    played = True
                if state == "D" and candidate != "D":
                    # Leaving D: don't carry a stale latch into the live period that follows.
                    dead_confirmed = False
                    restart_at = None
                state = candidate
                pending_symbol, pending_count = None, 0
            labels[i] = state
    return labels


class StateMachineValidationTests(unittest.TestCase):
    def test_default_dwell_uses_match_fps(self):
        # 1.0 s confirms on the 10th / 25th / 50th observation; Decision 8 backdates to frame 0.
        for fps, confirmed in ((10., 9), (25., 24), (50., 49)):
            with self.subTest(fps=fps):
                prediction = decode(*evidence_sequence("H" * 60, fps=fps))
                (event,) = prediction.diagnostics["transitions"]
                self.assertEqual((event["frame"], event["confirmed_frame"]), (0, confirmed))
                self.assertTrue(np.all(prediction.labels == "H"))

    def test_fractional_dwell_never_rounds_below_required_observations(self):
        # 0.1 s at 25 fps requires 3 observations, not Python round(2.5) == 2.
        config = {"state_machine": {"team_dwell_s": .1, "dead_dwell_s": .1}}
        result = decode(*evidence_sequence("H" * 5 + "D" * 5), config)
        self.assertEqual([t["confirmed_frame"] for t in result.diagnostics["transitions"]], [2, 7])
        self.assertEqual(result.labels.tolist(), list("HHHHHHHDDD"))  # H backdated, D not

    def test_explicit_fps_must_agree_with_match(self):
        inputs = evidence_sequence("H" * 60, fps=50.)
        with self.assertRaisesRegex(ValueError, "fps.*match"):
            decode(*inputs, {"state_machine": {"fps": 25.}})
        same = decode(*inputs, {"state_machine": {"fps": 50.}})
        np.testing.assert_array_equal(same.labels, decode(*inputs).labels)

    def test_mismatched_valid_contract_lengths_fail_before_broadcast_or_truncation(self):
        match, features, priors = evidence_sequence("H" * 10)
        for n in (1, 9, 11):
            _, other_features, other_priors = evidence_sequence("A" * n)
            for field, args in (("features", (match, other_features, priors)),
                                ("priors", (match, features, other_priors))):
                with self.subTest(field=field, n=n):
                    with self.assertRaisesRegex(ValueError, field):
                        decode(*args)

    def test_misaligned_feature_frames_fail(self):
        match, features, priors = evidence_sequence("H" * 20)
        features.frame = features.frame[::-1].copy()
        with self.assertRaisesRegex(ValueError, "frame"):
            decode(match, features, priors)

    def test_thresholds_and_weights_are_bounded(self):
        inputs = evidence_sequence("H")
        for name in ("dead_threshold", "dead_reliability_min", "restart_weight",
                     "team_margin_threshold", "team_reliability_min"):
            for value in (-.01, 1.01):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, name):
                        decode(*inputs, {"state_machine": {name: value}})

    def test_evidence_window_must_cover_every_dwell(self):
        with self.assertRaisesRegex(ValueError, "evidence_window_s"):
            decode(*evidence_sequence("H"), {"state_machine": {"evidence_window_s": .5}})

    def test_live_and_dead_thresholds_cannot_overlap(self):
        # Beks's review: overlapping thresholds let one stop clue set and clear the latch.
        for settings in ({"live_confirmed_threshold": .9},
                         {"live_confirmed_threshold": .6, "dead_threshold": .6}):
            with self.subTest(**settings):
                with self.assertRaisesRegex(ValueError, "live_confirmed_threshold"):
                    decode(*evidence_sequence("H"), {"state_machine": settings})

    def test_conflicting_restart_cannot_clear_a_confirmed_stop(self):
        for team in ("H", "A"):
            with self.subTest(team=team):
                match, features, priors = evidence_sequence(team * 30 + "D" * 10 + team * 30)
                # Both signals meet their default thresholds: adjusted dead=.65,
                # restart=.6. A dead decision must keep the stop latch set.
                priors.dead_evidence[30:40] = .95
                priors.restart_evidence[30:40] = .6
                result = decode(match, features, priors)
                self.assertTrue(np.all(result.labels[31:] == "D"))
                # A later unopposed restart must still release it normally.
                priors.restart_evidence[40] = .75
                result = decode(match, features, priors)
                self.assertEqual(label_transitions(result.labels, start=30),
                                 [(31, team, "D"), (40, "D", team)])

    def test_stop_fallback_requires_longer_support_than_ordinary_dwell(self):
        for settings in ({"latched_team_dwell_s": .04},
                         {"latched_team_dwell_s": .6}, {"team_dwell_s": 4.}):
            with self.subTest(**settings):
                with self.assertRaisesRegex(ValueError, "latched_team_dwell_s"):
                    decode(*evidence_sequence("H"), {"state_machine": settings})
        # Check rounded counts at the actual match rate, not the 25-fps fallback.
        config = {"state_machine": {"team_dwell_s": .1, "latched_team_dwell_s": .11}}
        with self.assertRaisesRegex(ValueError, "latched_team_dwell_s"):
            decode(*evidence_sequence("H"), config)  # both ceil to 3 at 25 fps
        result = decode(*evidence_sequence("H" * 20, fps=100.), config)
        self.assertEqual(result.diagnostics["transitions"][0]["confirmed_frame"], 9)  # 10th obs
        self.assertEqual(result.labels.tolist(), list("H" * 20))  # backdated (Decision 8)

    def test_zero_team_floors_do_not_turn_absent_or_tied_evidence_into_home(self):
        config = {"state_machine": {"team_reliability_min": 0., "team_margin_threshold": 0.}}
        for weight in (0., .9):
            with self.subTest(weight=weight):
                match, features, priors = evidence_sequence("." * 30)
                features.team_reliability[:] = weight
                result = decode(match, features, priors, config)
                self.assertTrue(np.all(result.labels == "D"))
        # Zero floors must still allow a genuine, positively weighted team clue.
        result = decode(*evidence_sequence("A" * 30), config)
        self.assertEqual(result.labels.tolist(), list("A" * 30))

    def test_zero_dead_floor_does_not_promote_zero_weight_stop_evidence(self):
        config = {"state_machine": {"dead_reliability_min": 0., "dead_threshold": .5}}
        result = decode(*evidence_sequence("H" * 30), config)
        self.assertEqual(result.labels.tolist(), list("H" * 30))

    def test_team_margin_boundary_is_inclusive_and_symmetric(self):
        for source in ("tracking", "tagging", "both"):
            for offset in (-1e-9, 0., 1e-9):
                for team in ("H", "A"):
                    with self.subTest(source=source, offset=offset, team=team):
                        match, features, priors = evidence_sequence("." * 40)
                        pair = [.575 + offset, .425 - offset]
                        if team == "A":
                            pair.reverse()
                        if source in ("tracking", "both"):
                            features.team_evidence[:] = pair
                            features.team_reliability[:] = .9
                        if source in ("tagging", "both"):
                            priors.tag_team_evidence[:] = pair
                            priors.tag_team_reliability[:] = .5
                        result = decode(match, features, priors)
                        expected = "D" * 40 if offset < 0 else team * 40
                        self.assertEqual(result.labels.tolist(), list(expected))

    # Decision 7 (tracking-first fusion): reliable tracking owns the frame; tags fill only frames
    # where tracking is below the reliability floor. Invented inputs throughout.
    def _tracking_and_tags(self, n, tracking_home, tracking_rel, tag_home, tag_rel):
        match, features, priors = evidence_sequence("." * n)
        features.team_evidence[:] = [tracking_home, 1 - tracking_home]
        features.team_reliability[:] = tracking_rel
        priors.tag_team_evidence[:] = [tag_home, 1 - tag_home]
        priors.tag_team_reliability[:] = tag_rel
        return match, features, priors

    def test_contested_reliable_tracking_pauses_instead_of_letting_a_tag_vote(self):
        # A duel (margin 0.04 < 0.15) inside an H tag window: nobody clearly has the ball.
        result = decode(*self._tracking_and_tags(40, .52, .9, 1., .5))
        self.assertTrue(np.all(result.labels == "D"), result.labels)
        self.assertEqual(result.diagnostics["team_sources"],
                         {"tracking": 0, "contested": 40, "tag": 0})

    def test_decisive_tracking_turnover_is_not_overruled_by_a_stale_tag(self):
        match, features, priors = self._tracking_and_tags(60, .3, .4, 1., .5)
        features.team_evidence[:30] = [.9, .1]  # H establishes possession first
        result = decode(match, features, priors)
        self.assertEqual(label_transitions(result.labels), [(30, "H", "A")])  # H backdated to 0

    def test_tag_fills_frames_where_tracking_is_below_the_floor(self):
        # Zero reliability must carry neutral evidence (contracts rule); .1 is a weak A reading.
        for tracking_home, tracking_rel in ((.5, 0.), (.1, .1)):
            with self.subTest(tracking_rel=tracking_rel):
                result = decode(*self._tracking_and_tags(
                    30, tracking_home, tracking_rel, 1., .5))
                self.assertEqual(result.labels.tolist(), list("H" * 30))
                self.assertEqual(result.diagnostics["team_sources"],
                                 {"tracking": 0, "contested": 0, "tag": 30})

    def test_two_sub_floor_sources_no_longer_add_up_to_a_decision(self):
        # Averaging summed reliabilities (.2 + .1 >= .25); one source must clear the floor alone.
        result = decode(*self._tracking_and_tags(30, .9, .2, 1., .1))
        self.assertTrue(np.all(result.labels == "D"))

    def test_tag_weight_below_decoder_floor_fails(self):
        # Review note: under Decision 7 a non-zero tag weight below the floor disables tags silently.
        inputs = self._tracking_and_tags(30, .5, 0., 1., .2)  # tag evidence present
        with self.assertRaisesRegex(ValueError, "team_reliability"):
            decode(*inputs, {"tagging": {"team_reliability": .2}})
        for ok in (0., .25):
            with self.subTest(team_reliability=ok):
                decode(*inputs, {"tagging": {"team_reliability": ok}})

    def test_tag_weight_check_skips_tracking_only_runs(self):
        # Almaz, PR #13: with tags disabled or missing, an unused default tag weight (0.5) below
        # a raised decoder floor must not reject a valid tracking-only run.
        config = {"data": {"load_tags": False}, "state_machine": {"team_reliability_min": .75}}
        result = decode(*self._tracking_and_tags(30, .95, .9, .5, 0.), config)
        self.assertEqual(result.labels.tolist(), list("H" * 30))
        # The same floor still rejects the weight once tag evidence is actually supplied.
        with self.assertRaisesRegex(ValueError, "team_reliability"):
            decode(*self._tracking_and_tags(30, .95, .9, 1., .5), config)

    # Decision 8: confirmed changes are backdated to their first supporting frame.
    def test_backdating_spans_paused_frames_and_never_overwrites_other_support(self):
        result = decode(*evidence_sequence("H" * 30 + "A" * 10 + "." * 5 + "A" * 15 + "H" * 5))
        self.assertEqual(result.labels[:30].tolist(), list("H" * 30))
        self.assertEqual(result.labels[30:60].tolist(), list("A" * 30))  # incl. the 5 paused
        (_, turnover) = result.diagnostics["transitions"]
        self.assertEqual((turnover["frame"], turnover["confirmed_frame"]), (30, 59))
        # Beks, PR #13: a stray touch, 5 s with no support, then 24 A confirms A, but the
        # boundary stays at the start of the latest support run (156), not the stray touch (30).
        result = decode(*evidence_sequence("H" * 30 + "A" + "." * 125 + "A" * 24 + "H" * 5))
        (_, turnover) = result.diagnostics["transitions"]
        self.assertEqual((turnover["frame"], turnover["confirmed_frame"]), (156, 179))
        self.assertTrue(np.all(result.labels[:156] == "H"))
        # Short gaps (a duel, an A every 6th frame) do not break the run: full backdate.
        result = decode(*evidence_sequence("H" * 30 + ("A" + "." * 5) * 25))
        self.assertEqual(label_transitions(result.labels, start=30), [(30, "H", "A")])
        # D is never backdated: two stray dead frames do not turn the gap between into a stop.
        result = decode(*evidence_sequence("H" * 30 + "D" + "." * 140 + "D"))
        self.assertEqual(label_transitions(result.labels, start=30), [(171, "H", "D")])
        # A competing candidate restarts the count, so backdating cannot reach past it.
        result = decode(*evidence_sequence("H" * 30 + "A" * 10 + "D" + "A" * 25))
        self.assertEqual(label_transitions(result.labels, start=30), [(41, "H", "A")])

    def test_safety_valve_exit_from_a_confirmed_stop_is_not_backdated(self):
        # Team evidence alone ends a latched stop only after latched_team_dwell (75 frames), and
        # stays at that confirmation frame: it is too weak to move the stop's end earlier.
        result = decode(*evidence_sequence("H" * 30 + "D" * 10 + "H" * 80))
        exit_ = result.diagnostics["transitions"][-1]
        self.assertEqual((exit_["frame"], exit_["confirmed_frame"], exit_["to_state"]),
                         (114, 114, "H"))
        self.assertTrue(np.all(result.labels[31:114] == "D"))

    # Decision 9 (ported from PR #16): tag protection and restart look-ahead.
    def _stale_tag_turnover(self, n_after):
        # H by tracking, then A tracking every 3rd frame with an H phase tag on the frames between.
        match, features, priors = evidence_sequence("H" * 30 + "." * n_after)
        for i in range(30, 30 + n_after):
            if i % 3 == 0:
                features.team_evidence[i], features.team_reliability[i] = (.05, .95), .9
            else:
                priors.tag_team_evidence[i], priors.tag_team_reliability[i] = (1., 0.), .5
        return match, features, priors

    def test_stale_tag_cannot_cancel_a_tracking_turnover(self):
        result = decode(*self._stale_tag_turnover(90))
        self.assertEqual(label_transitions(result.labels, start=30), [(30, "H", "A")])
        self.assertGreater(result.diagnostics["protected_tracking_frames"], 0)

    def test_opposing_tracking_still_cancels_a_pending_turnover(self):
        match, features, priors = self._stale_tag_turnover(90)
        features.team_evidence[60], features.team_reliability[60] = (.95, .05), .9  # real H
        priors.tag_team_reliability[60] = 0.
        result = decode(match, features, priors)
        # A support before 60 is discarded; the 20 A frames after it are under the 25-frame dwell.
        self.assertEqual(label_transitions(result.labels, start=30), [])

    def test_tag_protection_expires_with_the_evidence_window(self):
        match, features, priors = evidence_sequence("H" * 30 + "A" * 5 + "." * 200 + "A" * 20)
        priors.tag_team_evidence[35:235] = (1., 0.)  # H phase tag after 5 A tracking frames
        priors.tag_team_reliability[35:235] = .5
        result = decode(match, features, priors)
        # Once the 5 A frames are older than evidence_window_s, the H tag cancels them again, so
        # 20 later A frames alone are under the dwell: no turnover.
        self.assertEqual(label_transitions(result.labels, start=30), [])
        self.assertEqual(result.diagnostics["protected_tracking_frames"], 150)

    def test_restart_lookahead_puts_the_boundary_on_the_restart_frame(self):
        for gap, boundary in ((20, 30), (49, 30), (50, 81)):
            with self.subTest(gap=gap):
                result = decode(*evidence_sequence("D" * 30 + "R" + "." * gap + "H" * 25))
                self.assertEqual(label_transitions(result.labels), [(boundary, "D", "H")])
        # Another team seen in between cancels the look-ahead: the boundary stays at the H run.
        result = decode(*evidence_sequence("D" * 30 + "R" + "." * 5 + "AAA" + "." * 5 + "H" * 25))
        self.assertEqual(label_transitions(result.labels), [(44, "D", "H")])
        # A new stop in between clears it and re-arms the latch: H alone needs fresh proof.
        result = decode(*evidence_sequence("D" * 30 + "R" + "." * 5 + "DD" + "." * 5 + "H" * 25))
        self.assertTrue(np.all(result.labels == "D"))
        # Pre-commit review: a stray H right after the restart protects the A tags that follow;
        # those protected A votes still count as "another team seen", so no look-ahead jump.
        match, features, priors = evidence_sequence("D" * 30 + "R" + "H" + "." * 28 + "H" * 25)
        priors.tag_team_evidence[32:41], priors.tag_team_reliability[32:41] = (0., 1.), .5
        result = decode(match, features, priors)
        self.assertGreater(result.diagnostics["protected_tracking_frames"], 0)
        self.assertEqual(label_transitions(result.labels), [(60, "D", "H")])
        with self.assertRaisesRegex(ValueError, "restart_lookahead_s"):
            decode(*evidence_sequence("H"), {"state_machine": {"restart_lookahead_s": -.1}})

    def test_live_play_between_stop_clues_does_not_enter_dead(self):
        # Beks's review: isolated stops split by a restart and live play must not combine.
        result = decode(*evidence_sequence(
            "H" * 30 + "D" + "." * 4 + "R" * 6 + "." * 14 + "D" + "." * 20))
        self.assertEqual(label_transitions(result.labels, start=30), [])

    def test_dead_ball_weight_below_decoder_floor_fails(self):
        # Review note: evidence_weight becomes dead_reliability, so 0.25 < 0.3 silently disables D.
        inputs = evidence_sequence("H")
        with self.assertRaisesRegex(ValueError, "evidence_weight"):
            decode(*inputs, {"dead_ball": {"evidence_weight": .25}})
        for ok in ({"evidence_weight": 0.}, {"enabled": False, "evidence_weight": .25},
                   {"evidence_weight": .3}):
            with self.subTest(**ok):
                decode(*inputs, {"dead_ball": ok})

    def test_empty_single_and_excluded_frames(self):
        for symbols, half, expected in (("", [], ""), ("H", [1], "D"),
                                        ("HAD", [0, 0, 0], "XXX"),
                                        ("...", [1, 1, 1], "DDD")):
            with self.subTest(symbols=symbols):
                result = decode(*evidence_sequence(symbols, half=half))
                self.assertEqual(result.labels.tolist(), list(expected))
                self.assertEqual(result.diagnostics["transitions"], [])

    def test_long_missing_gap_does_not_create_stop_or_turnover(self):
        result = decode(*evidence_sequence("H" * 30 + "." * 1000))
        self.assertTrue(np.all(result.labels[14:] == "H"))

    def test_pending_evidence_expires_after_evidence_window(self):
        # Almaz's review (2026-11-10): 40s-old support must not combine with a fresh touch.
        result = decode(*evidence_sequence("H" * 30 + "A" * 24 + "." * 1000 + "A"))
        self.assertEqual(label_transitions(result.labels, start=30), [])
        # Within the default 150-frame window the gap is still tolerated (Decision 3); the
        # 120-frame gap breaks the support run for backdating, so the boundary is the last A.
        result = decode(*evidence_sequence("H" * 30 + "A" * 24 + "." * 120 + "A"))
        self.assertEqual(label_transitions(result.labels, start=30), [(174, "H", "A")])
        # Just outside it, the oldest support has aged out.
        result = decode(*evidence_sequence("H" * 30 + "A" * 24 + "." * 127 + "A"))
        self.assertEqual(label_transitions(result.labels, start=30), [])

    def test_confirmed_live_play_cancels_pending_stop(self):
        # Almaz's review (2026-11-10): two isolated stop frames split by live play are not a stop.
        result = decode(*evidence_sequence("H" * 30 + "D" + "R" * 25 + "D" + "." * 50))
        self.assertEqual(label_transitions(result.labels, start=30), [])
        # Without live play between them they still combine (Decision 3 pause, not reset).
        result = decode(*evidence_sequence("H" * 30 + "D" + "." * 25 + "D" + "." * 50))
        self.assertEqual(label_transitions(result.labels, start=30), [(56, "H", "D")])

    def test_incumbent_support_cancels_pending_turnover(self):
        result = decode(*evidence_sequence("H" * 30 + "A" * 24 + "H" + "A" * 25))
        self.assertEqual(label_transitions(result.labels, start=30), [(55, "H", "A")])

    def test_competing_stop_candidate_cancels_pending_turnover(self):
        # One stop observation cannot establish D, but invalidates the A run.
        result = decode(*evidence_sequence("H" * 30 + "A" * 24 + "D" + "A" * 25))
        self.assertEqual(label_transitions(result.labels, start=30), [(55, "H", "A")])

    def test_unknown_team_restart_does_not_guess_team_current_policy(self):
        # Decision 9: within restart_lookahead_s (50 frames) of the restart signal at 40, the
        # first team to take over owns the restart; beyond it, no team is guessed.
        result = decode(*evidence_sequence("H" * 30 + "D" * 10 + "R" * 50 + "A" * 25))
        self.assertEqual(label_transitions(result.labels, start=30),
                         [(31, "H", "D"), (40, "D", "A")])
        result = decode(*evidence_sequence("H" * 30 + "D" * 10 + "R" * 51 + "A" * 25))
        self.assertTrue(np.all(result.labels[31:91] == "D"))
        self.assertEqual(label_transitions(result.labels, start=30),
                         [(31, "H", "D"), (91, "D", "A")])

    def test_half_reset_discards_pending_and_confirmed_state(self):
        for gap in (0, 5):
            for first in ("H" * 30 + "A" * 24, "A" * 30 + "H" * 24):
                with self.subTest(gap=gap, first=first[0]):
                    # 20 second-half A frames are under the 25-frame dwell: they would only
                    # confirm A if pending (24 A) or confirmed (A) state leaked across the reset.
                    symbols = first + "A" * gap + "A" * 20
                    half = [1] * len(first) + [0] * gap + [2] * 20
                    result = decode(*evidence_sequence(symbols, half=half))
                    self.assertEqual(result.labels[-20:].tolist(), list("D" * 20))
                    self.assertTrue(np.all(result.labels[len(first):len(first) + gap] == "X"))

    def test_final_frame_confirms_only_when_dwell_completed(self):
        for count in (24, 25):
            with self.subTest(count=count):
                result = decode(*evidence_sequence("H" * 30 + "A" * count))
                events = [] if count == 24 else [(30, "H", "A")]
                self.assertEqual(label_transitions(result.labels, start=30), events)

    def test_measured_boundaries_and_missed_short_possession(self):
        # Decision 6 (2026-11-09): Restart and Same-team restart now carry +1 frame extra delay --
        # the cost of requiring the inserted "R" (restart proof) before team evidence counts.
        # Decision 8 (2026-11-11): team changes are backdated to their first supporting frame;
        # stops keep their 2-frame dwell (+1); restarts land on the restart frame (Decision 9).
        # The 100-frame occlusion breaks the support run, so that turnover lands at its last run
        # (+112), still earlier than unbacked confirmation (+124): the cost of not reaching back
        # to a stray touch across a long gap (Beks, PR #13).
        expected = (([0], 0, 0), ([1], 0, 0), ([0], 0, 0),
                    ([1, 0], 0, 0), ([112], 0, 0), ([], 2, 0),
                    ([0, 0], 0, 0), ([0, 0], 0, 0))
        for case, wanted in zip(TIMING_CASES, expected):
            with self.subTest(case=case.name):
                self.assertEqual(measure_timing(case), wanted)
                result = decode(*evidence_sequence(case.symbols))
                # A change backdated to a half's first frame has no earlier label to differ from.
                recorded = [(t["frame"], t["from_state"], t["to_state"])
                            for t in result.diagnostics["transitions"] if t["frame"] > 0]
                self.assertEqual(recorded, label_transitions(result.labels))

    def test_exhaustive_short_sequences_against_offline_grouped_reference(self):
        # 5,461 sequences, including empty; neutral gaps keep their frame offsets.
        # latched_required=75 matches state_machine's actual default latched_team_dwell_frames
        # (not overridden by this config) -- unreachable within length <= 6 either way, kept
        # explicit so this doesn't silently rely on the oracle's own default being coincidentally
        # equivalent to "no safety valve, same as ordinary gating" (team_required, 3).
        config = {"state_machine": {"team_dwell_s": .12, "dead_dwell_s": .08}}
        for length in range(7):
            for symbols in product("HAD.", repeat=length):
                result = decode(*evidence_sequence(symbols), config)
                expected = grouped_reference(symbols, [1] * length, 3, 2, latched_required=75,
                                             lookahead=50)
                self.assertEqual(result.labels.tolist(), expected, "".join(symbols))

    def test_seeded_half_sequences_against_reference(self):
        config = {"state_machine": {"team_dwell_s": .12, "dead_dwell_s": .08}}
        # Decision 10: also with the second half, and both halves, awaiting their kickoff.
        for policy in ({"1": "live_at_entry", "2": "live_at_entry"},
                       {"1": "live_at_entry", "2": "await_start"},
                       {"1": "await_start", "2": "await_start"}):
            rng = np.random.default_rng(20261108)
            for sample in range(200):
                symbols = rng.choice(list("HAD.R"), 80).tolist()
                half = [1] * 35 + [0] * 5 + [2] * 40
                result = decode(*evidence_sequence(symbols, half=half, period_start=policy), config)
                expected = grouped_reference(symbols, half, 3, 2, latched_required=75,
                                             lookahead=50, period_start=policy)
                self.assertEqual(result.labels.tolist(), expected, (policy, sample))

    def test_exhaustive_await_start_sequences_against_reference(self):
        # Decision 10: every sequence up to length 6 over H/A/D/./R in an await_start half, with a
        # 3-frame window (gate and evidence), so opening, closing by stop and by expiry, and
        # support trimming all occur; the expiry count guards against a vacuous pass.
        config = {"state_machine": {"team_dwell_s": .12, "dead_dwell_s": .08,
                                    "evidence_window_s": .12}}
        # Decision 11: again with a one-frame start tag at frame 2, which ends before most Rs.
        policy = {"1": "await_start"}
        expiries = 0
        for tag_start in (None, 2):
            for length in range(7):
                for symbols in product("HAD.R", repeat=length):
                    match, features, priors = evidence_sequence(symbols, period_start=policy)
                    if tag_start is not None:
                        match.events = _start_tag(tag_start, tag_start + 1)
                    result = decode(match, features, priors, config)
                    expected = grouped_reference(
                        symbols, [1] * length, 3, 2, latched_required=75, lookahead=50,
                        period_start=policy, window=3,
                        tag_start=tag_start if tag_start is not None and length > tag_start
                        else None)
                    self.assertEqual(result.labels.tolist(), expected,
                                     ("".join(symbols), tag_start))
                    if length and result.diagnostics["period_starts"][0]["closings"] and (
                            "D" not in "".join(symbols)):
                        expiries += 1
        self.assertGreater(expiries, 200)

    def test_team_swap_symmetry_with_conflicting_geometry_and_tags(self):
        rng = np.random.default_rng(42)
        for sample in range(50):
            match, features, priors = evidence_sequence("." * 120)
            home = rng.choice([.05, .25, .5, .75, .95], 120)
            features.team_evidence[:] = np.column_stack((home, 1 - home))
            features.team_reliability[:] = .8
            tag_home = rng.choice([.05, .5, .95], 120)
            priors.tag_team_evidence[:] = np.column_stack((tag_home, 1 - tag_home))
            priors.tag_team_reliability[:] = .5
            priors.dead_evidence[40:50], priors.dead_reliability[40:50] = .9, .5
            match.half[60:65], match.half[65:] = 0, 2
            config = {"state_machine": {"team_dwell_s": .08}}
            original = decode(match, features, priors, config)
            features.team_evidence = features.team_evidence[:, ::-1].copy()
            priors.tag_team_evidence = priors.tag_team_evidence[:, ::-1].copy()
            swapped = decode(match, features, priors, config)
            expected = [{"H": "A", "A": "H", "D": "D", "X": "X"}[x]
                        for x in original.labels]
            self.assertEqual(swapped.labels.tolist(), expected, sample)

    def test_repeated_calls_preserve_inputs_and_config(self):
        inputs = evidence_sequence("H" * 30 + "D" * 10 + "A" * 30)
        # "enabled" is a dead_ball.DeadBallConfig field, not TaggingConfig's -- decode() now
        # validates the tagging section strictly (Decision 6's restart-threshold guard), so this
        # uses a real TaggingConfig field instead of one that only ever worked by accident. Kept
        # below state_machine's default restart_evidence_threshold (0.6), which that same guard
        # requires.
        config = {"state_machine": {"team_dwell_s": .2}, "tagging": {"restart_strength": .4}}
        before = deepcopy((inputs, config))
        first = decode(*inputs, config)
        decode(*evidence_sequence("A" * 20))
        second = decode(*inputs, config)
        np.testing.assert_array_equal(first.labels, second.labels)
        self.assertEqual(first.diagnostics, second.diagnostics)
        for original, copy in zip(inputs, before[0]):
            for name, value in vars(original).items():
                if isinstance(value, np.ndarray):
                    np.testing.assert_array_equal(value, getattr(copy, name))
                else:
                    self.assertEqual(value, getattr(copy, name))
        self.assertEqual(config, before[1])

    def test_e3_priors_decode_and_export_synthetic_vertical_slice(self):
        # An invented in-pitch moving ball, then outside/still, then a restart.
        match, features, _ = evidence_sequence("H" * 30 + "." * 30 + "H" * 40)
        xy = np.column_stack((np.arange(100) * .12 + 10., np.full(100, 20.)))
        xy[30:60] = (-1., 20.)
        match.ball_xy_m = xy
        match.ball_observed[:] = True
        match.ball_speed_mps = np.full(100, 3.)
        match.ball_speed_mps[30:60] = 0.
        priors = build_priors(match, features)
        prediction = decode(match, features, priors)
        events = label_transitions(prediction.labels)
        # Decision 8: H is backdated to frame 0, so the half-start D never appears in labels.
        self.assertEqual([(a, b) for _, a, b in events], [("H", "D"), ("D", "H")])
        # E3 first rejects the jump, then needs 15 still observations; E2 adds one frame.
        # Decision 6 (2026-11-09): the final restart now also waits for E3's own confirmed-live
        # signal before team evidence counts at all (74 -> 79) -- team proximity alone is no
        # longer enough to leave a confirmed stop, which is the whole point of that decision.
        # Decision 8 (2026-11-11): the stop is not backdated (E3's first dead frame 45, plus E2's
        # 2-frame dwell); the restart is backdated to the first H frame after E3's live
        # confirmation clears the latch (65), though only confirmed W frames later.
        self.assertEqual(events, [(46, "H", "D"), (65, "D", "H")])
        self.assertEqual(prediction.diagnostics["transitions"][-1]["confirmed_frame"], 89)
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "first.csv", Path(temporary) / "second.csv"
            write_submission(prediction, first, n_expected=100)
            write_submission(decode(match, features, priors), second, n_expected=100)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            check = subprocess.run(
                [sys.executable, "evaluation/validate_submission.py", str(first), "--rows", "100"],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            )
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)


class E2MetricContractTests(unittest.TestCase):
    def test_official_metric_on_invented_perfect_sequence(self):
        labels = pm.label_codes(list("HHDDDAAAHH"))
        result = pm.evaluate(labels, labels, bootstrap_n=0)
        self.assertEqual(result["macro_f1"], 1.)
        self.assertEqual(result["spell_f1_mean"], 1.)
        self.assertEqual(result["n_gt_spells"], 3)

    def test_abstention_filling_does_not_cross_ungraded_gap(self):
        truth = pm.label_codes(list("HHXXAA"))
        prediction = pm.label_codes(list("HXXXAX"))
        result = pm.evaluate(truth, prediction, bootstrap_n=0)
        self.assertEqual(result["n_pred_spells"], 2)
        self.assertEqual(result["spell_f1_mean"], 1.)
        self.assertEqual(result["accuracy"], .5)

    def test_dead_ball_separates_same_team_spells(self):
        labels = pm.label_codes(list("HHDHH"))
        result = pm.evaluate(labels, labels, bootstrap_n=0)
        self.assertEqual(result["n_pred_spells"], 2)
        self.assertEqual(result["spell_f1_mean"], 1.)



AWAIT = {"1": "await_start", "2": "await_start"}


def _await(symbols, **kwargs):
    return decode(*evidence_sequence(symbols, period_start=AWAIT, **kwargs))


def _start_tag(start, end, kind="Kick Off (Start)"):
    return [{"start_frame": start, "end_frame": end, "code": "SET PIECES",
             "tags": {"Type": kind, "Team": "N/A"}}]


def _kickoff_match(fps, wait_s, missing_s=0., policy="await_start", approach_s=0.):
    """Invented geometry: ball at rest on the centre spot with a home player beside it for
    `wait_s`, then dribbled away at 3 m/s with that player alongside; the first `missing_s` of
    the dribble is unobserved. One away player and a second home player stand far off. With
    `approach_s`, that player first dribbles the ball to the spot (Almaz's pre-kickoff case)."""
    from possession.contracts import MatchData
    approach, wait, missing, play = (round(s * fps) for s in (approach_s, wait_s, missing_s, 3))
    n = approach + wait + missing + play
    centre = np.array([52.5, 34.])
    i, kick = np.arange(n), approach + wait
    t = np.where(i < approach, i - approach, np.clip(i - kick, 0, None)) / fps
    ball = centre + np.column_stack((3. * t, np.zeros(n)))
    waiting = (i >= approach) & (i < kick)
    kicker = ball + np.where(waiting[:, None], [-.8, 0.], [0., .5])
    players = np.stack([kicker, np.tile(centre + [15., 10.], (n, 1)),
                        np.tile(centre + [-20., -10.], (n, 1))], axis=1)
    speed = np.where(waiting, 0., 3.)
    ball[kick:kick + missing], speed[kick:kick + missing] = np.nan, np.nan
    return MatchData(
        frame=np.arange(n, dtype=np.int64), half=np.ones(n, dtype=np.int8), fps=fps,
        pitch_m=(105., 68.), ball_xy_m=ball, ball_observed=np.isfinite(ball).all(axis=1),
        players_xy_m=players, player_observed=np.ones((n, 3), dtype=bool),
        slot_team=np.array(["H", "A", "H"]), ball_speed_mps=speed,
        metadata={"period_start": {"1": policy}}), kick + missing


class HalfStartGateTests(unittest.TestCase):
    """Decision 10: an await_start period stays D until E3 confirms play started (R)."""

    def test_long_stationary_wait_never_opens_on_proximity(self):
        # 80 s of a decisive home player beside the ball: far past the team dwell and the 3 s
        # stop safety valve. Only the R opens the half; the boundary lands on it (Decision 9).
        result = _await("H" * 2000 + "R" + "H" * 40)
        self.assertTrue(np.all(result.labels[:2000] == "D"))
        self.assertEqual(label_transitions(result.labels), [(2000, "D", "H")])
        # A stop before kickoff must not hand control to the safety valve either.
        result = _await("D" * 10 + "H" * 500 + "R" + "H" * 40)
        self.assertEqual(label_transitions(result.labels), [(510, "D", "H")])

    def test_normal_kickoff_opens_on_the_restart_frame(self):
        result = _await("D" * 100 + "R" + "A" * 40)
        self.assertEqual(label_transitions(result.labels), [(100, "D", "A")])
        (log,) = result.diagnostics["period_starts"]
        self.assertEqual(log, {"half": 1, "policy": "await_start", "gated": True,
                               "start_tag": False, "openings": 1, "closings": 0,
                               "first_possession": 100})

    def test_kickoff_with_missing_ball_waits_for_the_signal(self):
        result = _await("H" * 100 + "." * 40 + "R" + "." * 5 + "H" * 30)
        self.assertTrue(np.all(result.labels[:140] == "D"))
        self.assertEqual(label_transitions(result.labels), [(140, "D", "H")])

    def test_evidence_banked_before_kickoff_does_not_count(self):
        # 500 home frames before the R, then fewer than one dwell after it: no possession.
        result = _await("H" * 500 + "R" + "H" * 20)
        self.assertTrue(np.all(result.labels == "D"))

    def test_stray_movement_expires_after_the_evidence_window(self):
        # One live frame, then 160 frames without fresh live evidence: the opening expires, so
        # the later home run cannot confirm. A real kickoff afterwards still works.
        result = _await("H" * 50 + "R" + "." * 160 + "H" * 100)
        self.assertTrue(np.all(result.labels == "D"))
        self.assertEqual(result.diagnostics["period_starts"][0]["closings"], 1)
        result = _await("H" * 50 + "R" + "." * 160 + "H" * 100 + "R" + "H" * 30)
        self.assertEqual(label_transitions(result.labels), [(311, "D", "H")])

    def test_support_from_an_expired_opening_does_not_carry_over(self):
        # 20 home frames while the gate is open, then it expires (frame 151); a later R reopens
        # it. Only the 5 frames after the new opening count, below the 25-frame dwell.
        result = _await("R" + "." * 120 + "H" * 20 + "." * 15 + "R" + "H" * 5)
        self.assertTrue(np.all(result.labels == "D"))

    def test_stop_before_first_possession_closes_the_gate_and_the_valve(self):
        # Without the gate, the stop latch's safety valve would end this stop after 75 frames.
        result = _await("R" + "D" * 5 + "H" * 100)
        self.assertTrue(np.all(result.labels == "D"))
        self.assertEqual(result.diagnostics["period_starts"][0]["closings"], 1)

    def test_a_late_signal_does_not_change_earlier_labels(self):
        # Codex review: labels before a signal must not depend on whether one arrives later.
        silent = _await("H" * 300).labels
        late = _await("H" * 300 + "." * 50 + "R" + "H" * 30).labels
        self.assertTrue(np.all(silent == "D"))
        np.testing.assert_array_equal(late[:300], silent)

    def test_unresolved_period_is_reported_not_hidden(self):
        result = _await("H" * 300)
        self.assertEqual(result.diagnostics["period_starts"][0]["first_possession"], None)

    def test_the_gate_ends_with_the_first_possession(self):
        # After the first possession, ordinary rules apply: the safety valve can end a later stop.
        result = _await("R" + "H" * 40 + "D" * 10 + "A" * 100)
        self.assertEqual([t[1:] for t in label_transitions(result.labels)],
                         [("H", "D"), ("D", "A")])

    def test_periods_follow_their_own_policy(self):
        # Half 1 live at entry, half 2 awaiting: only the second half waits for its signal.
        half = [1] * 40 + [0] * 5 + [2] * 80
        policy = {"1": "live_at_entry", "2": "await_start"}
        result = decode(*evidence_sequence("H" * 40 + "....." + "H" * 40 + "R" + "H" * 39,
                                           half=half, period_start=policy))
        self.assertTrue(np.all(result.labels[:40] == "H"))
        self.assertTrue(np.all(result.labels[45:85] == "D"))
        self.assertTrue(np.all(result.labels[85:] == "H"))
        self.assertEqual([log["policy"] for log in result.diagnostics["period_starts"]],
                         ["live_at_entry", "await_start"])

    def test_missing_policy_means_await_and_unknown_policy_fails(self):
        match, features, priors = evidence_sequence("H" * 60)
        match.metadata = {}
        self.assertTrue(np.all(decode(match, features, priors).labels == "D"))
        match.metadata = {"period_start": {"1": "kickoff_at_frame_100"}}
        with self.assertRaisesRegex(ValueError, "period_start"):
            decode(match, features, priors)
        # Integer or misspelt keys must fail, not silently fall back to await_start.
        for bad in ({1: "live_at_entry"}, {"first": "live_at_entry"}):
            match.metadata = {"period_start": bad}
            with self.subTest(keys=list(bad)), self.assertRaisesRegex(ValueError, "period_start"):
                decode(match, features, priors)

    def test_live_half_reports_its_first_possession(self):
        result = decode(*evidence_sequence("." * 10 + "H" * 30))
        self.assertEqual(result.diagnostics["period_starts"],
                         [{"half": 1, "policy": "live_at_entry", "gated": False,
                           "start_tag": False, "openings": 0, "closings": 0,
                           "first_possession": 10}])

    def test_gate_is_skipped_when_e3_is_disabled(self):
        # Review: with E3 off nothing can confirm a kickoff, so gating would pin the half in D.
        from possession.features import build_features
        match, kick = _kickoff_match(25., 20.)
        features = build_features(match)
        for dead_ball in ({"enabled": False}, {"evidence_weight": 0.}):
            with self.subTest(**dead_ball):
                config = {"dead_ball": dead_ball}
                result = decode(match, features, build_priors(match, features, config), config)
                (log,) = result.diagnostics["period_starts"]
                self.assertEqual((log["policy"], log["gated"]), ("await_start", False))
                self.assertEqual(result.labels[0], "H")

    def test_end_to_end_kickoff_through_e4_and_e3(self):
        # Almaz: without an earlier stop, E3 needs control plus sustained motion. Through the
        # real E4 features and E3 priors, at two frame rates, with and without a missed kick.
        from possession.features import build_features
        for fps in (25., 50.):
            for wait_s, missing_s in ((60., 0.), (0.2, 0.), (20., 1.)):
                with self.subTest(fps=fps, wait_s=wait_s, missing_s=missing_s):
                    match, kick = _kickoff_match(fps, wait_s, missing_s)
                    features = build_features(match)
                    priors = build_priors(match, features)
                    result = decode(match, features, priors)
                    self.assertTrue(np.all(result.labels[:kick] == "D"), "no H before the kick")
                    first = result.diagnostics["period_starts"][0]["first_possession"]
                    self.assertIsNotNone(first, "E3 must confirm a synthetic kickoff")
                    self.assertLessEqual(first - kick, round(.5 * fps))
                    self.assertEqual(result.labels[-1], "H")
        # The same input declared live at entry keeps today's start: H from the first frame.
        match, kick = _kickoff_match(25., 60., policy="live_at_entry")
        features = build_features(match)
        result = decode(match, features, build_priors(match, features))
        self.assertEqual(result.labels[0], "H")

    # Decision 11: no opening before the period's first Kick Off (Start) tag frame.

    def _tagged(self, symbols, start, end, kind="Kick Off (Start)", half=None):
        match, features, priors = evidence_sequence(symbols, period_start=AWAIT, half=half)
        match.events = _start_tag(start, end, kind)
        return decode(match, features, priors)

    def test_live_evidence_before_the_start_tag_cannot_open_the_half(self):
        # Almaz: dribbling the ball to the spot gives generic live evidence before the kickoff.
        # Without a tag it opens the half at frame 50; with one, only the R after its start does.
        symbols = "H" * 50 + "R" + "H" * 100 + "R" + "H" * 30
        self.assertEqual(label_transitions(_await(symbols).labels)[0][0], 50)
        result = self._tagged(symbols, 140, 200)
        self.assertEqual(label_transitions(result.labels), [(151, "D", "H")])
        log = result.diagnostics["period_starts"][0]
        self.assertEqual((log["start_tag"], log["openings"]), (True, 1))

    def test_only_the_start_of_the_tag_matters(self):
        # A tag that ended before the kickoff forbids openings before its start, not after.
        result = self._tagged("H" * 50 + "R" + "H" * 149 + "R" + "H" * 30, 100, 110)
        self.assertEqual(label_transitions(result.labels), [(200, "D", "H")])

    def test_no_start_tag_in_the_period_means_no_restriction(self):
        # Missing tag fails open (today's gate), never a half pinned in D. A tag before the
        # period's graded frames, or of another kind, is not this period's start tag.
        symbols, half = "." * 20 + "H" * 30 + "R" + "H" * 40, [0] * 20 + [1] * 71
        expected = label_transitions(
            decode(*evidence_sequence(symbols, half=half, period_start=AWAIT)).labels)
        self.assertIn((50, "D", "H"), expected)
        for start, end, kind in ((0, 20, "Kick Off (Start)"), (60, 80, "Kick Off (After Goal)"),
                                 (60, 80, "Throw-in")):
            with self.subTest(kind=kind, start=start):
                result = self._tagged(symbols, start, end, kind, half=half)
                self.assertEqual(label_transitions(result.labels), expected)
                self.assertFalse(result.diagnostics["period_starts"][0]["start_tag"])
        # The next period's start tag does not restrict this one.
        result = self._tagged("R" + "H" * 40 + "." * 5 + "R" + "H" * 40, 70, 80,
                              half=[1] * 41 + [0] * 5 + [2] * 41)
        self.assertEqual(result.labels[40], "H")
        self.assertEqual([log["start_tag"] for log in result.diagnostics["period_starts"]],
                         [False, True])
        # Almaz: nor does one in a later disconnected block of the same half number.
        symbols, half = "R" + "H" * 40 + "." * 5 + "R" + "H" * 40, [1] * 41 + [0] * 5 + [1] * 41
        untagged = decode(*evidence_sequence(symbols, half=half, period_start=AWAIT))
        result = self._tagged(symbols, 70, 80, half=half)
        np.testing.assert_array_equal(result.labels[:41], untagged.labels[:41])
        self.assertEqual([log["start_tag"] for log in result.diagnostics["period_starts"]],
                         [False, True])

    def test_live_at_entry_periods_ignore_start_tags(self):
        match, features, priors = evidence_sequence("H" * 40)
        match.events = _start_tag(20, 30)
        self.assertTrue(np.all(decode(match, features, priors).labels == "H"))

    def test_end_to_end_start_tag_cases(self):
        # Almaz's mechanism through real E4 features and E3 priors at 25 and 50 fps: a player
        # dribbles the ball to the spot (5 s, controlled, so E3 reports live motion), it rests
        # 20 s, then the kick. Tag start/end in seconds relative to the kick; None = no tag.
        from possession.features import build_features
        cases = {
            "missing": None,             # fails open: today's early opening, reported
            "starts_in_wait": (-10, None),  # the approach is stale evidence before eligibility
            "ends_before_kick": (-10, -5),  # only the start matters
            "starts_late": (1, None),       # delayed to the tag start, never before it
            "starts_early": (-30, None),    # documented limit: the approach opens it again
        }
        for fps in (25., 50.):
            for name, window in cases.items():
                with self.subTest(fps=fps, case=name):
                    match, kick = _kickoff_match(fps, 20., approach_s=5.)
                    n = len(match.frame)
                    if window is not None:
                        start = max(0, kick + round(window[0] * fps))
                        end = n if window[1] is None else kick + round(window[1] * fps)
                        match.events = _start_tag(start, end)
                    features = build_features(match)
                    result = decode(match, features, build_priors(match, features))
                    (log,) = result.diagnostics["period_starts"]
                    first = log["first_possession"]
                    self.assertEqual(log["start_tag"], window is not None)
                    self.assertIsNotNone(first)
                    if name in ("missing", "starts_early"):
                        self.assertLess(first, kick - round(20 * fps))
                        continue
                    allowed = max(kick, start)
                    self.assertTrue(np.all(result.labels[:allowed] == "D"), "no H before it")
                    self.assertGreaterEqual(first, allowed, "boundary clamped at the opening")
                    self.assertLessEqual(first - allowed, round(.5 * fps))


if __name__ == "__main__":
    unittest.main()
