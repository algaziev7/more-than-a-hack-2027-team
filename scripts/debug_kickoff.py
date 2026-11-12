"""One human-run local kickoff investigation. Never run restricted inputs in AI tools.

Writes a private JSON/HTML report and a separate qualitative-only summary.
No network, labels from a human, threshold search, or prediction repair.
"""

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from games import asset_paths  # noqa: E402
from possession.data import bundle_root, load_match  # noqa: E402
from possession.dead_ball import (  # noqa: E402
    CONFIRMED_KICKOFF, LIVE_MOTION, CONFIRMED_RESTART, DeadBallConfig,
    _kickoff_context, _motion, _section, build_priors, summarize_kickoff_diagnostics,
    summarize_kickoff_coverage,
)
from possession.features import build_features  # noqa: E402
from possession.state_machine import (  # noqa: E402
    StateMachineConfig, _decisive_state_per_frame, decode,
)
from scripts.audit_kickoff_source import audit_metadata  # noqa: E402
from scripts.predict import load_config  # noqa: E402


def number(value):
    return float(value) if np.isfinite(value) else None


def investigate(match, features, priors, prediction, config, check_frame, half, window_s):
    """Pure analysis of supplied arrays; never opens source assets."""
    coverage = summarize_kickoff_coverage(match, check_frame, config)
    if int(match.half[check_frame]) != half:
        raise ValueError("check frame must belong to the selected half")
    settings = replace(StateMachineConfig(**config.get("state_machine", {})), fps=match.fps)
    _, is_dead, generic, _ = _decisive_state_per_frame(features, priors, settings)
    dead_settings = _section(config, "dead_ball", DeadBallConfig)
    usable, still, moving, _ = _motion(match, dead_settings)
    gates = summarize_kickoff_diagnostics(match, features, config)
    flags = priors.diagnostic_flags
    active = match.half == half
    context = _kickoff_context(match.events, len(match.frame))
    tag_edges = np.diff(np.r_[False, context & active, False].astype(int))
    tag_windows = [[int(start), int(end)] for start, end in zip(
        np.flatnonzero(tag_edges == 1), np.flatnonzero(tag_edges == -1))]
    first_generic = np.flatnonzero(active & generic)
    first_kickoff = np.flatnonzero(active & ((flags & CONFIRMED_KICKOFF) != 0))
    upper = min(len(match.frame)-1, check_frame+math.ceil(window_s*match.fps))
    prefix = np.flatnonzero(active & (match.frame <= upper))
    # Bounded display sampling; include exact evidence and check markers too.
    samples = prefix[np.linspace(0, len(prefix)-1, min(1200, len(prefix)), dtype=int)]
    markers = [check_frame]
    for found in (first_generic, first_kickoff):
        if len(found):
            at = int(found[0])
            markers.extend(range(max(0, at-int(window_s*match.fps)),
                                 min(len(match.frame), at+int(window_s*match.fps)+1)))
    samples = np.unique(np.r_[samples, markers])
    samples = samples[match.half[samples] == half]
    snapshots = []
    for i in samples:
        players = [[number(x), number(y), str(team)]
                   for (x, y), observed, team in zip(
                       match.players_xy_m[i], match.player_observed[i], match.slot_team)
                   if observed]
        ball = [number(v) for v in match.ball_xy_m[i]] if match.ball_observed[i] else None
        snapshots.append({
            "frame": int(i), "ball": ball, "players": players,
            "raw_speed": None if match.ball_speed_mps is None else number(match.ball_speed_mps[i]),
            "feature_speed": number(features.features["ball_speed_mps"][i]),
            "nearest_home": number(features.features["home_nearest_m"][i]),
            "nearest_away": number(features.features["away_nearest_m"][i]),
            "control_reliability": number(features.team_reliability[i]),
            "control": bool(features.team_reliability[i] >= .5
                            and features.team_evidence[i].max() >= .75),
            "team_evidence": [number(v) for v in features.team_evidence[i]],
            "start_tag_context": bool(context[i]),
            "dead_evidence": number(priors.dead_evidence[i]),
            "dead_reliability": number(priors.dead_reliability[i]),
            "restart_evidence": number(priors.restart_evidence[i]),
            "usable": bool(usable[i]), "still": bool(still[i]), "moving": bool(moving[i]),
            "dead": bool(is_dead[i]), "generic_opening_evidence": bool(generic[i]),
            "live_motion": bool(flags[i] & LIVE_MOTION),
            "restart_pulse": bool(flags[i] & CONFIRMED_RESTART),
            "kickoff": bool(flags[i] & CONFIRMED_KICKOFF),
            "label": str(prediction.labels[i]),
        })
    gate_status = ("HALF_START_GATE_TRACE_PRESENT" if "period_starts" in prediction.diagnostics
                   else "HALF_START_GATE_NOT_IN_CHECKOUT")
    return {
        "config": config, "half": half, "fps": match.fps, "pitch_m": list(match.pitch_m),
        "centre_radius_m": dead_settings.kickoff_centre_radius_m,
        "check_frame": check_frame, "coverage": coverage, "detector": gates,
        "decoder_status": gate_status,
        "decoder_period_starts": prediction.diagnostics.get("period_starts"),
        "start_tag_windows": tag_windows,
        "decoder_transitions": prediction.diagnostics.get("transitions", []),
        "first_generic_evidence": int(first_generic[0]) if len(first_generic) else None,
        "kickoff_confirmations": first_kickoff.tolist(), "snapshots": snapshots,
        "limits": ["Generic opening evidence is not an observed gate transition.",
                   "Current-checkout labels do not simulate unmerged PR #18.",
                   "The check frame is diagnostic only; no detector receives it.",
                   "Tracking accuracy and the referee's decision remain unverified.",
                   "Display snapshots are sampled; no missing position is filled."],
    }


