"""Human-only local video overlay for tracking-quality review, not annotation.

Run restricted inputs only in a separate local terminal. The generated page
uses a local video file picker; it uploads nothing and makes no network calls.
No possession labels, corrections or detector settings are produced.
"""

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from games import asset_paths  # noqa: E402
from possession.data import bundle_root, load_match  # noqa: E402
from possession.dead_ball import DeadBallConfig, _section  # noqa: E402
from starter.load_homography import load as load_homography, project  # noqa: E402
from scripts.predict import load_config  # noqa: E402


def project_metres(matrix, xy_m, pitch_m):
    """Canonical metres -> normalized pitch -> supplied image homography."""
    xy = np.asarray(xy_m, dtype=float)/np.asarray(pitch_m, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        x, y = project(matrix, xy[..., 0], xy[..., 1])
    return np.stack((x, y), axis=-1)


def image_point(value):
    return [float(x) for x in value] if np.isfinite(value).all() else None


def make_overlay(match, matrices, errors, valid, check_frame, window_s, radius_m):
    match.validate()
    n = len(match.frame)
    if matrices.shape != (n, 3, 3) or errors.shape != (n,) or valid.shape != (n,):
        raise ValueError("homography and tracking must use the same full timeline")
    if not 0 <= check_frame < n:
        raise ValueError("check frame must be inside the tracking timeline")
    if not math.isfinite(window_s) or not 0 < window_s <= 60:
        raise ValueError("display window must be positive and at most 60 seconds")
    if not math.isfinite(radius_m) or radius_m <= 0:
        raise ValueError("display radius must be positive")
    span = math.ceil(window_s*match.fps)
    start, end = max(0, check_frame-span), min(n-1, check_frame+span)
    centre = np.asarray(match.pitch_m)/2
    angle = np.linspace(0, 2*np.pi, 49)
    circle = centre + radius_m*np.column_stack((np.cos(angle), np.sin(angle)))
    pitch_lines = [np.array([[0, 0], [match.pitch_m[0], 0], match.pitch_m,
                            [0, match.pitch_m[1]], [0, 0]], dtype=float),
                   np.array([[centre[0], 0], [centre[0], match.pitch_m[1]]])]
    frames = {}
    for i in range(start, end+1):
        matrix = matrices[i]
        reliable_matrix = bool(valid[i] and np.isfinite(matrix).all()
                               and np.linalg.matrix_rank(matrix) == 3)
        row = {"homography_valid": reliable_matrix,
               "reprojection_error": float(errors[i]) if np.isfinite(errors[i]) else None,
               "ball": None, "players": [], "centre": None, "region": [], "pitch_lines": []}
        if reliable_matrix:
            row["centre"] = image_point(project_metres(matrix, centre, match.pitch_m))
            row["region"] = [image_point(p) for p in project_metres(matrix, circle, match.pitch_m)]
            row["pitch_lines"] = [[image_point(p) for p in project_metres(matrix, line, match.pitch_m)]
                                  for line in pitch_lines]
            if match.ball_observed[i]:
                row["ball"] = image_point(project_metres(matrix, match.ball_xy_m[i], match.pitch_m))
            for xy, observed, team in zip(match.players_xy_m[i], match.player_observed[i], match.slot_team):
                if observed:
                    point = image_point(project_metres(matrix, xy, match.pitch_m))
                    if point is not None:
                        row["players"].append([*point, str(team)])
        frames[str(i)] = row
    return {"fps": float(match.fps), "expected_duration_s": n/match.fps,
            "start": start, "end": end, "check": check_frame, "frames": frames}


HTML = r'''<!doctype html><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; media-src blob:; connect-src 'none'">
<title>Private geometry review</title><style>
body{font:16px system-ui;max-width:1250px;margin:20px auto;background:#f5f5f5}
.stage{position:relative}video{width:100%;display:block}canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
input[type=range]{width:100%}pre{white-space:pre-wrap}.notice{background:#fff3ca;padding:12px}
</style><h1>Local tracking geometry review — keep private</h1>
<p class="notice">This page uploads nothing. Select the tactical MP4 from your laptop.
Review tracking quality only; do not record possession labels, correct coordinates by hand,
or choose thresholds from this match. Keep this page and screenshots out of hosted AI tools.</p>
<input id="file" type="file" accept="video/*"><button id="check">Go to diagnostic check</button>
<button id="back">Previous frame</button><button id="next">Next frame</button>
<label><input id="show" type="checkbox" checked>Show projected tracking</label>
<input id="slider" type="range"><p id="timing"></p><p id="status">Choose the local tactical video.</p>
<div class="stage"><video id="video" controls preload="metadata"></video><canvas id="overlay"></canvas></div>
<p>Yellow: tracked ball. Blue/red: H/A slots (compare near players' feet).
White cross and ring: calculated pitch centre and detector region. White lines: pitch boundary/halfway line.
Homography may fit the field while ball tracking remains wrong; airborne projections can also be misleading.</p>
<pre id="details"></pre><h2>Local review checklist</h2>
<ol><li>First check video timing. A lagging moving-player overlay can be a timing issue.</li>
<li>Do projected pitch lines and centre agree with actual field markings?</li>
<li>Do several projected player points agree with players' ground positions?</li>
<li>Then compare the tracked ball with the visible ball across the window.</li></ol>
<p>Share only an overall conclusion: TIMING_UNCERTAIN, GEOMETRY_UNCERTAIN,
PLAYERS_ALIGN_BALL_UNCERTAIN, OVERLAY_LOOKS_CONSISTENT, or CANNOT_ASSESS.
These are review impressions, not measured calibration accuracy or kickoff labels.</p>
<script>const data=__DATA__;const video=document.getElementById('video'),canvas=document.getElementById('overlay'),
ctx=canvas.getContext('2d'),slider=document.getElementById('slider'),status=document.getElementById('status');
slider.min=data.start;slider.max=data.end;slider.value=data.check;let blob=null,lastFrame=null;
const accurate=typeof video.requestVideoFrameCallback==='function';
document.getElementById('timing').textContent='Timing assumption: constant frame rate, first video PTS = 0. '+
(accurate?'Overlay follows decoded media timestamps.':'Browser lacks decoded-frame callbacks: timing is approximate.');
function poly(points){ctx.beginPath();let started=false;for(const p of points){if(!p){started=false;continue;}
if(started)ctx.lineTo(p[0],p[1]);else{ctx.moveTo(p[0],p[1]);started=true;}}ctx.stroke();}
function dot(p,color,size){if(!p)return;ctx.fillStyle=color;ctx.beginPath();ctx.arc(p[0],p[1],size,0,2*Math.PI);ctx.fill();}
function draw(frame,width,height){lastFrame=frame;canvas.width=width||video.videoWidth||1;canvas.height=height||video.videoHeight||1;
const row=data.frames[String(frame)];ctx.clearRect(0,0,canvas.width,canvas.height);
if(!row){status.textContent='Decoded frame outside the exported review window. Use the slider.';return;}
slider.value=frame;status.textContent='Decoded frame '+frame+' — '+(row.homography_valid?'homography available':'NO VALID HOMOGRAPHY');
document.getElementById('details').textContent=JSON.stringify({frame,homography_valid:row.homography_valid,
reprojection_error:row.reprojection_error,ball_observed:row.ball!==null,player_points:row.players.length},null,2);
if(!document.getElementById('show').checked||!row.homography_valid)return;
ctx.strokeStyle='white';ctx.lineWidth=2;for(const line of row.pitch_lines)poly(line);poly(row.region);
if(row.centre){const [x,y]=row.centre;ctx.beginPath();ctx.moveTo(x-7,y);ctx.lineTo(x+7,y);ctx.moveTo(x,y-7);ctx.lineTo(x,y+7);ctx.stroke();}
for(const [x,y,team] of row.players)dot([x,y],team==='H'?'#55aaff':'#ff6666',4);dot(row.ball,'#ffff00',5);}
function seek(frame){if(!video.src)return;video.pause();video.currentTime=(Math.max(data.start,Math.min(data.end,frame))+.5)/data.fps;}
if(accurate){function callback(now,meta){draw(Math.round(meta.mediaTime*data.fps),meta.width,meta.height);
video.requestVideoFrameCallback(callback);}video.requestVideoFrameCallback(callback);}
else{for(const event of ['seeked','timeupdate'])video.addEventListener(event,()=>draw(Math.floor(video.currentTime*data.fps)));}
slider.addEventListener('input',()=>seek(Number(slider.value)));
document.getElementById('check').addEventListener('click',()=>seek(data.check));
document.getElementById('back').addEventListener('click',()=>seek((lastFrame===null?data.check:lastFrame)-1));
document.getElementById('next').addEventListener('click',()=>seek((lastFrame===null?data.check:lastFrame)+1));
document.getElementById('show').addEventListener('change',()=>{if(lastFrame!==null)draw(lastFrame);});
document.getElementById('file').addEventListener('change',event=>{const file=event.target.files[0];if(!file)return;
if(blob)URL.revokeObjectURL(blob);blob=URL.createObjectURL(file);video.src=blob;});
video.addEventListener('loadedmetadata',()=>{const mismatch=Math.abs(video.duration-data.expected_duration_s)>1/data.fps;
document.getElementById('timing').textContent+=(mismatch?' WARNING: video duration differs from tracking. Verify the file and timing before judging geometry.':' Duration is compatible; this alone does not prove exact frame alignment.');seek(data.check);});
video.addEventListener('error',()=>{status.textContent='Video could not be decoded. Try another local browser; no upload is needed.';});
</script>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/input-v1.json")
    parser.add_argument("--data-dir")
    parser.add_argument("--check-frame", type=int, required=True, help="inspection only, never inference")
    parser.add_argument("--window-s", type=float, default=10)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    root = bundle_root(args.data_dir)
    paths = asset_paths(data_dir=root)
    if not Path(paths["homography"]).is_file():
        parser.error("tactical homography CSV is missing; place it in the local tactical folder")
    match = load_match(data_dir=root, config=config)
    # The supplied loader preserves row order, so verify frame IDs before use.
    table = pd.read_csv(paths["homography"], usecols=["frame", "valid"])
    if (not np.array_equal(table["frame"].to_numpy(), match.frame)
            or not table["valid"].isin([0, 1]).all()):
        parser.error("homography frame IDs/validity do not match the canonical timeline")
    matrices, errors, valid = load_homography(data_dir=root)
    settings = _section(config, "dead_ball", DeadBallConfig)
    data = make_overlay(match, matrices, errors, valid, args.check_frame,
                        args.window_s, settings.kickoff_centre_radius_m)
    destination = ROOT/"runs"/"kickoff-geometry"/"private-overlay.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(HTML.replace("__DATA__", json.dumps(data, allow_nan=False).replace("<", "\\u003c")),
                           encoding="utf-8")
    print("Saved runs/kickoff-geometry/private-overlay.html. Open locally and select the tactical MP4.")
    print("Keep the page, video, coordinates and screenshots local.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
