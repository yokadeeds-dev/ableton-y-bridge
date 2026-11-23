"""Compare Live 12 Melody-to-MIDI output against source vocal audio.

Fetches MIDI notes from a track's arrangement clip via AbletonMCP socket,
loads the original audio file, runs F0 tracking (pyin) and onset detection,
then per-note compares true pitch and timing against the MIDI conversion.
"""
import os
import socket
import json
import sys
import math
import numpy as np
import librosa
from collections import Counter

# --- Config ---
MIDI_TRACK = 11           # 0-basiert: "12-Melody to MIDI"
MIDI_CLIP = 0
AUDIO_TRACK = 9           # 0-basiert: "VOCAL VORLAGE"
AUDIO_CLIP = 0
BPM = 83.0
SR = 22050
FMIN = 80.0               # ~E2, female vocal lower bound
FMAX = 1000.0             # ~B5, generous upper
PC_NAMES = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B']
F_MINOR = {5, 7, 8, 10, 0, 1, 3}


def call_mcp(cmd, params):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
    return 12.0 * math.log2(f / 440.0) + 69.0 if f and f > 0 else None


def beats_to_sec(b):
    return b * 60.0 / BPM


def main():
    print('=== fetching MIDI notes ===')
    r = call_mcp('get_arrangement_midi_notes', {'track_index': MIDI_TRACK, 'clip_index': MIDI_CLIP})
    notes = r['result']['notes']
    print(f'  {len(notes)} notes, clip_length={r["result"]["clip_length"]} beats')

    print('=== fetching audio path ===')
    r = call_mcp('get_clip_audio_info', {'track_index': AUDIO_TRACK, 'clip_index': AUDIO_CLIP,
                                         'arrangement': True})
    path = r['result']['file_path']
    print(f'  {path}')

    print('=== loading audio ===')
    y, sr = librosa.load(path, sr=SR, mono=True)
    dur = len(y) / sr
    print(f'  {dur:.2f} s @ {sr} Hz  ({len(y)} samples)')

    print('=== running pyin (this takes ~20-60s) ===')
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y, fmin=FMIN, fmax=FMAX, sr=sr,
        frame_length=2048, hop_length=256, fill_na=np.nan)
    hop_sec = 256 / sr
    times = np.arange(len(f0)) * hop_sec
    print(f'  {len(f0)} F0 frames, hop={hop_sec*1000:.1f} ms')

    print('=== onset detection ===')
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, hop_length=256, units='time', backtrack=False)
    print(f'  {len(onset_frames)} onsets detected')

    print('\n=== per-note analysis ===')
    ghost = []
    pitch_wrong = []
    pitch_ok = []
    timing_off = []
    for n in notes:
        start_s = beats_to_sec(n['start_time'])
        end_s = beats_to_sec(n['start_time'] + n['duration'])
        # F0 frames inside note (with small margin)
        i0 = max(0, int((start_s + 0.020) / hop_sec))  # skip 20ms attack
        i1 = min(len(f0), int(end_s / hop_sec))
        if i1 <= i0:
            i1 = i0 + 1
        seg_f0 = f0[i0:i1]
        seg_voiced = voiced_prob[i0:i1]
        valid = seg_f0[~np.isnan(seg_f0)]
        voiced_ratio = float(np.mean(seg_voiced > 0.5)) if len(seg_voiced) else 0.0
        if len(valid) < 3 or voiced_ratio < 0.30:
            ghost.append({'note': n, 'voiced_ratio': voiced_ratio, 'valid_frames': len(valid)})
            continue
        median_f0 = float(np.median(valid))
        true_midi = freq_to_midi(median_f0)
        cents_off = (true_midi - n['pitch']) * 100  # positive = MIDI is lower than truth, no wait: true - midi >0 means truth higher than MIDI pitch
        nearest_pitch = int(round(true_midi))
        delta_semitones = nearest_pitch - n['pitch']
        # Timing: nearest onset to note start
        if len(onset_frames):
            ons_diff = onset_frames - start_s
            i_near = int(np.argmin(np.abs(ons_diff)))
            onset_delta_ms = float(ons_diff[i_near]) * 1000
        else:
            onset_delta_ms = None
        record = {
            'note': n,
            'true_midi': round(true_midi, 2),
            'cents_off': round(cents_off, 1),
            'nearest_pitch': nearest_pitch,
            'delta': delta_semitones,
            'voiced_ratio': round(voiced_ratio, 2),
            'onset_delta_ms': round(onset_delta_ms, 1) if onset_delta_ms is not None else None,
        }
        if delta_semitones == 0:
            pitch_ok.append(record)
        else:
            pitch_wrong.append(record)
        if onset_delta_ms is not None and abs(onset_delta_ms) > 80:
            timing_off.append(record)

    n_total = len(notes)
    print(f'\n=== SUMMARY ({n_total} MIDI notes vs Audio) ===')
    print(f'  Pitch OK (within semitone of audio F0): {len(pitch_ok)}  ({100*len(pitch_ok)/n_total:.1f}%)')
    print(f'  Pitch WRONG: {len(pitch_wrong)}  ({100*len(pitch_wrong)/n_total:.1f}%)')
    print(f'  GHOST notes (unvoiced/no F0): {len(ghost)}  ({100*len(ghost)/n_total:.1f}%)')
    print(f'  Timing off (|onset_delta| > 80ms): {len(timing_off)}  ({100*len(timing_off)/n_total:.1f}%)')

    # Breakdown of pitch corrections
    delta_counter = Counter(r['delta'] for r in pitch_wrong)
    print('\n--- Pitch corrections needed (semitone delta) ---')
    for d, c in sorted(delta_counter.items(), key=lambda x: -x[1]):
        sign = '+' if d > 0 else ''
        print(f'  {sign}{d} st : {c} notes')

    # Which out-of-scale notes are actually correct vs wrong
    out_of_scale_notes = [n for n in notes if n['pitch'] % 12 not in F_MINOR]
    out_pcs = Counter(n['pitch'] % 12 for n in out_of_scale_notes)
    print('\n--- Out-of-scale MIDI notes: how many are real vs artefact ---')
    ok_pcs = Counter(r['note']['pitch'] % 12 for r in pitch_ok if r['note']['pitch'] % 12 not in F_MINOR)
    wrong_pcs = Counter(r['note']['pitch'] % 12 for r in pitch_wrong if r['note']['pitch'] % 12 not in F_MINOR)
    ghost_pcs = Counter(g['note']['pitch'] % 12 for g in ghost if g['note']['pitch'] % 12 not in F_MINOR)
    print('  PC   total  audio_says_OK  audio_says_WRONG  ghost')
    for pc in sorted(out_pcs):
        print(f'  {PC_NAMES[pc]:3s}   {out_pcs[pc]:4d}      {ok_pcs.get(pc,0):4d}            {wrong_pcs.get(pc,0):4d}            {ghost_pcs.get(pc,0):4d}')

    # Example WRONG out-of-scale notes
    print('\n--- First 20 out-of-scale WRONG notes (audio truth vs MIDI) ---')
    out_wrong = [r for r in pitch_wrong if r['note']['pitch'] % 12 not in F_MINOR]
    out_wrong.sort(key=lambda r: r['note']['start_time'])
    for r in out_wrong[:20]:
        n = r['note']
        p = n['pitch']
        np_ = r['nearest_pitch']
        print(f"  beat={n['start_time']:7.2f}  MIDI={PC_NAMES[p%12]}{p//12-1}({p})  audio_truth={PC_NAMES[np_%12]}{np_//12-1}({np_})  cents_off={r['cents_off']:+6.1f}  onset_delta={r['onset_delta_ms']}ms")

    # Ghost-note timestamps
    print(f'\n--- First 15 GHOST notes (no audio F0) ---')
    for g in ghost[:15]:
        n = g['note']
        p = n['pitch']
        print(f"  beat={n['start_time']:7.2f}  pitch={PC_NAMES[p%12]}{p//12-1}({p})  dur={n['duration']:.2f}  voiced_ratio={g['voiced_ratio']:.2f}")

    # Save full report as JSON for follow-up
    out = {
        'summary': {
            'total': n_total,
            'pitch_ok': len(pitch_ok),
            'pitch_wrong': len(pitch_wrong),
            'ghost': len(ghost),
            'timing_off': len(timing_off),
        },
        'pitch_wrong': pitch_wrong,
        'ghost': [{'note': g['note'], 'voiced_ratio': g['voiced_ratio']} for g in ghost],
        'timing_off': timing_off,
    }
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'melody_to_midi_report.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
    print('\nFull JSON report saved: melody_to_midi_report.json')


if __name__ == '__main__':
    main()
