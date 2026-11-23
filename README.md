# Ableton Y Bridge

An MCP server and a Remote Script that let an AI assistant (Claude or any other MCP
client) work inside **Ableton Live 12**: read the Set, build tracks and clips, write
MIDI, load and adjust devices, handle warp markers and locators, and edit `.als` project
files where Live's own API ends.

> **Unofficial.** Not made, endorsed or supported by Ableton. "Ableton" and "Live" are
> trademarks of Ableton AG.
>
> **Windows first.** Written and tested on Windows 11 with Live 12.3.6. macOS is untested.
>
> **It changes your open Live Set directly.** Destructive steps need a confirmation and
> every change is journalled, but ordinary edits happen at once. Work on a copy of
> Sets you care about.

## What it can do

79 tools, grouped by subject. Every tool carries a zone: *read* (26), *reversible* (46)
or *destructive* (7, they run only with `confirm=true`). Every change gets a numbered
journal entry and most can be taken back one by one; see [Safety](#safety).

| Area | Tools |
|---|---|
| Session and transport | `get_session_info`, `set_tempo`, `start_playback`, `stop_playback`, `jump_to_time`, `set_arrangement_loop`, `set_arrangement_record`, `fire_scene`, `set_scene_tempo`, `switch_view`, `focus_view`, `undo`, `redo` |
| Tracks and mixer | `get_track_info`, `create_midi_track`, `create_audio_track`, `set_track_name`, `set_track_volume` (dB as Live shows it), `set_track_mute`, `set_track_color`, `set_track_send`, `select_tracks`, `group_tracks`, `freeze_track`, `get_return_tracks`, `set_return_track_volume` |
| Clips and notes | `create_clip`, `set_clip_name`, `fire_clip`, `stop_clip`, `add_notes_to_clip`, `replace_notes_in_clip`, `delete_notes_from_clip`, `humanize_clip`, `transpose_notes`, `normalize_clip`, `get_clip_key`, `analyze_midi_session`, `generate_euclidean_rhythm`, `generate_automation_curve` |
| Devices and browser | `get_browser_tree`, `get_browser_items_at_path`, `search_vst`, `load_instrument_or_effect`, `load_device_on_master`, `load_device_on_return`, `load_drum_kit`, `get_device_parameters`, `set_device_parameter`, `set_return_device_parameter`, `delete_device`, `set_eq_mode`, `set_sidechain_routing` |
| Arrangement | `get_arrangement_clips`, `set_clip_warp_mode`, `get_warp_markers`, `set_warp_marker`, `set_warp_markers_batch`, `get_locators`, `create_locator`, `delete_locator`, `clear_locators` |
| `.als` project files | `als_warp_read`, `als_warp_write`, `als_warp_derive`, `set_tempo_automation`, `set_wavetable_mod_routing`, `snapshot_session`, `list_snapshots` |
| Levels and mastering help | `get_master_analysis`, `apply_mastering_corrections`, `suggest_mastering_chain`, `color_track_by_spectrum`, `color_all_tracks_by_spectrum` |
| Safety | `get_safety_status`, `list_ai_changes`, `undo_ai_change` |
| Maintenance | `bridge_status` (version and health check), `hot_reload` |

All track, clip, scene and device indices count from 0. Positions and lengths are in beats.

## How it works

```
MCP client  --stdio-->  MCP_Server (Python)  --TCP 127.0.0.1:9877-->  Remote Script inside Live
                              ^
                              +-- UDP 7878: level/spectrum frames from an optional analyzer
```

- **Remote Script** (`AbletonMCP_Remote_Script/`): runs inside Live. A small TCP server
  accepts `{"type": ..., "params": {...}}` messages. Each command is looked up in a
  **command register** (handler plus metadata: zone, undo behaviour, parameters, timeout)
  and executed on Live's main thread; the reply is `{"status": "success", "result": ...}`
  or `{"status": "error", "message": ..., "code": ...}`.
- **MCP server** (`MCP_Server/`): turns the tools above into bridge commands and does
  what cannot be done inside Live: reading audio files, editing `.als` files, typing the
  two keyboard shortcuts Live has no API for (save, group).
- **Hot reload**: all command handlers can be replaced while Live runs (`hot_reload`).
  The socket server and the other core modules need a restart of Live;
  `bridge_status` tells you when that is the case.

## Installation (Windows)

Requirements: Ableton Live 12, Python 3.10 or newer.

1. Get the code and install the one required package:

   ```powershell
   git clone <this repository> ableton-y-bridge
   cd ableton-y-bridge
   python -m pip install "mcp[cli]>=1.8"
   ```

   Optional: `python -m pip install soundfile` lets `normalize_clip` read AIFF, FLAC and
   MP3 files (16- and 32-bit WAV work without it).

2. Install the Remote Script into Live's User Library:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install_remote_script.ps1
   ```

   This copies `AbletonMCP_Remote_Script` to
   `Documents\Ableton\User Library\Remote Scripts\AbletonMCP`. An existing folder of that
   name is moved to `Documents\Ableton\Remote Script Backups` first; the same script with
   `-Restore` puts the latest backup back.

3. Start Live, open **Settings > Link, Tempo & MIDI** and choose **AbletonMCP** as a
   Control Surface (input and output stay at "None"). Live's status bar shows
   "Ableton Y Bridge 2.1.0 on port 9877".

4. Tell your MCP client about the server. For Claude Desktop or Claude Code:

   ```json
   {
     "mcpServers": {
       "AbletonMCP": {
         "command": "python",
         "args": ["C:/path/to/ableton-y-bridge/MCP_Server/server.py"]
       }
     }
   }
   ```

5. Ask the assistant to call `bridge_status`. It reports the bridge version, the number of
   commands and Live's version.

Settings (host, port, timeouts, pacing, analyzer port, snapshot folder) are environment
variables; see [.env.example](.env.example). No keys or accounts are needed.

## Safety

- **Zones.** Each tool is *read*, *reversible* or *destructive*. Destructive tools
  (`delete_device`, `clear_locators`, `snapshot_session` and the four tools that write
  `.als` files) do nothing unless called with `confirm=true`; the assistant is told to
  ask you first. The bridge itself refuses destructive commands without that flag.
- **Journal.** Every change made through the bridge gets a number, shown in the tool
  answer (`Journal: #12 Track 'Bass' fader: 0.0 dB -> -6.0 dB`). `list_ai_changes`
  shows the list.
- **Single-step undo.** `undo_ai_change(12)` takes back exactly step 12 and leaves
  every other step alone. If you changed the same thing in Live since, your setting
  stays and the tool says so.
- **Limit.** `ABLETON_MCP_MAX_ZONE=read` (or `reversible`) in the server's environment
  restricts what the assistant can do at all.

Details, the list of what can be taken back, and the limits of all this:
[docs/SAFETY.md](docs/SAFETY.md).

## Things to know

- **Save and group use the keyboard.** Live's API can neither save a Set nor group tracks.
  `snapshot_session` and `group_tracks` bring Live's window to the front and type
  Ctrl+S / Ctrl+G. They refuse to type when Live is not in front or shows a dialog, and
  they say so. Windows only.
- **Journal files** are written to `%USERPROFILE%\.ableton-y-bridge\journals`.
- **Saving needs a Set that has a file.** An untitled Set, a Set outside a Project folder
  or one made by an older Live version makes Live open a dialog instead of saving.
- **Locators** can only be created or deleted while the transport is stopped
  (`clear_locators` stops it itself).
- **Freezing** is not possible through Live's API; `freeze_track` reports the state.
- **One selected track.** Live's API has no multi-selection.
- **Spectrum and loudness** need the external analyzer (below). Without it
  `get_master_analysis` shows Live's master meter only.
- **`.als` tools** edit the file on disk and make a backup by default. Reload the project
  in Live to see the change, and do not save from Live in between.
- **`eval_code`** (run a Python expression inside Live) exists as a bridge command for
  development and is switched off unless you create the file `allow_eval.flag` next to
  the installed script.
- The bridge listens on the loopback address only. Anything that can open a local TCP
  connection can send commands, as with other Remote Script bridges.

## Optional parts

- `analyzer/`: a WASAPI loopback analyzer (`audio_analyzer.py`) that sends level,
  loudness and a five-band spectrum over UDP, a small dashboard, and a wrapper to run it
  as a Windows service. Needs the packages in `analyzer/requirements.txt`.
- `m4l/`: sources for a Max for Live device that sends the same frames from inside Live.
- `tools/melody_check/`: scripts that compare Live's Melody-to-MIDI result with the
  source vocal (project-specific settings at the top of each file).
- `docs/PROMPTS.md`: example prompts.

## For developers

A command is a function with a decorator; the register is the only place that knows
command names:

```python
# AbletonMCP_Remote_Script/handlers/tracks.py
@command("set_track_mute", zone=REVERSIBLE, summary="Mute or unmute a track",
         params=[Int("track_index"), Bool("mute")])
def set_track_mute(live, track_index, mute):
    track = live.track(track_index)
    track.mute = mute
    return {"track_index": track_index, "name": track.name, "mute": bool(track.mute)}
```

Drop a new file into `handlers/`, call `hot_reload`, and the command is there. The bridge
command `list_commands` returns the whole register with zones and parameters.

Tests:

```powershell
python -m unittest discover -s tests          # offline, against a fake Live object model
python tests\live_protocol.py --work-dir <scratch folder>   # every tool once, against a running Live
```

The second one writes [docs/LIVE_TEST_PROTOCOL.md](docs/LIVE_TEST_PROTOCOL.md); see also
[docs/LIVE_TEST_NOTES.md](docs/LIVE_TEST_NOTES.md) for what was and was not covered.
Use a throwaway Set for it.

## Origin and thanks

The idea of driving Live from an MCP server through a socket in a Remote Script, and the
simple JSON wire format, come from [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp)
and [uisato/ableton-mcp-extended](https://github.com/uisato/ableton-mcp-extended). This
project began as a fork of the latter. Thank you both for the inspiration.

The code in this repository has since been written from scratch and contains no code from
those projects; [docs/TEMPLATE_AUDIT.md](docs/TEMPLATE_AUDIT.md) documents the comparison.
The wire format is kept compatible so that clients speaking it continue to work.

## Why open source

I believe in open source. Knowledge and progress grow when they are shared, and I don't
like seeing progress held back because someone sits on it for financial reasons. Together
we can shape things much better than each on our own.

That is why Ableton Y Bridge is licensed under the AGPL: anyone may use, study and improve
it, and improvements stay open for everyone. The commercial licence exists only for those
who want to build it into a closed product.

## Licence

Ableton Y Bridge is dual-licensed:

- **Open source:** [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-only).
- **Commercial licence:** for embedding it in a closed or commercial product without the
  AGPL obligations. See [LICENSING.md](LICENSING.md).

Contributions need the contributor agreement in [CONTRIBUTING.md](CONTRIBUTING.md).
Specifications and conformance tests developed together with other projects are kept in
separate repositories under the MIT licence, so that projects under other licences can
use them too.
