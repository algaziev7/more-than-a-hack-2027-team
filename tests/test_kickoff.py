"""Invented kickoff episodes; no match assets, annotations or published timings."""

import copy
import unittest
from dataclasses import fields

import numpy as np

from possession.contracts import PriorData
from possession.dead_ball import (
    CONFIRMED_KICKOFF, _kickoff_context, build_priors, summarize_prior_diagnostics,
    summarize_kickoff_diagnostics,
    summarize_kickoff_coverage,
)
from possession.features import build_features
from tests.test_dead_ball import match_input, control_features


def kickoff_match(fps=25.):
    n = int(5 * fps)
    match = match_input(n=n, fps=fps)
    centre = np.asarray(match.pitch_m) / 2
    match.ball_xy_m[:] = centre
    start = int(fps)
    match.ball_xy_m[start:, 0] += np.arange(1, n - start + 1) * 3 / fps
    match.ball_speed_mps[start:] = 3.
    match.events = [{"start_frame": 0, "end_frame": n, "code": "SET PIECES",
                     "tags": {"Type": "Kick Off (Start)", "Team": "N/A"}}]
    match.players_xy_m[:, 0, :] = match.ball_xy_m
    match.players_xy_m[:, 0, 0] += .2
    match.players_xy_m[:, 1, :] = match.ball_xy_m
    match.players_xy_m[:, 1, 0] += 10
    return match


def pulses(match, features=None, config=None):
    prior = build_priors(match, features, config)
    return np.flatnonzero(prior.diagnostic_flags & CONFIRMED_KICKOFF)


def hide(match, indices):
    match.ball_xy_m[indices] = np.nan
    match.ball_observed[indices] = False
    if match.ball_speed_mps is not None:
        match.ball_speed_mps[indices] = np.nan


