# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Snap MIDI note starts to nearest audio onset.

Operates on the already-cleaned 115-note clip. For every note where the
nearest librosa onset is between 80 and 250 ms away, the note start is
snapped to that onset. Duration is preserved. Notes whose nearest onset is
too far away (>250ms) are left alone — those are probably not aligned at
all and a snap would be a guess.
"""
import socket
import json
import math
import numpy as np
import librosa

MIDI_TRACK = 11
MIDI_CLIP = 0
AUDIO_TRACK = 9
AUDIO_CLIP = 0
BPM = 83.0
SR = 22050
SNAP_MIN_MS = 80
SNAP_MAX_MS = 250
PC_NAMES = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B']


def call_mcp(cmd, params, timeout=30):
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


def main():
    sec_per_beat = 60.0 / BPM

    print('=== fetching current MIDI ===')
    r = call_mcp('get_arrangement_midi_notes', {'track_index': MIDI_TRACK, 'clip_index': MIDI_CLIP})
    notes = r['result']['notes']
    print(f'  {len(notes)} notes')

    print('=== fetching audio path + loading ===')
    p = call_mcp('get_clip_audio_info', {'track_index': AUDIO_TRACK, 'clip_index': AUDIO_CLIP,
                                         'arrangement': True})
    path = p['result']['file_path']
    y, sr = librosa.load(path, sr=SR, mono=True)
    print(f'  {len(y)/sr:.2f} s @ {sr} Hz')

    print('=== onset detection ===')
    onsets_sec = librosa.onset.onset_detect(y=y, sr=sr, hop_length=256, units='time', backtrack=False)
    onsets_sec = np.asarray(onsets_sec)
    print(f'  {len(onsets_sec)} onsets')

    print('\n=== analysing snap candidates ===')
    snapped = []
    too_far = []
    in_tolerance = []
    notes_sorted = sorted(notes, key=lambda n: n['start_time'])

    new_notes = []
    for n in notes_sorted:
        start_sec = n['start_time'] * sec_per_beat
        diffs = onsets_sec - start_sec
        i_near = int(np.argmin(np.abs(diffs)))
        delta_ms = float(diffs[i_near]) * 1000  # positive: onset is later than MIDI start
        abs_ms = abs(delta_ms)
        record = {
            'pitch': n['pitch'],
            'midi_beat': round(n['start_time'], 3),
            'midi_sec': round(start_sec, 3),
            'onset_sec': round(float(onsets_sec[i_near]), 3),
            'delta_ms': round(delta_ms, 1),
        }
        if abs_ms <= SNAP_MIN_MS:
            # Already aligned, keep as-is
            in_tolerance.append(record)
            new_start = n['start_time']
        elif abs_ms <= SNAP_MAX_MS:
            # Snap to onset
            new_start = float(onsets_sec[i_near]) / sec_per_beat
            record['new_beat'] = round(new_start, 3)
            snapped.append(record)
        else:
            # Too far — don't snap, probably no matching onset
            too_far.append(record)
            new_start = n['start_time']
        new_notes.append({
            'pitch': n['pitch'],
            'start_time': new_start,
            'duration': n['duration'],
            'velocity': n['velocity'],
            'mute': n.get('mute', False),
        })

    print(f'  in tolerance (<= {SNAP_MIN_MS}ms): {len(in_tolerance)}')
    print(f'  SNAPPED ({SNAP_MIN_MS}-{SNAP_MAX_MS}ms): {len(snapped)}')
    print(f'  too far (> {SNAP_MAX_MS}ms, left alone): {len(too_far)}')

    if snapped:
        print(f'\n--- First 20 snapped notes ---')
        for r in snapped[:20]:
            p = r['pitch']
            print(f"  pitch={PC_NAMES[p%12]}{p//12-1}({p})  midi_beat={r['midi_beat']:7.3f}  -> new_beat={r['new_beat']:7.3f}  "
                  f"delta={r['delta_ms']:+6.1f}ms")

    if too_far:
        print(f'\n--- {len(too_far)} notes too far from any onset (>250ms) — left alone ---')
        for r in too_far[:10]:
            p = r['pitch']
            print(f"  pitch={PC_NAMES[p%12]}{p//12-1}({p})  midi_beat={r['midi_beat']:7.3f}  delta={r['delta_ms']:+7.1f}ms")

    # Sort by start before write (Live tolerates unsorted, but cleaner)
    new_notes.sort(key=lambda x: x['start_time'])

    print('\n=== writing back ===')
    w = call_mcp('replace_arrangement_clip_notes', {
        'track_index': MIDI_TRACK,
        'clip_index': MIDI_CLIP,
        'notes': new_notes,
    })
    print('Response:', w)

    # Verify
    v = call_mcp('get_arrangement_midi_notes', {'track_index': MIDI_TRACK, 'clip_index': MIDI_CLIP})
    print(f"\nVerification: clip now has {v['result']['note_count']} notes")


if __name__ == '__main__':
    main()
