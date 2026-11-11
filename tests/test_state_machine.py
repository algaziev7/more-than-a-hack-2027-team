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

CONFIG = StateMachineConfig()  # fps=25 -> dead_dwell_frames=2, team_dwell_frames=25
W = CONFIG.team_dwell_frames
LEAD = W + 5  # home evidence long enough to establish H before the event under test
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
        n = LEAD + 20
        features, priors = _establish_home(n)
        blip = slice(LEAD, LEAD + 5)  # 5 frames, well under team_dwell_frames
        features.team_evidence[blip] = [0.05, 0.95]
        features.team_reliability[blip] = 0.9
        labels = _run(_match(n), features, priors)
        # Decision 8: H is backdated to frame 0, so the whole half is H despite the blip.
        self.assertTrue(np.all(labels == H), labels)

    def test_sustained_turnover_flips_possession(self):
        """Evidence for the other team held past team_dwell_frames must flip the label."""
        n = LEAD + W + 10
        features, priors = _establish_home(n)
        turnover = slice(LEAD, n)  # W + 10 frames, past the dwell
        features.team_evidence[turnover] = [0.05, 0.95]
        features.team_reliability[turnover] = 0.9
        labels = _run(_match(n), features, priors)
        # Decision 8: the boundary sits at the first A frame, not W frames later.
        self.assertTrue(np.all(labels[:LEAD] == H), labels)
        self.assertTrue(np.all(labels[LEAD:] == A), labels)

    def test_short_but_real_possession_is_captured(self):
        """Contrast with the deflection case: evidence held just past the dwell IS a possession."""
        short_spell = slice(LEAD, LEAD + W + 2)  # just over the dwell
        n = short_spell.stop + W + 5  # long enough for H to earn its own dwell back afterwards
        features, priors = _establish_home(n)
        features.team_evidence[short_spell] = [0.05, 0.95]
        features.team_reliability[short_spell] = 0.9
        labels = _run(_match(n), features, priors)
        # Decision 8: both boundaries land exactly where the evidence changes.
        self.assertTrue(np.all(labels[short_spell] == A), labels)
        self.assertTrue(np.all(labels[short_spell.stop:] == H), labels)

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
        stoppage = slice(LEAD, LEAD + 15)
        n = stoppage.stop + W + 10
        features, priors = _establish_home(n)
        priors.dead_evidence[stoppage] = 0.95
        priors.dead_reliability[stoppage] = 0.9
        features.team_reliability[stoppage] = 0.0
        priors.restart_evidence[stoppage.stop] = 0.75
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
        n = LEAD + 40
        features, priors = _establish_home(n)
        noisy = range(LEAD, LEAD + 30)
        for i in noisy:
            home_now = (i % 2 == 0)
            features.team_evidence[i] = [0.95, 0.05] if home_now else [0.05, 0.95]
            features.team_reliability[i] = 0.9
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels == H), labels)

    def test_player_standing_near_ball_does_not_resume_a_confirmed_stop(self):
        """Decision 6 (2026-11-09), found by Almaz: the throw-in scenario.

        Play is confirmed stopped. The stop signal then simply goes quiet (tag window ended, no
        opinion either way) -- NOT confirmed live -- while a player happens to stand near the
        ball the whole time, waiting to take the throw. Team proximity alone must not read as
        "that team has it": the throw hasn't been taken, there's no proof play resumed. This
        sequence is well under the safety-valve threshold (latched_team_dwell_frames, ~75 frames
        by default) -- see test_sustained_team_evidence_eventually_overrides_an_unresolved_stop
        for what happens if proximity alone persists far longer than that.
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

    def test_bare_tagged_restart_window_does_not_clear_the_latch(self):
        """A second review found the real bug in the first fix: Smart Tagging's bare SET PIECES
        window sets restart_evidence to its flat default (0.5) for the window's *entire* span --
        including every frame a tagged stop is also confirmed on. At threshold 0.5, that alone
        cleared the Decision 6 latch on the very same frame it got set, making the fix a no-op
        for exactly the tagged-stoppage case (a throw-in) it exists to fix. Reproduced
        independently before trusting the report; threshold raised to 0.6 (strictly above
        tagging's bare hint, at or below E3's confirmed-restart pulse of 0.75) to fix it.
        """
        n = 60
        features, priors = _establish_home(n)
        confirmed_stop = slice(5, 21)
        priors.dead_evidence[confirmed_stop] = 0.9
        priors.dead_reliability[confirmed_stop] = 0.5
        priors.restart_evidence[:] = 0.5  # a bare tag window, spanning the whole sequence
        features.team_evidence[25:] = [0.9, 0.1]
        features.team_reliability[25:] = 0.8
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels == D), labels)

    def test_sustained_team_evidence_eventually_overrides_an_unresolved_stop(self):
        """A third review found that the latch, as first written, had no expiry at all: E3's own
        escape path needs a usable ball, and an occlusion (41% of graded frames, in clusters)
        also wipes its recent-stop context -- so a restart happening during an occlusion, with
        tracking still ambiguous once the ball reappears, could pin D indefinitely. Reproduced
        independently with the reviewer's own repro before trusting it (920 frames / ~37s stuck).

        Fix: sustained, reliable team evidence can still exit a latched D, but only after
        latched_team_dwell_frames -- several times longer than an ordinary team change needs,
        which is exactly what makes it categorically different from Almaz's brief-proximity case
        above rather than a backdoor around it.
        """
        n = 200
        features, priors = _establish_home(n)
        confirmed_stop = slice(0, 20)
        priors.dead_evidence[confirmed_stop] = 0.9
        priors.dead_reliability[confirmed_stop] = 0.5
        unresolved = slice(20, 200)
        priors.dead_evidence[unresolved] = 0.5
        priors.dead_reliability[unresolved] = 0.0
        priors.restart_evidence[unresolved] = 0.0
        features.team_evidence[unresolved] = [0.05, 0.95]
        features.team_reliability[unresolved] = 0.9
        labels = _run(_match(n), features, priors)
        # Well short of the ~75-frame safety valve: must still be waiting, not have given up.
        self.assertTrue(np.all(labels[20:90] == D), labels[20:90])
        # Well past it: must eventually have left D despite zero restart/live-motion proof ever.
        self.assertIn(A, labels[150:], "sustained team evidence must eventually override the latch")

    def test_sparse_scattered_evidence_never_overrides_a_latched_stop(self):
        """A fifth review found the safety valve reused Decision 3's unbounded gap tolerance,
        so 75 *scattered* supporting frames spread over any length of time -- not sustained at
        all -- would still eventually override a confirmed stop. A per-gap bound can't fix this
        either (verified before landing on the real fix): any fixed bound still lets a long
        enough chain of just-under-the-bound gaps span an arbitrary total duration. Reproduced
        independently with the reviewer's own repro (one supporting frame every 12 frames, for
        ~37s) before trusting it -- it used to reach A at frame 918; it must never leave D now.

        Fixed with a genuine sliding window: only occurrences within the last
        2 * latched_team_dwell_frames count toward the safety valve, so it can never reflect
        more than that many frames of real elapsed time, however it's distributed.
        """
        n = 1000
        features, priors = _features(n), _priors(n)  # neutral everywhere except what's set below
        confirmed_stop = slice(0, 30)
        priors.dead_evidence[confirmed_stop] = 0.9
        priors.dead_reliability[confirmed_stop] = 0.5
        for i in range(30, n, 12):
            features.team_evidence[i] = [0.1, 0.9]
            features.team_reliability[i] = 0.9
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels == D), "scattered touches must never look sustained")

    def test_stray_dead_blip_during_live_play_does_not_delay_an_unrelated_turnover(self):
        """A fourth review found that `dead_confirmed` can latch while `current_state` is
        already H/A -- a single is_dead frame that never reaches dead_dwell_frames sets it
        regardless of current state. If a live-motion confirmation later arrives mid-turnover,
        clearing that stale latch was wiping the turnover's progress even though it was never
        actually gated (current_state wasn't D when the turnover started). Reproduced
        independently before trusting the report (H->A delayed from frame 45 to 54). Fixed: the
        progress is only discarded when `current_state == D` at the moment the gate lifts.
        """
        n = 70
        features, priors = _establish_home(n)
        stray_blip = 30  # looks momentarily dead, but never reaches dead_dwell_frames
        priors.dead_evidence[stray_blip] = 0.9
        priors.dead_reliability[stray_blip] = 0.5
        turnover = slice(31, 70)
        features.team_evidence[turnover] = [0.05, 0.95]
        features.team_reliability[turnover] = 0.9
        live_motion_confirmation = 40  # unrelated to the turnover; just happens to land inside it
        priors.dead_evidence[live_motion_confirmation] = 0.1
        priors.dead_reliability[live_motion_confirmation] = 0.5
        result = decode(_match(n), features, priors)
        # Confirmed on schedule (31 + W - 1), not delayed by the stray blip; Decision 8 then
        # backdates the boundary to the turnover's first frame.
        (event,) = result.diagnostics["transitions"][1:]
        self.assertEqual((event["frame"], event["confirmed_frame"]), (31, 31 + W - 1))
        self.assertTrue(np.all(result.labels[:31] == H), result.labels[:31])
        self.assertTrue(np.all(result.labels[31:] == A), result.labels[31:])

    def test_latch_does_not_survive_a_safety_valve_exit_into_a_later_turnover(self):
        """Companion to the above: the latch must not persist past the D period it belongs to
        either. A safety-valve exit (sustained evidence, no real restart proof) must clear it,
        so a later, unrelated turnover with its own live-motion-confirmation frame isn't delayed
        by a stale latch left over from the stop before it.
        """
        n = 250
        features, priors = _establish_home(n)
        confirmed_stop = slice(0, 20)
        priors.dead_evidence[confirmed_stop] = 0.9
        priors.dead_reliability[confirmed_stop] = 0.5
        # No restart/live proof ever -- H only returns via the safety valve, well after frame 95.
        features.team_evidence[20:150] = [0.95, 0.05]
        features.team_reliability[20:150] = 0.9
        labels_before_turnover = _run(_match(n), features, priors).copy()
        self.assertIn(H, labels_before_turnover[95:150], "the safety valve must have fired by here")

        turnover = slice(150, 250)
        features.team_evidence[turnover] = [0.05, 0.95]
        features.team_reliability[turnover] = 0.9
        live_motion_confirmation = 160  # unrelated; just happens to land inside the turnover
        priors.dead_evidence[live_motion_confirmation] = 0.1
        priors.dead_reliability[live_motion_confirmation] = 0.5
        labels = _run(_match(n), features, priors)
        self.assertTrue(np.all(labels[164:] == A), labels[164:])

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
        n = LEAD + 55
        features, priors = _establish_home(n)
        turnover = range(LEAD, LEAD + 45)  # 30 decisive frames, every 3rd one is a gap
        for i in turnover:
            if i % 3 == 0:
                features.team_reliability[i] = 0.0  # a gap: no decisive signal this frame
            else:
                features.team_evidence[i] = [0.05, 0.95]
                features.team_reliability[i] = 0.9
        labels = _run(_match(n), features, priors)
        self.assertIn(A, labels[list(turnover)], "the turnover must still be detected")
        # Checked near the end of the turnover window, before home evidence resumes and earns
        # its own dwell back -- this isolates "did the gappy turnover register at all".
        self.assertTrue(np.all(labels[LEAD + 40:LEAD + 45] == A), labels)

    def test_half_reset_defaults_to_dead_not_carried_state(self):
        """Second half starts at D regardless of how half one ended, and needs its own dwell."""
        for n2, expected in ((W - 1, D), (W + 5, H)):
            with self.subTest(n2=n2):
                n1, gap = 30, 5
                half = np.concatenate([np.full(n1, 1), np.full(gap, 0), np.full(n2, 2)])
                n = len(half)
                match = SimpleNamespace(frame=np.arange(n), half=half)
                features = _features(n, team_h=0.95, team_rel=0.9)  # strong home evidence throughout
                labels = decode(match, features, _priors(n)).labels
                self.assertTrue(np.all(labels[:n1] == H), "first half earns H (backdated)")
                self.assertTrue(np.all(labels[n1:n1 + gap] == X), "ungraded gap must stay X")
                # W - 1 frames of home evidence cannot earn H: no inheritance from half one.
                # W + 5 frames earn it, backdated to the second half's first frame.
                self.assertTrue(np.all(labels[n1 + gap:] == expected), labels[n1 + gap:])


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
