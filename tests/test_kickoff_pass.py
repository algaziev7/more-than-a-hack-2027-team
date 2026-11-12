"""Controlled-pass hypothesis tested on invented sequences only."""

import unittest

import numpy as np

from possession.features import build_features
from possession.kickoff_pass import controlled_pass_candidates
from tests.test_kickoff import kickoff_match, hide


def pass_match(fps=25., offset=(4., 3.), jitter=False):
    match = kickoff_match(fps)
    n, start = len(match.frame), int(fps)
    origin = np.asarray(match.pitch_m)/2 + offset
    match.ball_xy_m[:] = origin
    motion = np.minimum(np.arange(1, n-start+1)*3/fps, 8.)
    match.ball_xy_m[start:, 0] += motion
    match.ball_speed_mps[:] = 0
    match.ball_speed_mps[start:start+int(8/3*fps)] = 3
    if jitter:
        match.ball_xy_m[:start, 1] += .02*np.where(np.arange(start)%2, 1, -1)
    # Two stationary H slots: kicker and receiver; A is remote. Slots are used
    # for geometry only, never as identities carried between observations.
    match.players_xy_m = np.tile(np.array([origin+[.2, 0], origin+[8.2, 0],
                                          origin+[0, 15]])[None], (n, 1, 1))
    match.player_observed = np.ones((n, 3), dtype=bool)
    match.slot_team = np.array(["H", "H", "A"])
    return match


def candidates(match):
    return np.flatnonzero(controlled_pass_candidates(match, build_features(match)))


class ControlledPassTests(unittest.TestCase):
    def test_offset_and_jitter_passes_confirm_at_reception_at_both_fps(self):
        for fps in (25., 50.):
            for offset in ((0., 0.), (4., 3.), (-4., -3.)):
                with self.subTest(fps=fps, offset=offset):
                    found = candidates(pass_match(fps, offset, jitter=True))
                    self.assertEqual(len(found), 1)
                    self.assertGreater(found[0], int(3*fps))

    def test_accompanied_ball_approaching_centre_then_stopping_is_rejected(self):
        match = pass_match()
        match.ball_xy_m[:, 0] = match.pitch_m[0]-match.ball_xy_m[:, 0]
        match.players_xy_m[:, 0] = match.ball_xy_m + [.2, 0]
        self.assertEqual(len(candidates(match)), 0)

    def test_stationary_wait_is_rejected(self):
        match = pass_match()
        match.ball_xy_m[:] = match.ball_xy_m[0]
        match.ball_speed_mps[:] = 0
        self.assertEqual(len(candidates(match)), 0)

    def test_missing_tag_no_settlement_and_no_reception_are_rejected(self):
        for variant in ("tag", "settlement", "reception"):
            match = pass_match()
            if variant == "tag":
                match.events = []
            elif variant == "settlement":
                match.ball_xy_m[:25, 0] += np.arange(25)*.12-3
                match.ball_speed_mps[:25] = 3
            else:
                match.players_xy_m[:, 1] += [20, 0]
            self.assertEqual(len(candidates(match)), 0, variant)

    def test_short_gaps_are_neutral_and_long_gaps_reset(self):
        for fps in (25., 50.):
            match = pass_match(fps)
            hide(match, [int(2*fps), int(2*fps)+2])
            self.assertEqual(len(candidates(match)), 1)
            match = pass_match(fps)
            hide(match, np.arange(int(fps), int(1.5*fps)))
            self.assertEqual(len(candidates(match)), 0)

    def test_expiry_half_reset_and_disabled_mode(self):
        match = pass_match()
        match.half[25:] = 2
        self.assertEqual(len(candidates(match)), 0)
        match = pass_match()
        features = build_features(match)
        self.assertFalse(controlled_pass_candidates(
            match, features, {"dead_ball": {"enabled": False}}).any())
        self.assertFalse(controlled_pass_candidates(
            match, features, {"dead_ball": {"restart_context_s": .4}}).any())
        self.assertFalse(controlled_pass_candidates(match, None).any())
        with self.assertRaises(ValueError):
            controlled_pass_candidates(match, features, [])

    def test_preparatory_pass_is_an_unresolved_false_positive(self):
        # These observations could describe a kickoff OR a pre-whistle pass.
        # No supplied feature encodes the referee's permission. The experiment
        # must expose this ambiguity rather than calling the candidate reliable.
        # Concrete counterexample: a controlled preparatory pass TOWARDS the
        # centre, received and settled there. This must not be sold as kickoff
        # proof merely because it rejects a player accompanying the ball.
        pre_whistle_pass = pass_match(offset=(-8., 0.))
        np.testing.assert_allclose(pre_whistle_pass.ball_xy_m[-1],
                                   np.asarray(pre_whistle_pass.pitch_m)/2)
        self.assertEqual(len(candidates(pre_whistle_pass)), 1)


if __name__ == "__main__":
    unittest.main()
