# Ableton Y Bridge — Example Prompts

**English** · [Deutsch](PROMPTS.de.md)

Two example prompts that build a small project in Live step by step. Copy them into Claude
(Claude Desktop, Cowork or Claude Code) with Ableton Y Bridge connected.

---

## Prompt 1 — Basic Setup (Claude Haiku)

> Run this first to create the base project "KI-Studio" with Kick, Snare, HiHat, Bass, Pad, Vox tracks and a Compressor on the Bass track.

---

## Prompt 2 — Advanced Routing, Sidechain, Reverb, Pad & Delay (Claude Haiku/Sonnet)

**Prerequisites:** Prompt 1 has been executed. Project "KI-Studio" exists with Kick, Snare, HiHat, Bass, Pad, Vox, Compressor on Bass.

```
You are an Ableton assistant with reasoning capabilities for complex, iterative tasks.
Prerequisite: Prompt 1 (Haiku) has already been executed.
The project "KI-Studio" exists with Kick, Snare, HiHat, Bass, Pad, Vox, Compressor on Bass.

=== TASK A — Sidechain Routing (Kick → Bass Compressor) ===
1. Create a new MIDI track: Name "[GHOST] Kick Trigger", Color dark gray, Mute = True
2. Load Drum Rack with TR-808 Kit (same as Kick track)
3. Create clip in Scene 1, 2 bars, with Note 36 on every quarter note
   (Beat 1.1, 2.1, 3.1, 4.1 per bar), Velocity 100, Duration 0.25
4. Activate the Compressor on the Bass track with the [GHOST] track as sidechain source:
   * Use set_sidechain_routing with source_track=[GHOST]-index, target_track=Bass-index, device_index=0
   * Log device.available_input_routing_types to see available routing types
   * Iterate: try matching on track name fragments, track index, partial strings
   * Check the log (%APPDATA%\Ableton\Live 12.x.x\Preferences\Log.txt) for routing_set=True
   * If routing_set=False: adjust the match expression and call hot_reload, then retry
   * Only when routing_set=True: proceed to Task B

=== TASK B — Reverb on Drums (Return Track) ===
5. Make sure Return Track A exists (Ableton creates it automatically)
6. Load a Reverb on Return Track A: search "Reverb" in browser and load on Return Track A
7. Set Reverb parameters on Return A:
   * Decay Time: ~2.5s (raw ~0.55)
   * Dry/Wet: 1.0 (Return Track is always 100% Wet)
8. Set the Send from Drums → Return A to ~0.25 (25% Send)
   * Use set_return_device_parameter if needed; iterate until Send value is correctly set

=== TASK C — Wavetable Pad ===
9. Search the Ableton Browser for a Wavetable Pad preset:
   * Search terms: "Wavetable", "Pad", "Atmospheric" — try get_browser_items_at_path
   * Load an atmospheric pad preset onto the Pad track
10. Create a Pad clip in Scene 1 (4 bars):
    * Note 52 (E3), Beat 1.1, Velocity 70, Duration 3.9
    * Note 55 (G3), Beat 1.1, Velocity 65, Duration 3.9
    * Note 59 (B3), Beat 1.1, Velocity 60, Duration 3.9
11. Pad Volume: 0.55

=== TASK D — Load Eventide Delay VST3 ===
12. Search for Eventide in the VST3 browser: search_vst("Eventide")
13. If Eventide Delay found: load on Pad track (after Wavetable instrument)
14. If not found: load Ableton's "Simple Delay" instead and set:
    * Left/Right time to 1/8 note (Sync)
    * Feedback: 35%
    * Dry/Wet: 0.30
15. Report what was loaded.

Important notes for all tasks:
* ALWAYS load audio effects AFTER the instrument
* After changing a command handler, call hot_reload
* On errors: read the log first, then adjust strategy — do not blindly repeat
```

---

## Tools these prompts rely on

| Tool | What it does |
|------|-------------|
| `set_sidechain_routing` | Routes sidechain source to a compressor via Live API |
| `load_device_on_return` | Loads a device directly onto a Return track |
| `set_track_send` | Sets the send level from a track to a Return |
| `set_track_color` | Colors tracks with Ableton's 70-color palette |
| `search_vst` | Searches for VST3 plugins in the browser |
| `hot_reload` | Reloads the command handlers without restarting Live |

---

## Tips for Running These Prompts

- Use **Claude Haiku** for Prompt 1 (fast, simple track creation)
- Use **Claude Sonnet** for Prompt 2 (complex routing, iteration, reasoning)
- Make sure Live is open and **AbletonMCP** is selected as a Control Surface before running
- Live's status bar then shows "Ableton Y Bridge … on port 9877"; the MCP server connects
  to that port
