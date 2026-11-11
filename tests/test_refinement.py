"""Invented refinement scenarios, including adversarial negatives and integration."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from possession.dead_ball import build_priors, CONFIRMED_RESTART
from possession.export import write_submission
from possession.pipeline import predict_match
from possession.run_manifest import write_run_manifest
from possession.state_machine import StateMachineConfig, decode
from tests.e2_scenarios import evidence_sequence, label_transitions
from tests.test_dead_ball import match_input

CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'configs/possession-v2.json').read_text())


def decoded(symbols, config=None, **kwargs):
    return decode(*evidence_sequence(symbols, **kwargs), config=CONFIG if config is None else config)


class RefinementTests(unittest.TestCase):
    def test_unknown_restart_uses_nearby_confirmed_team(self):
        out = decoded('D'*30 + 'R'*20 + 'A'*30)
        np.testing.assert_array_equal(out.labels, list('D'*30 + 'A'*50))
        self.assertEqual(out.diagnostics['live_unknown_frames'], 0)
        self.assertEqual(label_transitions(out.labels), [(30, 'D', 'A')])
        self.assertEqual(out.diagnostics['confirmations'][-1]['frame'], 57)

    def test_unresolvable_live_is_unknown_not_stopped_or_invented_team(self):
        out = decoded('D'*30 + 'R'*200)
        np.testing.assert_array_equal(out.labels, list('D'*30 + 'X'*200))
        self.assertEqual(out.diagnostics['live_unknown_frames'], 200)

    def test_restart_lookahead_is_bounded(self):
        out = decoded('D'*30 + 'R'*60 + 'A'*30)
        np.testing.assert_array_equal(out.labels[30:90], 'X')
        self.assertEqual(out.diagnostics['live_unknown_frames'], 60)

    def test_unknown_assignment_cannot_cross_stop_half_or_conflicting_team(self):
        for symbols in ('D'*30+'R'*10+'D'*10+'A'*30,
                        'D'*30+'R'*10+'H'*2+'A'*30):
            out = decoded(symbols)
            self.assertTrue(np.all(out.labels[30:40] == 'X'))
        symbols = 'D'*30+'R'*10+'A'*30
        out = decoded(symbols, half=[1]*40+[2]*30)
        np.testing.assert_array_equal(out.labels[30:40], 'X')
        np.testing.assert_array_equal(out.labels[40:], 'A')

    def test_pending_tracking_survives_incumbent_tag_gaps(self):
        m,f,p = evidence_sequence('H'*30 + ('A'*14+'.')*10)
        # Below the strong-control threshold: must exercise normal accumulation.
        f.team_reliability[f.team_reliability > 0] = .6
        p.tag_team_evidence[:] = [1.,0.]
        p.tag_team_reliability[:] = .5
        out = decode(m,f,p,CONFIG)
        self.assertTrue(np.all(out.labels[30:] == 'A'))
        self.assertGreater(out.diagnostics['protected_tracking_frames'], 0)

    def test_tracking_opposition_still_cancels_pending_turnover(self):
        m,f,p = evidence_sequence('H'*30 + 'A'*7 + 'H' + 'A'*7 + 'H'*30)
        out = decode(m,f,p,CONFIG)
        self.assertFalse(np.any(out.labels == 'A'))

    def test_protection_expires_and_tags_can_decide_without_tracking(self):
        m,f,p = evidence_sequence('H'*30+'A'*7+'.'*200)
        p.tag_team_evidence[:] = [1.,0.]
        p.tag_team_reliability[:] = .5
        out = decode(m,f,p,CONFIG)
        # A's last support is at 36; its protected lifetime ends after 150 frames.
        self.assertLessEqual(out.diagnostics['protected_tracking_frames'],150)
        self.assertEqual(out.labels[-1], 'H')
        m,f,p = evidence_sequence('.'*40)
        p.tag_team_evidence[:] = [0.,1.]
        p.tag_team_reliability[:] = .5
        out = decode(m,f,p,CONFIG)
        np.testing.assert_array_equal(out.labels, 'A')
        self.assertEqual(out.diagnostics['confirmations'][0]['frame'],14)

    def test_strong_short_possession_survives_and_boundaries_are_refined(self):
        out = decoded('H'*30+'A'*14+'H'*30)
        np.testing.assert_array_equal(out.labels, list('H'*30+'A'*14+'H'*30))
        self.assertEqual(label_transitions(out.labels), [(30,'H','A'),(44,'A','H')])
        self.assertEqual([t['frame'] for t in out.diagnostics['transitions']], [30,44])

    def test_brief_deflections_and_weak_short_possessions_remain_filtered(self):
        for length in (1,2,7):
            self.assertFalse(np.any(decoded('H'*30+'A'*length+'H'*30).labels=='A'))
        m,f,p = evidence_sequence('H'*30+'A'*14+'H'*30)
        f.team_reliability[:] = .6
        self.assertFalse(np.any(decode(m,f,p,CONFIG).labels=='A'))

    def test_strong_confirmation_requires_consecutive_tracking(self):
        out = decoded('H'*30+'A'*4+'.'+'A'*4+'H'*30)
        self.assertFalse(np.any(out.labels=='A'))

    def test_short_possession_at_end_of_half_is_not_discarded(self):
        np.testing.assert_array_equal(decoded('H'*30+'A'*14).labels[-14:], 'A')

    def test_long_occlusion_is_not_backdated_to_old_support(self):
        m,f,p = evidence_sequence('H'*30+'A'*7+'.'*100+'A'*8)
        f.team_reliability[f.team_reliability>0] = .6
        out = decode(m,f,p,CONFIG)
        self.assertEqual(label_transitions(out.labels), [(137,'H','A')])

    def test_stop_latch_cannot_be_bypassed_by_short_strong_tracking(self):
        out = decoded('D'*30+'A'*74)
        np.testing.assert_array_equal(out.labels,'D')
        out = decoded('D'*30+'A'*75)
        np.testing.assert_array_equal(out.labels[:-1],'D')
        self.assertEqual(out.labels[-1],'A')

    def test_stop_and_restart_boundaries_remain_distinct(self):
        out = decoded('H'*30+'D'*10+'R'+'H'*30)
        np.testing.assert_array_equal(out.labels,list('H'*30+'D'*10+'H'*31))
        self.assertEqual(label_transitions(out.labels),[(30,'H','D'),(40,'D','H')])

    def test_no_refinement_crosses_excluded_frames_or_half(self):
        m,f,p=evidence_sequence('H'*30+'A'*4+'A'*4+'H'*30,
                               half=[1]*34+[2]*34)
        out=decode(m,f,p,CONFIG)
        self.assertFalse(np.any(out.labels=='A'))
        m,f,p=evidence_sequence('H'*30+'.'*4+'A'*30,half=[1]*30+[0]*4+[2]*30)
        out=decode(m,f,p,CONFIG)
        np.testing.assert_array_equal(out.labels[30:34],'X')
        np.testing.assert_array_equal(out.labels[34:],'A')

    def test_fps_scaling_and_custom_zero_backdate(self):
        for fps in (10.,25.,50.):
            k=int(np.ceil(.32*fps))
            out=decoded('H'*50+'A'*(k-1)+'H'*50, fps=fps)
            self.assertFalse(np.any(out.labels=='A'))
            out=decoded('H'*50+'A'*k+'H'*50, fps=fps)
            np.testing.assert_array_equal(out.labels[50:50+k],'A')
        config=copy.deepcopy(CONFIG)
        config['state_machine']['max_backdate_s']=0
        out=decoded('H'*30+'A'*30,config)
        self.assertEqual(label_transitions(out.labels)[-1],(37,'H','A'))

    def test_swap_symmetry_determinism_and_no_input_mutation(self):
        args=evidence_sequence('H'*30+'D'*10+'R'*4+'A'*14+'H'*30)
        original=copy.deepcopy(args)
        first=decode(*args,CONFIG)
        second=decode(*args,CONFIG)
        np.testing.assert_array_equal(first.labels,second.labels)
        self.assertEqual(first.diagnostics,second.diagnostics)
        np.testing.assert_array_equal(args[1].team_evidence,original[1].team_evidence)
        np.testing.assert_array_equal(args[2].dead_evidence,original[2].dead_evidence)
        args[1].team_evidence=args[1].team_evidence[:,::-1].copy()
        args[2].tag_team_evidence=args[2].tag_team_evidence[:,::-1].copy()
        swapped=decode(*args,CONFIG)
        expected=[{'H':'A','A':'H'}.get(x,x) for x in first.labels]
        np.testing.assert_array_equal(swapped.labels,expected)

    def test_candidate_enables_gaps_and_preserves_restart_context(self):
        m=match_input(n=40,tagged=True)
        for i in (10,20,30):
            m.ball_observed[i]=False
            m.ball_xy_m[i]=np.nan
            m.ball_speed_mps[i]=np.nan
        m.ball_xy_m[31:,0]+=np.arange(1,10)*.3
        m.ball_speed_mps[31:]=3.
        p=build_priors(m,config=CONFIG)
        np.testing.assert_array_equal(np.flatnonzero(p.diagnostic_flags & CONFIRMED_RESTART),[32])
        np.testing.assert_array_equal(p.dead_reliability[[10,20,30]],0)

    def test_disabled_and_absent_tags_with_strict_decoder_floor(self):
        m,f,p=evidence_sequence('H'*30)
        config={'data':{'load_tags':False},'state_machine':{'team_reliability_min':.75}}
        self.assertEqual(decode(m,f,p,config).labels[-1],'H')
        del config['data']
        self.assertEqual(decode(m,f,p,config).labels[-1],'H')

    def test_config_rejects_invalid_types_bounds_and_weaker_strong_thresholds(self):
        for options in ({'offline_refinement':1}, {'max_backdate_s':-1},
                        {'restart_lookahead_s':float('inf')}, {'strong_team_dwell_s':0},
                        {'offline_refinement':True,'strong_team_dwell_s':1},
                        {'offline_refinement':True,'max_backdate_s':7},
                        {'offline_refinement':True,'strong_team_reliability':.1},
                        {'offline_refinement':True,'strong_team_margin':.1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                StateMachineConfig(**options)

    def test_candidate_fixes_the_baseline_counterexamples(self):
        legacy = copy.deepcopy(CONFIG)
        legacy['state_machine']['offline_refinement'] = False
        before = decoded('D'*30+'R'*20+'A'*30, legacy)
        after = decoded('D'*30+'R'*20+'A'*30)
        self.assertTrue(np.all(before.labels[30:50] == 'D'))
        self.assertTrue(np.all(after.labels[30:50] == 'A'))
        before = decoded('H'*30+'A'*14+'H'*30, legacy)
        self.assertFalse(np.any(before.labels == 'A'))
        self.assertEqual(np.count_nonzero(decoded('H'*30+'A'*14+'H'*30).labels == 'A'), 14)

    def test_seeded_half_independence_and_swap_symmetry(self):
        rng = np.random.default_rng(1024)
        for _ in range(60):
            symbols = ''.join(rng.choice(list('HAD.R'), 160))
            half = [1]*80 + [0]*3 + [2]*77
            args = evidence_sequence(symbols, half=half)
            result = decode(*args, CONFIG)
            suffix = decoded(symbols[83:], half=[2]*77)
            np.testing.assert_array_equal(result.labels[83:], suffix.labels)
            args[1].team_evidence = args[1].team_evidence[:, ::-1].copy()
            swapped = decode(*args, CONFIG)
            expected = [{'H':'A', 'A':'H'}.get(x,x) for x in result.labels]
            np.testing.assert_array_equal(swapped.labels, expected)
            np.testing.assert_array_equal(result.labels[80:83], 'X')
        self.assertEqual(len(decoded('').labels), 0)

    def test_full_length_real_stages_export_and_manifest(self):
        # The loader is the only stub: all geometry/priors/decoder/export are real.
        m=match_input(n=199319, fps=25.)
        m.half[:20]=0
        m.players_xy_m[:,0]=m.ball_xy_m+[.1,0.]
        m.players_xy_m[:,1]=m.ball_xy_m+[5.,0.]
        with patch('possession.pipeline.load_match',return_value=m):
            out=predict_match(config=CONFIG)
        np.testing.assert_array_equal(out.labels[:20],'X')
        np.testing.assert_array_equal(out.labels[20:],'H')
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            one=write_submission(out,target/'one.csv')
            two=write_submission(out,target/'two.csv')
            self.assertEqual(one.read_bytes(),two.read_bytes())
            manifest=write_run_manifest(out,one,target/'manifest.json')
            record=json.loads(manifest.read_text())
            self.assertEqual(record['checks']['official_validator'],'pass')
            self.assertEqual(record['config']['dead_ball']['max_missing_gap_s'],.2)

if __name__=='__main__': unittest.main()
