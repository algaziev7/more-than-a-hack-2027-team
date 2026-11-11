"""E2's optional offline decoder policy; only public contracts and arrays.

Candidate generation and config validation live in state_machine.py. This module
consumes those decisions without reading files, labels or match-specific rules.
"""
from collections import deque
import math

import numpy as np

from possession.contracts import Prediction


def decode_refined(match, features, candidate, is_dead, exit_dead_ok, sources, settings):
    n = len(candidate)
    half = np.asarray(match.half)
    labels = np.full(n, 'X', dtype=object)
    unknown = np.zeros(n, dtype=bool)
    confirmations = []
    protected = 0
    pending = deque()  # (frame, tracking) within the currently applicable window
    pending_team = None
    tracking_count = 0
    state, previous_half, latched = 'D', 0, False
    segment_start = 0
    unknown_start = None
    unknown_first_team, unknown_conflict = None, False
    strong_run = 0
    last_strong_team = None
    last_barrier = -1
    backdate = math.floor(settings.max_backdate_s * settings.fps)
    lookahead = math.floor(settings.restart_lookahead_s * settings.fps)
    strong_required = max(1, math.ceil(settings.strong_team_dwell_s * settings.fps))
    strength = ((features.team_reliability >= settings.strong_team_reliability)
                & (np.abs(features.team_evidence[:, 0] - features.team_evidence[:, 1])
                   >= settings.strong_team_margin - 8 * np.finfo(float).eps))

    for i in range(n):
        h = int(half[i])
        if h == 0:
            previous_half = 0
            continue
        if h != previous_half:
            state, latched = 'D', False
            pending.clear()
            pending_team = None
            tracking_count = 0
            strong_run, last_strong_team = 0, None
            segment_start, last_barrier = i, i - 1
            unknown_start, unknown_first_team, unknown_conflict = None, None, False
        previous_half = h

        if is_dead[i]:
            latched = True
            last_barrier = i
        elif exit_dead_ok[i]:
            if pending_team == 'D' or (latched and state == 'D'):
                pending.clear()
                pending_team = None
                tracking_count = 0
            latched = False
            if state == 'D':
                state, segment_start = 'X', i
                unknown_start, unknown_first_team, unknown_conflict = i, None, False
                last_barrier = i - 1
                strong_run, last_strong_team = 0, None

        window = (2 * settings.latched_team_dwell_frames
                  if state == 'D' and latched else settings.evidence_window_frames)
        while pending and i - pending[0][0] > window:
            tracking_count -= pending.popleft()[1]
        if not pending:
            pending_team = None

        vote = candidate[i]
        tracking = bool(sources['tracking'][i])
        # Do not let a coarse incumbent tag erase fresh tracking toward a turnover.
        if (sources['tag'][i] and pending_team in ('H', 'A')
                and vote != pending_team and tracking_count > 0):
            vote = None
            protected += 1
        if vote in ('H', 'A') and state == 'X':
            if unknown_first_team is None:
                unknown_first_team = vote
            elif unknown_first_team != vote:
                unknown_conflict = True

        if vote in ('H', 'A') and tracking and strength[i]:
            strong_run = strong_run + 1 if last_strong_team == vote else 1
            last_strong_team = vote
        else:
            strong_run, last_strong_team = 0, None

        if vote is None:
            labels[i] = state
            unknown[i] = state == 'X'
            continue
        if vote == state:
            pending.clear()
            pending_team = None
            tracking_count = 0
            labels[i] = state
            continue
        if vote != pending_team:
            pending.clear()
            pending_team = vote
            tracking_count = 0
        pending.append((i, tracking))
        tracking_count += tracking
        gated = vote in ('H', 'A') and state == 'D' and latched
        required = (settings.dead_dwell_frames if vote == 'D' else
                    settings.latched_team_dwell_frames if gated else settings.team_dwell_frames)
        strong_confirmed = (vote in ('H', 'A') and not gated
                            and strong_run >= strong_required)
        if len(pending) >= required or strong_confirmed:
            # Boundary must be supported by an actual observation within the bound.
            floor = max(segment_start, i - backdate)
            if vote in ('H', 'A'):
                floor = max(floor, last_barrier + 1)
            boundary = i if gated else next((j for j, _ in pending if j >= floor), i)
            if (state == 'X' and vote in ('H', 'A') and unknown_start is not None
                    and i - unknown_start <= lookahead and not unknown_conflict
                    and last_barrier < unknown_start):
                boundary = unknown_start
            labels[boundary:i + 1] = vote
            unknown[boundary:i + 1] = False
            confirmations.append({'frame': int(i), 'boundary_frame': int(boundary),
                                  'from_state': state, 'to_state': vote,
                                  'reason': 'strong_tracking' if strong_confirmed else 'dwell'})
            state, segment_start = vote, boundary
            pending.clear()
            pending_team = None
            tracking_count = 0
            if vote in ('H', 'A'):
                latched = False
            unknown_start, unknown_first_team, unknown_conflict = None, None, False
        labels[i] = state
        unknown[i] = state == 'X'

    # Final transitions describe final CSV boundaries, not provisional causal states.
    changes = np.flatnonzero((labels[1:] != labels[:-1]) & (half[1:] > 0)
                             & (half[1:] == half[:-1])) + 1
    transitions = [{'frame': int(i), 'from_state': str(labels[i - 1]),
                    'to_state': str(labels[i]), 'reason': 'offline refined boundary'}
                   for i in changes]
    return Prediction(labels, {'transitions': transitions, 'confirmations': confirmations,
                               'team_sources': {key: int(np.count_nonzero(mask & (half > 0)))
                                                for key, mask in sources.items()},
                               'protected_tracking_frames': protected,
                               'live_unknown_frames': int(unknown.sum())})
