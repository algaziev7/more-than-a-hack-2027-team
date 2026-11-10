"""Invented scenarios for stoppage priors; no competition assets or GT."""

import copy
from dataclasses import fields, replace
import math
import unittest
from unittest.mock import patch

import numpy as np

from possession.contracts import FeatureData, MatchData, PriorData
from possession.dead_ball import (
    CONFIRMED_RESTART, LIVE_MOTION, STOP_OUTSIDE_AND_STILL, STOP_TAG_AND_STILL,
    UNUSABLE_BALL, DeadBallConfig, build_priors, summarize_prior_diagnostics,
)
from possession.features import build_features
from possession.tagging import UNKNOWN_TEAM, build_tagging_priors


def match_input(n=12, fps=10., outside=False, tagged=False):
    ball = np.tile([-.75 if outside else 10., 20.], (n, 1))
    return MatchData(
        frame=np.arange(n, dtype=np.int64), half=np.ones(n, dtype=np.int8),
        fps=fps, pitch_m=(105.3, 68.), ball_xy_m=ball,
        ball_observed=np.ones(n, dtype=bool),
        players_xy_m=np.tile([[[10., 20.], [15., 20.]]], (n, 1, 1)),
        player_observed=np.ones((n, 2), dtype=bool), slot_team=np.array(["H", "A"]),
        ball_speed_mps=np.zeros(n),
        events=([{"start_frame": 0, "end_frame": n, "code": "SET PIECES",
                  "tags": {"Team": "N/A", "Type": "Throw-in"}}] if tagged and n else []),
    )


def control_features(match, supported=True):
    n = len(match.frame)
    return FeatureData(
        match.frame.copy(), {}, {},
        np.tile([.9, .1] if supported else [.5, .5], (n, 1)),
        np.full(n, .8 if supported else 0.),
    )


def motion_after_stop():
    match = match_input(n=18)
    match.events = [{"start_frame": 0, "end_frame": 6, "code": "SET PIECES",
                     "tags": {"Team": "N/A"}}]
    match.ball_xy_m[6:, 0] += np.arange(1, 13) * .3
    match.ball_speed_mps[6:] = 3.
    return match


def assert_neutral(priors, selection=slice(None)):
    np.testing.assert_array_equal(priors.dead_evidence[selection], .5)
    np.testing.assert_array_equal(priors.dead_reliability[selection], 0.)


