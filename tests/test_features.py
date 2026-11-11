from dataclasses import replace
import unittest

import numpy as np

from possession.contracts import MatchData
from possession.dead_ball import build_priors
from possession.features import build_features, reliability_breakdown
from tests.fixtures import synthetic_match


def tracking(ball, players, half=None, speed=None):
    ball = np.array(ball, dtype=float).reshape(-1, 2)
    players = np.array(players, dtype=float).reshape(len(ball), 3, 2)
    n = len(ball)
    return MatchData(
        frame=np.arange(n, dtype=np.int64),
        half=np.ones(n, dtype=np.int8) if half is None else np.array(half, dtype=np.int8),
        fps=25., pitch_m=(105., 68.),
        ball_xy_m=ball, ball_observed=np.isfinite(ball).all(axis=1),
        players_xy_m=players, player_observed=np.isfinite(players).all(axis=2),
        slot_team=np.array(["H", "A", "H"]),
        ball_speed_mps=None if speed is None else np.array(speed, dtype=float),
    )


class TrackingFeatureTests(unittest.TestCase):
    def test_distances_density_and_evidence_in_canonical_units(self):
        match = tracking([[10, 20]], [[[10.6, 20], [20, 20], [10, 24]]])
        out = build_features(match, {"seed": 7})
        np.testing.assert_array_equal(out.frame, match.frame)
        self.assertAlmostEqual(out.features["home_nearest_m"][0], .6)
        self.assertEqual(out.features["home_next_nearest_m"][0], 4)
        self.assertEqual(out.features["away_nearest_m"][0], 10)
        self.assertFalse(out.validity["away_next_nearest_m"][0])
        self.assertAlmostEqual(out.features["home_distance_advantage_m"][0], 9.4)
        self.assertEqual(out.features["home_nearby_count"][0], 2)
        self.assertEqual(out.features["away_nearby_count"][0], 0)
        self.assertEqual(out.features["ball_boundary_distance_m"][0], 10)
        self.assertGreater(out.team_evidence[0, 0], .75)
        self.assertGreater(out.team_reliability[0], .5)

    def test_missing_players_and_ambiguous_control_are_neutral(self):
        nan = np.nan
        match = tracking([[10, 20], [10, 20]],
                         [[[10, 20], [nan, nan], [12, 20]],
                          [[10, 20], [10, 20], [12, 20]]])
        out = build_features(match)
        self.assertFalse(out.validity["away_nearby_count"][0])
        self.assertFalse(out.validity["home_distance_advantage_m"][0])
        np.testing.assert_array_equal(out.team_evidence, .5)
        np.testing.assert_array_equal(out.team_reliability, 0)

    def test_missing_ball_duration_and_speed_reset_at_half_boundaries(self):
        nan = np.nan
        ball = [[10, 20], [10.2, 20], [nan, nan], [nan, nan],
                [nan, nan], [40, 20], [40.4, 20], [41, 20], [0, 20]]
        players = [[[10, 20], [40, 20], [60, 20]]] * len(ball)
        match = tracking(ball, players, half=[1, 1, 1, 1, 2, 2, 2, 0, 2])
        out = build_features(match)
        np.testing.assert_allclose(out.features["ball_missing_duration_s"],
                                   [0, 0, .04, .08, .04, 0, 0, nan, 0])
        np.testing.assert_allclose(out.features["ball_speed_mps"],
                                   [nan, 5, nan, nan, nan, nan, 10, nan, nan])
        self.assertTrue(out.validity["ball_boundary_distance_m"][8])
        np.testing.assert_array_equal(out.team_reliability[[2, 3, 4, 7]], 0)

    def test_implausible_ball_and_player_jumps_are_rejected(self):
        match = tracking([[10, 20], [10, 20], [50, 20]],
                         [[[11, 20], [20, 20], [15, 20]],
                          [[10, 20], [20, 20], [15, 20]],
                          [[10, 20], [20, 20], [15, 20]]], speed=[0, 0, 0])
        out = build_features(match)
        self.assertEqual(out.features["home_nearest_m"][1], 5)
        self.assertFalse(out.validity["home_next_nearest_m"][1])
        self.assertFalse(out.validity["ball_speed_mps"][2])
        self.assertFalse(out.validity["home_nearest_m"][2])
        self.assertEqual(out.team_reliability[2], 0)
        self.assertEqual(out.features["ball_missing_duration_s"][2], 0)

    def test_observed_half_boundary_does_not_create_a_tracking_jump(self):
        match = tracking([[10, 20], [80, 20]],
                         [[[10, 20], [25, 20], [40, 20]],
                          [[65, 20], [80, 20], [95, 20]]], half=[1, 2])
        out = build_features(match)
        np.testing.assert_array_equal(out.validity["ball_speed_mps"], False)
        np.testing.assert_array_equal(out.team_evidence, [[1, 0], [0, 1]])

    def test_speed_uses_valid_raw_or_displacement_and_flags_disagreement(self):
        match = tracking([[10, 20], [10.4, 20], [10.8, 20], [11.2, 20]],
                         [[[10, 20], [20, 20], [15, 20]]] * 4,
                         speed=[2, np.nan, 30, 10])
        out = build_features(match)
        np.testing.assert_allclose(out.features["ball_speed_mps"], [2, 10, np.nan, 10])
        np.testing.assert_allclose(out.features["ball_speed_disagreement_mps"],
                                   [np.nan, np.nan, 20, 0], atol=1e-10)

    def test_outside_pitch_has_geometry_but_neutral_team_evidence(self):
        match = tracking([[-.5, 20]], [[[0, 20], [5, 20], [8, 20]]])
        out = build_features(match)
        self.assertEqual(out.features["ball_boundary_distance_m"][0], -.5)
        self.assertEqual(out.features["home_nearest_m"][0], .5)
        np.testing.assert_array_equal(out.team_evidence, .5)
        np.testing.assert_array_equal(out.team_reliability, 0)

    def test_fast_ball_weakens_clues_and_distant_players_give_no_clue(self):
        players = [[[10.5, 20], [20, 20], [16, 20]]]
        slow = build_features(tracking([[10, 20]], players, speed=[2]))
        fast = build_features(tracking([[10, 20]], players, speed=[16]))
        far = build_features(tracking([[10, 30]], players, speed=[2]))
        np.testing.assert_array_equal(slow.team_evidence, fast.team_evidence)
        np.testing.assert_allclose(fast.team_reliability, slow.team_reliability / 2)
        np.testing.assert_array_equal(far.team_evidence, .5)
        np.testing.assert_array_equal(far.team_reliability, 0)

    def test_rejected_raw_speed_does_not_strengthen_fast_ball_clue(self):
        match = tracking([[9.2, 20], [10, 20]],
                         [[[10.4, 20], [20, 20], [15, 20]]] * 2)
        displacement_only = build_features(match)
        for raw_speed in (35., 100.):
            with self.subTest(raw_speed=raw_speed):
                out = build_features(replace(match, ball_speed_mps=np.array([np.nan, raw_speed])))
                self.assertFalse(out.validity["ball_speed_mps"][1])
                self.assertAlmostEqual(out.team_reliability[1],
                                       displacement_only.team_reliability[1])

    def test_e3_uses_our_team_clue_to_support_live_motion(self):
        ball = np.column_stack((10 + .12 * np.arange(10), np.full(10, 20)))
        players = ball[:, None, :] + np.array([[.4, 0], [10, 0], [4, 0]])
        match = tracking(ball, players)
        features = build_features(match)
        neutral = build_priors(match)
        supported = build_priors(match, features=features)
        np.testing.assert_array_equal(neutral.dead_reliability, 0)
        np.testing.assert_array_equal(supported.dead_reliability[:5], 0)
        np.testing.assert_array_equal(supported.dead_evidence[5:], .1)

    def test_swapping_teams_and_mirroring_preserve_the_expected_clues(self):
        match = synthetic_match()
        before = match.players_xy_m.copy()
        out = build_features(match)
        swapped = build_features(replace(match, slot_team=match.slot_team[::-1].copy()))
        reflected = build_features(replace(
            match, ball_xy_m=np.array(match.pitch_m) - match.ball_xy_m,
            players_xy_m=np.array(match.pitch_m) - match.players_xy_m,
        ))
        np.testing.assert_allclose(out.team_evidence[:, ::-1], swapped.team_evidence)
        np.testing.assert_allclose(out.team_reliability, swapped.team_reliability)
        np.testing.assert_allclose(out.team_evidence, reflected.team_evidence)
        np.testing.assert_allclose(out.team_reliability, reflected.team_reliability)
        for name, value in out.features.items():
            np.testing.assert_allclose(value, reflected.features[name], atol=1e-12)
            np.testing.assert_array_equal(out.validity[name], reflected.validity[name])
        np.testing.assert_array_equal(match.players_xy_m, before)

    def test_empty_match_and_missing_team_slots_are_supported(self):
        empty = build_features(tracking([], []))
        self.assertEqual(empty.team_evidence.shape, (0, 2))
        match = tracking([[10, 20]], [[[11, 20], [20, 20], [15, 20]]])
        out = build_features(replace(match, slot_team=np.array(["H", "H", "H"])))
        self.assertFalse(out.validity["away_nearest_m"][0])
        np.testing.assert_array_equal(out.team_reliability, 0)

    def test_reliability_counts_proximity_and_speed_but_not_margin(self):
        # Separate halves isolate frames, so only the supplied raw speed matters.
        far_slot = [50, 50]
        players = [[[10.5, 20], [20, 20], far_slot],    # reliable: proximity 0.83
                   [[12.4, 20], [99, 60], far_slot],    # far: nearest 2.4 m > 2.25 m
                   [[11, 20], [11.2, 20], far_slot],    # contested: margin 0.09 < 0.15
                   [[10.5, 20], [20, 20], far_slot],    # fast: 32 m/s quarters it
                   [[30, 20], [40, 20], far_slot],      # no evidence beyond 3 m
                   [[11, 20], [12, 20], far_slot]]      # 1 m vs 2 m: was rejected before (c)
        match = tracking([[10, 20]] * 6, players, half=[1, 2, 1, 2, 1, 2],
                         speed=[0, 0, 0, 32, 0, 0])
        out = build_features(match)
        np.testing.assert_allclose(out.team_reliability, [5 / 6, .2, 2 / 3, 5 / 24, 0, 2 / 3])
        self.assertEqual(reliability_breakdown(out), {
            "tracking_frames": 5, "below_cutoff": 2, "far": 1, "fast": 1, "contested": 1})
