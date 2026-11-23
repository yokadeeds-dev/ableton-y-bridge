# Live test protocol

Run on 2026-11-22 21:43 against Ableton Live 12.3.6 (Python 3.11.6), bridge 2.1.0, source hash `201f4c469c7e`, 87 commands.

Produced by `tests/live_protocol.py`: the MCP server runs as a child process and every tool is called through the MCP protocol, as an assistant would.

## Summary

- Tools offered by the server: 79
- Tools called: 79
- Calls made: 146 (146 pass)
- Tools never called: none

Verdicts: **pass** = answered as expected; **limit** = works as far as Live's API or the environment allows, see note; **skipped** = precondition missing; **FAIL** = wrong or error answer.

## Result per tool

| Tool | Verdict | Calls |
|---|---|---:|
| `add_notes_to_clip` | pass | 1 |
| `als_warp_derive` | pass | 2 |
| `als_warp_read` | pass | 3 |
| `als_warp_write` | pass | 1 |
| `analyze_midi_session` | pass | 1 |
| `apply_mastering_corrections` | pass | 2 |
| `bridge_status` | pass | 2 |
| `clear_locators` | pass | 2 |
| `color_all_tracks_by_spectrum` | pass | 1 |
| `color_track_by_spectrum` | pass | 1 |
| `create_audio_track` | pass | 2 |
| `create_clip` | pass | 2 |
| `create_locator` | pass | 3 |
| `create_midi_track` | pass | 3 |
| `delete_device` | pass | 3 |
| `delete_locator` | pass | 1 |
| `delete_notes_from_clip` | pass | 1 |
| `fire_clip` | pass | 1 |
| `fire_scene` | pass | 1 |
| `focus_view` | pass | 1 |
| `freeze_track` | pass | 1 |
| `generate_automation_curve` | pass | 1 |
| `generate_euclidean_rhythm` | pass | 1 |
| `get_arrangement_clips` | pass | 1 |
| `get_browser_items_at_path` | pass | 1 |
| `get_browser_tree` | pass | 1 |
| `get_clip_key` | pass | 3 |
| `get_device_parameters` | pass | 2 |
| `get_locators` | pass | 2 |
| `get_master_analysis` | pass | 2 |
| `get_return_tracks` | pass | 1 |
| `get_safety_status` | pass | 1 |
| `get_session_info` | pass | 6 |
| `get_track_info` | pass | 5 |
| `get_warp_markers` | pass | 3 |
| `group_tracks` | pass | 1 |
| `hot_reload` | pass | 3 |
| `humanize_clip` | pass | 1 |
| `jump_to_time` | pass | 1 |
| `list_ai_changes` | pass | 2 |
| `list_snapshots` | pass | 1 |
| `load_device_on_master` | pass | 1 |
| `load_device_on_return` | pass | 1 |
| `load_drum_kit` | pass | 1 |
| `load_instrument_or_effect` | pass | 4 |
| `normalize_clip` | pass | 1 |
| `redo` | pass | 1 |
| `replace_notes_in_clip` | pass | 2 |
| `search_vst` | pass | 1 |
| `select_tracks` | pass | 1 |
| `set_arrangement_loop` | pass | 2 |
| `set_arrangement_record` | pass | 2 |
| `set_clip_name` | pass | 1 |
| `set_clip_warp_mode` | pass | 1 |
| `set_device_parameter` | pass | 1 |
| `set_eq_mode` | pass | 2 |
| `set_return_device_parameter` | pass | 1 |
| `set_return_track_volume` | pass | 2 |
| `set_scene_tempo` | pass | 1 |
| `set_sidechain_routing` | pass | 1 |
| `set_tempo` | pass | 3 |
| `set_tempo_automation` | pass | 2 |
| `set_track_color` | pass | 1 |
| `set_track_mute` | pass | 2 |
| `set_track_name` | pass | 4 |
| `set_track_send` | pass | 1 |
| `set_track_volume` | pass | 5 |
| `set_warp_marker` | pass | 2 |
| `set_warp_markers_batch` | pass | 4 |
| `set_wavetable_mod_routing` | pass | 1 |
| `snapshot_session` | pass | 1 |
| `start_playback` | pass | 1 |
| `stop_clip` | pass | 1 |
| `stop_playback` | pass | 2 |
| `suggest_mastering_chain` | pass | 1 |
| `switch_view` | pass | 1 |
| `transpose_notes` | pass | 1 |
| `undo` | pass | 1 |
| `undo_ai_change` | pass | 11 |