HTML = r'''<!doctype html><meta charset="utf-8"><title>Private kickoff investigation</title>
<style>body{font:16px system-ui;max-width:1080px;margin:24px auto;background:#f5f5f5}
canvas{background:white;width:100%;border:1px solid #ccc}input{width:100%}pre{white-space:pre-wrap}
</style><h1>Private kickoff investigation — keep local</h1>
<p>Inspect source declarations and detector gates below, then scrub the tracking timeline.
Blue: H slots. Red: A slots. Yellow: observed ball. White ring: detector centre region.
Missing ball is not drawn. These are automatic tracking positions, not verified physical positions.</p>
<pre id="overview"></pre><button id="check">Go to check</button>
<button id="generic">Go to first generic signal</button><button id="kickoff">Go to first kickoff signal</button>
<label>Tracking timeline <input id="slider" type="range" min="0" value="0"></label>
<canvas id="pitch" width="1000" height="640"></canvas><pre id="snapshot"></pre>
<details><summary>All private diagnostic gates</summary><pre id="gates"></pre></details>
<script>const report=__REPORT__;
const rows=report.snapshots, slider=document.getElementById('slider');slider.max=rows.length-1;
document.getElementById('overview').textContent=JSON.stringify({source:report.source,
decoder_status:report.decoder_status,check_frame:report.check_frame,
first_generic_evidence:report.first_generic_evidence,kickoff_confirmations:report.kickoff_confirmations,
start_tag_windows:report.start_tag_windows,
coverage:report.coverage,limits:report.limits},null,2);
document.getElementById('gates').textContent=JSON.stringify(report.detector,null,2);
const canvas=document.getElementById('pitch'),ctx=canvas.getContext('2d');
function draw(){const row=rows[Number(slider.value)], [L,W]=report.pitch_m;
const s=Math.min(900/L,550/W),ox=45,oy=40;
ctx.clearRect(0,0,1000,640);ctx.fillStyle='#24583e';ctx.fillRect(ox,oy,L*s,W*s);
ctx.strokeStyle='white';ctx.strokeRect(ox,oy,L*s,W*s);ctx.beginPath();
ctx.moveTo(ox+L*s/2,oy);ctx.lineTo(ox+L*s/2,oy+W*s);ctx.stroke();ctx.beginPath();
ctx.arc(ox+L*s/2,oy+W*s/2,report.centre_radius_m*s,0,2*Math.PI);ctx.stroke();
for(const [x,y,team] of row.players){ctx.fillStyle=team==='H'?'#65aaff':'#ff7777';
ctx.beginPath();ctx.arc(ox+x*s,oy+y*s,4,0,2*Math.PI);ctx.fill();}
if(row.ball){ctx.fillStyle='#ffdf00';ctx.beginPath();ctx.arc(ox+row.ball[0]*s,oy+row.ball[1]*s,5,0,2*Math.PI);ctx.fill();}
document.getElementById('snapshot').textContent=JSON.stringify({...row,players:row.players.length},null,2);}
slider.addEventListener('input',draw);
for(const [id,at] of [['check',report.check_frame],['generic',report.first_generic_evidence],
['kickoff',report.kickoff_confirmations.length?report.kickoff_confirmations[0]:null]]){
const button=document.getElementById(id);button.disabled=at===null;
button.addEventListener('click',()=>{let closest=0;for(let i=1;i<rows.length;i++){
if(Math.abs(rows[i].frame-at)<Math.abs(rows[closest].frame-at))closest=i;}slider.value=closest;draw();});}
draw();</script>'''


