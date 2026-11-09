"""Synthetic tests for possession/state_machine.py.

No match data needed -- these are exactly the fixtures TEAM_PLAN.md asks E2 to build before E1's
real loader exists, and AGENTS.md/RULES.md forbid using the public ground truth for anything but
a pipeline sanity check, so these are the only tests allowed to drive this module's design.
`match`, `features` and `priors` are duck-typed (plain SimpleNamespace) per
docs/team/INTERFACES.md -- no dependency on possession/contracts.py, which does not exist yet.

Run with:
    python -m unittest tests.test_state_machine -v
"""

import unittest
from types import SimpleNamespace

import numpy as np

from possession.contracts import Prediction
from possession.state_machine import A, D, H, X, StateMachineConfig, decode
from tests.fixtures import neutral_features, neutral_priors, synthetic_match

CONFIG = StateMachineConfig()  # fps=25 -> dead_dwell_frames=2, team_dwell_frames=15
# decode() takes the shared pipeline config dict (see possession.state_machine._section), not a
# StateMachineConfig directly. CONFIG's values are the defaults, so `None` behaves identically --
# it's kept here purely to compute expected frame offsets (e.g. CONFIG.team_dwell_frames) below.


def _match(n, half=1):
    return SimpleNamespace(frame=np.arange(n), half=np.full(n, half, dtype=int))


def _features(n, team_h=0.5, team_rel=0.0):
    """team_h is P(home) per frame; team_rel is features.team_reliability per frame."""
    team_h = np.full(n, team_h, dtype=float)
    return SimpleNamespace(
        team_evidence=np.column_stack([team_h, 1.0 - team_h]),
        team_reliability=np.full(n, team_rel, dtype=float),
    )


def _priors(n, dead=0.0, dead_rel=0.0, restart=0.0, tag_h=0.5, tag_rel=0.0):
    tag_h = np.full(n, tag_h, dtype=float)
    return SimpleNamespace(
        dead_evidence=np.full(n, dead, dtype=float),
        dead_reliability=np.full(n, dead_rel, dtype=float),
        restart_evidence=np.full(n, restart, dtype=float),
        tag_team_evidence=np.column_stack([tag_h, 1.0 - tag_h]),
        tag_team_reliability=np.full(n, tag_rel, dtype=float),
    )


def _run(match, features, priors, config=None):
    return decode(match, features, priors, config).labels


def _establish_home(n_lead):
    """n_lead frames of strong, reliable home evidence -- enough to clear team_dwell_frames."""
    return _features(n_lead, team_h=0.95, team_rel=0.9), _priors(n_lead)


def _run_length_encode(labels):
    """[(value, length)] -- small local helper, this module's own, not a shared utility."""
    out = []
    for value in labels:
        if out and out[-1][0] == value:
            out[-1] = (value, out[-1][1] + 1)
        else:
            out.append((value, 1))
    return out


