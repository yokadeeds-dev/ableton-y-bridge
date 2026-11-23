# Y Meter (Max for Live)

A small audio effect that measures the track it sits on and sends the numbers to the
MCP server, so the assistant can see levels and the spectrum per track while the song
plays.

- **Measures:** RMS and peak of the track, and the level of five bands: sub (20-60 Hz),
  low (60-250 Hz), mid (250 Hz-2 kHz), high (2-8 kHz), air (8-20 kHz). The bands are split
  with `cross~` crossovers; the RMS window is 200 ms.
- **Sends:** about five times a second, an OSC message to UDP `127.0.0.1:7878`:
  `/ytrack <track name> rms peak sub low mid high air` (linear amplitudes). The track name
  comes from Live and follows renames.
- **Audio:** passes through unchanged.
- Built only from native Max objects; it needs no extra files and Live 12 Suite (or Live
  with Max for Live).

## Install

`Y Meter.amxd` in this folder is ready to use. Copy it into your User Library, or build
and copy it in one go:

```powershell
python m4l\build_y_meter.py --install
```

It lands in `User Library > Presets > Audio Effects > Max Audio Effect`.

## Use

Drop **Y Meter** on every track you want to look at, usually as the last device. Then ask
the assistant for `get_track_levels`; tracks with the device show RMS, peak and the bands
next to Live's own meter reading. A Y Meter on the main track also feeds
`get_master_analysis`.

## Things to know

- **Where it measures:** at its place in the device chain, so normally **before** the
  track fader and pan. Live's meter values in `get_track_levels` are **after** the fader.
- **RMS, not loudness:** there is no K-weighting, so the values are not LUFS.
- **Names:** frames are matched to tracks by name. Two tracks with the same name share
  one entry.
- **Several MCP servers:** when more than one server runs (for example Claude Desktop and
  Claude Code each started one), the first one owns UDP 7878 and passes every frame on to
  the others; if it ends, another takes over within about two seconds. `bridge_status`
  shows each server's role under `analyzer_feed`. Servers older than bridge 2.2.0 do not
  take part: restart them. For a different port, build a copy with `--port` and set
  `ABLETON_MCP_ANALYZER_PORT` to match.
- Each instance costs a little CPU (five filters and seven meters).
