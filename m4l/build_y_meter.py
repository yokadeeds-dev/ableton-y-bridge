#!/usr/bin/env python3
# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Builds the Max for Live audio effect "Y Meter".

Y Meter sits on any track, passes the audio through unchanged and measures it:
RMS, peak and the level of five bands (sub, low, mid, high, air, split with
cross~ crossovers at 60, 250, 2000 and 8000 Hz). About five times a second it
sends an OSC message to the MCP server on UDP 127.0.0.1:7878:

    /ytrack <track name> rms peak sub low mid high air     (linear amplitudes)

The track name comes from Live (live.path this_device canonical_parent) and
follows renames. Only native Max objects are used, so the device needs no
extra files.

    python m4l/build_y_meter.py              # writes m4l/Y Meter.amxd
    python m4l/build_y_meter.py --install    # also copies it into the User Library
"""

import argparse
import json
import os
import shutil
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "Y Meter.amxd")
USER_LIBRARY_TARGET = os.path.join(
    os.path.expanduser("~"), "Documents", "Ableton", "User Library", "Presets",
    "Audio Effects", "Max Audio Effect", "Y Meter.amxd")

PORT = 7878
INTERVAL_MS = 200
WINDOW = 8820          # RMS window in samples (200 ms at 44.1 kHz)
SPLITS = (60, 250, 2000, 8000)
BANDS = ("sub", "low", "mid", "high", "air")

# id -> (text, inlets, outlets, outlet types); "msg:" marks a message box,
# "comment:" a comment.
OBJECTS = {}
LINES = []


def obj(oid, text, inlets, outlets, types=None):
    OBJECTS[oid] = (text, inlets, outlets, types or [""] * outlets)


def wire(src, outlet, dst, inlet):
    LINES.append((src, outlet, dst, inlet))


def build_graph(port=PORT):
    sig = ["signal"]
    # audio through
    obj("in", "plugin~ 2", 2, 2, sig * 2)
    obj("out", "plugout~ 2", 2, 2, sig * 2)
    wire("in", 0, "out", 0)
    wire("in", 1, "out", 1)
    # mono sum and peak of both channels
    obj("sum", "+~", 2, 1, sig)
    obj("half", "*~ 0.5", 2, 1, sig)
    wire("in", 0, "sum", 0)
    wire("in", 1, "sum", 1)
    wire("sum", 0, "half", 0)
    obj("absl", "abs~", 1, 1, sig)
    obj("absr", "abs~", 1, 1, sig)
    obj("maxlr", "maximum~", 2, 1, sig)
    obj("peak", "peakamp~", 2, 1, ["float"])
    wire("in", 0, "absl", 0)
    wire("in", 1, "absr", 0)
    wire("absl", 0, "maxlr", 0)
    wire("absr", 0, "maxlr", 1)
    wire("maxlr", 0, "peak", 0)
    # overall RMS
    obj("avg_rms", "average~ %d rms" % WINDOW, 1, 1, sig)
    obj("snap_rms", "snapshot~", 2, 1, ["float"])
    wire("half", 0, "avg_rms", 0)
    wire("avg_rms", 0, "snap_rms", 0)
    # five bands: each crossover passes its low part to a band and its high
    # part on to the next crossover
    source = ("half", 0)
    band_names = iter(BANDS)
    for number, split in enumerate(SPLITS):
        cid = "cross%d" % number
        obj(cid, "cross~ %d" % split, 2, 2, sig * 2)
        wire(source[0], source[1], cid, 0)
        band_sources = [(cid, 0)]
        source = (cid, 1)
        if number == len(SPLITS) - 1:
            band_sources.append((cid, 1))
        for band_source in band_sources:
            band = next(band_names)
            obj("avg_" + band, "average~ %d rms" % WINDOW, 1, 1, sig)
            obj("snap_" + band, "snapshot~", 2, 1, ["float"])
            wire(band_source[0], band_source[1], "avg_" + band, 0)
            wire("avg_" + band, 0, "snap_" + band, 0)
    # clock: the trigger fires right to left, so all values reach the pack
    # before the stored track name (leftmost outlet) makes it send
    obj("load", "loadmess 1", 1, 1)
    obj("metro", "metro %d" % INTERVAL_MS, 2, 1, ["bang"])
    obj("trig", "t " + " ".join(["b"] * 8), 1, 8, ["bang"] * 8)
    wire("load", 0, "metro", 0)
    wire("metro", 0, "trig", 0)
    obj("pack", "pack s " + " ".join(["0."] * 7), 8, 1)
    readers = ["snap_rms", "peak"] + ["snap_" + band for band in BANDS]
    for position, reader in enumerate(readers, start=1):
        wire("trig", position, reader, 0)
        wire(reader, 0, "pack", position)
    obj("name", "zl reg", 2, 2, ["", ""])
    wire("trig", 0, "name", 0)
    wire("name", 0, "pack", 0)
    obj("addr", "prepend /ytrack", 1, 1)
    obj("udp", "udpsend 127.0.0.1 %d" % port, 1, 0, [])
    wire("pack", 0, "addr", 0)
    wire("addr", 0, "udp", 0)
    # track name from Live, kept up to date by live.observer
    obj("device", "live.thisdevice", 1, 3, ["bang", "int", "int"])
    obj("init", "t b b", 1, 2, ["bang", "bang"])
    obj("msg_prop", "msg:property name", 2, 1)
    obj("msg_path", "msg:path this_device canonical_parent", 2, 1)
    obj("path", "live.path", 1, 3, ["", "", ""])
    obj("observe", "live.observer", 2, 2, ["", ""])
    obj("tosym", "tosymbol", 1, 1)
    wire("device", 0, "init", 0)
    wire("init", 1, "msg_prop", 0)
    wire("init", 0, "msg_path", 0)
    wire("msg_prop", 0, "observe", 0)
    wire("msg_path", 0, "path", 0)
    wire("path", 0, "observe", 1)
    wire("observe", 0, "tosym", 0)
    wire("tosym", 0, "name", 1)
    obj("label", "comment:Y Meter: level and 5-band spectrum of this track -> "
                 "Ableton Y Bridge (UDP %d)" % port, 1, 0, [])


def patcher():
    ids = {name: "obj-%d" % (number + 1) for number, name in enumerate(OBJECTS)}
    boxes = []
    for number, (name, (text, inlets, outlets, types)) in enumerate(OBJECTS.items()):
        rect = [30.0 + 190.0 * (number % 5), 30.0 + 60.0 * (number // 5), 170.0, 22.0]
        box = {"id": ids[name], "numinlets": inlets, "numoutlets": outlets,
               "patching_rect": rect, "fontname": "Arial", "fontsize": 12.0}
        if text.startswith("msg:"):
            box.update(maxclass="message", text=text[4:], outlettype=[""])
        elif text.startswith("comment:"):
            box.update(maxclass="comment", text=text[8:], numinlets=1, numoutlets=0,
                       presentation=1, presentation_rect=[6.0, 6.0, 220.0, 50.0],
                       linecount=3)
            box["patching_rect"] = [30.0, 30.0 + 60.0 * (len(OBJECTS) // 5 + 1), 400.0, 22.0]
        else:
            box.update(maxclass="newobj", text=text)
            if outlets:
                box["outlettype"] = types
        boxes.append({"box": box})
    lines = [{"patchline": {"source": [ids[s], o], "destination": [ids[d], i]}}
             for s, o, d, i in LINES]
    return {"patcher": {
        "fileversion": 1,
        "appversion": {"major": 9, "minor": 0, "revision": 0,
                       "architecture": "x64", "modernui": 1},
        "classnamespace": "box",
        "rect": [100.0, 100.0, 1000.0, 600.0],
        "openinpresentation": 1,
        "default_fontsize": 12.0,
        "default_fontface": 0,
        "default_fontname": "Arial",
        "gridonopen": 1,
        "gridsize": [15.0, 15.0],
        "statusbarvisible": 2,
        "toolbarvisible": 1,
        "devicewidth": 232.0,
        "description": "Level and five-band spectrum of a track for Ableton Y Bridge",
        "digest": "",
        "tags": "Ableton Y Bridge meter",
        "boxes": boxes,
        "lines": lines,
        "dependency_cache": [],
        "latency": 0,
        "autosave": 0,
    }}


def amxd_bytes(patch):
    """Live's .amxd container: 'ampf' header, device type 'aaaa' (audio
    effect), a 'meta' chunk and the patcher JSON in a 'ptch' chunk."""
    body = json.dumps(patch, indent=1).encode("utf-8") + b"\n\x00"
    return (b"ampf" + struct.pack("<I", 4) + b"aaaa"
            + b"meta" + struct.pack("<I", 4) + struct.pack("<I", 0)
            + b"ptch" + struct.pack("<I", len(body)) + body)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--install", action="store_true",
                        help="copy the device into Live's User Library")
    parser.add_argument("--port", type=int, default=PORT,
                        help="UDP port to send to (default %d)" % PORT)
    parser.add_argument("--out", default=OUT, help="output file")
    args = parser.parse_args()
    build_graph(args.port)
    with open(args.out, "wb") as handle:
        handle.write(amxd_bytes(patcher()))
    print("wrote %s (%d objects, %d connections)" % (args.out, len(OBJECTS), len(LINES)))
    if args.install:
        os.makedirs(os.path.dirname(USER_LIBRARY_TARGET), exist_ok=True)
        shutil.copyfile(args.out, os.path.join(os.path.dirname(USER_LIBRARY_TARGET), os.path.basename(args.out)))
        print("installed into %s" % os.path.dirname(USER_LIBRARY_TARGET))


if __name__ == "__main__":
    main()
