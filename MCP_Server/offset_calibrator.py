"""
Offset Calibrator for Drums vs Bass Warp Markers
=================================================
Helps dial in the correct SecTime offset between two audio clips that
share a musical grid but were rendered with a time offset (e.g., Suno
stems where drums and bass were exported with a known sample delay).

Two modes:

  sweep  — Write several backup copies of the .als with different offsets
           so you can A/B-compare them in Ableton. Each output file gets
           a suffix like "_offset-1.2190.als".

  preview — Compute derived markers for a range of offsets and print
            a comparison table (first 3 markers each). No writes.

Usage:
  python offset_calibrator.py preview <path.als> --center -1.2190 --step 0.010 --count 5
  python offset_calibrator.py sweep <path.als> --offsets -1.19,-1.21,-1.23
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent))
import als_warp_writer as a


DEFAULT_SOURCE = "[SUNO] Bass"
DEFAULT_TARGET = "[SUNO] Drums"


def _cmd_preview(args) -> int:
    tree = a.read_als(args.path)
    src = a.find_clip(tree, args.source_track, args.source_clip, None)
    src_markers = a.get_clip_markers(src)

    # Build offset list
    if args.offsets:
        offsets = [float(x) for x in args.offsets.split(",")]
    else:
        c, step, n = args.center, args.step, args.count
        # center ± step*(n//2)
        half = n // 2
        offsets = [c + step * (i - half) for i in range(n)]

    print(f"Source: {args.source_track!r} / {a._clip_name(src)!r} -> {len(src_markers)} markers")
    print(f"Offsets (seconds): {offsets}")
    print()

    # Header
    header = ["Offset", "drum[0] sec", "drum[1] sec", "drum[2] sec", "first_diff_ms"]
    print(f"{header[0]:>10}  {header[1]:>12}  {header[2]:>12}  {header[3]:>12}  {header[4]:>14}")
    print("-" * 70)

    # Compute current drum[0] as reference for diff
    try:
        tgt = a.find_clip(tree, args.target_track, args.target_clip, None)
        current = a.get_clip_markers(tgt)
        current_first = current[0][0] if current else None
    except a.ALSClipNotFound:
        current_first = None

    for off in offsets:
        derived = a.compute_offset_markers(src_markers, off)
        d0 = derived[0][0] if len(derived) > 0 else float("nan")
        d1 = derived[1][0] if len(derived) > 1 else float("nan")
        d2 = derived[2][0] if len(derived) > 2 else float("nan")
        diff_ms = (d0 - current_first) * 1000 if current_first is not None else float("nan")
        print(f"{off:>+10.4f}  {d0:>12.6f}  {d1:>12.6f}  {d2:>12.6f}  {diff_ms:>+14.2f}")

    if current_first is not None:
        print()
        print(f"Current drum[0] sec = {current_first:.6f}s  "
              f"(this is what's in the file right now)")
    return 0


def _cmd_sweep(args) -> int:
    if not args.offsets:
        print("Error: --offsets is required for sweep mode")
        return 1
    offsets = [float(x) for x in args.offsets.split(",")]

    tree = a.read_als(args.path)
    src = a.find_clip(tree, args.source_track, args.source_clip, None)
    src_markers = a.get_clip_markers(src)
    tgt_name = args.target_track
    tgt_clip_name = args.target_clip

    out_dir = Path(args.output_dir) if args.output_dir else Path(args.path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Path(args.path).stem

    written: List[Path] = []
    for off in offsets:
        # Re-read fresh tree so each variant is independent
        tree = a.read_als(args.path)
        tgt = a.find_clip(tree, tgt_name, tgt_clip_name, None)
        new_markers = a.compute_offset_markers(src_markers, off)
        problems = a.validate_markers(new_markers)
        a.set_clip_markers(tgt, new_markers)

        out_name = f"{base}_offset{off:+.4f}.als"
        out_path = out_dir / out_name
        a.write_als(tree, out_path, backup=False)
        written.append(out_path)
        warn = f" (warnings: {len(problems)})" if problems else ""
        print(f"  wrote {out_path.name} | offset={off:+.4f}s | {len(new_markers)} markers{warn}")

    print()
    print(f"Done. {len(written)} variants in {out_dir}")
    print("Tip: open each in Ableton and A/B-compare the first bars.")
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    # preview
    pv = sub.add_parser("preview", help="Print comparison table, no writes")
    pv.add_argument("path")
    pv.add_argument("--source-track", default=DEFAULT_SOURCE)
    pv.add_argument("--source-clip", default=None)
    pv.add_argument("--target-track", default=DEFAULT_TARGET)
    pv.add_argument("--target-clip", default=None)
    pv.add_argument("--center", type=float, default=-1.2190, help="Center offset (default: -1.2190)")
    pv.add_argument("--step", type=float, default=0.010, help="Step between offsets (default: 0.010s = 10ms)")
    pv.add_argument("--count", type=int, default=5, help="Number of offsets centered around --center (odd recommended)")
    pv.add_argument("--offsets", default=None, help="Comma-separated explicit offsets (overrides center/step/count)")
    pv.set_defaults(func=_cmd_preview)

    # sweep
    sw = sub.add_parser("sweep", help="Write multiple .als copies with different offsets")
    sw.add_argument("path")
    sw.add_argument("--source-track", default=DEFAULT_SOURCE)
    sw.add_argument("--source-clip", default=None)
    sw.add_argument("--target-track", default=DEFAULT_TARGET)
    sw.add_argument("--target-clip", default=None)
    sw.add_argument("--offsets", required=True, help="Comma-separated offsets, e.g. '-1.19,-1.21,-1.23'")
    sw.add_argument("--output-dir", default=None, help="Where to write variants (default: alongside source)")
    sw.set_defaults(func=_cmd_sweep)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
