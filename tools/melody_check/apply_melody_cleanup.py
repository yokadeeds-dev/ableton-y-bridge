# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Apply the Melody-to-MIDI cleanup: delete ghost notes, fix pitch errors.

Reads melody_to_midi_report.json + melody_original_notes_backup.json,
builds the corrected note list, and writes it back via the new
replace_arrangement_clip_notes command on the AbletonMCP remote script.
"""
import os
import socket
import json

MIDI_TRACK = 11
MIDI_CLIP = 0
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


def note_key(n):
    return (round(n['start_time'], 4),
            n['pitch'],
            round(n['duration'], 4))


def main():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'melody_original_notes_backup.json'), 'r', encoding='utf-8') as f:
        backup = json.load(f)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'melody_to_midi_report.json'), 'r', encoding='utf-8') as f:
        report = json.load(f)

    original = backup['notes']
    print(f'Original: {len(original)} notes')

    # Build lookup: ghost set
    ghost_keys = set()
    for g in report['ghost']:
        ghost_keys.add(note_key(g['note']))
    print(f'Ghost keys: {len(ghost_keys)}')

    # Build lookup: pitch correction map (only fixable deltas)
    FIXABLE = {-12, -1, 1, 2}
    pitch_fix = {}  # key -> new_pitch
    skipped_extreme = []
    for r in report['pitch_wrong']:
        n = r['note']
        d = r['delta']
        if d in FIXABLE:
            pitch_fix[note_key(n)] = (n['pitch'], r['nearest_pitch'])
        else:
            skipped_extreme.append(r)
    print(f'Pitch fixes: {len(pitch_fix)}  (skipped extreme outliers: {len(skipped_extreme)})')

    # Build cleaned note list
    cleaned = []
    deleted = 0
    fixed = 0
    for n in original:
        k = (round(n['start_time'], 4), n['pitch'], round(n['duration'], 4))
        if k in ghost_keys:
            deleted += 1
            continue
        new_pitch = n['pitch']
        if k in pitch_fix:
            _, new_pitch = pitch_fix[k]
            fixed += 1
        cleaned.append({
            'pitch': new_pitch,
            'start_time': n['start_time'],
            'duration': n['duration'],
            'velocity': n['velocity'],
            'mute': n.get('mute', False),
        })

    print(f'\nDeleted: {deleted}  Pitch-fixed: {fixed}  Remaining: {len(cleaned)}')
    print(f'(Original {len(original)} - deleted {deleted} = expected {len(original)-deleted})')

    # Write back
    print('\nWriting cleaned notes back to clip...')
    r = call_mcp('replace_arrangement_clip_notes', {
        'track_index': MIDI_TRACK,
        'clip_index': MIDI_CLIP,
        'notes': cleaned,
    })
    print('Response:', r)

    # Verify
    v = call_mcp('get_arrangement_midi_notes', {'track_index': MIDI_TRACK, 'clip_index': MIDI_CLIP})
    print(f"\nVerification: clip now has {v['result']['note_count']} notes")

    # Print the 2 extreme outliers that were skipped
    if skipped_extreme:
        print(f'\n--- Skipped extreme outliers (manual check needed) ---')
        for r in skipped_extreme:
            n = r['note']
            p = n['pitch']
            np_ = r['nearest_pitch']
            print(f"  beat={n['start_time']:7.2f}  MIDI={PC_NAMES[p%12]}{p//12-1}({p})  audio_truth={PC_NAMES[np_%12]}{np_//12-1}({np_})  delta={r['delta']:+d}st  voiced_ratio={r['voiced_ratio']}")


if __name__ == '__main__':
    main()
