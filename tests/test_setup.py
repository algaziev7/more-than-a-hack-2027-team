import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_setup import check_data, inspect_video
from tests.fixtures import synthetic_match


class SetupTests(unittest.TestCase):
    def test_private_inventory_records_missing_assets_without_loading_video(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('scripts.check_setup.load_match', return_value=synthetic_match()):
                report = check_data(root, inventory=True)
            self.assertEqual(len(report['assets']), 9)
            self.assertTrue(all(not value['present'] for value in report['assets'].values()))
            self.assertNotIn(str(root), json.dumps(report))

    @patch('scripts.check_setup.shutil.which', return_value='/synthetic/ffprobe')
    def test_reference_video_count_and_format_checked(self, _):
        for count, fps, width, success in ((199319, '25/1', 1920, True),
                                           (199318, '25/1', 1920, False),
                                           (199319, '30/1', 1920, False),
                                           (199319, '25/1', 1280, False)):
            output = {'streams': [{'nb_read_frames': str(count), 'avg_frame_rate': fps,
                                    'width': width, 'height': 1080}]}
            result = subprocess.CompletedProcess([], 0, json.dumps(output), '')
            with patch('scripts.check_setup.subprocess.run', return_value=result):
                if success:
                    self.assertEqual(inspect_video('synthetic.mp4')['frame_count'], 199319)
                else:
                    with self.assertRaises(ValueError):
                        inspect_video('synthetic.mp4')

    @patch('scripts.check_setup.shutil.which', return_value=None)
    def test_missing_optional_decoder_is_actionable(self, _):
        with self.assertRaisesRegex(RuntimeError, 'ffprobe'):
            inspect_video('synthetic.mp4')


if __name__ == '__main__':
    unittest.main()
