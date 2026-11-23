# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Bidirectional coverage check and duration alignment.

For the cleaned MIDI clip (115 notes), find:
  1. Voiced audio segments that have NO matching MIDI note -> gap, insert new note
  2. MIDI notes that overlap a voiced segment but are clearly shorter/longer
     than the audio -> adjust duration to match
  3. MIDI notes that have NO voiced segment overlap -> already removed by previous
     ghost cleanup, but re-verify

Strategy: voiced segments are runs where pyin's voiced_flag is true for >=100ms.
For each segment we compute median F0 -> suggested MIDI pitch.
"""
import socket
import json
import math
import numpy as np
import librosa
from collections import Counter

MIDI_TRACK = 11
MIDI_CLIP = 0
AUDIO_TRACK = 9
AUDIO_CLIP = 0
BPM = 83.0
SR = 22050
HOP = 256
FMIN = 80.0
FMAX = 1000.0
MIN_SEG_MS = 100        # ignore voiced segments shorter than this
MIN_GAP_MS = 150        # only fill gaps where a segment >= this is uncovered
DUR_ADJUST_RATIO = 0.6  # adjust MIDI duration if note covers < 60% or > 140% of seg
PC_NAMES = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B']


def call_mcp(cmd, params, timeout=60):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(('localhost', 9877))
    s.sendall(json.dumps({'type': cmd, 'params': params}).encode())
    buf = b''
    while True:
        c = s.recv(65536)
        if not c:
            break
        buf += c
        try:
            json.loads(buf.decode())
            break
        except Exception:
            pass
    s.close()
    return json.loads(buf.decode())


def freq_to_midi(f):
    return 12.0 * math.log2(f / 440.0) + 69.0


def main():
    sec_per_beat = 60.0 / BPM

    print('=== fetching current MIDI ===')
    r = call_mcp('get_arrangement_midi_notes', {'track_index': MIDI_TRACK, 'clip_index': MIDI_CLIP})
    notes = sorted(r['result']['notes'], key=lambda n: n['start_time'])
    print(f'  {len(notes)} notes')

    print('=== audio + pyin (~30s) ===')
    p = call_mcp('get_clip_audio_info', {'track_index': AUDIO_TRACK, 'clip_index': AUDIO_CLIP,
                                         'arrangement': True})
    path = p['result']['file_path']
    y, sr = librosa.load(path, sr=SR, mono=True)
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y, fmin=FMIN, fmax=FMAX, sr=sr,
        frame_length=2048, hop_length=HOP, fill_na=np.nan)
    hop_sec = HOP / sr
    print(f'  {len(f0)} frames, hop={hop_sec*1000:.1f} ms')

    # === voiced segments ===
    is_voiced = voiced_prob > 0.5
    segments = []
    in_seg = False
    seg_start_f = 0
    min_seg_frames = int(MIN_SEG_MS / 1000 / hop_sec)
    for i, v in enumerate(is_voiced):
        if v and not in_seg:
            seg_start_f = i
            in_seg = True
        elif not v and in_seg:
            seg_end_f = i
            in_seg = False
            if (seg_end_f - seg_start_f) >= min_seg_frames:
                seg_f0 = f0[seg_start_f:seg_end_f]
                valid = seg_f0[~np.isnan(seg_f0)]
                if len(valid):
                    med = float(np.median(valid))
                    segments.append({
                        'start_sec': seg_start_f * hop_sec,
                        'end_sec': seg_end_f * hop_sec,
                        'median_f0': med,
                        'midi_pitch': int(round(freq_to_midi(med))),
                    })
    if in_seg:
        seg_end_f = len(is_voiced)
        if (seg_end_f - seg_start_f) >= min_seg_frames:
            seg_f0 = f0[seg_start_f:seg_end_f]
            valid = seg_f0[~np.isnan(seg_f0)]
            if len(valid):
                med = float(np.median(valid))
                segments.append({
                    'start_sec': seg_start_f * hop_sec,
                    'end_sec': seg_end_f * hop_sec,
                    'median_f0': med,
                    'midi_pitch': int(round(freq_to_midi(med))),
                })
    print(f'  voiced segments >= {MIN_SEG_MS}ms: {len(segments)}')

    # === bidirectional coverage ===
    note_start_sec = [n['start_time'] * sec_per_beat for n in notes]
    note_end_sec = [(n['start_time'] + n['duration']) * sec_per_beat for n in notes]

    seg_to_notes = [[] for _ in segments]
    note_to_segs = [[] for _ in notes]
    for si, s in enumerate(segments):
        for ni in range(len(notes)):
            if note_start_sec[ni] < s['end_sec'] and note_end_sec[ni] > s['start_sec']:
                seg_to_notes[si].append(ni)
                note_to_segs[ni].append(si)

    uncovered_segs = [(si, s) for si, s in enumerate(segments) if not seg_to_notes[si]]
    orphan_notes = [(ni, notes[ni]) for ni in range(len(notes)) if not note_to_segs[ni]]

    print(f'\n=== Coverage ===')
    print(f'  voiced segments without MIDI:  {len(uncovered_segs)}')
    print(f'  MIDI notes without voiced seg: {len(orphan_notes)}')

    # === gap fills ===
    new_notes_from_gaps = []
    min_gap_sec = MIN_GAP_MS / 1000
    for si, s in uncovered_segs:
        dur_sec = s['end_sec'] - s['start_sec']
        if dur_sec >= min_gap_sec:
            start_beat = s['start_sec'] / sec_per_beat
            dur_beat = dur_sec / sec_per_beat
            new_notes_from_gaps.append({
                'pitch': s['midi_pitch'],
                'start_time': start_beat,
                'duration': dur_beat,
                'velocity': 80,
                'mute': False,
                '_source': 'gap_fill',
            })
    print(f'  gap-fill candidates (>= {MIN_GAP_MS}ms): {len(new_notes_from_gaps)}')

    # === duration adjustments ===
    adjusted_notes = []
    n_adjusted_longer = 0
    n_adjusted_shorter = 0
    for ni, n in enumerate(notes):
        new_start = n['start_time']
        new_dur = n['duration']
        new_pitch = n['pitch']
        segs = note_to_segs[ni]
        if len(segs) == 1:
            s = segments[segs[0]]
            # Compute audio overlap with this single segment
            seg_dur = s['end_sec'] - s['start_sec']
            note_dur_sec = n['duration'] * sec_per_beat
            ratio = note_dur_sec / seg_dur if seg_dur > 0 else 1.0
            # Only this note attached to this segment?
            if len(seg_to_notes[segs[0]]) == 1 and (ratio < DUR_ADJUST_RATIO or ratio > 1/DUR_ADJUST_RATIO):
                # Adjust duration to segment span
                new_start = s['start_sec'] / sec_per_beat
                new_dur = seg_dur / sec_per_beat
                if note_dur_sec < seg_dur:
                    n_adjusted_longer += 1
                else:
                    n_adjusted_shorter += 1
        adjusted_notes.append({
            'pitch': new_pitch,
            'start_time': new_start,
            'duration': new_dur,
            'velocity': n['velocity'],
            'mute': n.get('mute', False),
        })

    print(f'  duration adjustments: {n_adjusted_longer} extended, {n_adjusted_shorter} shortened')

    # === merge: adjusted + gap fills ===
    final_notes = list(adjusted_notes)
    for g in new_notes_from_gaps:
        final_notes.append({k: v for k, v in g.items() if not k.startswith('_')})
    final_notes.sort(key=lambda x: x['start_time'])

    print(f'\n=== Final note count ===')
    print(f'  before: 115')
    print(f'  after:  {len(final_notes)}  (+{len(new_notes_from_gaps)} gap-fills, durations adjusted on {n_adjusted_longer + n_adjusted_shorter})')

    # Print some gap fills
    if new_notes_from_gaps:
        print(f'\n--- First 20 gap-fill notes ---')
        for g in sorted(new_notes_from_gaps, key=lambda x: x['start_time'])[:20]:
            p = g['pitch']
            print(f"  beat={g['start_time']:7.2f}  pitch={PC_NAMES[p%12]}{p//12-1}({p})  dur={g['duration']:.2f} beats")

    print('\n=== writing back ===')
    w = call_mcp('replace_arrangement_clip_notes', {
        'track_index': MIDI_TRACK,
        'clip_index': MIDI_CLIP,
        'notes': final_notes,
    })
    print('Response:', w)

    v = call_mcp('get_arrangement_midi_notes', {'track_index': MIDI_TRACK, 'clip_index': MIDI_CLIP})
    print(f"Verification: {v['result']['note_count']} notes")

    # Final pitch-class distribution
    print('\n--- Final pitch-class distribution ---')
    pc_cnt = Counter(n['pitch'] % 12 for n in final_notes)
    pc_dur = {}
    for n in final_notes:
        pc_dur[n['pitch'] % 12] = pc_dur.get(n['pitch'] % 12, 0) + n['duration']
    total = sum(pc_dur.values())
    in_fmin = {5, 7, 8, 10, 0, 1, 3}
    print('PC   Name   InScale  Count  %Dauer')
    for p in sorted(pc_dur, key=lambda x: -pc_dur[x]):
        flag = 'YES' if p in in_fmin else 'NO '
        print(f' {p:2d}  {PC_NAMES[p]:4s}  {flag}     {pc_cnt[p]:4d}  {100*pc_dur[p]/total:5.1f}%')


if __name__ == '__main__':
    main()
