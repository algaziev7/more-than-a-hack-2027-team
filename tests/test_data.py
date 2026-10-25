import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from games import GAME
from possession.data import bundle_root, load_match, read_events, read_slot_teams, read_tracking, validate_config

META = '<Tracking><Team id="home"/><Team id="away"/><Player teamId="home"/><Player teamId="away"/></Tracking>'
ROWS = [
    '1:0,0,0;1,1,2:0.5,0.25,4',
    '2:0.1,0.2,1;NaN,NaN,NaN:NaN,NaN,NaN',
    '3:0.2,0.2,1;0.8,0.8,1:1.01,-0.1,0',
    '4:0.3,0.2,1;0.7,0.8,1:0.25,0.5,NaN',
]


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        folder = self.root / 'tactical'
        folder.mkdir()
        self.meta = folder / 'BAR-ATH_tactical_atd.xml'
        self.raw = folder / 'BAR-ATH_tactical_atd.txt'
        self.tags = folder / 'BAR-ATH_tactical_smart_tagging.xml'
        self.meta.write_text(META, encoding='utf-8')
        self.write_rows(ROWS)
        self.teams = np.array(['H', 'A'])

    def write_rows(self, rows):
        self.raw.write_text('\n'.join(rows) + '\n', encoding='utf-8')

    def load_small(self, config=None):
        spec = {GAME: {'n_video_frames': 4, 'fps': 25, 'pitch': (105.3, 68.)}}
        with patch('possession.data.GAMES', spec), patch(
                'possession.data.half_video_blocks', return_value=[(1, 0, 1), (2, 3, 3)]):
            return load_match(self.root, config, cache_dir=self.root / 'cache')

    def test_slot_mapping_uses_metadata_order_and_rejects_unknown_ids(self):
        np.testing.assert_array_equal(read_slot_teams(self.meta), self.teams)
        for metadata in (META.replace('teamId="away"', 'teamId="other"'),
                         META.replace('id="away"', 'id="home"'), '<Tracking/>'):
            self.meta.write_text(metadata, encoding='utf-8')
            with self.assertRaises(ValueError):
                read_slot_teams(self.meta)

    def test_metres_missingness_speed_and_outside_pitch_preserved(self):
        ball, players, speed = read_tracking(self.raw, self.teams, 4, (105.3, 68.))
        np.testing.assert_allclose(ball[0], [52.65, 17.])
        np.testing.assert_allclose(players[0, 1], [105.3, 68.])
        self.assertTrue(np.isnan(ball[1]).all())
        self.assertTrue(np.isnan(players[1, 1]).all())
        self.assertGreater(ball[2, 0], 105.3)
        self.assertLess(ball[2, 1], 0)
        self.assertEqual(speed[0], 4.)
        self.assertTrue(np.isnan(speed[3]))

    def test_missing_coordinates_ignore_numeric_speed_placeholders(self):
        # Invented inputs: speed need not be absent when a track is missing.
        for placeholder in ('0', '2.5', '-1', 'inf', 'NaN'):
            self.write_rows([
                ROWS[0],
                f'2:0.1,0.2,1;NaN,NaN,{placeholder}:NaN,NaN,{placeholder}',
                *ROWS[2:],
            ])
            with self.subTest(placeholder=placeholder):
                ball, players, speed = read_tracking(self.raw, self.teams, 4, (105.3, 68.))
                self.assertTrue(np.isnan(ball[1]).all())
                self.assertTrue(np.isnan(players[1, 1]).all())
                self.assertTrue(np.isnan(speed[1]))
                self.assertEqual(speed[0], 4.)

    def test_missing_position_speed_is_masked_in_match_and_cache(self):
        self.write_rows([ROWS[0], '2:0.1,0.2,1;NaN,NaN,0:NaN,NaN,3', *ROWS[2:]])
        config = {'data': {'cache': True}}
        match = self.load_small(config)
        with patch('possession.data.read_tracking', side_effect=AssertionError('cache miss')):
            cached = self.load_small(config)
        for loaded in (match, cached):
            self.assertFalse(loaded.ball_observed[1])
            self.assertFalse(loaded.player_observed[1, 1])
            self.assertTrue(np.isnan(loaded.ball_speed_mps[1]))
            self.assertEqual(loaded.ball_speed_mps[0], 4.)

    def test_every_id_is_checked_including_middle_order_and_duplicates(self):
        for ids in ([1, 3, 2, 4], [1, 2, 2, 4], [0, 1, 2, 3], [1, 2, 4, 5]):
            self.write_rows([str(i) + row[row.index(':'):] for i, row in zip(ids, ROWS)])
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, 'frame IDs'):
                read_tracking(self.raw, self.teams, 4, (105.3, 68.))

    def test_truncated_extra_and_blank_records_fail(self):
        for rows in (ROWS[:3], ROWS + [ROWS[-1]], [ROWS[0], '', *ROWS[2:]]):
            self.write_rows(rows)
            with self.subTest(count=len(rows)), self.assertRaises(ValueError):
                read_tracking(self.raw, self.teams, 4, (105.3, 68.))

    def test_malformed_observations_fail_without_leaking_rows(self):
        for ball in ('NaN,0,0', '0,inf,0', '0,0,-1', '0,0,inf', 'secret,0,0',
                     '0,0', 'NaN,NaN,secret'):
            self.write_rows([f'1:0,0,0;1,1,2:{ball}', *ROWS[1:]])
            with self.subTest(ball=ball), self.assertRaises(ValueError) as caught:
                read_tracking(self.raw, self.teams, 4, (105.3, 68.))
            self.assertNotIn('secret', str(caught.exception))
        self.write_rows([ROWS[0].replace(';1,1,2', ''), *ROWS[1:]])
        with self.assertRaisesRegex(ValueError, 'slot count'):
            read_tracking(self.raw, self.teams, 4, (105.3, 68.))

    def test_loader_halves_optional_tags_and_no_input_mutation(self):
        config = {'schema_version': 1, 'data': {'cache': False}}
        before = copy.deepcopy(config)
        match = self.load_small(config)
        np.testing.assert_array_equal(match.half, [1, 1, 0, 2])
        np.testing.assert_array_equal(match.ball_observed, [True, False, True, True])
        self.assertEqual(match.events, [])
        self.assertFalse(match.metadata['tags_available'])
        self.assertEqual(config, before)
        self.assertNotIn(str(self.root), json.dumps(match.metadata))

    def test_event_rounding_clipping_overlap_and_original_tags(self):
        self.tags.write_text('''<root>
          <instance><start>-1</start><end>0.06</end><code>SET PIECES</code>
            <label><group>Team</group><text>N/A</text></label></instance>
          <instance><start>0.02</start><end>2</end><code>BUILD UP</code>
            <label><group>Team</group><text>Barcelona</text></label></instance>
          <instance><start>2</start><end>3</end><code>EMPTY</code></instance>
        </root>''', encoding='utf-8')
        events = read_events(self.tags, 4, 25)
        self.assertEqual([(e['start_frame'], e['end_frame']) for e in events], [(0, 2), (0, 4)])
        self.assertEqual(events[0]['tags'], {'Team': 'N/A'})
        self.assertEqual(self.load_small().events, events)
        self.assertEqual(self.load_small({'data': {'load_tags': False}}).events, [])

    def test_invalid_event_intervals_rejected(self):
        for start, end in (('NaN', '1'), ('2', '1'), ('bad', '1')):
            self.tags.write_text(f'<root><instance><start>{start}</start><end>{end}</end></instance></root>')
            with self.assertRaises(ValueError):
                read_events(self.tags, 4, 25)

    def test_loaded_events_are_compatible_with_merged_tagging_and_prior_contract(self):
        from possession.contracts import PriorData
        from possession.tagging import build_tagging_signals

        self.tags.write_text('''<root><instance><start>0.04</start><end>0.12</end>
          <code>BUILD UP</code><label><group>Team</group><text>Barcelona</text></label>
        </instance></root>''', encoding='utf-8')
        match = self.load_small()
        original = copy.deepcopy(match.events)
        signals = build_tagging_signals(match.events, n_frames=len(match.frame))
        priors = PriorData(**{name: np.asarray(getattr(signals, name)) for name in (
            'dead_evidence', 'dead_reliability', 'restart_evidence',
            'tag_team_evidence', 'tag_team_reliability', 'diagnostic_flags')})
        np.testing.assert_array_equal(signals.frame, match.frame)
        np.testing.assert_array_equal(priors.tag_team_evidence[1:3], [[1., 0.], [1., 0.]])
        np.testing.assert_array_equal(priors.tag_team_reliability, [0., .5, .5, 0.])
        self.assertEqual(match.events, original)

    def test_cache_hit_and_input_config_invalidation(self):
        config = {'data': {'cache': True}}
        first = self.load_small(config)
        with patch('possession.data.read_tracking', side_effect=AssertionError('cache miss')):
            cached = self.load_small(config)
        np.testing.assert_equal(cached.ball_xy_m, first.ball_xy_m)
        np.testing.assert_array_equal(cached.half, first.half)
        changed_config = self.load_small({'data': {'cache': True}, 'seed': 1})
        self.assertNotEqual(first.metadata['cache_key'], changed_config.metadata['cache_key'])
        self.write_rows([ROWS[0].replace('0.5,0.25,4', '0.4,0.25,4'), *ROWS[1:]])
        changed_input = self.load_small(config)
        self.assertNotEqual(first.metadata['cache_key'], changed_input.metadata['cache_key'])
        self.assertNotEqual(first.ball_xy_m[0, 0], changed_input.ball_xy_m[0, 0])

    def test_cache_metadata_tags_schema_and_code_invalidation(self):
        config = {'data': {'cache': True}}
        first = self.load_small(config)
        self.meta.write_text(META + '\n')
        changed_meta = self.load_small(config)
        self.assertNotEqual(first.metadata['cache_key'], changed_meta.metadata['cache_key'])
        self.tags.write_text('<root/>')
        with_tags = self.load_small(config)
        self.assertNotEqual(changed_meta.metadata['cache_key'], with_tags.metadata['cache_key'])
        with patch('possession.data.SCHEMA_VERSION', 2):
            changed_schema = self.load_small(config)
        self.assertNotEqual(with_tags.metadata['cache_key'], changed_schema.metadata['cache_key'])
        # Source-file digests are part of the key; no need to edit actual code in a test.
        from possession.data import sha256_file
        def changed_digest(path):
            return 'new-code' if Path(path).name == 'contracts.py' else sha256_file(path)
        with patch('possession.data.sha256_file', side_effect=changed_digest):
            changed_code = self.load_small(config)
        self.assertNotEqual(with_tags.metadata['cache_key'], changed_code.metadata['cache_key'])

    def test_corrupt_cache_rebuilt_and_pickle_disallowed(self):
        config = {'data': {'cache': True}}
        match = self.load_small(config)
        cache = self.root / 'cache' / (match.metadata['cache_key'] + '.npz')
        cache.write_bytes(b'broken')
        rebuilt = self.load_small(config)
        np.testing.assert_equal(match.ball_xy_m, rebuilt.ball_xy_m)
        with np.load(cache, allow_pickle=False) as archive:
            self.assertFalse(any(archive[name].dtype.hasobject for name in archive.files))

    def test_malformed_cache_json_is_rebuilt(self):
        config = {'data': {'cache': True}}
        match = self.load_small(config)
        cache = self.root / 'cache' / (match.metadata['cache_key'] + '.npz')
        for info in ('null', '[]', '{"metadata":null}'):
            np.savez(cache, info=np.array(info))
            rebuilt = self.load_small(config)
            np.testing.assert_equal(rebuilt.ball_xy_m, match.ball_xy_m)

    def test_inputs_changing_during_load_are_rejected(self):
        from possession.data import read_tracking as original
        def changing_input(*args):
            arrays = original(*args)
            self.write_rows([ROWS[0].replace('0.5,0.25,4', '0.4,0.25,4'), *ROWS[1:]])
            return arrays
        with patch('possession.data.read_tracking', side_effect=changing_input):
            with self.assertRaisesRegex(ValueError, 'changed during loading'):
                self.load_small()

    def test_missing_and_mistyped_paths_are_actionable(self):
        with self.assertRaisesRegex(FileNotFoundError, 'MTAH_DATA_DIR'):
            bundle_root(self.root / 'missing')
        self.raw.unlink()
        with self.assertRaisesRegex(FileNotFoundError, 'tactical'):
            self.load_small()

    def test_environment_is_read_at_call_time(self):
        with patch.dict(os.environ, {'MTAH_DATA_DIR': str(self.root)}):
            self.assertEqual(bundle_root(), self.root.resolve())

    def test_invalid_config_and_paths_rejected(self):
        for config in ([], {'schema_version': 2}, {'schema_version': True}, {'seed': -1},
                       {'seed': True}, {'data': {'cache': 'yes'}},
                       {'data': {'data_dir': '/private/local'}}, {'state': {'x': float('nan')}},
                       {'model': {'path': '/private/local'}}, {'model': {'path': 'C:\\private\\local'}},
                       {'state': {1: 'value'}}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_config(config)


if __name__ == '__main__':
    unittest.main()