class DeadBallTests(unittest.TestCase):
    def test_stationary_ball_alone_is_not_a_stoppage(self):
        assert_neutral(build_priors(match_input()))

    def test_tag_alone_with_missing_ball_does_not_declare_dead(self):
        match = match_input(tagged=True)
        match.ball_xy_m[:] = np.nan
        match.ball_observed[:] = False
        match.ball_speed_mps[:] = np.nan
        priors = build_priors(match)
        assert_neutral(priors)
        np.testing.assert_array_equal(priors.restart_evidence, .5)
        self.assertTrue(np.all(priors.diagnostic_flags & UNUSABLE_BALL))

    def test_tag_and_sustained_stillness_support_a_stoppage(self):
        priors = build_priors(match_input(tagged=True))
        assert_neutral(priors, slice(0, 5))
        np.testing.assert_array_equal(priors.dead_evidence[5:], .9)
        np.testing.assert_array_equal(priors.dead_reliability[5:], .5)
        self.assertTrue(np.all(priors.diagnostic_flags[5:] & STOP_TAG_AND_STILL))
        # Throw-in team remains unknown even after stop confirmation.
        np.testing.assert_array_equal(priors.tag_team_reliability, 0.)
        self.assertTrue(np.all(priors.diagnostic_flags & UNKNOWN_TEAM))

    def test_sustained_outside_still_ball_works_without_tags(self):
        priors = build_priors(match_input(outside=True))
        np.testing.assert_array_equal(priors.dead_evidence[5:], .9)
        self.assertTrue(np.all(priors.diagnostic_flags[5:] & STOP_OUTSIDE_AND_STILL))
        np.testing.assert_array_equal(priors.restart_evidence, 0.)

    def test_short_false_stop_is_not_confirmed(self):
        match = match_input()
        match.events = [{"start_frame": 1, "end_frame": 5, "code": "SET PIECES", "tags": {}}]
        assert_neutral(build_priors(match))

    def test_tag_end_does_not_extend_dead_evidence(self):
        match = match_input(tagged=True)
        match.events[0]["end_frame"] = 6
        priors = build_priors(match)
        self.assertEqual(priors.dead_evidence[5], .9)
        assert_neutral(priors, slice(6, None))

    def test_restart_requires_motion_and_emits_one_pulse(self):
        priors = build_priors(motion_after_stop())
        self.assertEqual(priors.dead_evidence[5], .9)
        assert_neutral(priors, slice(6, 7))
        np.testing.assert_array_equal(priors.dead_evidence[7:], .1)
        pulses = np.flatnonzero(priors.diagnostic_flags & CONFIRMED_RESTART)
        np.testing.assert_array_equal(pulses, [7])
        self.assertEqual(priors.restart_evidence[7], .75)
        self.assertTrue(np.all(priors.diagnostic_flags[7:] & LIVE_MOTION))

    def test_moving_ball_without_stop_or_control_is_neutral(self):
        match = match_input()
        match.ball_xy_m[:, 0] += np.arange(12) * .3
        match.ball_speed_mps[:] = 3.
        assert_neutral(build_priors(match))
        assert_neutral(build_priors(match, control_features(match, supported=False)))

    def test_motion_pause_does_not_repeat_restart_without_a_new_stop(self):
        match = motion_after_stop()
        match.ball_xy_m[8:10] = match.ball_xy_m[7]
        match.ball_speed_mps[8:10] = 0.
        match.ball_xy_m[10:, 0] = match.ball_xy_m[7, 0] + np.arange(1, 9) * .3
        priors = build_priors(match)
        np.testing.assert_array_equal(np.flatnonzero(priors.diagnostic_flags & CONFIRMED_RESTART), [7])

    def test_new_confirmed_stop_can_produce_a_second_restart(self):
        match = match_input(n=20)
        match.events = [
            {"start_frame": 0, "end_frame": 6, "code": "SET PIECES", "tags": {}},
            {"start_frame": 8, "end_frame": 15, "code": "SET PIECES", "tags": {}},
        ]
        match.ball_xy_m[6:, 0] = 10.6
        match.ball_xy_m[6, 0] = 10.3
        match.ball_speed_mps[6:8] = 3.
        match.ball_xy_m[15:, 0] += np.arange(1, 6) * .3
        match.ball_speed_mps[15:] = 3.
        priors = build_priors(match)
        np.testing.assert_array_equal(np.flatnonzero(priors.diagnostic_flags & CONFIRMED_RESTART), [7, 16])

    def test_motion_plus_beks_control_supports_live_without_inventing_restart(self):
        match = match_input()
        match.ball_xy_m[:, 0] += np.arange(12) * .3
        match.ball_speed_mps[:] = 3.
        priors = build_priors(match, control_features(match))
        np.testing.assert_array_equal(priors.dead_evidence[1:], .1)
        np.testing.assert_array_equal(priors.restart_evidence, 0.)
        self.assertFalse(np.any(priors.diagnostic_flags & CONFIRMED_RESTART))

    def test_outside_motion_is_not_a_live_restart(self):
        match = motion_after_stop()
        match.ball_xy_m[:, 0] = -2.
        match.ball_xy_m[6:, 1] += np.arange(1, 13) * .3
        priors = build_priors(match, control_features(match))
        self.assertFalse(np.any(priors.diagnostic_flags & LIVE_MOTION))
        self.assertFalse(np.any(priors.diagnostic_flags & CONFIRMED_RESTART))

    def test_restart_context_expires(self):
        match = motion_after_stop()
        # Pause without supporting tag long enough for previous stop to expire.
        match.ball_xy_m[6:10] = match.ball_xy_m[5]
        match.ball_speed_mps[6:10] = 0.
        match.ball_xy_m[10:, 0] = 10. + np.arange(1, 9) * .3
        priors = build_priors(match, config={"dead_ball": {"restart_context_s": .3}})
        assert_neutral(priors, slice(6, None))
        self.assertFalse(np.any(priors.diagnostic_flags & CONFIRMED_RESTART))

    def test_missing_observations_reset_stop_confirmation(self):
        match = match_input(tagged=True)
        match.ball_xy_m[3] = np.nan
        match.ball_observed[3] = False
        match.ball_speed_mps[3] = np.nan
        priors = build_priors(match)
        assert_neutral(priors, slice(0, 9))
        np.testing.assert_array_equal(priors.dead_evidence[9:], .9)

    def test_gap_cannot_connect_old_stop_to_restart(self):
        match = motion_after_stop()
        match.ball_xy_m[6] = np.nan
        match.ball_observed[6] = False
        match.ball_speed_mps[6] = np.nan
        priors = build_priors(match)
        assert_neutral(priors, slice(6, None))
        self.assertFalse(np.any(priors.diagnostic_flags & CONFIRMED_RESTART))

    def test_half_change_resets_context_even_without_excluded_frames(self):
        match = motion_after_stop()
        match.half[6:] = 2
        priors = build_priors(match)
        assert_neutral(priors, slice(6, None))
        self.assertFalse(np.any(priors.diagnostic_flags & CONFIRMED_RESTART))

    def test_second_half_is_independent_of_first(self):
        original = motion_after_stop()
        original.half[6:8] = 0
        original.half[8:] = 2
        changed = copy.deepcopy(original)
        changed.ball_xy_m[:6] = [100., 60.]
        changed.events = []
        left, right = build_priors(original), build_priors(changed)
        for field in fields(PriorData):
            np.testing.assert_array_equal(getattr(left, field.name)[8:],
                                          getattr(right, field.name)[8:])

    def test_excluded_frames_are_neutral_even_when_tagged(self):
        match = match_input(tagged=True)
        match.half[:] = 0
        priors = build_priors(match)
        assert_neutral(priors)
        np.testing.assert_array_equal(priors.tag_team_evidence, .5)
        for name in ("tag_team_reliability", "restart_evidence", "diagnostic_flags"):
            np.testing.assert_array_equal(getattr(priors, name), 0)

    def test_derive_speed_only_from_adjacent_observations(self):
        match = replace(match_input(tagged=True), ball_speed_mps=None)
        priors = build_priors(match)
        assert_neutral(priors, slice(0, 6))  # Frame 0 has no speed.
        np.testing.assert_array_equal(priors.dead_evidence[6:], .9)
        self.assertTrue(priors.diagnostic_flags[0] & UNUSABLE_BALL)

    def test_disagreement_between_speed_and_positions_is_not_stop_or_motion(self):
        match = match_input(tagged=True)
        match.ball_speed_mps[:] = 3.
        priors = build_priors(match, control_features(match))
        assert_neutral(priors, slice(1, None))
        self.assertFalse(np.any(priors.diagnostic_flags & CONFIRMED_RESTART))

    def test_jump_and_implausible_coordinates_cannot_confirm_a_stop(self):
        for bad in ([-5., 20.], [1e200, 20.]):
            match = match_input(tagged=True)
            match.ball_xy_m[5] = bad
            priors = build_priors(match)
            self.assertTrue(priors.diagnostic_flags[5] & UNUSABLE_BALL)
            assert_neutral(priors, slice(0, 11))

    def test_supplied_extreme_speed_is_unusable(self):
        match = match_input(tagged=True)
        match.ball_speed_mps[:] = 100.
        priors = build_priors(match)
        assert_neutral(priors)
        self.assertTrue(np.all(priors.diagnostic_flags & UNUSABLE_BALL))

    def test_config_duration_uses_ceiling_and_is_fps_aware(self):
        for fps in (10., 25., 50.):
            match = match_input(n=40, fps=fps, tagged=True)
            seconds = .25
            first = math.ceil(seconds * fps) - 1
            priors = build_priors(match, config={"dead_ball": {"stop_duration_s": seconds}})
            assert_neutral(priors, slice(0, first))
            self.assertEqual(priors.dead_evidence[first], .9)

    def test_no_input_mutation_and_deterministic_independent_outputs(self):
        match = motion_after_stop()
        features = control_features(match)
        before, before_features = copy.deepcopy(match), copy.deepcopy(features)
        config = {"dead_ball": {"evidence_weight": .3}, "schema_version": 1}
        prior_config = copy.deepcopy(config)
        left, right = build_priors(match, features, config), build_priors(match, features, config)
        for field in fields(PriorData):
            np.testing.assert_array_equal(getattr(left, field.name), getattr(right, field.name))
            self.assertFalse(np.shares_memory(getattr(left, field.name), getattr(right, field.name)))
        np.testing.assert_array_equal(match.ball_xy_m, before.ball_xy_m)
        np.testing.assert_array_equal(match.half, before.half)
        np.testing.assert_array_equal(features.team_evidence, before_features.team_evidence)
        self.assertEqual(match.events, before.events)
        self.assertEqual(config, prior_config)

    def test_disabled_detector_preserves_tagging_inside_halves(self):
        match = match_input(tagged=True)
        expected = build_tagging_priors(match.events, len(match.frame))
        for options in ({"enabled": False}, {"evidence_weight": 0}):
            priors = build_priors(match, config={"dead_ball": options})
            for field in fields(PriorData):
                np.testing.assert_array_equal(getattr(priors, field.name), getattr(expected, field.name))

    def test_disabled_restart_tag_does_not_create_a_tagged_stop(self):
        priors = build_priors(match_input(tagged=True), config={"tagging": {"restart_strength": 0}})
        assert_neutral(priors)

    def test_tagging_semantics_and_weights_are_preserved(self):
        match = match_input()
        match.events = [{"start_frame": 1, "end_frame": 5, "code": "BUILD UP",
                         "tags": {"Team": "Barcelona"}}]
        priors = build_priors(match, config={"tagging": {"team_reliability": .3}})
        np.testing.assert_array_equal(priors.tag_team_evidence[1:5], [[1., 0.]] * 4)
        np.testing.assert_array_equal(priors.tag_team_reliability[1:5], .3)
        assert_neutral(priors)

    def test_team_swap_and_pitch_mirror_preserve_dead_live_evidence(self):
        match = motion_after_stop()
        features = control_features(match)
        changed = copy.deepcopy(match)
        changed.ball_xy_m[:, 0] = match.pitch_m[0] - changed.ball_xy_m[:, 0]
        changed.slot_team = np.where(changed.slot_team == "H", "A", "H")
        swapped = replace(features, team_evidence=features.team_evidence[:, ::-1].copy())
        left, right = build_priors(match, features), build_priors(changed, swapped)
        for name in ("dead_evidence", "dead_reliability", "restart_evidence", "diagnostic_flags"):
            np.testing.assert_array_equal(getattr(left, name), getattr(right, name))

    def test_empty_match_and_single_frame(self):
        empty = build_priors(match_input(n=0))
        self.assertEqual(empty.tag_team_evidence.shape, (0, 2))
        self.assertEqual(empty.dead_evidence.shape, (0,))
        assert_neutral(build_priors(match_input(n=1, tagged=True)))

    def test_bad_config_and_invalid_thresholds_fail_clearly(self):
        for config in ([], {"dead_ball": None}, {"dead_ball": {"typo": 1}},
                       {"tagging": {"typo": 1}}, {"tagging": []}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                build_priors(match_input(), config=config)
        for name, value in (("enabled", 1), ("stationary_speed_mps", True),
                            ("stop_duration_s", float("nan")), ("motion_duration_s", 0),
                            ("restart_context_s", -1), ("moving_speed_mps", .1),
                            ("max_ball_speed_mps", 1), ("outside_margin_m", 0),
                            ("position_margin_m", .1), ("evidence_weight", 1.1)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                DeadBallConfig(**{name: value})

    def test_invalid_or_misaligned_shared_inputs_are_rejected(self):
        match = match_input()
        with self.assertRaises(TypeError):
            build_priors({})
        with self.assertRaises(TypeError):
            build_priors(match, features={})
        with self.assertRaises(ValueError):
            build_priors(match, control_features(match_input(n=10)))
        features = control_features(match)
        features.team_reliability[0] = np.nan
        with self.assertRaises(ValueError):
            build_priors(match, features)
        match.ball_observed[0] = False
        with self.assertRaises(ValueError):
            build_priors(match)

    def test_builder_does_not_open_files(self):
        match = motion_after_stop()
        with patch("builtins.open", side_effect=AssertionError("unexpected file access")):
            self.assertIsInstance(build_priors(match), PriorData)

    def test_full_length_synthetic_output_is_valid(self):
        priors = build_priors(match_input(n=199319))
        self.assertIsInstance(priors, PriorData)
        self.assertEqual(priors.tag_team_evidence.shape, (199319, 2))
        assert_neutral(priors)


class MissingGapTests(unittest.TestCase):
    config = {"dead_ball": {"max_missing_gap_s": .2}}

    @staticmethod
    def missing(match, frames):
        match.ball_xy_m[frames] = np.nan
        match.ball_observed[frames] = False
        match.ball_speed_mps[frames] = np.nan

    def test_short_gap_preserves_support_but_contributes_no_evidence(self):
        match = match_input(tagged=True)
        self.missing(match, [3, 4])
        prior = build_priors(match, config=self.config)
        assert_neutral(prior, slice(0, 7))
        self.assertEqual(prior.dead_evidence[7], .9)  # Six observed candidates.
        assert_neutral(build_priors(match), slice(0, 10))

    def test_repeated_short_gaps_cannot_bank_unbounded_support(self):
        match = match_input(n=30, tagged=True)
        self.missing(match, list(range(1, 30, 2)))
        assert_neutral(build_priors(match, config=self.config))

    def test_long_gap_resets_pending_and_confirmed_context(self):
        match = motion_after_stop()
        self.missing(match, [6, 7, 8])
        prior = build_priors(match, config=self.config)
        assert_neutral(prior, slice(6, None))
        self.assertFalse(np.any(prior.diagnostic_flags & CONFIRMED_RESTART))

    def test_short_gap_allows_one_restart_after_fresh_motion_confirmation(self):
        match = motion_after_stop()
        self.missing(match, [6])
        prior = build_priors(match, config=self.config)
        assert_neutral(prior, slice(6, 8))
        np.testing.assert_array_equal(np.flatnonzero(prior.diagnostic_flags & CONFIRMED_RESTART), [8])

    def test_missing_ball_alone_never_confirms_stop(self):
        match = match_input(tagged=True)
        self.missing(match, list(range(2, 12)))
        assert_neutral(build_priors(match, config=self.config))

    def test_relocated_still_ball_does_not_join_old_stop_support(self):
        match = match_input(tagged=True)
        self.missing(match, [3])
        match.ball_xy_m[4:, 0] += 2.
        prior = build_priors(match, config=self.config)
        assert_neutral(prior, slice(0, 9))
        self.assertEqual(prior.dead_evidence[9], .9)

    def test_rejected_observed_ball_is_not_treated_as_occlusion(self):
        match = match_input(tagged=True)
        match.ball_speed_mps[3] = 100.
        prior = build_priors(match, config=self.config)
        assert_neutral(prior, slice(0, 9))
        self.assertEqual(prior.dead_evidence[9], .9)

    def test_half_boundary_discards_retained_stop(self):
        match = motion_after_stop()
        self.missing(match, [6])
        match.half[7:] = 2
        assert_neutral(build_priors(match, config=self.config), slice(6, None))

    def test_gap_budget_uses_fps_and_never_rounds_up(self):
        for fps in (10., 25., 50.):
            match = match_input(n=80, fps=fps, tagged=True)
            budget = math.floor(.2 * fps)
            self.missing(match, list(range(2, 2 + budget)))
            first = math.ceil(.6 * fps) + budget - 1
            prior = build_priors(match, config=self.config)
            assert_neutral(prior, slice(0, first))
            self.assertEqual(prior.dead_evidence[first], .9)
        match = match_input(tagged=True)
        self.missing(match, [3])
        prior = build_priors(match, config={"dead_ball": {"max_missing_gap_s": .09}})
        np.testing.assert_array_equal(prior.dead_evidence, build_priors(match).dead_evidence)

    def test_budget_validation_and_diagnostic_partition(self):
        for value in (-.1, .7, True, float("nan")):
            with self.assertRaises(ValueError):
                DeadBallConfig(max_missing_gap_s=value)
        match = match_input(tagged=True)
        self.missing(match, [3, 4])
        report = summarize_prior_diagnostics(match, build_features(match), self.config)
        self.assertEqual(report["frame_counts"]["confirmed_stop_frames"], 5)
        self.assertEqual(report["event_counts"]["confirmed_stop_runs"], 1)
        self.assertEqual(report["event_counts"]["pending_stop_runs_reset_by_unusable_ball"], 0)
        self.assertEqual(report["without_control_comparison"]["changed_stop_frames"], 0)


class PriorDiagnosticsTests(unittest.TestCase):
    def test_attrition_partition_and_common_denominator(self):
        match = match_input(tagged=True)
        report = summarize_prior_diagnostics(match)
        counts = report["frame_counts"]
        self.assertEqual(counts["graded_frames"], 12)
        self.assertEqual(counts["ball_usable_frames"], 12)
        self.assertEqual(counts["confirmed_stop_frames"], 7)
        self.assertEqual(counts["usable_without_confirmed_stop_frames"], 5)
        self.assertEqual(counts["stop_candidate_below_dwell_frames"], 5)
        self.assertEqual(report["event_counts"]["confirmed_stop_runs"], 1)
        self.assertEqual(report["graded_frame_shares"]["confirmed_stop_frames"], 7 / 12)
        self.assertEqual(counts["ball_usable_frames"], sum(counts[name] for name in (
            "usable_not_still_frames", "still_without_stop_context_frames",
            "stop_candidate_below_dwell_frames", "confirmed_stop_frames")))

    def test_missing_and_rejected_observations_reset_incomplete_runs(self):
        match = match_input(tagged=True)
        match.ball_xy_m[3] = np.nan
        match.ball_observed[3] = False
        match.ball_speed_mps[3] = np.nan
        match.ball_speed_mps[7] = 100.
        report = summarize_prior_diagnostics(match)
        counts = report["frame_counts"]
        self.assertEqual(counts["ball_missing_frames"], 1)
        self.assertEqual(counts["ball_observed_unusable_frames"], 1)
        self.assertEqual(counts["confirmed_stop_frames"], 0)
        self.assertEqual(report["event_counts"]["pending_stop_runs_reset_by_unusable_ball"], 2)
        self.assertEqual(counts["ball_usable_frames"], 10)

    def test_lost_support_and_half_resets_are_separate(self):
        match = match_input(n=10)
        match.half[6:] = 2
        match.events = [
            {"start_frame": 0, "end_frame": 2, "code": "SET PIECES", "tags": {}},
            {"start_frame": 4, "end_frame": 10, "code": "SET PIECES", "tags": {}},
        ]
        events = summarize_prior_diagnostics(match)["event_counts"]
        self.assertEqual(events["pending_stop_runs_reset_by_lost_support"], 1)
        self.assertEqual(events["pending_stop_runs_reset_by_half_change"], 1)
        self.assertEqual(events["confirmed_stop_runs"], 0)

    def test_restart_is_counted_once_and_is_not_stop_cancellation(self):
        report = summarize_prior_diagnostics(motion_after_stop())
        self.assertEqual(report["event_counts"]["confirmed_stop_runs"], 1)
        self.assertEqual(report["event_counts"]["stop_contexts_followed_by_confirmed_live"], 1)
        self.assertEqual(report["confirmed_stop_run_share_followed_by_live"], 1.)
        self.assertEqual(report["confirmed_stop_frames_overwritten_by_live"], 0)

    def test_real_feature_builder_cannot_remove_stop_support(self):
        for match in (match_input(tagged=True), match_input(outside=True), motion_after_stop()):
            with self.subTest(events=bool(match.events)):
                features = build_features(match)
                before = build_priors(match)
                after = build_priors(match, features)
                np.testing.assert_array_equal(before.dead_evidence > .5, after.dead_evidence > .5)
                report = summarize_prior_diagnostics(match, features)
                self.assertEqual(report["without_control_comparison"]["changed_stop_frames"], 0)
                self.assertEqual(report["confirmed_stop_frames_overwritten_by_live"], 0)

    def test_control_adds_live_evidence_without_changing_stops(self):
        match = match_input()
        match.ball_xy_m[:, 0] += np.arange(12) * .3
        match.ball_speed_mps[:] = 3.
        match.players_xy_m[:, 0] = match.ball_xy_m + [.1, 0.]
        match.players_xy_m[:, 1] = match.ball_xy_m + [5., 0.]
        comparison = summarize_prior_diagnostics(match, build_features(match))["without_control_comparison"]
        self.assertEqual(comparison["changed_stop_frames"], 0)
        self.assertEqual(comparison["additional_live_frames_with_control"], 11)

    def test_empty_disabled_and_excluded_reports_are_json_totals_only(self):
        import json

        for match, config in ((match_input(n=0), None),
                              (match_input(), {"dead_ball": {"enabled": False}}),
                              (match_input(), {"dead_ball": {"evidence_weight": 0}})):
            report = summarize_prior_diagnostics(match, config=config)
            self.assertIsNone(report["confirmed_stop_run_share_followed_by_live"])
            json.dumps(report, allow_nan=False)
            if not len(match.frame):
                self.assertTrue(all(v is None for v in report["graded_frame_shares"].values()))
        match = match_input(tagged=True)
        match.half[:] = 0
        report = summarize_prior_diagnostics(match)
        self.assertTrue(all(v == 0 for v in report["frame_counts"].values()))
        self.assertTrue(all(v is None for v in report["graded_frame_shares"].values()))


if __name__ == "__main__":
    unittest.main()
