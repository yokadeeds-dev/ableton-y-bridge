# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Level and spectrum feedback, and mastering helpers built on it.

Spectrum data comes from an external analyzer (see ``analyzer/`` and
``m4l/``) that sends frames over UDP; without it only Live's own master
meter is available.
"""

from __future__ import annotations

from ..analyzer_feed import BAND_ORDER, BAND_RANGES, audible_bands
from ..coerce import BoolLike, FloatLike, IntLike, to_bool, to_float, to_int
from ..core import READ, REVERSIBLE, analyzer, live, tool

STYLES = {
    "streaming": {"lufs": -14.0, "peak": -1.0, "label": "Streaming"},
    "club": {"lufs": -9.0, "peak": -1.0, "label": "Club / EDM"},
    "dancefloor": {"lufs": -7.0, "peak": -0.5, "label": "Dancefloor (loud)"},
}
MAXIMIZER_URI = "query:Plugins#VST3:iZotope:Ozone%2012%20Maximizer"
NO_ANALYZER = ("No analyzer signal. Start analyzer/audio_analyzer.py (or the Max for Live "
               "analyzer device), play the song and call this again.")

# 24-bit RGB per band, snapped by Live to its palette.
BAND_COLOURS = {
    "sub": 0x1A3CFF,   # deep blue
    "low": 0xFF6400,   # orange
    "mid": 0x00C840,   # green
    "high": 0xFFD000,  # yellow
    "air": 0x00DCFF,   # cyan
}


def _style(name: str) -> dict:
    key = (name or "").strip().lower()
    if key not in STYLES:
        raise ValueError(f"unknown style '{name}'; choose from {', '.join(STYLES)}")
    return STYLES[key]


def _spectral_findings(bands: dict) -> list:
    """Rule-of-thumb observations about the balance of the five bands.

    Returns (observation, suggested action) pairs. The thresholds are coarse
    on purpose: they point at something to listen for, they do not judge.
    """
    findings = []
    get = bands.get
    if "sub" in bands and "low" in bands and get("sub") > get("low") + 3:
        findings.append((f"sub ({get('sub'):.1f} dB) sits above the low band ({get('low'):.1f} dB)",
                         "try a low shelf of about -2 dB around 40 Hz"))
    if "low" in bands and "mid" in bands and get("low") > get("mid") + 6:
        findings.append((f"low band ({get('low'):.1f} dB) is far above the mids ({get('mid'):.1f} dB)",
                         "check 200-400 Hz for mud, a bell of about -3 dB"))
    if "mid" in bands and "high" in bands and get("mid") < get("high") - 4:
        findings.append((f"mids ({get('mid'):.1f} dB) are below the highs ({get('high'):.1f} dB)",
                         "a gentle lift of about +1.5 dB around 1-3 kHz may add body"))
    if "air" in bands and "mid" in bands and get("air") < get("mid") - 12:
        findings.append((f"air band ({get('air'):.1f} dB) is far below the mids",
                         "a high shelf of +1 to +2 dB around 10 kHz may open the top"))
    if "high" in bands and "mid" in bands and get("high") > get("mid") + 2:
        findings.append((f"highs ({get('high'):.1f} dB) are above the mids ({get('mid'):.1f} dB)",
                         "listen for harshness; a high shelf of about -1 dB around 8 kHz"))
    return findings



def _master_y_meter():
    """Frame of a Y Meter device on the master track (Live 12 calls it 'Main')."""
    measured = analyzer.tracks()
    return measured.get("Main") or measured.get("Master")


BAND_FLOOR_DB = -90.0  # quieter bands are shown as silent


def _db(value) -> str:
    return "silent" if value is None else f"{value:6.1f} dB"


@tool(READ)
def get_track_levels(seconds: FloatLike = 2.0, include_returns: BoolLike = True) -> str:
    """Levels of all tracks side by side while the song plays.

    Samples Live's output meters of every track, return track and the master
    for a few seconds (about ten readings a second) and lists the highest and
    the average reading per track in dBFS (post-fader; the conversion was
    checked against sine tones of known level). Good for comparing tracks
    and spotting tracks that go over 0 dB; not a loudness measurement. Tracks
    that carry the "Y Meter" Max for Live device also show RMS, peak and the
    five-band spectrum measured where the device sits (usually pre-fader).
    Start playback first; silent or stopped tracks read "silent".

    - seconds: sampling window in seconds, 0 to 10 (default 2)
    - include_returns: also list the return tracks (default true)
    """
    window = to_float(seconds, "seconds")
    if not 0.0 <= window <= 10.0:
        raise ValueError("seconds must be between 0 and 10")
    result = live.call("get_track_meters", seconds=window,
                       include_returns=to_bool(include_returns, "include_returns"))
    measured = analyzer.tracks()
    rows = [f"Track levels over {result['seconds']:.1f} s ({result['samples']} readings, "
            f"{'playing' if result.get('playing') else 'transport stopped'})",
            "Live meter, post-fader: highest / average reading (dBFS)", ""]
    labels = {"track": lambda r: f"{r['index']:>3}", "return": lambda r: f"R{r['index']:<2}",
              "master": lambda r: "  M"}
    for row in result["tracks"]:
        head = f"{labels[row['kind']](row)}  {row['name'][:28]:<28}"
        if not row.get("audio_output"):
            rows.append(f"{head}  (no audio output)")
            continue
        line = f"{head}  {_db(row.get('peak_db'))} / {_db(row.get('mean_db'))}"
        if row.get("over_0db"):
            line += f"  over 0 dB in {row['over_0db']} readings"
        rows.append(line)
        frame = measured.get(row["name"])
        if frame:
            bands = "  ".join(f"{band} {frame['bands'][band]:.0f}" for band in BAND_ORDER
                              if frame["bands"].get(band, -999.0) > BAND_FLOOR_DB)
            rows.append(f"       Y Meter: RMS {frame['rms_db']:.1f} dB, peak "
                        f"{frame['peak_db']:.1f} dBFS" + (f" | {bands} dB" if bands else ""))
    if not result.get("playing"):
        rows += ["", "The transport was stopped: start playback and call again."]
    if not measured:
        rows += ["", "Spectrum per track: put the \"Y Meter\" Max for Live device on the "
                     "tracks you want to look at (see m4l/README.md)."]
    return "\n".join(rows)


@tool(READ)
def get_master_analysis() -> str:
    """Current level of the master track, plus the spectrum if an analyzer runs.

    The meter values come from Live's master output meter (a momentary peak
    reading, not a loudness measurement) and are only meaningful while the
    song plays. Loudness (LUFS approximation) and the five-band spectrum
    appear when the external analyzer is sending.
    """
    meter = live.call("get_master_levels")
    peak = meter.get("peak_db")
    rows = [
        "Master track (Live's output meter)",
        f"  peak: {'silent' if peak is None else f'{peak:.1f} dBFS'}",
        f"  meter L/R: {meter['meter_left']:.4f} / {meter['meter_right']:.4f}",
        f"  transport: {'playing' if meter.get('is_playing') else 'stopped'}",
    ]
    frame = analyzer.fresh() or _master_y_meter()
    if frame is None:
        rows += ["", "Analyzer: no signal (start analyzer/audio_analyzer.py or the "
                     "Max for Live analyzer to get loudness and spectrum)."]
        return "\n".join(rows)
    rows += ["", "Analyzer (external measurement)"]
    for label, key, unit in (("loudness (approx.)", "lufs_approx", "LUFS"),
                             ("RMS", "rms_db", "dB"), ("peak", "peak_db", "dBFS")):
        if isinstance(frame.get(key), (int, float)):
            rows.append(f"  {label}: {frame[key]:.1f} {unit}")
    bands = audible_bands(frame)
    for name in BAND_ORDER:
        if name in bands:
            rows.append(f"  {name:<4} ({BAND_RANGES[name]}): {bands[name]:.1f} dB")
    return "\n".join(rows)


@tool(READ)
def apply_mastering_corrections(target_lufs: FloatLike = -14.0,
                                true_peak_ceiling: FloatLike = -1.0,
                                style: str = "streaming") -> str:
    """Compare the playing mix with a loudness target and say what to change.

    Despite its name this tool changes nothing in Live: it reads the
    analyzer and reports the loudness gap and spectral observations with
    the tool calls that would address them.

    - target_lufs: wanted integrated loudness; the default follows the style
    - true_peak_ceiling: wanted peak ceiling in dBTP; default follows the style
    - style: 'streaming' (-14 LUFS), 'club' (-9), 'dancefloor' (-7)
    """
    preset = _style(style)
    wanted_lufs = to_float(target_lufs, "target_lufs")
    wanted_peak = to_float(true_peak_ceiling, "true_peak_ceiling")
    # The defaults mean "use the style's value".
    if wanted_lufs == -14.0:
        wanted_lufs = preset["lufs"]
    if wanted_peak == -1.0:
        wanted_peak = preset["peak"]
    rows = [f"Mastering check, style {preset['label']}",
            f"Target: {wanted_lufs:g} LUFS, ceiling {wanted_peak:g} dBTP", ""]
    frame = analyzer.fresh()
    if frame is None:
        return "\n".join(rows + [NO_ANALYZER])
    loudness = float(frame.get("lufs_approx", 0.0))
    gap = wanted_lufs - loudness
    rows += [f"Now: {loudness:.1f} LUFS (approx.), peak {float(frame.get('peak_db', 0.0)):.1f} dBFS",
             f"Gap to target: {gap:+.1f} dB"]
    if abs(gap) > 0.5:
        rows.append(f"  -> raise or lower the limiter input by about {gap:+.1f} dB")
    findings = _spectral_findings(audible_bands(frame))
    rows += ["", "Spectrum:"]
    rows += [f"  - {seen}: {advice}" for seen, advice in findings] or ["  balanced, nothing stands out"]
    rows += ["", "Possible next steps:",
             f"  1. load_device_on_master(uri='{MAXIMIZER_URI}')  (or another limiter)",
             f"  2. set its ceiling to {wanted_peak:g} dBTP with set_device_parameter",
             "  3. apply EQ changes with set_device_parameter, then get_master_analysis"]
    return "\n".join(rows)


@tool(READ)
def suggest_mastering_chain(style: str = "streaming") -> str:
    """Propose a mastering chain as a list of tool calls, without applying it.

    Explains each step so it can be confirmed one by one. Uses the analyzer
    if it is sending, otherwise general starting values.

    - style: 'streaming' (-14 LUFS), 'club' (-9), 'dancefloor' (-7)
    """
    preset = _style(style)
    frame = analyzer.fresh()
    rows = [f"Mastering chain proposal: {preset['label']}",
            f"Target: {preset['lufs']:g} LUFS, ceiling {preset['peak']:g} dBTP", ""]
    if frame is None:
        rows += ["No analyzer signal: the steps below are general starting points.", ""]
        loudness, bands = None, {}
    else:
        loudness, bands = float(frame.get("lufs_approx", -20.0)), audible_bands(frame)
        rows += [f"Measured now: {loudness:.1f} LUFS (approx.), "
                 f"{preset['lufs'] - loudness:+.1f} dB to the target", ""]
    rows += ["Step 1 - limiter on the master",
             f"  load_device_on_master(uri='{MAXIMIZER_URI}')",
             "  (any limiter works; Live's own is 'query:AudioFx#Limiter')", "",
             f"Step 2 - ceiling at {preset['peak']:g} dBTP",
             "  get_device_parameters(use_master=true, device_index=<limiter>) to find the",
             "  ceiling parameter and its raw range, then set_device_parameter(...)", "",
             "Step 3 - tonal balance"]
    findings = _spectral_findings(bands)
    if findings:
        rows += [f"  - {seen}: {advice}" for seen, advice in findings]
    elif bands:
        rows.append("  the five bands look balanced; no EQ move suggested")
    else:
        rows.append("  no spectrum available; judge by ear or start the analyzer")
    if loudness is not None and abs(preset["lufs"] - loudness) > 0.5:
        rows += ["", "Step 4 - loudness",
                 f"  drive the limiter input by about {preset['lufs'] - loudness:+.1f} dB"]
    rows += ["", "Then - verify", "  get_master_analysis() while the loudest part plays"]
    return "\n".join(rows)


def _dominant_band():
    frame = analyzer.fresh()
    if frame is None:
        raise ValueError(NO_ANALYZER)
    bands = audible_bands(frame)
    if not bands:
        raise ValueError("The analyzer reports silence in all bands; play something first.")
    name = max(bands, key=bands.get)
    return name, bands


@tool(REVERSIBLE)
def color_track_by_spectrum(track_index: IntLike = 0, dry_run: BoolLike = False) -> str:
    """Colour one track by the frequency band that dominates what plays now.

    Solo the track first: the analyzer hears the master output. Colours:
    sub = blue, low = orange, mid = green, high = yellow, air = cyan.

    - track_index: track number, counting from 0
    - dry_run: only report the band and colour, change nothing
    """
    index = to_int(track_index, "track_index")
    band, bands = _dominant_band()
    colour = BAND_COLOURS[band]
    levels = "  ".join(f"{name}:{bands[name]:.1f}" for name in BAND_ORDER if name in bands)
    text = (f"Dominant band: {band} ({bands[band]:.1f} dB) -> #{colour:06X}. "
            f"Levels in dB: {levels}.")
    if to_bool(dry_run, "dry_run"):
        return text + " Dry run, colour not set."
    result = live.call("set_track_color", track_index=index, color_rgb=colour)
    return text + f" Track {index} '{result['name']}' coloured."


@tool(REVERSIBLE)
def color_all_tracks_by_spectrum(dry_run: BoolLike = False) -> str:
    """Give every track the colour of the band that dominates the master right now.

    All tracks get the same colour, because the analyzer measures the
    master output, not single tracks. For per-track colours solo each track
    and use color_track_by_spectrum.

    - dry_run: only report, change nothing
    """
    band, bands = _dominant_band()
    colour = BAND_COLOURS[band]
    count = live.call("get_session_info")["track_count"]
    if to_bool(dry_run, "dry_run"):
        return f"Dry run: {count} tracks would get #{colour:06X} ({band})."
    for index in range(count):
        live.call("set_track_color", track_index=index, color_rgb=colour)
    return f"Coloured {count} tracks #{colour:06X} for the dominant band '{band}'."
