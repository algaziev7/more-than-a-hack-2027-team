"""Synthetic tests only: no competition data or public ground truth."""

import copy
from pathlib import Path
import tempfile
import unittest

from possession.tagging import (
    ATTACKING_CODES, RESTART_WINDOW, TEAM_CONFLICT, UNKNOWN_TEAM,
    TaggingConfig, build_tagging_signals, load_tagging_signals,
)


def event(code="BUILD UP", team="Barcelona", start=2, end=5):
    return {"code": code, "start_frame": start, "end_frame": end,
            "tags": {"Team": team}}


class TaggingTests(unittest.TestCase):
    def test_empty_events_are_neutral_with_full_length(self):
        result = build_tagging_signals([], 8)
        self.assertEqual(result.frame, list(range(8)))
        self.assertEqual(result.tag_team_evidence, [(0.5, 0.5)] * 8)
        self.assertEqual(result.tag_team_reliability, [0.0] * 8)
        self.assertEqual(result.restart_evidence, [0.0] * 8)
        self.assertEqual(result.dead_evidence, [0.5] * 8)
        self.assertEqual(result.dead_reliability, [0.0] * 8)

    def test_attacking_allowlist_and_exclusive_end(self):
        for code in ATTACKING_CODES:
            with self.subTest(code=code):
                result = build_tagging_signals([event(code=code)], 8)
                self.assertEqual(result.tag_team_evidence[1], (0.5, 0.5))
                self.assertEqual(result.tag_team_evidence[2:5], [(1.0, 0.0)] * 3)
                self.assertEqual(result.tag_team_evidence[5], (0.5, 0.5))
                self.assertEqual(result.tag_team_reliability[2:5], [0.5] * 3)

    def test_club_aliases_case_and_whitespace(self):
        for team in ("Atletic Club", "ATHLETIC CLUB", " athletic   club "):
            e = event(code=" build   UP ", team=team)
            e["tags"] = {" team ": team}
            self.assertEqual(build_tagging_signals([e], 8).tag_team_evidence[2],
                             (0.0, 1.0))

    def test_set_pieces_do_not_predict_live_owner_or_dead_ball(self):
        for kind in ("Throw-in", "Corner Kick", "Goal Kick", "Free Kick",
                     "Kick Off (After Goal)", "Kick Off (Start)"):
            with self.subTest(kind=kind):
                e = event(code="SET PIECES", team="N/A" if kind == "Throw-in" else "Barcelona")
                e["tags"]["Type"] = kind
                result = build_tagging_signals([e], 8)
                self.assertEqual(result.restart_evidence, [0, 0, .5, .5, .5, 0, 0, 0])
                self.assertEqual(result.tag_team_reliability, [0.0] * 8)
                self.assertEqual(result.dead_reliability, [0.0] * 8)
                self.assertTrue(result.diagnostic_flags[2] & RESTART_WINDOW)
                if kind == "Throw-in":
                    self.assertTrue(result.diagnostic_flags[2] & UNKNOWN_TEAM)

    def test_missing_and_unknown_team_are_neutral(self):
        for tags in (None, {}, {"Team": "N/A"}, {"Team": "Unknown Club"},
                     {"Team": "Barcelona", "team": "Athletic Club"}):
            e = event()
            e["tags"] = tags
            result = build_tagging_signals([e], 8)
            self.assertEqual(result.tag_team_reliability, [0.0] * 8)
            self.assertTrue(result.diagnostic_flags[2] & UNKNOWN_TEAM)

    def test_defensive_ambiguous_and_unknown_codes_are_neutral(self):
        for code in ("DEFENDING IN MIDDLE THIRD", "DEFENSIVE TRANSITION",
                     "PLAYERS IN THE BOX", "GOALS", "NEW CODE", None):
            result = build_tagging_signals([event(code=code)], 8)
            self.assertEqual(result.tag_team_reliability, [0.0] * 8)
            self.assertEqual(result.restart_evidence, [0.0] * 8)

    def test_conflict_only_cancels_overlapping_frames(self):
        events = [event(start=1, end=5), event(team="Athletic Club", start=3, end=7)]
        result = build_tagging_signals(events, 8)
        self.assertEqual(result.tag_team_evidence[1], (1.0, 0.0))
        self.assertEqual(result.tag_team_evidence[3:5], [(0.5, 0.5)] * 2)
        self.assertEqual(result.tag_team_reliability[3:5], [0, 0])
        self.assertTrue(result.diagnostic_flags[3] & TEAM_CONFLICT)
        self.assertEqual(result.tag_team_evidence[5], (0.0, 1.0))

    def test_duplicates_and_input_order_do_not_change_output(self):
        events = [event(), event(team="Athletic Club", start=4, end=6),
                  event(code="SET PIECES", start=0, end=3)]
        expected = build_tagging_signals(events, 8)
        self.assertEqual(build_tagging_signals(events * 4, 8), expected)
        self.assertEqual(build_tagging_signals(reversed(events), 8), expected)

    def test_team_swap_swaps_columns(self):
        home = build_tagging_signals([event()], 8)
        away = build_tagging_signals([event(team="Athletic Club")], 8)
        self.assertEqual(home.tag_team_evidence, [tuple(reversed(p)) for p in away.tag_team_evidence])
        self.assertEqual(home.tag_team_reliability, away.tag_team_reliability)

    def test_bounds_clip_and_zero_length_disappears(self):
        events = [event(start=-5, end=2), event(team="Athletic Club", start=6, end=20),
                  event(start=3, end=3), event(start=10, end=12), event(start=-4, end=-1)]
        result = build_tagging_signals(events, 8)
        self.assertEqual(result.tag_team_evidence,
                         [(1., 0.)] * 2 + [(.5, .5)] * 4 + [(0., 1.)] * 2)
        self.assertEqual(build_tagging_signals(events, 0).frame, [])

    def test_invalid_frames_and_events_fail_explicitly(self):
        for n in (-1, 2.5, True):
            with self.assertRaises(ValueError):
                build_tagging_signals([], n)
        for bad in ({}, None, event(start=5, end=2), event(start=2.5), event(start=True)):
            with self.assertRaises(ValueError):
                build_tagging_signals([bad], 8)
        e = event()
        e["tags"] = ["Barcelona"]
        with self.assertRaises(ValueError):
            build_tagging_signals([e], 8)

    def test_config_limits_and_zero_weights(self):
        for value in (-.1, 1.1, float("nan"), float("inf"), "0.5", True):
            with self.assertRaises(ValueError):
                TaggingConfig(team_reliability=value)
            with self.assertRaises(ValueError):
                TaggingConfig(restart_strength=value)
        result = build_tagging_signals([event(), event(code="SET PIECES")], 8,
                                       TaggingConfig(team_reliability=0, restart_strength=0))
        self.assertEqual(result.tag_team_evidence, [(0.5, 0.5)] * 8)
        self.assertEqual(result.restart_evidence, [0.0] * 8)

    def test_inputs_are_unchanged_and_runs_are_independent(self):
        events = [event()]
        before = copy.deepcopy(events)
        first = build_tagging_signals(events, 8)
        first.tag_team_evidence[2] = (0, 1)
        second = build_tagging_signals(events, 8)
        self.assertEqual(events, before)
        self.assertEqual(second.tag_team_evidence[2], (1.0, 0.0))

    def test_real_loader_on_synthetic_xml_and_frame_rounding(self):
        xml = '''<file><ALL_INSTANCES>
        <instance><start>0.10</start><end>0.22</end><code>BUILD UP</code>
          <label><group>Team</group><text>Barcelona</text></label></instance>
        <instance><start>0.24</start><end>0.32</end><code>SET PIECES</code>
          <label><group>Team</group><text>N/A</text></label>
          <label><group>Type</group><text>Throw-in</text></label></instance>
        </ALL_INSTANCES></file>'''
        with tempfile.TemporaryDirectory() as folder:
            tactical = Path(folder) / "tactical"
            tactical.mkdir()
            (tactical / "BAR-ATH_tactical_smart_tagging.xml").write_text(xml)
            result = load_tagging_signals(data_dir=folder)
        self.assertEqual(len(result.frame), 199319)
        # Python round: .10*25 -> 2; .22*25 -> 6. End is exclusive.
        self.assertEqual(result.tag_team_evidence[2:6], [(1., 0.)] * 4)
        self.assertEqual(result.tag_team_reliability[6], 0)
        self.assertEqual(result.restart_evidence[6:8], [.5, .5])
        self.assertEqual(result.restart_evidence[8], 0)


if __name__ == "__main__":
    unittest.main()