## Every call

| # | Tool | Arguments | Verdict | ms | Answer (first line) | Note |
|---:|---|---|---|---:|---|---|
| 1 | `bridge_status` | `{}` | pass | 809 | { |  |
| 2 | `hot_reload` | `{}` | pass | 299 | Hot reload ok: 87 commands from 18 modules, source hash 201f4c469c7e. |  |
| 3 | `bridge_status` | `{}` | pass | 1114 | { | after hot reload |
| 4 | `hot_reload` | `{}` | pass | 316 | Hot reload ok: 88 commands from 19 modules, source hash fea450051790. New: reload_probe. | new handler file picked up from disk |
| 5 | `hot_reload` | `{}` | pass | 713 | Hot reload ok: 87 commands from 18 modules, source hash 201f4c469c7e. Gone: reload_probe. | removed handler file dropped |
| 6 | `set_warp_markers_batch` | `{"track_index": "version", "clip_index": 0, "markers": "[]"}` | pass | 1149 | {"bridge_version": "2.1.0", "command_count": 87, "file_hash": "201f4c469c7e", "mtime": ... | old keyword spelling of the version check |
| 7 | `get_session_info` | `{}` | pass | 298 | { |  |
| 8 | `set_tempo` | `{"tempo": 123}` | pass | 1001 | Tempo is now 123.00 BPM (was 120.00). |  |
| 9 | `jump_to_time` | `{"time": 8}` | pass | 398 | Play position is at beat 8.000. |  |
| 10 | `set_arrangement_loop` | `{"start": 4, "length": 8, "enabled": true}` | pass | 1132 | Loop 4 to 12 beats, on. |  |
| 11 | `set_arrangement_loop` | `{"start": 0, "length": 4, "enabled": false}` | pass | 1315 | Loop 0 to 4 beats, off. | switch loop off again |
| 12 | `set_arrangement_record` | `{"enabled": true}` | pass | 500 | Arrangement Record is ON. |  |
| 13 | `set_arrangement_record` | `{"enabled": false}` | pass | 416 | Arrangement Record is off. |  |
| 14 | `switch_view` | `{"view": "Arranger"}` | pass | 200 | Showing the Arranger view. |  |
| 15 | `focus_view` | `{"view": "Session"}` | pass | 199 | The Session view has the focus. |  |
| 16 | `create_midi_track` | `{"index": -1}` | pass | 648 | New MIDI track '5-MIDI' at index 4. |  |
| 17 | `create_audio_track` | `{"index": -1}` | pass | 651 | New audio track '6-Audio' at index 5. |  |
| 18 | `create_audio_track` | `{"index": -1}` | pass | 552 | New audio track '7-Audio' at index 6. | second audio track |
| 19 | `create_midi_track` | `{"index": -1}` | pass | 930 | New MIDI track '8-MIDI' at index 7. | track for the drum kit |
| 20 | `set_track_name` | `{"track_index": 4, "name": "v2 Test MIDI"}` | pass | 717 | Track 4: '5-MIDI' is now 'v2 Test MIDI'. |  |
| 21 | `set_track_name` | `{"track_index": 5, "name": "v2 Test Audio"}` | pass | 917 | Track 5: '6-Audio' is now 'v2 Test Audio'. |  |
| 22 | `set_track_name` | `{"track_index": 6, "name": "v2 Test Audio 2"}` | pass | 931 | Track 6: '7-Audio' is now 'v2 Test Audio 2'. |  |
| 23 | `get_track_info` | `{"track_index": 4}` | pass | 399 | { |  |
| 24 | `set_track_volume` | `{"track_index": 4, "volume_db": -6}` | pass | 966 | Track 4 'v2 Test MIDI' fader at -6.0 dB (raw 0.7000). |  |
| 25 | `set_track_volume` | `{"track_index": 4, "volume_db": "-inf"}` | pass | 1016 | Track 4 'v2 Test MIDI' fader at -inf dB (raw 0.0000). | closed fader |
| 26 | `set_track_volume` | `{"track_index": 4, "volume_db": -12}` | pass | 915 | Track 4 'v2 Test MIDI' fader at -12.0 dB (raw 0.5500). |  |
| 27 | `set_track_mute` | `{"track_index": 4, "mute": true}` | pass | 1231 | Track 4 'v2 Test MIDI' is muted. |  |
| 28 | `set_track_mute` | `{"track_index": 4, "mute": false}` | pass | 901 | Track 4 'v2 Test MIDI' is audible. |  |
| 29 | `set_track_color` | `{"track_index": 4, "color_index": 12}` | pass | 1000 | Track 4 'v2 Test MIDI' has palette colour 12. |  |
| 30 | `get_return_tracks` | `{}` | pass | 297 | { |  |
| 31 | `set_track_send` | `{"track_index": 4, "send_index": 0, "value": 0.25}` | pass | 1068 | Send 0 of 'v2 Test MIDI' at 0.250 (-34.8 dB). |  |
| 32 | `set_return_track_volume` | `{"index": 0, "volume": 0.7}` | pass | 1131 | Return 0 'A-Reverb' fader at -6.0 dB. |  |
| 33 | `set_return_track_volume` | `{"index": 0, "volume": 0.85}` | pass | 1118 | Return 0 'A-Reverb' fader at 0.0 dB. | back to unity |
| 34 | `select_tracks` | `{"track_indices": [4, 5]}` | pass | 200 | Selected track 4 'v2 Test MIDI'. Live's API selects one track only. To group several, s... |  |
| 35 | `freeze_track` | `{"track_index": 4, "freeze": true}` | pass | 432 | Track 4 'v2 Test MIDI' is not frozen. Live's API has no freeze call. Use 'Freeze Track'... | Live's API cannot freeze; tool reports state only |
| 36 | `create_clip` | `{"track_index": 4, "clip_index": 0, "length": 4}` | pass | 949 | Created a 4-beat MIDI clip on track 4, slot 0. |  |
| 37 | `set_clip_name` | `{"track_index": 4, "clip_index": 0, "name": "v2 chord"}` | pass | 1206 | Clip on track 4, slot 0 is now 'v2 chord'. |  |
| 38 | `add_notes_to_clip` | `{"track_index": 4, "clip_index": 0, "notes": [{"pitch": 60, "start_...` | pass | 1228 | Added 4 notes to 'v2 chord'. |  |
| 39 | `replace_notes_in_clip` | `{"track_index": 4, "clip_index": 0, "notes": [{"pitch": 60, "start_...` | pass | 1263 | 'v2 chord' now holds 5 notes (4 removed). |  |
| 40 | `get_clip_key` | `{"track_index": 4, "clip_index": 0}` | pass | 300 | { |  |
| 41 | `delete_notes_from_clip` | `{"track_index": 4, "clip_index": 0, "pitch": 46}` | pass | 949 | Deleted 1 notes from 'v2 chord', 4 left. |  |
| 42 | `humanize_clip` | `{"track_index": 4, "clip_index": 0, "timing_amount": 0.01, "velocit...` | pass | 1001 | Humanized 4 notes in 'v2 chord'. |  |
| 43 | `transpose_notes` | `{"track_index": 4, "clip_index": 0, "semitones": 2}` | pass | 1150 | Transposed 4 notes in 'v2 chord' by +2 semitones. |  |
| 44 | `get_clip_key` | `{"track_index": 4, "clip_index": 0}` | pass | 197 | { | after transposing by +2 |
| 45 | `create_clip` | `{"track_index": 4, "clip_index": 1, "length": 4}` | pass | 999 | Created a 4-beat MIDI clip on track 4, slot 1. | clip for the pattern |
| 46 | `generate_euclidean_rhythm` | `{"steps": 16, "pulses": 5, "pitch": 36, "track_index": 4, "clip_ind...` | pass | 1117 | { |  |
| 47 | `generate_automation_curve` | `{"curve_type": "triangle", "steps": 9}` | pass | 6 | { |  |
| 48 | `analyze_midi_session` | `{"max_tracks": 8}` | pass | 1826 | MIDI session analysis |  |
| 49 | `fire_clip` | `{"track_index": 4, "clip_index": 0}` | pass | 115 | Launched 'v2 chord' (track 4, slot 0). |  |
| 50 | `stop_clip` | `{"track_index": 4, "clip_index": 0}` | pass | 98 | Stop sent to track 4. |  |
| 51 | `set_scene_tempo` | `{"scene_index": 0, "tempo": 101}` | pass | 1135 | Scene 0 '' now carries 101.00 BPM. |  |
| 52 | `fire_scene` | `{"scene_index": 0}` | pass | 131 | Launched scene 0 ''. |  |
| 53 | `stop_playback` | `{}` | pass | 366 | Stopped at beat 13.43. |  |
| 54 | `start_playback` | `{}` | pass | 431 | Playing from beat 8.35. |  |
| 55 | `get_master_analysis` | `{}` | pass | 231 | Master track (Live's output meter) |  |
| 56 | `stop_playback` | `{}` | pass | 419 | Stopped at beat 9.96. | second call |
| 57 | `undo` | `{}` | pass | 1248 | Undone. |  |
| 58 | `redo` | `{}` | pass | 913 | Redone. |  |
| 59 | `get_browser_tree` | `{"category_type": "all"}` | pass | 551 | Browser (107 folders listed) |  |
| 60 | `get_browser_items_at_path` | `{"path": "audio_effects", "limit": 10}` | pass | 202 | audio_effects  (query:AudioFx) |  |
| 61 | `load_instrument_or_effect` | `{"track_index": 4, "uri": "query:Synths#Wavetable"}` | pass | 818 | Loaded 'Wavetable' onto track 4 'v2 Test MIDI'; new device(s): Wavetable. |  |
| 62 | `load_instrument_or_effect` | `{"track_index": 5, "uri": "query:AudioFx#Compressor"}` | pass | 880 | Loaded 'Compressor' onto track 5 'v2 Test Audio'; new device(s): Compressor. | audio effect onto an audio track |
| 63 | `load_instrument_or_effect` | `{"track_index": 5, "uri": "query:AudioFx#EQ%20Eight"}` | pass | 785 | Loaded 'EQ Eight' onto track 5 'v2 Test Audio'; new device(s): EQ Eight. |  |
| 64 | `get_track_info` | `{"track_index": 5}` | pass | 299 | { | to read the device chain |
| 65 | `get_device_parameters` | `{"track_index": 5, "device_index": 1}` | pass | 232 | EQ Eight on v2 Test Audio: 84 parameters |  |
| 66 | `set_eq_mode` | `{"track_index": 5, "device_index": 1, "mode": 2}` | pass | 1033 | EQ Eight on v2 Test Audio is in M/S mode. |  |
| 67 | `set_eq_mode` | `{"track_index": 5, "device_index": 1, "mode": 0}` | pass | 1097 | EQ Eight on v2 Test Audio is in Stereo mode. | back to Stereo |
| 68 | `set_device_parameter` | `{"track_index": 5, "device_index": 1, "param_name": "1 Gain A", "va...` | pass | 901 | EQ Eight on v2 Test Audio: 1 Gain A = 3.00 dB (raw 3.0000). |  |
| 69 | `set_sidechain_routing` | `{"target_track_index": 5, "device_index": 0, "source_track_index": 4}` | pass | 1247 | Compressor on v2 Test Audio: sidechain switched on, input set to 'v2 Test MIDI'. |  |
| 70 | `load_device_on_master` | `{"uri": "query:AudioFx#Limiter"}` | pass | 851 | Loaded 'Limiter' onto the master track; new device(s): Limiter. |  |
| 71 | `get_device_parameters` | `{"use_master": true, "device_index": 0}` | pass | 399 | Limiter on Master: 13 parameters | master chain |
| 72 | `delete_device` | `{"track_index": 0, "device_index": 0, "use_master": true}` | pass | 6 | Not executed [needs_confirmation]: delete_device is destructive (Remove a device from a... | destructive tool without confirm: refused |
| 73 | `delete_device` | `{"track_index": 0, "device_index": 0, "use_master": true, "confirm"...` | pass | 880 | Removed 'Limiter' from Master. Left: none. |  |
| 74 | `list_ai_changes` | `{"limit": 1}` | pass | 315 | 1 of 45 journal steps (file: %USERPROFILE%\.ableton-y-bridge\journals\v2 Wegwerf.alv2 ... | the deletion is in the journal |
| 75 | `undo_ai_change` | `{"number": 45}` | pass | 414 | Error in undo_ai_change [unsupported]: #45 (Deleted device 'Limiter' from Master) was o... | recorded only: Live's own undo is the way back |
| 76 | `load_device_on_return` | `{"return_index": 0, "uri": "query:AudioFx#Reverb"}` | pass | 1084 | Loaded 'Reverb' onto return track 'A-Reverb \| Reverb'; new device(s): Reverb. |  |
| 77 | `set_return_device_parameter` | `{"return_index": 0, "device_index": 1, "param_name": "Dry/Wet", "va...` | pass | 1232 | Reverb on A-Reverb \| Reverb: Dry/Wet = 50 % (raw 0.5000). |  |
| 78 | `delete_device` | `{"track_index": 0, "device_index": 1, "use_return": true, "return_i...` | pass | 968 | Removed 'Reverb' from A-Reverb \| Reverb. Left: Reverb. | remove the test reverb from Return A |
| 79 | `load_drum_kit` | `{"track_index": 7, "rack_uri": "query:Synths#Drum%20Rack", "kit_pat...` | pass | 2247 | Drum Rack with kit 'Drum Rack' loaded on track 7. | kit_path 'drums': first loadable item of that folder |
| 80 | `search_vst` | `{"name": "e"}` | pass | 200 | 20 plug-in(s) matching 'e': | any installed plug-in with an 'e' in its name |
| 81 | `set_warp_markers_batch` | `{"track_index": "tempo", "clip_index": 0, "markers": "[{\"arr_clip_...` | pass | 1950 | {"clips_created": [{"track": 5, "file": "v2_test_tone_214312.wav", "position": 0.0, "ok... | keyword route: place the test tone on two audio tracks |
| 82 | `get_arrangement_clips` | `{"track_index": 5}` | pass | 214 | Track 5 'v2 Test Audio': 1 Arrangement clip(s) |  |
| 83 | `set_clip_warp_mode` | `{"track_index": 5, "clip_index": 0, "mode": 4}` | pass | 1131 | Track 5 clip 0: warp mode Complex, warping on. |  |
| 84 | `get_warp_markers` | `{"track_index": 5, "clip_index": 0}` | pass | 219 | 'v2_test_tone_214312': 2 warp markers |  |
| 85 | `set_warp_marker` | `{"track_index": 5, "clip_index": 0, "beat_time": 4.0, "sample_time"...` | pass | 1014 | Warp marker added: 2.0000 s at beat 4.0000. |  |
| 86 | `set_warp_markers_batch` | `{"track_index": "5", "clip_index": 0, "markers": "[{\"beat_time\": ...` | pass | 1022 | Set 2 of 2 warp markers; the clip now has 5. |  |
| 87 | `set_warp_markers_batch` | `{"track_index": "warp_intel", "clip_index": "5:0", "markers": "[{\"...` | pass | 228 | {"count": 5, "avg_drift_beats": 0.00625, "max_drift_beats": 0.03125, "max_drift_at_beat... | keyword route: warp_intel |
| 88 | `normalize_clip` | `{"track_index": 5, "clip_index": 0, "arrangement": true, "target_db...` | pass | 1316 | 'v2_test_tone_214312': file peak -6.02 dBFS, clip gain 0.00 dB -> 5.02 dB (wanted +5.02... | test tone peaks at -6.02 dBFS, so +5 dB gain |
| 89 | `create_locator` | `{"time": 8, "name": "v2 A"}` | pass | 1447 | Created locator 'v2 A' at beat 8. |  |
| 90 | `create_locator` | `{"time": 16, "name": "v2 B"}` | pass | 1533 | Created locator 'v2 B' at beat 16. |  |
| 91 | `get_locators` | `{}` | pass | 299 | { |  |
| 92 | `delete_locator` | `{"index": 0}` | pass | 1983 | Deleted locator 'v2 A' at beat 8; 1 left. |  |
| 93 | `clear_locators` | `{}` | pass | 8 | Not executed [needs_confirmation]: clear_locators is destructive (Delete all locators o... | without confirm: refused |
| 94 | `clear_locators` | `{"confirm": true}` | pass | 1842 | Deleted 1 locators, 0 left. |  |
| 95 | `get_safety_status` | `{}` | pass | 316 | { |  |
| 96 | `get_session_info` | `{}` | pass | 201 | { | before the journal checks |
| 97 | `set_tempo` | `{"tempo": 117}` | pass | 949 | Tempo is now 117.00 BPM (was 101.00). |  |
| 98 | `set_track_name` | `{"track_index": 4, "name": "v2 Journal"}` | pass | 915 | Track 4: 'v2 Test MIDI' is now 'v2 Journal'. |  |
| 99 | `undo_ai_change` | `{"number": 61}` | pass | 314 | Took back #61: Tempo: 101.00 -> 117.00 BPM | takes back the tempo step only |
| 100 | `get_session_info` | `{}` | pass | 203 | { | tempo is back, the later rename is still there |
| 101 | `undo_ai_change` | `{"number": 61}` | pass | 198 | Error in undo_ai_change [busy]: #61 was already taken back | a step cannot be taken back twice |
| 102 | `undo_ai_change` | `{"number": 62}` | pass | 168 | Took back #62: Track 4 name: 'v2 Test MIDI' -> 'v2 Journal' | rename taken back |
| 103 | `set_track_volume` | `{"track_index": 4, "volume_db": -20}` | pass | 1267 | Track 4 'v2 Test MIDI' fader at -20.0 dB (raw 0.3600). |  |
| 104 | `set_track_volume` | `{"track_index": 4, "volume_db": -3}` | pass | 1250 | Track 4 'v2 Test MIDI' fader at -3.0 dB (raw 0.7749). |  |
| 105 | `undo_ai_change` | `{"number": 63}` | pass | 195 | Error in undo_ai_change [changed_since]: #63 not taken back: the fader was changed sinc... | the fader was moved again since: the older step is refused |
| 106 | `undo_ai_change` | `{"number": 64}` | pass | 199 | Took back #64: Track 'v2 Test MIDI' fader: -20.0 dB -> -3.0 dB |  |
| 107 | `get_track_info` | `{"track_index": 4}` | pass | 200 | { | fader is back at -20 dB |
| 108 | `replace_notes_in_clip` | `{"track_index": 4, "clip_index": 0, "notes": [{"pitch": 48, "start_...` | pass | 1019 | 'v2 chord' now holds 1 notes (4 removed). |  |
| 109 | `undo_ai_change` | `{"number": 65}` | pass | 214 | Took back #65: Replaced the notes of 'v2 chord': 4 -> 1 notes | notes restored |
| 110 | `get_clip_key` | `{"track_index": 4, "clip_index": 0}` | pass | 300 | { | the four notes are back |
| 111 | `get_track_info` | `{"track_index": 6}` | pass | 300 | { | device count before |
| 112 | `load_instrument_or_effect` | `{"track_index": 6, "uri": "query:AudioFx#Compressor"}` | pass | 663 | Loaded 'Compressor' onto track 6 'v2 Test Audio 2'; new device(s): Compressor. |  |
| 113 | `undo_ai_change` | `{"number": 66}` | pass | 213 | Took back #66: Loaded 'Compressor' onto 'v2 Test Audio 2' | the loaded device is removed again |
| 114 | `get_track_info` | `{"track_index": 6}` | pass | 138 | { | device count after undo |
| 115 | `create_locator` | `{"time": 32, "name": "v2 U"}` | pass | 1532 | Created locator 'v2 U' at beat 32. |  |
| 116 | `undo_ai_change` | `{"number": 67}` | pass | 831 | Took back #67: Created locator 'v2 U' at beat 32 | the locator is deleted again |
| 117 | `get_locators` | `{}` | pass | 199 | { | no locator left |
| 118 | `set_warp_marker` | `{"track_index": 5, "clip_index": 0, "beat_time": 10.0, "sample_time...` | pass | 1466 | Warp marker added: 5.0000 s at beat 10.0000. |  |
| 119 | `get_warp_markers` | `{"track_index": 5, "clip_index": 0}` | pass | 299 | 'v2_test_tone_214312': 6 warp markers | with the extra marker |
| 120 | `undo_ai_change` | `{"number": 68}` | pass | 316 | Took back #68: Clip 'v2_test_tone_214312': warp marker added (5.000 s at beat 10.000) | warp markers restored |
| 121 | `get_warp_markers` | `{"track_index": 5, "clip_index": 0}` | pass | 217 | 'v2_test_tone_214312': 5 warp markers | one marker fewer |
| 122 | `get_session_info` | `{}` | pass | 299 | { | track count before |
| 123 | `create_midi_track` | `{"index": -1}` | pass | 567 | New MIDI track '9-MIDI' at index 8. |  |
| 124 | `undo_ai_change` | `{"number": 69}` | pass | 382 | Took back #69: Created MIDI track '9-MIDI' at index 8 | the new track is deleted again |
| 125 | `get_session_info` | `{}` | pass | 199 | { | track count after undo |
| 126 | `list_ai_changes` | `{"limit": 0}` | pass | 400 | 69 of 69 journal steps (file: %USERPROFILE%\.ableton-y-bridge\journals\v2 Wegwerf.alv2... |  |
| 127 | `apply_mastering_corrections` | `{"style": "streaming"}` | pass | 4 | Mastering check, style Streaming | without analyzer |
| 128 | `get_master_analysis` | `{}` | pass | 225 | Master track (Live's output meter) | synthetic analyzer frame sent by the test, not a real measurement |
| 129 | `apply_mastering_corrections` | `{"style": "streaming"}` | pass | 8 | Mastering check, style Streaming | synthetic analyzer frame sent by the test, not a real measurement |
| 130 | `suggest_mastering_chain` | `{"style": "club"}` | pass | 10 | Mastering chain proposal: Club / EDM | synthetic analyzer frame sent by the test, not a real measurement |
| 131 | `color_track_by_spectrum` | `{"track_index": 4, "dry_run": false}` | pass | 1132 | Dominant band: mid (-21.0 dB) -> #00C840. Levels in dB: sub:-32.0  low:-24.0  mid:-21.0... | synthetic analyzer frame sent by the test, not a real measurement |
| 132 | `color_all_tracks_by_spectrum` | `{"dry_run": true}` | pass | 316 | Dry run: 8 tracks would get #00C840 (mid). | synthetic analyzer frame sent by the test, not a real measurement |
| 133 | `snapshot_session` | `{"label": "v2test", "snapshot_dir": "<scratch folder>/...` | pass | 1448 | Snapshot: <scratch folder>... |  |
| 134 | `list_snapshots` | `{"snapshot_dir": "<scratch folder>/...` | pass | 5 | 1 snapshot(s) in <scratch folder>... |  |
| 135 | `als_warp_read` | `{"als_path": "<scratch folder>/...` | pass | 74 | [0] '3-Audio': 0 clip(s) |  |
| 136 | `als_warp_read` | `{"als_path": "<scratch folder>/...` | pass | 19 | { | markers of one clip |
| 137 | `als_warp_write` | `{"als_path": "<scratch folder>/...` | pass | 810 | Wrote 3 warp markers to 'v2 Test Audio' / 'v2_test_tone_214312'. Backup: %USERPROFILE%... |  |
| 138 | `als_warp_derive` | `{"als_path": "<scratch folder>/...` | pass | 82 | Dry run: 3 markers would go to 'v2 Test Audio 2' / 'v2_test_tone_214312' with offset +0... | dry run needs no confirm |
| 139 | `als_warp_derive` | `{"als_path": "<scratch folder>/...` | pass | 1049 | Wrote 3 markers to 'v2 Test Audio 2' / 'v2_test_tone_214312', derived from 'v2 Test Aud... |  |
| 140 | `als_warp_read` | `{"als_path": "<scratch folder>/...` | pass | 34 | { | read back the derived markers |
| 141 | `set_tempo_automation` | `{"als_path": "<scratch folder>/...` | pass | 1497 | { |  |
| 142 | `set_tempo_automation` | `{"als_path": "<scratch folder>/...` | pass | 32 | { | read back |
| 143 | `set_wavetable_mod_routing` | `{"als_path": "<scratch folder>/...` | pass | 1202 | { |  |
| 144 | `group_tracks` | `{"track_indices": [5, 6]}` | pass | 2395 | Grouped 2 tracks (v2 Test Audio, v2 Test Audio 2) into '6-Group' at index 5. Later trac... | types Shift+Right and Ctrl+G into Live's window |
| 145 | `get_session_info` | `{}` | pass | 203 | { | after grouping |
| 146 | `set_tempo` | `{"tempo": 120.0}` | pass | 1113 | Tempo is now 120.00 BPM (was 101.00). | restore the tempo |
