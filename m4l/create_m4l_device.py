#!/usr/bin/env python3
"""
Creates an AbletonMCP_Analyzer.amxd Max for Live device.
The device uses Max's built-in objects to analyze audio and send UDP.

Since .amxd files are binary (zipped), we create the patcher JSON
and use Max's command line (if available) or write instructions.

Alternative: We create a maxpat JSON file + a Python script approach.
"""

import os
import json, zipfile, os, shutil, struct

# The Max patcher JSON for our audio analyzer
# Uses: adc~ -> meter~ + spectroscope~ -> js (for UDP sending)
# We use the "udpsend" object in Max

patcher = {
    "patcher": {
        "fileversion": 1,
        "appversion": {"major": 8, "minor": 6, "revision": 2, "architecture": "x64", "modernui": 1},
        "classnamespace": "dsp.audioeffect",
        "rect": [100, 100, 640, 480],
        "bglocked": 0,
        "openinpresentation": 0,
        "default_fontsize": 12.0,
        "default_fontface": 0,
        "default_fontname": "Arial",
        "gridonopen": 1,
        "gridsize": [15.0, 15.0],
        "gridsnaponopen": 1,
        "objectsnaponopen": 1,
        "statusbarvisible": 2,
        "toolbarvisible": 1,
        "lefttoolbarpinned": 0,
        "toptoolbarpinned": 0,
        "righttoolbarpinned": 0,
        "bottomtoolbarpinned": 0,
        "toolbars_unpinned_last_save": 0,
        "tallnewobj": 0,
        "boxanimatetime": 200,
        "enablehscroll": 1,
        "enablevscroll": 1,
        "devicewidth": 0.0,
        "description": "AbletonMCP Audio Analyzer - sends LUFS/RMS/Peak via UDP to localhost:7878",
        "digest": "",
        "tags": "AbletonMCP analyzer",
        "style": "",
        "subpatcher_template": "",
        "assistshowspatchername": 0,
        "boxes": [
            # inlet~ 1 (left audio)
            {"box": {"id": "obj-1", "maxclass": "inlet~", "numinlets": 0, "numoutlets": 1,
                     "outlettype": ["signal"], "patching_rect": [60, 30, 30, 30], "comment": "L"}},
            # inlet~ 2 (right audio)
            {"box": {"id": "obj-2", "maxclass": "inlet~", "numinlets": 0, "numoutlets": 1,
                     "outlettype": ["signal"], "patching_rect": [100, 30, 30, 30], "comment": "R"}},
            # outlet~ 1
            {"box": {"id": "obj-3", "maxclass": "outlet~", "numinlets": 1, "numoutlets": 0,
                     "patching_rect": [60, 420, 30, 30], "comment": "L"}},
            # outlet~ 2
            {"box": {"id": "obj-4", "maxclass": "outlet~", "numinlets": 1, "numoutlets": 0,
                     "patching_rect": [100, 420, 30, 30], "comment": "R"}},
            # average~ for RMS L
            {"box": {"id": "obj-5", "maxclass": "average~", "numinlets": 1, "numoutlets": 1,
                     "outlettype": ["signal"], "patching_rect": [60, 90, 60, 30],
                     "attr": {"mode": "rms"}}},
            # average~ for RMS R
            {"box": {"id": "obj-6", "maxclass": "average~", "numinlets": 1, "numoutlets": 1,
                     "outlettype": ["signal"], "patching_rect": [130, 90, 60, 30],
                     "attr": {"mode": "rms"}}},
            # snapshot~ L (converts signal to number every N ms)
            {"box": {"id": "obj-7", "maxclass": "snapshot~", "numinlets": 1, "numoutlets": 1,
                     "outlettype": ["float"], "patching_rect": [60, 140, 70, 30]}},
            # snapshot~ R
            {"box": {"id": "obj-8", "maxclass": "snapshot~", "numinlets": 1, "numoutlets": 1,
                     "outlettype": ["float"], "patching_rect": [140, 140, 70, 30]}},
            # metro 200 (triggers snapshots every 200ms)
            {"box": {"id": "obj-9", "maxclass": "metro", "numinlets": 2, "numoutlets": 1,
                     "outlettype": ["bang"], "patching_rect": [220, 90, 60, 30],
                     "text": "metro 200"}},
            # toggle (auto-start metro)
            {"box": {"id": "obj-10", "maxclass": "toggle", "numinlets": 1, "numoutlets": 1,
                     "outlettype": ["int"], "patching_rect": [220, 50, 20, 20]}},
            # loadbang
            {"box": {"id": "obj-11", "maxclass": "loadbang", "numinlets": 0, "numoutlets": 1,
                     "outlettype": ["bang"], "patching_rect": [220, 20, 60, 30]}},
            # js udp_sender.js
            {"box": {"id": "obj-12", "maxclass": "js", "numinlets": 1, "numoutlets": 1,
                     "outlettype": [""], "patching_rect": [60, 250, 120, 30],
                     "text": "js ableton_mcp_udp.js"}},
            # number boxes for display
            {"box": {"id": "obj-13", "maxclass": "flonum", "numinlets": 1, "numoutlets": 1,
                     "outlettype": ["float"], "patching_rect": [60, 190, 70, 22]}},
            {"box": {"id": "obj-14", "maxclass": "flonum", "numinlets": 1, "numoutlets": 1,
                     "outlettype": ["float"], "patching_rect": [140, 190, 70, 22]}},
            # comment
            {"box": {"id": "obj-15", "maxclass": "comment", "numinlets": 1, "numoutlets": 0,
                     "patching_rect": [60, 295, 300, 20],
                     "text": "AbletonMCP Audio Analyzer → UDP localhost:7878"}},
        ],
        "lines": [
            # inlet L -> average~ L
            {"patchline": {"source": ["obj-1", 0], "destination": ["obj-5", 0]}},
            # inlet R -> average~ R
            {"patchline": {"source": ["obj-2", 0], "destination": ["obj-6", 0]}},
            # inlet L -> outlet L (passthrough)
            {"patchline": {"source": ["obj-1", 0], "destination": ["obj-3", 0]}},
            # inlet R -> outlet R (passthrough)
            {"patchline": {"source": ["obj-2", 0], "destination": ["obj-4", 0]}},
            # average~ L -> snapshot~ L
            {"patchline": {"source": ["obj-5", 0], "destination": ["obj-7", 0]}},
            # average~ R -> snapshot~ R
            {"patchline": {"source": ["obj-6", 0], "destination": ["obj-8", 0]}},
            # metro -> snapshot~ L trigger
            {"patchline": {"source": ["obj-9", 0], "destination": ["obj-7", 0]}},
            # metro -> snapshot~ R trigger
            {"patchline": {"source": ["obj-9", 0], "destination": ["obj-8", 0]}},
            # loadbang -> toggle
            {"patchline": {"source": ["obj-11", 0], "destination": ["obj-10", 0]}},
            # toggle -> metro
            {"patchline": {"source": ["obj-10", 0], "destination": ["obj-9", 0]}},
            # snapshot~ L -> flonum display
            {"patchline": {"source": ["obj-7", 0], "destination": ["obj-13", 0]}},
            # snapshot~ R -> flonum display
            {"patchline": {"source": ["obj-8", 0], "destination": ["obj-14", 0]}},
            # snapshot~ L -> js
            {"patchline": {"source": ["obj-7", 0], "destination": ["obj-12", 0]}},
        ]
    }
}

# Write the maxpat JSON (human-readable Max patch)
maxpat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'AbletonMCP_Analyzer.maxpat')
with open(maxpat_path, 'w') as f:
    json.dump(patcher, f, indent=2)

print(f"Written: {maxpat_path}")
print("NOTE: .amxd requires Max for Live to package. See instructions below.")