class KickoffTests(unittest.TestCase):
    def test_long_stationary_wait_never_confirms(self):
        for fps in (25., 50.):
            match = kickoff_match(fps)
            match.ball_xy_m[:] = np.asarray(match.pitch_m) / 2
            match.ball_speed_mps[:] = 0
            self.assertEqual(len(pulses(match, control_features(match))), 0)

    def test_approach_centre_then_settle_is_not_kickoff(self):
        for fps in (25., 50.):
            match = kickoff_match(fps)
            start, end = int(fps), int(3 * fps)
            centre = np.asarray(match.pitch_m) / 2
            match.ball_xy_m[:] = centre
            match.ball_xy_m[:start, 0] -= 6
            match.ball_xy_m[start:end, 0] -= 6 - np.arange(1, end-start+1)*3/fps
            match.ball_speed_mps[:] = 0
            match.ball_speed_mps[start:end] = 3
            self.assertEqual(len(pulses(match, control_features(match))), 0)

    def test_normal_kickoff_through_real_features_at_both_fps(self):
        for fps in (25., 50.):
            match = kickoff_match(fps)
            found = pulses(match, build_features(match))
            self.assertEqual(len(found), 1)
            self.assertGreaterEqual(found[0], int(fps))
            self.assertLess(found[0], int(2*fps))

    def test_control_at_kick_only_suffices(self):
        for fps in (25., 50.):
            match = kickoff_match(fps)
            features = control_features(match, supported=False)
            start = int(fps)
            features.team_evidence[start] = [.9, .1]
            features.team_reliability[start] = .8
            self.assertEqual(len(pulses(match, features)), 1)

    def test_kick_control_remains_valid_during_a_bounded_longer_motion_dwell(self):
        for fps in (25., 50.):
            match = kickoff_match(fps)
            features = control_features(match, supported=False)
            start = int(fps)
            features.team_evidence[start] = [.9, .1]
            features.team_reliability[start] = .8
            found = pulses(match, features, {"dead_ball": {"motion_duration_s": 1.2}})
            np.testing.assert_array_equal(found, [start + int(1.2*fps) - 1])

    def test_remembered_kick_control_expires_and_does_not_leak_to_a_new_episode(self):
        match = kickoff_match()
        features = control_features(match, supported=False)
        features.team_evidence[25] = [.9, .1]
        features.team_reliability[25] = .8
        self.assertEqual(len(pulses(match, features,
                                    {"dead_ball": {"motion_duration_s": 3.2}})), 0)
        # An invented return to the centre, a fresh settlement, then a second
        # departure without fresh control. Rejected return motion cannot carry
        # the first kick's corroboration into the new episode.
        centre = np.asarray(match.pitch_m)/2
        match.ball_xy_m[45:] = centre
        match.ball_speed_mps[45:] = 0
        match.ball_xy_m[75:, 0] += np.arange(1, len(match.frame)-74)*.12
        match.ball_speed_mps[75:] = 3
        self.assertEqual(len(pulses(match, features)), 1)

    def test_control_at_stationary_reception_can_confirm(self):
        for fps in (25., 50.):
            match = kickoff_match(fps)
            reception = int(2*fps)
            match.ball_xy_m[reception:] = match.ball_xy_m[reception-1]
            match.ball_speed_mps[reception:] = 0
            features = control_features(match, supported=False)
            features.team_evidence[reception] = [.9, .1]
            features.team_reliability[reception] = .8
            np.testing.assert_array_equal(pulses(match, features), [reception])

    def test_missing_motion_frames_pause_observed_support(self):
        for fps in (25., 50.):
            for raw_speed in (True, False):
                match = kickoff_match(fps)
                if not raw_speed:
                    match.ball_speed_mps = None
                # Confirmation must include support from before the gaps, rather
                # than merely succeeding on a later uninterrupted run.
                start = int(fps)
                hide(match, [start+4, start+9, start+14])
                found = pulses(match, control_features(match),
                               {"dead_ball": {"motion_duration_s": .6}})
                np.testing.assert_array_equal(found, [start + int(.6*fps) + 2])
                self.assertTrue(match.ball_observed[found[0]])

    def test_long_gap_loses_settlement_and_cannot_open_on_reacquisition(self):
        for fps in (25., 50.):
            match = kickoff_match(fps)
            hide(match, np.arange(int(fps), int(1.5*fps)))
            self.assertEqual(len(pulses(match, control_features(match))), 0)

    def test_no_context_no_control_or_no_settlement_never_confirms(self):
        for variant in ("no_tags", "after_goal", "no_control", "no_settlement", "outside"):
            match = kickoff_match()
            features = control_features(match)
            if variant == "no_tags":
                match.events = []
            elif variant == "after_goal":
                match.events[0]["tags"]["Type"] = "Kick Off (After Goal)"
            elif variant == "no_control":
                features = control_features(match, supported=False)
            elif variant == "no_settlement":
                match.ball_xy_m[:, 0] += np.arange(len(match.frame)) * .12
                match.ball_speed_mps[:] = 3
            else:
                match.ball_xy_m[:, 1] = -1
            self.assertEqual(len(pulses(match, features)), 0, variant)

    def test_context_window_is_half_open_and_cannot_supply_boundary(self):
        match = kickoff_match()
        match.events[0]["end_frame"] = int(match.fps)
        self.assertEqual(len(pulses(match, control_features(match))), 0)
        match = kickoff_match()
        match.events[0]["start_frame"] = int(match.fps)
        self.assertEqual(len(pulses(match, control_features(match))), 0)

    def test_context_clips_windows_to_timeline_without_negative_index_wrap(self):
        cases = (
            (-3, 3, [True, True, True, False, False]),
            (2, 8, [False, False, True, True, True]),
            (-3, 8, [True, True, True, True, True]),
            (-9, -1, [False]*5),
            (5, 9, [False]*5),
            (2, 2, [False]*5),
        )
        for start, end, expected in cases:
            event = {"start_frame": start, "end_frame": end, "code": "SET PIECES",
                     "tags": {"Type": "Kick Off (Start)"}}
            with self.subTest(start=start, end=end):
                np.testing.assert_array_equal(_kickoff_context([event], 5), expected)
                np.testing.assert_array_equal(_kickoff_context([event], 0), [])

    def test_public_match_contract_still_requires_clipped_events(self):
        match = kickoff_match()
        match.events[0]["start_frame"] = -1
        with self.assertRaisesRegex(ValueError, "clipped"):
            build_priors(match)

    def test_short_motion_and_stale_control_do_not_confirm(self):
        match = kickoff_match()
        start = int(match.fps)
        match.ball_xy_m[start+2:] = match.ball_xy_m[start+1]
        match.ball_speed_mps[start+2:] = 0
        self.assertEqual(len(pulses(match, control_features(match))), 0)
        match = kickoff_match()
        features = control_features(match, supported=False)
        features.team_evidence[0] = [.9, .1]
        features.team_reliability[0] = .8
        # Move departure later without introducing a contradictory position jump.
        match.ball_xy_m[:] = np.asarray(match.pitch_m)/2
        match.ball_xy_m[50:, 0] += np.arange(1, len(match.frame)-49)*.12
        match.ball_speed_mps[:50] = 0
        self.assertEqual(len(pulses(match, features)), 0)

    def test_repeated_small_gaps_exhaust_total_motion_budget(self):
        match = kickoff_match()
        start = int(match.fps)
        hide(match, np.arange(start+2, start+20, 3))
        found = pulses(match, control_features(match),
                       {"dead_ball": {"motion_duration_s": 1.}})
        self.assertEqual(len(found), 0)

    def test_all_missing_departure_and_stationary_reacquisition_do_not_confirm(self):
        match = kickoff_match()
        start = int(match.fps)
        hide(match, np.arange(start, len(match.frame)))
        self.assertEqual(len(pulses(match, control_features(match))), 0)
        match = kickoff_match()
        hide(match, [start, start+1])
        match.ball_xy_m[start+2:] = match.ball_xy_m[start+2]
        match.ball_speed_mps[start+2:] = 0
        self.assertEqual(len(pulses(match, control_features(match))), 0)

    def test_late_control_after_confirmed_stop_cannot_issue_opening(self):
        match = kickoff_match()
        reception = int(2*match.fps)
        match.ball_xy_m[reception:] = match.ball_xy_m[reception-1]
        match.ball_speed_mps[reception:] = 0
        features = control_features(match, supported=False)
        late = reception + int(.8*match.fps)
        features.team_evidence[late:] = [.9, .1]
        features.team_reliability[late:] = .8
        self.assertEqual(len(pulses(match, features)), 0)

    def test_mirroring_and_swapping_teams_preserve_confirmation(self):
        match = kickoff_match()
        expected = pulses(match, build_features(match))
        match.ball_xy_m[:] = np.asarray(match.pitch_m) - match.ball_xy_m
        match.players_xy_m[:] = np.asarray(match.pitch_m) - match.players_xy_m
        match.slot_team[:] = ["A", "H"]
        np.testing.assert_array_equal(pulses(match, build_features(match)), expected)

    def test_half_reset_and_rejected_observation_drop_episode(self):
        for variant in ("half", "rejected", "cross_gap_jump"):
            match = kickoff_match()
            start = int(match.fps)
            if variant == "half":
                match.half[start:] = 2
            elif variant == "rejected":
                match.ball_speed_mps[start] = 100
            else:
                hide(match, [start])
                match.ball_xy_m[start+1:, 0] += 20
            self.assertEqual(len(pulses(match, control_features(match))), 0, variant)

    def test_disabled_and_zero_weight_emit_no_kickoff(self):
        match = kickoff_match()
        for settings in ({"enabled": False}, {"evidence_weight": 0}):
            self.assertEqual(len(pulses(match, control_features(match),
                                        {"dead_ball": settings})), 0)

    def test_generic_priors_and_inputs_unchanged_by_kickoff_context(self):
        match = kickoff_match()
        features = control_features(match)
        before = copy.deepcopy(match)
        left = build_priors(match, features)
        # Generic set-piece semantics are identical for this alternate tag type.
        match.events[0]["tags"]["Type"] = "Throw-in"
        right = build_priors(match, features)
        for field in fields(PriorData):
            if field.name != "diagnostic_flags":
                np.testing.assert_array_equal(getattr(left, field.name), getattr(right, field.name))
        np.testing.assert_array_equal(left.diagnostic_flags & ~CONFIRMED_KICKOFF,
                                      right.diagnostic_flags)
        np.testing.assert_array_equal(match.ball_xy_m, before.ball_xy_m)
        self.assertEqual(len(pulses(before, features)), 1)
        report = summarize_prior_diagnostics(before, features)
        self.assertEqual(report["event_counts"]["confirmed_kickoffs"], 1)

    def test_duplicate_and_normalised_context_does_not_multiply_pulses(self):
        match = kickoff_match()
        match.events *= 2
        match.events[0]["tags"] = {" TYPE ": "  KICK OFF (START) "}
        self.assertEqual(len(pulses(match, control_features(match))), 1)

    def test_settings_validation(self):
        match = kickoff_match()
        for options in ({"kickoff_centre_radius_m": 0}, {"kickoff_departure_m": .5},
                        {"kickoff_control_window_s": 0}, {"kickoff_max_missing_gap_s": -.1},
                        {"kickoff_departure_m": float("nan")}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                build_priors(match, config={"dead_ball": options})

    def test_diagnostic_stages_use_actual_detector_gates(self):
        expected = (
            "NO_START_TAG_CONTEXT", "NO_USABLE_BALL_IN_CONTEXT",
            "NO_CONFIRMED_CENTRE_SETTLEMENT", "NO_SUSTAINED_MOTION_AFTER_SETTLEMENT",
            "NO_CONFIRMED_DEPARTURE", "NO_ENDPOINT_CONTROL", "ONE_CONFIRMATION",
        )
        for stage in expected:
            match = kickoff_match()
            features = control_features(match)
            if stage == "NO_START_TAG_CONTEXT":
                match.events = []
            elif stage == "NO_USABLE_BALL_IN_CONTEXT":
                hide(match, slice(None))
            elif stage == "NO_CONFIRMED_CENTRE_SETTLEMENT":
                match.ball_xy_m[:, 0] += 5
            elif stage == "NO_SUSTAINED_MOTION_AFTER_SETTLEMENT":
                match.ball_xy_m[:] = np.asarray(match.pitch_m)/2
                match.ball_speed_mps[:] = 0
            elif stage == "NO_CONFIRMED_DEPARTURE":
                start = int(match.fps)
                match.ball_xy_m[start:, 0] = match.pitch_m[0]/2 + (
                    .3 * np.where(np.arange(len(match.frame)-start) % 2, 1, -1))
            elif stage == "NO_ENDPOINT_CONTROL":
                features = control_features(match, supported=False)
            with self.subTest(stage=stage):
                report = summarize_kickoff_diagnostics(match, features)
                self.assertEqual(report["periods"]["1"]["stage"], stage)

    def test_diagnostics_preserve_every_prior_and_are_json_serializable(self):
        import json
        match = kickoff_match()
        features = control_features(match)
        before = build_priors(match, features)
        report = summarize_kickoff_diagnostics(match, features)
        after = build_priors(match, features)
        for field in fields(PriorData):
            np.testing.assert_array_equal(getattr(before, field.name), getattr(after, field.name))
        json.dumps(report, allow_nan=False)
        self.assertEqual(report["periods"]["1"]["confirmed_kickoffs"], 1)

    def test_diagnostic_settlement_details_distinguish_missing_evidence(self):
        details = (
            "SLOW_CENTRE_SEEN_BEFORE_TAG", "NO_CENTRE_OBSERVATION_IN_TAG",
            "NO_USABLE_CENTRE_OBSERVATION", "CENTRE_OBSERVATIONS_FAIL_STILLNESS",
            "FRAGMENTED_SETTLEMENT_SUPPORT",
        )
        for detail in details:
            match = kickoff_match()
            centre = np.asarray(match.pitch_m)/2
            if detail == "SLOW_CENTRE_SEEN_BEFORE_TAG":
                match.events[0]["start_frame"] = int(match.fps)
            elif detail == "NO_CENTRE_OBSERVATION_IN_TAG":
                match.ball_xy_m[:, 0] += 5
            elif detail == "NO_USABLE_CENTRE_OBSERVATION":
                match.ball_xy_m[:] = centre
                match.ball_speed_mps[:] = 100
                match.ball_xy_m[-20:, 0] += 5
                match.ball_speed_mps[-20:] = 0
            elif detail == "CENTRE_OBSERVATIONS_FAIL_STILLNESS":
                match.ball_xy_m[:, 0] = centre[0] + np.where(
                    np.arange(len(match.frame)) % 2, .2, -.2)
                match.ball_speed_mps[:] = 3
            else:
                match.ball_xy_m[:] = centre
                moving = np.arange(len(match.frame)) % 7 >= 5
                match.ball_xy_m[moving, 0] += .3
                match.ball_speed_mps[:] = 0
                match.ball_speed_mps[moving] = 3
            features = control_features(match)
            with self.subTest(detail=detail):
                report = summarize_kickoff_diagnostics(match, features)
                self.assertEqual(report["periods"]["1"]["settlement_detail"], detail)

    def test_diagnostic_lookback_never_supplies_detector_evidence_or_crosses_halves(self):
        match = kickoff_match()
        start = int(match.fps)
        match.events[0]["start_frame"] = start
        features = control_features(match)
        report = summarize_kickoff_diagnostics(match, features)
        self.assertEqual(report["periods"]["1"]["confirmed_kickoffs"], 0)
        self.assertGreater(report["periods"]["1"]["slow_centre_before_tag_frames"], 0)
        self.assertEqual(len(pulses(match, features)), 0)
        match.half[start:] = 2
        report = summarize_kickoff_diagnostics(match, features)
        self.assertEqual(report["periods"]["2"]["slow_centre_before_tag_frames"], 0)

    def test_coverage_check_finds_settlement_before_tag_without_changing_inference(self):
        match = kickoff_match()
        check = int(match.fps)
        match.events[0]["start_frame"] = check
        features = control_features(match)
        before = build_priors(match, features)
        report = summarize_kickoff_coverage(match, check)
        self.assertEqual(report["tag_coverage"], "TAG_COVERS_CHECK")
        self.assertEqual(report["pre_tag_centre"], "SLOW_CENTRE_OBSERVED_BEFORE_TAG")
        self.assertEqual(report["window_observation"], "CENTRE_OBSERVED_IN_CHECK_WINDOW")
        after = build_priors(match, features)
        for field in fields(PriorData):
            np.testing.assert_array_equal(getattr(before, field.name), getattr(after, field.name))
        self.assertEqual(len(pulses(match, features)), 0)

    def test_coverage_check_distinguishes_occlusion_and_observed_ball_away_from_centre(self):
        match = kickoff_match()
        check = int(match.fps)
        hide(match, [check])
        report = summarize_kickoff_coverage(match, check)
        self.assertEqual(report["check_observation"], "BALL_MISSING_AT_CHECK")
        self.assertEqual(report["window_observation"], "CENTRE_OBSERVED_IN_CHECK_WINDOW")
        hide(match, slice(None))
        report = summarize_kickoff_coverage(match, check)
        self.assertEqual(report["window_observation"], "BALL_MISSING_THROUGH_CHECK_WINDOW")
        match = kickoff_match()
        match.ball_xy_m[:, 0] += 5
        report = summarize_kickoff_coverage(match, check)
        self.assertEqual(report["pre_tag_centre"], "NO_CENTRE_OBSERVATION_BEFORE_TAG")
        self.assertEqual(report["window_observation"],
                         "BALL_OBSERVED_AWAY_FROM_CENTRE_IN_CHECK_WINDOW")

    def test_coverage_check_does_not_borrow_observations_across_half_boundary(self):
        match = kickoff_match()
        start = int(match.fps)
        match.half[start:] = 2
        match.ball_xy_m[start:, 0] += 5
        match.events[0]["start_frame"] = start+1
        report = summarize_kickoff_coverage(match, start+2)
        self.assertEqual(report["pre_tag_centre"], "NO_CENTRE_OBSERVATION_BEFORE_TAG")
        self.assertEqual(report["window_observation"],
                         "BALL_OBSERVED_AWAY_FROM_CENTRE_IN_CHECK_WINDOW")

    def test_coverage_check_rejects_invalid_checks_and_handles_missing_tag(self):
        match = kickoff_match()
        for check in (-1, len(match.frame), True, 1.5):
            with self.subTest(check=check), self.assertRaises(ValueError):
                summarize_kickoff_coverage(match, check)
        match.half[0] = 0
        with self.assertRaises(ValueError):
            summarize_kickoff_coverage(match, 0)
        match.events = []
        report = summarize_kickoff_coverage(match, int(match.fps))
        self.assertEqual(report["tag_coverage"], "TAG_MISSES_CHECK")
        self.assertEqual(report["pre_tag_centre"], "CHECK_NOT_IN_START_TAG")

    def test_diagnostics_report_blocked_stop_and_disabled_inference(self):
        match = kickoff_match()
        reception = int(2*match.fps)
        match.ball_xy_m[reception:] = match.ball_xy_m[reception-1]
        match.ball_speed_mps[reception:] = 0
        features = control_features(match, supported=False)
        late = reception + int(.8*match.fps)
        features.team_evidence[late:] = [.9, .1]
        features.team_reliability[late:] = .8
        report = summarize_kickoff_diagnostics(match, features)
        self.assertEqual(report["periods"]["1"]["stage"], "BLOCKED_BY_CONFIRMED_STOP")
        disabled = summarize_kickoff_diagnostics(match, features, {"dead_ball": {"enabled": False}})
        self.assertEqual(disabled, {"enabled": False, "periods": {}})

    def test_local_diagnostic_command_saves_synthetic_report_without_printing_it(self):
        import contextlib
        import io
        import json
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from scripts import diagnose_kickoff as cli

        match = kickoff_match()
        console = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cli, "ROOT", Path(directory)), \
                    patch.object(cli, "load_config", return_value={}), \
                    patch.object(cli, "load_match", return_value=match), \
                    contextlib.redirect_stdout(console):
                self.assertEqual(cli.main([]), 0)
                self.assertEqual(cli.main(["--check-frame", str(int(match.fps))]), 0)
            report = json.loads((Path(directory)/"runs"/"kickoff-gates.json").read_text())
            self.assertEqual(report["periods"]["1"]["stage"], "ONE_CONFIRMATION")
            summary = (Path(directory)/"runs"/"kickoff-summary.txt").read_text()
            self.assertTrue(summary.startswith("Half 1: ONE_CONFIRMATION\n"))
            self.assertIn("tag_coverage: TAG_COVERS_CHECK", summary)
            self.assertNotIn("counts", summary)
            self.assertIn("coverage_check", report)
        self.assertNotIn("ONE_CONFIRMATION", console.getvalue())
        self.assertNotIn("confirmed_kickoffs", console.getvalue())


if __name__ == "__main__":
    unittest.main()
