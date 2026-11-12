"""Public-schema contract checks using invented EPTS metadata and tracking."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np

from games import GAME
from possession.data import load_match
from possession.dead_ball import CONFIRMED_KICKOFF, build_priors
from possession.features import build_features
from scripts.audit_kickoff_source import audit_metadata
from scripts import audit_kickoff_source as audit_cli
from tests.test_kickoff import kickoff_match


METADATA = '''<root><Metadata>
<GlobalConfig><FrameRate>25</FrameRate></GlobalConfig>
<Teams><Team id="home"/><Team id="away"/></Teams>
<Players><Player teamId="home"/><Player teamId="away"/></Players>
<Devices><Device><Sensors><Sensor id="position"><Channels>
<Channel id="x"><Unit>normalized</Unit></Channel>
<Channel id="y"><Unit>normalized</Unit></Channel>
</Channels></Sensor></Sensors></Device></Devices>
</Metadata><DataFormatSpecifications>
<DataFormatSpecification separator=":" startFrame="1" endFrame="999">
<StringRegister name="frameCount"/><SplitRegister separator=";"/>
<SplitRegister separator=","><BallChannelRef channelId="x"/>
<BallChannelRef channelId="y"/><BallChannelRef channelId="s"/></SplitRegister>
</DataFormatSpecification></DataFormatSpecifications></root>'''


class KickoffSourceTests(unittest.TestCase):
    def test_audit_command_needs_only_metadata_and_keeps_contents_local(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tactical = root/"tactical"
            tactical.mkdir()
            (tactical/"BAR-ATH_tactical_atd.xml").write_text(METADATA)
            console = io.StringIO()
            with patch.object(audit_cli, "ROOT", root), contextlib.redirect_stdout(console):
                self.assertEqual(audit_cli.main(["--data-dir", str(root)]), 0)
            report = (root/"runs"/"kickoff-source-audit.txt").read_text()
            self.assertIn("NORMALIZED_XY_DECLARED", report)
            self.assertNotIn("<", report)
            self.assertNotIn("NORMALIZED_XY_DECLARED", console.getvalue())

    def test_metadata_contract_is_explicit_and_mismatches_are_not_guessed(self):
        variants = (
            (METADATA, "NORMALIZED_XY_DECLARED", "RAW_XY_SPEED_LAYOUT_DECLARED", "FRAME_RATE_MATCHES"),
            (METADATA.replace("normalized", "meters"), "POSITION_UNITS_NOT_NORMALIZED",
             "RAW_XY_SPEED_LAYOUT_DECLARED", "FRAME_RATE_MATCHES"),
            (METADATA.replace('channelId="x"', 'channelId="s"'), "NORMALIZED_XY_DECLARED",
             "RAW_LAYOUT_DIFFERS_FROM_READER", "FRAME_RATE_MATCHES"),
            (METADATA.replace("<FrameRate>25</FrameRate>", "<FrameRate>50</FrameRate>"),
             "NORMALIZED_XY_DECLARED", "RAW_XY_SPEED_LAYOUT_DECLARED", "FRAME_RATE_DIFFERS"),
            ("<root/>", "POSITION_UNITS_UNVERIFIED", "RAW_LAYOUT_UNVERIFIED", "FRAME_RATE_UNVERIFIED"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"synthetic.xml"
            for source, units, layout, rate in variants:
                path.write_text(source)
                report = audit_metadata(path, 25)
                self.assertEqual(report, {"position_units": units, "raw_layout": layout,
                                          "frame_rate": rate})

    def test_normalized_centre_survives_actual_loader_features_and_priors(self):
        for fps in (25., 50.):
            original = kickoff_match(fps)
            with tempfile.TemporaryDirectory() as directory:
                bundle = Path(directory)
                tactical = bundle/"tactical"
                tactical.mkdir()
                (tactical/"BAR-ATH_tactical_atd.xml").write_text(
                    METADATA.replace("<FrameRate>25</FrameRate>",
                                     "<FrameRate>{}</FrameRate>".format(int(fps))))
                rows = []
                for i in range(len(original.frame)):
                    ball = original.ball_xy_m[i]/np.asarray(original.pitch_m)
                    players = original.players_xy_m[i]/np.asarray(original.pitch_m)
                    slots = ";".join("{},{},0".format(*xy) for xy in players)
                    rows.append("{}:{}:{},{},{}".format(i+1, slots, *ball,
                                                       original.ball_speed_mps[i]))
                (tactical/"BAR-ATH_tactical_atd.txt").write_text("\n".join(rows)+"\n")
                root = ET.Element("root")
                event = ET.SubElement(root, "instance")
                for key, value in (("start", "0"), ("end", "5"), ("code", "SET PIECES")):
                    ET.SubElement(event, key).text = value
                label = ET.SubElement(event, "label")
                ET.SubElement(label, "group").text = "Type"
                ET.SubElement(label, "text").text = "Kick Off (Start)"
                ET.ElementTree(root).write(tactical/"BAR-ATH_tactical_smart_tagging.xml")
                spec = {GAME: {"n_video_frames": len(original.frame), "fps": fps,
                               "pitch": original.pitch_m}}
                with patch("possession.data.GAMES", spec), patch(
                        "possession.data.half_video_blocks",
                        return_value=[(2, 0, len(original.frame)-1)]):
                    match = load_match(bundle, {"data": {"cache": False}})
                np.testing.assert_allclose(match.ball_xy_m[0], np.asarray(match.pitch_m)/2)
                np.testing.assert_allclose(match.ball_xy_m, original.ball_xy_m)
                priors = build_priors(match, build_features(match))
                self.assertEqual(np.count_nonzero(priors.diagnostic_flags & CONFIRMED_KICKOFF), 1)


if __name__ == "__main__":
    unittest.main()