def write_reports(report, destination):
    destination.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, allow_nan=False, indent=2)
    (destination/"private-report.json").write_text(text+"\n", encoding="utf-8")
    # Escape script delimiters even when config contains user-supplied strings.
    (destination/"private-report.html").write_text(
        HTML.replace("__REPORT__", text.replace("<", "\\u003c")), encoding="utf-8")
    period = report["detector"]["periods"].get(str(report["half"]), {})
    safe = {**{key: report["source"].get(key, "UNVERIFIED")
               for key in ("position_units", "raw_layout", "frame_rate")},
            "decoder_status": report["decoder_status"],
            "detector_stage": period.get("stage", "E3_DISABLED_OR_PERIOD_ABSENT"),
            "settlement_detail": period.get("settlement_detail", "NOT_APPLICABLE"),
            **{key: value for key, value in report["coverage"].items() if key != "counts"},
            "calibration": "PHYSICAL_TRACKING_ACCURACY_UNVERIFIED"}
    (destination/"shareable-summary.txt").write_text(
        "\n".join("{}: {}".format(key, value) for key, value in safe.items())+"\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/input-v1.json")
    parser.add_argument("--data-dir")
    parser.add_argument("--check-frame", type=int, required=True,
                        help="published frame for diagnostics only; never passed to inference")
    parser.add_argument("--half", type=int, choices=[1, 2], default=2)
    parser.add_argument("--window-s", type=float, default=10,
                        help="display window only; never changes detector configuration")
    args = parser.parse_args(argv)
    if not math.isfinite(args.window_s) or not 0 < args.window_s <= 60:
        parser.error("display window must be positive and at most 60 seconds")
    config = load_config(args.config)
    match = load_match(data_dir=args.data_dir, config=config)
    # Finish real inference before any diagnostic use of the check frame.
    features = build_features(match, config=config)
    priors = build_priors(match, features=features, config=config)
    prediction = decode(match, features, priors, config=config)
    report = investigate(match, features, priors, prediction, config,
                         args.check_frame, args.half, args.window_s)
    paths = asset_paths(data_dir=bundle_root(args.data_dir))
    report["source"] = audit_metadata(paths["atd_meta"], match.fps)
    write_reports(report, ROOT/"runs"/"kickoff-debug")
    print("Saved runs/kickoff-debug/. Open private-report.html locally.")
    print("Only shareable-summary.txt is intended to be shared; keep the private reports local.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
