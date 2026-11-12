"""Human-terminal-only EPTS contract audit. No tracking rows or predictions read.

Run on restricted metadata only in a separate local terminal. Reports contain
categories rather than metadata contents, and are saved under ignored runs/.
"""

import argparse
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from games import GAME, GAMES, asset_paths  # noqa: E402
from possession.data import bundle_root  # noqa: E402


def audit_metadata(path, expected_fps):
    """Check explicit declarations; absent declarations never imply agreement.

    Schema reference: Kloppy v3.18.0 Metrica EPTS metadata/models. The team's
    raw reader assumes normalized x,y,s ball records and one record per frame.
    This verifies that assumption, not tracking accuracy or physical placement.
    """
    root = ET.parse(path).getroot()
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    position = root.find(".//Sensor[@id='position']")
    channels = {} if position is None else {
        channel.get("id"): (channel.findtext("Unit") or "").strip().casefold()
        for channel in position.findall("Channels/Channel")}
    if not channels.get("x") or not channels.get("y"):
        units = "POSITION_UNITS_UNVERIFIED"
    elif channels["x"] == channels["y"] == "normalized":
        units = "NORMALIZED_XY_DECLARED"
    else:
        units = "POSITION_UNITS_NOT_NORMALIZED"
    specifications = root.findall(".//DataFormatSpecification")
    layout = "RAW_LAYOUT_UNVERIFIED"
    if specifications:
        matched = True
        for spec in specifications:
            children = list(spec)
            if (spec.get("separator") != ":" or len(children) != 3
                    or children[0].tag != "StringRegister"
                    or children[1].tag != "SplitRegister" or children[1].get("separator") != ";"
                    or children[2].tag != "SplitRegister" or children[2].get("separator") != ","
                    or [child.tag for child in children[2]] != ["BallChannelRef"]*3
                    or [child.get("channelId") for child in children[2]] != ["x", "y", "s"]):
                matched = False
        layout = "RAW_XY_SPEED_LAYOUT_DECLARED" if matched else "RAW_LAYOUT_DIFFERS_FROM_READER"
    try:
        fps = float(root.findtext(".//GlobalConfig/FrameRate"))
        rate = "FRAME_RATE_MATCHES" if fps == expected_fps else "FRAME_RATE_DIFFERS"
    except (TypeError, ValueError):
        rate = "FRAME_RATE_UNVERIFIED"
    return {"position_units": units, "raw_layout": layout, "frame_rate": rate}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", help="bundle root; defaults to MTAH_DATA_DIR or ./data")
    args = parser.parse_args(argv)
    paths = asset_paths(data_dir=bundle_root(args.data_dir))
    report = audit_metadata(paths["atd_meta"], GAMES[GAME]["fps"])
    destination = ROOT / "runs" / "kickoff-source-audit.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join("{}: {}".format(key, value)
                                   for key, value in report.items()) + "\n", encoding="utf-8")
    print("Saved runs/kickoff-source-audit.txt. Inspect locally.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
