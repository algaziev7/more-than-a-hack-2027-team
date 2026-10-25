import json
from pathlib import Path
import random
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from games import GAME, GAMES
from possession.contracts import Prediction
from possession.export import write_submission
from scripts.predict import load_config, run_prediction
from tests.fixtures import synthetic_prediction


class ExportCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_exact_bytes_and_stable_newlines(self):
        prediction = synthetic_prediction()
        path = write_submission(prediction, self.root / 'nested' / 'one.csv', n_expected=8)
        expected = 'frame,label\n' + ''.join(f'{i},{v}\n' for i, v in enumerate('XHHXXAAX'))
        self.assertEqual(path.read_bytes(), expected.encode('utf-8'))
        second = write_submission(prediction, self.root / 'two.csv', n_expected=8)
        self.assertEqual(path.read_bytes(), second.read_bytes())

    def test_invalid_predictions_do_not_replace_existing_output(self):
        target = self.root / 'result.csv'
        target.write_bytes(b'previous')
        with self.assertRaises(ValueError):
            write_submission(synthetic_prediction(), target)
        prediction = synthetic_prediction()
        prediction.labels[2] = '?'
        with self.assertRaises(ValueError):
            write_submission(prediction, target, n_expected=8)
        self.assertEqual(target.read_bytes(), b'previous')

    def test_failed_write_cleans_temporary_file(self):
        target = self.root / 'result.csv'
        target.write_bytes(b'previous')
        with patch('possession.export.os.replace', side_effect=OSError('write failure')):
            with self.assertRaises(OSError):
                write_submission(synthetic_prediction(), target, n_expected=8)
        self.assertEqual(list(self.root.iterdir()), [target])
        self.assertEqual(target.read_bytes(), b'previous')

    def test_json_duplicates_nonfinite_and_invalid_versions_fail(self):
        path = self.root / 'config.json'
        for content in ('{"seed":0,"seed":1}', '{"seed":NaN}', '{"schema_version":2}', '[]', '{'):
            path.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                load_config(path)
        path.write_text('{"schema_version":1,"seed":42}')
        self.assertEqual(load_config(path)['seed'], 42)

    def test_cli_seeds_and_delegates_to_e5_and_exports_full_length(self):
        observed = []
        def predict_match(data_dir, config):
            observed.append((data_dir, config, random.random(), np.random.random()))
            return Prediction(np.full(GAMES[GAME]['n_video_frames'], 'X'))
        module = types.ModuleType('possession.pipeline')
        module.predict_match = predict_match
        config = {'schema_version': 1, 'seed': 11}
        with patch.dict(sys.modules, {'possession.pipeline': module}):
            first = run_prediction(self.root, config, self.root / 'one.csv')
            second = run_prediction(self.root, config, self.root / 'two.csv')
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(observed[0], observed[1])
        self.assertEqual(observed[0][0], self.root.resolve())
        self.assertEqual(len(first.read_text().splitlines()), 199320)

    def test_unavailable_e5_is_explicit_and_writes_no_output(self):
        target = self.root / 'result.csv'
        with patch('scripts.predict.importlib.import_module',
                   side_effect=ModuleNotFoundError(name='possession.pipeline')):
            with self.assertRaisesRegex(RuntimeError, 'E5 integration'):
                run_prediction(self.root, {}, target)
        self.assertFalse(target.exists())

    def test_internal_missing_dependency_is_not_misreported_as_missing_pipeline(self):
        with patch('scripts.predict.importlib.import_module',
                   side_effect=ModuleNotFoundError(name='missing_internal_dependency')):
            with self.assertRaises(ModuleNotFoundError):
                run_prediction(self.root, {}, self.root / 'result.csv')


if __name__ == '__main__':
    unittest.main()
