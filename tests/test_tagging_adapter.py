"""Integration with E1's real contracts using invented events only."""

from dataclasses import fields
import unittest

import numpy as np

from possession.contracts import PriorData
from possession.tagging import (
    RESTART_WINDOW, TEAM_CONFLICT, UNKNOWN_TEAM, TaggingConfig,
    build_tagging_priors, build_tagging_signals, to_prior_data,
)
from tests.fixtures import neutral_priors, synthetic_match


def event(team="Barcelona", start=1, end=4, code="BUILD UP"):
    return {"start_frame": start, "end_frame": end, "code": code,
            "tags": {"Team": team}}


class TaggingAdapterTests(unittest.TestCase):
    def test_shared_match_events_create_valid_prior_data(self):
        match = synthetic_match()
        priors = build_tagging_priors(match.events, len(match.frame))
        self.assertIsInstance(priors, PriorData)
        self.assertEqual(priors.tag_team_evidence.shape, (8, 2))
        np.testing.assert_array_equal(priors.tag_team_evidence[1:3], [[1., 0.]] * 2)
        np.testing.assert_array_equal(priors.tag_team_reliability[1:3], [.5, .5])
        np.testing.assert_array_equal(priors.dead_evidence, np.full(8, .5))
        np.testing.assert_array_equal(priors.dead_reliability, np.zeros(8))

    def test_conversion_preserves_all_clues_and_diagnostic_flags(self):
        events = [event(), event(team="Athletic Club", start=2, end=5),
                  event(team="N/A", start=3, end=6, code="SET PIECES")]
        signals = build_tagging_signals(events, 8)
        priors = to_prior_data(signals)
        for field in fields(PriorData):
            name = field.name
            expected = np.asarray(getattr(signals, name))
            np.testing.assert_array_equal(getattr(priors, name), expected)
        self.assertEqual(priors.diagnostic_flags[3],
                         TEAM_CONFLICT | UNKNOWN_TEAM | RESTART_WINDOW)
        for field in fields(PriorData):
            array = getattr(priors, field.name)
            self.assertEqual(array.shape[0], 8)
            self.assertIn(array.dtype.kind, "iu" if field.name == "diagnostic_flags" else "f")

    def test_no_tags_matches_shared_neutral_fixture(self):
        match = synthetic_match()
        priors = build_tagging_priors([], len(match.frame))
        expected = neutral_priors(match)
        for field in fields(PriorData):
            if field.name != "diagnostic_flags":
                np.testing.assert_array_equal(getattr(priors, field.name),
                                              getattr(expected, field.name))
        np.testing.assert_array_equal(priors.diagnostic_flags, np.zeros(8, dtype=int))

    def test_empty_timeline_has_correct_two_column_shape(self):
        priors = build_tagging_priors([], 0)
        self.assertEqual(priors.tag_team_evidence.shape, (0, 2))
        for field in fields(PriorData):
            if field.name != "tag_team_evidence":
                self.assertEqual(getattr(priors, field.name).shape, (0,))
        self.assertIn(priors.diagnostic_flags.dtype.kind, "iu")

    def test_unknown_throw_in_keeps_restart_without_team_or_dead_claim(self):
        priors = build_tagging_priors([event(team="N/A", code="SET PIECES")], 8)
        np.testing.assert_array_equal(priors.restart_evidence[1:4], [.5] * 3)
        np.testing.assert_array_equal(priors.tag_team_evidence, np.full((8, 2), .5))
        np.testing.assert_array_equal(priors.tag_team_reliability, np.zeros(8))
        np.testing.assert_array_equal(priors.dead_reliability, np.zeros(8))

    def test_config_is_used_without_reweighting(self):
        priors = build_tagging_priors(
            [event(), event(code="SET PIECES")], 8,
            TaggingConfig(team_reliability=.25, restart_strength=.75),
        )
        np.testing.assert_array_equal(priors.tag_team_reliability[1:4], [.25] * 3)
        np.testing.assert_array_equal(priors.restart_evidence[1:4], [.75] * 3)
        np.testing.assert_array_equal(priors.tag_team_evidence[1:4], [[1., 0.]] * 3)

    def test_copies_are_independent_in_both_directions(self):
        signals = build_tagging_signals([event()], 8)
        first, second = to_prior_data(signals), to_prior_data(signals)
        first.tag_team_evidence[1] = [0., 1.]
        first.diagnostic_flags[1] = 99
        self.assertEqual(signals.tag_team_evidence[1], (1., 0.))
        self.assertEqual(signals.diagnostic_flags[1], 0)
        signals.tag_team_reliability[1] = .9
        np.testing.assert_array_equal(second.tag_team_evidence[1], [1., 0.])
        self.assertEqual(second.tag_team_reliability[1], .5)
        self.assertEqual(second.diagnostic_flags[1], 0)

    def test_reordered_float_and_boolean_frames_are_not_silently_cast(self):
        for frame in ([0, 2, 1], [0, 1., 2], [False, 1, 2], [1, 2, 3]):
            signals = build_tagging_signals([], 3)
            signals.frame = frame
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                to_prior_data(signals)

    def test_mismatched_lengths_are_rejected(self):
        for field in fields(PriorData):
            signals = build_tagging_signals([], 8)
            setattr(signals, field.name, getattr(signals, field.name)[:-1])
            with self.subTest(field=field.name), self.assertRaises(ValueError):
                to_prior_data(signals)
        # Equal lengths among fields must still match the frame timeline.
        signals = build_tagging_signals([], 3)
        signals.frame = list(range(8))
        with self.assertRaises(ValueError):
            to_prior_data(signals)

    def test_invalid_clues_are_checked_by_the_shared_contract(self):
        for name, value in (("tag_team_reliability", np.nan),
                            ("restart_evidence", 1.1), ("dead_evidence", 1.)):
            signals = build_tagging_signals([], 8)
            getattr(signals, name)[1] = value
            with self.subTest(field=name), self.assertRaises(ValueError):
                to_prior_data(signals)
        signals = build_tagging_signals([], 8)
        signals.tag_team_evidence[1] = (1., 0.)  # Weight is still zero.
        with self.assertRaises(ValueError):
            to_prior_data(signals)

    def test_reason_codes_are_not_silently_truncated(self):
        for flags in ([.5] * 8, [True] * 8):
            signals = build_tagging_signals([], 8)
            signals.diagnostic_flags = flags
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                to_prior_data(signals)


if __name__ == "__main__":
    unittest.main()