class StateMachineTests(unittest.TestCase):

    def test_pass_within_team_keeps_possession(self):
        """A pass is just continued strong evidence for the same team -- no event at all."""
        n = 40
        features, priors = _establish_home(n)
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels[-10:] == H), labels)

    def test_brief_deflection_does_not_flip_possession(self):
        """A short contrary touch (well under team_dwell_frames) must not change the label."""
        n = 50
        features, priors = _establish_home(n)
        blip = slice(20, 25)  # 5 frames, team_dwell_frames is 15
        features.team_evidence[blip] = [0.05, 0.95]
        features.team_reliability[blip] = 0.9
        labels = _run(_match(n), features, priors)
        # Skip the unavoidable D warm-up every half starts in (see Decision 2); the blip itself
        # sits well after it, so this still proves the blip alone never causes a flip.
        self.assertTrue(np.all(labels[CONFIG.team_dwell_frames:] == H), labels)

    def test_sustained_turnover_flips_possession(self):
        """Evidence for the other team held past team_dwell_frames must flip the label."""
        n = 60
        features, priors = _establish_home(n)
        turnover = slice(20, 45)  # 25 frames, well past the 15-frame dwell
        features.team_evidence[turnover] = [0.05, 0.95]
        features.team_reliability[turnover] = 0.9
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels[40:45] == A), labels)

    def test_short_but_real_possession_is_captured(self):
        """Contrast with the deflection case: evidence held just past the dwell IS a possession."""
        n = 70  # long enough for A to register AND for H to earn its own dwell back afterwards
        features, priors = _establish_home(n)
        short_spell = slice(20, 37)  # 17 frames, just over the 15-frame dwell
        features.team_evidence[short_spell] = [0.05, 0.95]
        features.team_reliability[short_spell] = 0.9
        labels = _run(_match(n), features, priors)
        self.assertIn(A, labels[short_spell], "a 17-frame hold should register, unlike a blip")
        # Home evidence resumes at frame 37 but needs its own team_dwell_frames to take effect
        # (37 + 15 = 52), so the "back to home" check has to sit safely after that, not right at 45.
        self.assertTrue(np.all(labels[55:] == H), "and possession should return to home after")

    def test_stoppage_is_detected_as_dead(self):
        """Reliable dead-ball evidence held past dead_dwell_frames must produce D."""
        n = 40
        features, priors = _establish_home(n)
        stoppage = slice(15, 30)  # 15 frames, dead_dwell_frames is 8
        priors.dead_evidence[stoppage] = 0.95
        priors.dead_reliability[stoppage] = 0.9
        features.team_reliability[stoppage] = 0.0  # tracker loses the ball during the stoppage
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels[25:30] == D), labels)

    def test_same_team_restart_creates_two_separate_spells(self):
        """D must appear as its own block between two H runs, even though the team is unchanged.

        Decision 6 (2026-11-09): team evidence alone cannot exit a confirmed stop -- it needs
        independent proof play resumed. A single restart-confirmation frame right as the
        stoppage ends stands in for that proof (a tag window or E3's own live-motion
        confirmation, in reality); without it this stoppage would never end at all.
        """
        n = 70
        features, priors = _establish_home(n)
        stoppage = slice(20, 35)
        priors.dead_evidence[stoppage] = 0.95
        priors.dead_reliability[stoppage] = 0.9
        features.team_reliability[stoppage] = 0.0
        priors.restart_evidence[35] = 0.75
        labels = _run(_match(n), features, priors)

        # Drop the unavoidable D warm-up every half starts in (Decision 2) before encoding runs,
        # so it isn't mistaken for the stoppage we're actually testing.
        runs = [key for key, _ in _run_length_encode(labels[CONFIG.team_dwell_frames:]) if key != X]
        collapsed = [runs[0]]
        for state in runs[1:]:
            if state != collapsed[-1]:
                collapsed.append(state)
        self.assertEqual(collapsed, [H, D, H], collapsed)

    def test_missing_evidence_holds_current_state(self):
        """No ball, no tag, no reliability at all: the state must persist, not drift to D or X."""
        n = 60
        features, priors = _establish_home(n)
        gap = slice(20, 55)  # a long stretch with nothing to vote on
        features.team_reliability[gap] = 0.0
        priors.dead_reliability[gap] = 0.0
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels[gap] == H), labels)

    def test_noisy_flicker_does_not_flip_possession(self):
        """Per-frame alternating strong evidence never accumulates a consecutive run."""
        n = 60
        features, priors = _establish_home(n)
        noisy = range(20, 50)
        for i in noisy:
            home_now = (i % 2 == 0)
            features.team_evidence[i] = [0.95, 0.05] if home_now else [0.05, 0.95]
            features.team_reliability[i] = 0.9
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels[CONFIG.team_dwell_frames:] == H), labels)

    def test_player_standing_near_ball_does_not_resume_a_confirmed_stop(self):
        """Decision 6 (2026-11-09), found by Almaz: the throw-in scenario.

        Play is confirmed stopped. The stop signal then simply goes quiet (tag window ended, no
        opinion either way) -- NOT confirmed live -- while a player happens to stand near the
        ball the whole time, waiting to take the throw. Team proximity alone must not read as
        "that team has it": the throw hasn't been taken, there's no proof play resumed.
        """
        n = 60
        features, priors = _establish_home(n)
        confirmed_stop = slice(0, 30)
        priors.dead_evidence[confirmed_stop] = 0.9
        priors.dead_reliability[confirmed_stop] = 0.5
        quiet_but_unresolved = slice(30, 60)
        priors.dead_evidence[quiet_but_unresolved] = 0.5   # neutral: no opinion, NOT "confirmed live"
        priors.dead_reliability[quiet_but_unresolved] = 0.0
        priors.restart_evidence[quiet_but_unresolved] = 0.0
        features.team_evidence[quiet_but_unresolved] = [0.95, 0.05]  # a player merely nearby
        features.team_reliability[quiet_but_unresolved] = 0.9
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels == D), labels)

    def test_restart_with_real_evidence_still_works(self):
        """Contrast with the above: once there's genuine proof play resumed, team evidence
        resumes deciding who has it, exactly as before Decision 6."""
        n = 60
        features, priors = _establish_home(n)
        confirmed_stop = slice(0, 30)
        priors.dead_evidence[confirmed_stop] = 0.9
        priors.dead_reliability[confirmed_stop] = 0.5
        priors.restart_evidence[30] = 0.75  # the throw is actually taken here
        features.team_evidence[30:60] = [0.95, 0.05]
        features.team_reliability[30:60] = 0.9
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels[45:] == H), labels)

    def test_ordinary_kickoff_is_unaffected_by_the_restart_gate(self):
        """Decision 6 only gates leaving a *confirmed* stop. The half-start default D (nothing
        has ever confirmed a stop -- an ordinary kickoff) is untouched: team evidence alone still
        establishes possession, exactly as it did before this decision existed."""
        n = 40
        features, priors = _establish_home(n)  # no dead/restart signal anywhere in this fixture
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels[CONFIG.team_dwell_frames:] == H), labels)

    def test_turnover_survives_missing_evidence_gaps_inside_it(self):
        """Decision 3: a gap mid-turnover must pause the dwell count, not reset it.

        Without the fix, every missing-evidence frame below would zero the pending count and the
        turnover (well past team_dwell_frames in total decisive support) could fail to register at
        all -- exactly the scenario a 41%-missing-ball match produces routinely.
        """
        n = 70
        features, priors = _establish_home(n)
        turnover = range(20, 50)  # 30 frames, but every 3rd one is a missing-evidence gap
        for i in turnover:
            if i % 3 == 0:
                features.team_reliability[i] = 0.0  # a gap: no decisive signal this frame
            else:
                features.team_evidence[i] = [0.05, 0.95]
                features.team_reliability[i] = 0.9
        labels = _run(_match(n), features, priors)
        self.assertIn(A, labels[list(turnover)], "the turnover must still be detected")
        # Checked near the end of the turnover window, before home evidence resumes at frame 50
        # and earns its own dwell back -- this isolates "did the gappy turnover register at all".
        self.assertTrue(np.all(labels[45:50] == A), labels)

    def test_half_reset_defaults_to_dead_not_carried_state(self):
        """Second half starts at D regardless of how half one ended, and needs its own dwell."""
        n1, gap, n2 = 30, 5, 30
        half = np.concatenate([np.full(n1, 1), np.full(gap, 0), np.full(n2, 2)])
        n = len(half)
        match = SimpleNamespace(frame=np.arange(n), half=half)

        features = _features(n, team_h=0.95, team_rel=0.9)  # strong home evidence throughout
        priors = _priors(n)

        labels = decode(match, features, priors).labels
        self.assertTrue(np.all(labels[n1:n1 + gap] == X), "ungraded gap must stay X")

        second_half_start = n1 + gap
        warmup_end = second_half_start + CONFIG.team_dwell_frames
        self.assertTrue(
            np.all(labels[second_half_start:warmup_end - 1] == D),
            "second half must not inherit home possession or jump to it before its own dwell",
        )
        self.assertTrue(np.all(labels[warmup_end:] == H), "but should settle into H once earned")


class RealContractsCompatibilityTests(unittest.TestCase):
    """Decode against the team's actual shared fixtures (tests/fixtures.py), not just the
    lightweight SimpleNamespace stand-ins above -- proves this returns a real
    possession.contracts.Prediction and accepts real MatchData/FeatureData/PriorData, which the
    stand-ins alone can't verify.
    """

    def test_decode_accepts_real_contract_types_and_returns_real_prediction(self):
        match = synthetic_match()
        features = neutral_features(match)
        priors = neutral_priors(match)

        result = decode(match, features, priors)

        self.assertIsInstance(result, Prediction)
        self.assertEqual(len(result.labels), len(match.frame))
        self.assertTrue(np.all(result.labels[match.half == 0] == X), result.labels)
        # No decisive evidence anywhere in this fixture -> stays on the D default, never X.
        self.assertTrue(np.all(result.labels[match.half != 0] == D), result.labels)

    def test_decode_rejects_unknown_config_key(self):
        match = synthetic_match()
        with self.assertRaises(ValueError):
            decode(match, neutral_features(match), neutral_priors(match),
                   {"state_machine": {"not_a_real_setting": 1}})


if __name__ == "__main__":
    unittest.main()
