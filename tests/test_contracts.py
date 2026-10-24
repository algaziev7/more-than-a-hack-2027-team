from dataclasses import replace
import unittest

import numpy as np

from possession.contracts import FeatureData, Prediction, PriorData
from tests.fixtures import neutral_features, neutral_priors, synthetic_match, synthetic_prediction


class ContractTests(unittest.TestCase):
    def test_shared_examples(self):
        match = synthetic_match()
        neutral_features(match)
        neutral_priors(match)
        self.assertEqual(len(synthetic_prediction().labels), len(match.frame))

    def test_every_frame_id_and_dtype_are_checked(self):
        match = synthetic_match()
        for frame in (np.array([0, 1, 3, 2, 4, 5, 6, 7], dtype=np.int64),
                      match.frame.astype(float), match.frame.astype(np.int32)):
            with self.subTest(dtype=frame.dtype), self.assertRaises(ValueError):
                replace(match, frame=frame)

    def test_missing_coordinates_require_nan_pairs_and_correct_masks(self):
        match = synthetic_match()
        for pair in ([np.nan, 1.], [np.inf, 1.], [0., 0.]):
            ball = match.ball_xy_m.copy()
            ball[2] = pair
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                replace(match, ball_xy_m=ball)
        with self.assertRaises(ValueError):
            replace(match, ball_observed=match.ball_observed.astype(int))

    def test_observed_zero_coordinate_is_valid(self):
        match = synthetic_match()
        ball = match.ball_xy_m.copy()
        ball[0] = 0
        replace(match, ball_xy_m=ball)

    def test_unknown_slot_team_and_invalid_half_rejected(self):
        match = synthetic_match()
        with self.assertRaises(ValueError):
            replace(match, slot_team=np.array(["H", "?"]))
        with self.assertRaises(ValueError):
            replace(match, half=np.full(8, 3, dtype=np.int8))

    def test_units_and_speed_missingness(self):
        match = synthetic_match()
        for kwargs in ({"fps": 0}, {"pitch_m": (105.3, np.inf)},
                       {"ball_speed_mps": np.ones(8)},
                       {"ball_speed_mps": np.full(8, -1.)}):
            with self.subTest(kwargs=list(kwargs)), self.assertRaises(ValueError):
                replace(match, **kwargs)
        speed = np.full(8, np.nan)
        speed[0] = 0
        replace(match, ball_speed_mps=speed)

    def test_event_boundaries_must_be_clipped_nonempty_integers(self):
        match = synthetic_match()
        for start, end in ((-1, 3), (3, 3), (2, 9), (1., 3)):
            event = dict(match.events[0], start_frame=start, end_frame=end)
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                replace(match, events=[event])

    def test_feature_shapes_validity_and_evidence(self):
        match = synthetic_match()
        neutral = neutral_features(match)
        with self.assertRaises(ValueError):
            replace(neutral, features={"speed": np.zeros(8)})
        with self.assertRaises(ValueError):
            replace(neutral, team_evidence=np.full((8, 2), .9))
        with self.assertRaises(ValueError):
            replace(neutral, team_evidence=np.tile([1., 0.], (8, 1)))
        with self.assertRaises(ValueError):
            FeatureData(match.frame, {"distance": np.full(8, np.nan)},
                        {"distance": np.ones(8, dtype=bool)},
                        neutral.team_evidence, neutral.team_reliability)

    def test_priors_reject_nonfinite_reliability_and_non_neutral_absence(self):
        neutral = neutral_priors(synthetic_match())
        for kwargs in ({"dead_reliability": np.full(8, np.nan)},
                       {"dead_evidence": np.ones(8)},
                       {"restart_evidence": np.ones(7)},
                       {"tag_team_reliability": np.full(8, 2.)}):
            with self.subTest(kwargs=list(kwargs)), self.assertRaises(ValueError):
                replace(neutral, **kwargs)

    def test_predictions_reject_invalid_labels_and_dimensions(self):
        for labels in (np.array(["h"]), np.array(["HH"]), np.array([""]),
                       np.array([["H"]]), ["H"]):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                Prediction(labels)


if __name__ == "__main__":
    unittest.main()
