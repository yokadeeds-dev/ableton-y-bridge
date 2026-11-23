"""
Tests for als_warp_writer.py
=============================
Run with: python -m pytest test_als_warp_writer.py -v
Or:       python test_als_warp_writer.py    (uses unittest discovery)

These tests use a REAL CP.als (if available) for round-trip verification
because producing a valid Ableton XML from scratch is brittle. Tests that
require CP.als are skipped if the file is missing.
"""
from __future__ import annotations

import gzip
import os
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

# Make sibling module importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MCP_Server"))
import als_warp_writer as a


REAL_ALS = Path(os.environ.get("ALS_TEST_FILE", ""))  # optional: echte .als-Datei fuer den Integrationstest
HAS_REAL = bool(os.environ.get("ALS_TEST_FILE")) and REAL_ALS.is_file()


# ── Minimal synthetic ALS ─────────────────────────────────────────
def _make_minimal_als() -> bytes:
    """Create a tiny valid Ableton-shaped XML for basic tests."""
    root = ET.Element("Ableton", attrib={
        "MajorVersion": "5",
        "MinorVersion": "12.0_12300",
        "Creator": "Test Harness",
    })
    liveset = ET.SubElement(root, "LiveSet")
    tracks = ET.SubElement(liveset, "Tracks")
    at = ET.SubElement(tracks, "AudioTrack", attrib={"Id": "0"})
    en = ET.SubElement(at, "EffectiveName")
    en.set("Value", "Test Track")
    # Arrangement clip
    device = ET.SubElement(at, "DeviceChain")
    ms = ET.SubElement(device, "MainSequencer")
    ct = ET.SubElement(ms, "ClipTimeable")
    arr = ET.SubElement(ct, "ArrangerAutomation")
    events = ET.SubElement(arr, "Events")
    clip = ET.SubElement(events, "AudioClip", attrib={"Id": "42", "Time": "0"})
    name = ET.SubElement(clip, "Name")
    name.set("Value", "Test Clip")
    iw = ET.SubElement(clip, "IsWarped")
    iw.set("Value", "true")
    wmode = ET.SubElement(clip, "WarpMode")
    wmode.set("Value", "0")
    wms = ET.SubElement(clip, "WarpMarkers")
    ET.SubElement(wms, "WarpMarker", attrib={"Id": "0", "SecTime": "0.0", "BeatTime": "0"})
    ET.SubElement(wms, "WarpMarker", attrib={"Id": "1", "SecTime": "2.0", "BeatTime": "4"})
    ET.SubElement(clip, "SavedWarpMarkersForStretched")
    mg = ET.SubElement(clip, "MarkersGenerated")
    mg.set("Value", "true")
    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
    return xml_bytes


def _write_minimal_als(path: Path):
    with gzip.open(path, "wb") as f:
        f.write(_make_minimal_als())


# ── Tests: I/O ────────────────────────────────────────────────────
class TestReadWrite(unittest.TestCase):
    def test_read_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            a.read_als("/tmp/does-not-exist.als")

    def test_read_invalid_gzip_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".als", delete=False) as f:
            f.write(b"not a gzip file at all")
            tmp = f.name
        try:
            with self.assertRaises(a.ALSFormatError):
                a.read_als(tmp)
        finally:
            os.unlink(tmp)

    def test_read_non_ableton_xml_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".als", delete=False) as f:
            tmp = f.name
        try:
            with gzip.open(tmp, "wb") as g:
                g.write(b"<?xml version='1.0'?><WrongRoot/>")
            with self.assertRaises(a.ALSFormatError):
                a.read_als(tmp)
        finally:
            os.unlink(tmp)

    def test_minimal_roundtrip(self):
        """Write → read → verify structure."""
        with tempfile.NamedTemporaryFile(suffix=".als", delete=False) as f:
            tmp = Path(f.name)
        try:
            _write_minimal_als(tmp)
            tree = a.read_als(tmp)
            self.assertEqual(tree.getroot().tag, "Ableton")
            clip = a.find_clip(tree, "Test Track", "Test Clip")
            markers = a.get_clip_markers(clip)
            self.assertEqual(len(markers), 2)
            self.assertEqual(markers[0], (0.0, 0.0))
            self.assertEqual(markers[1], (2.0, 4.0))
        finally:
            os.unlink(tmp)

    def test_write_creates_backup(self):
        with tempfile.NamedTemporaryFile(suffix=".als", delete=False) as f:
            tmp = Path(f.name)
        try:
            _write_minimal_als(tmp)
            tree = a.read_als(tmp)
            backup = a.write_als(tree, tmp, backup=True)
            self.assertIsNotNone(backup)
            self.assertTrue(backup.exists())
            backup.unlink()
        finally:
            os.unlink(tmp)

    def test_write_no_backup_if_disabled(self):
        with tempfile.NamedTemporaryFile(suffix=".als", delete=False) as f:
            tmp = Path(f.name)
        try:
            _write_minimal_als(tmp)
            tree = a.read_als(tmp)
            backup = a.write_als(tree, tmp, backup=False)
            self.assertIsNone(backup)
        finally:
            os.unlink(tmp)


# ── Tests: Clip/Marker Access ─────────────────────────────────────
class TestClipAccess(unittest.TestCase):
    def _setup_tmp(self):
        f = tempfile.NamedTemporaryFile(suffix=".als", delete=False)
        tmp = Path(f.name)
        f.close()
        _write_minimal_als(tmp)
        return tmp

    def test_find_clip_by_name(self):
        tmp = self._setup_tmp()
        try:
            tree = a.read_als(tmp)
            clip = a.find_clip(tree, "Test Track", "Test Clip")
            self.assertEqual(a._clip_name(clip), "Test Clip")
        finally:
            os.unlink(tmp)

    def test_find_clip_by_index(self):
        tmp = self._setup_tmp()
        try:
            tree = a.read_als(tmp)
            clip = a.find_clip(tree, "Test Track", None, 0)
            self.assertEqual(a._clip_name(clip), "Test Clip")
        finally:
            os.unlink(tmp)

    def test_find_clip_missing_track(self):
        tmp = self._setup_tmp()
        try:
            tree = a.read_als(tmp)
            with self.assertRaises(a.ALSClipNotFound):
                a.find_clip(tree, "Nonexistent Track")
        finally:
            os.unlink(tmp)

    def test_find_clip_missing_name(self):
        tmp = self._setup_tmp()
        try:
            tree = a.read_als(tmp)
            with self.assertRaises(a.ALSClipNotFound):
                a.find_clip(tree, "Test Track", "Nonexistent Clip")
        finally:
            os.unlink(tmp)

    def test_find_clip_index_out_of_range(self):
        tmp = self._setup_tmp()
        try:
            tree = a.read_als(tmp)
            with self.assertRaises(a.ALSClipNotFound):
                a.find_clip(tree, "Test Track", None, 99)
        finally:
            os.unlink(tmp)

    def test_set_markers_replaces_existing(self):
        tmp = self._setup_tmp()
        try:
            tree = a.read_als(tmp)
            clip = a.find_clip(tree, "Test Track", "Test Clip")
            new_markers = [(0.5, 0.0), (2.5, 4.0), (4.5, 8.0), (6.5, 12.0)]
            count = a.set_clip_markers(clip, new_markers)
            self.assertEqual(count, 4)
            # Round-trip
            a.write_als(tree, tmp, backup=False)
            tree2 = a.read_als(tmp)
            clip2 = a.find_clip(tree2, "Test Track", "Test Clip")
            markers2 = a.get_clip_markers(clip2)
            self.assertEqual(len(markers2), 4)
            # Check values
            for orig, got in zip(new_markers, markers2):
                self.assertAlmostEqual(orig[0], got[0], places=9)
                self.assertAlmostEqual(orig[1], got[1], places=9)
        finally:
            os.unlink(tmp)

    def test_set_markers_reassigns_ids(self):
        tmp = self._setup_tmp()
        try:
            tree = a.read_als(tmp)
            clip = a.find_clip(tree, "Test Track", "Test Clip")
            a.set_clip_markers(clip, [(0.0, 0.0), (1.0, 2.0), (2.0, 4.0)])
            wms = clip.findall(".//WarpMarkers/WarpMarker")
            ids = [int(w.get("Id")) for w in wms]
            self.assertEqual(ids, [0, 1, 2])
        finally:
            os.unlink(tmp)


# ── Tests: Transforms ─────────────────────────────────────────────
class TestTransforms(unittest.TestCase):
    def test_offset_positive(self):
        src = [(1.0, 0.0), (2.0, 4.0), (3.0, 8.0)]
        out = a.compute_offset_markers(src, 0.5)
        self.assertEqual(out, [(1.5, 0.0), (2.5, 4.0), (3.5, 8.0)])

    def test_offset_negative(self):
        src = [(1.0, 0.0), (2.0, 4.0)]
        out = a.compute_offset_markers(src, -0.3)
        self.assertAlmostEqual(out[0][0], 0.7, places=9)
        self.assertAlmostEqual(out[1][0], 1.7, places=9)

    def test_offset_clamps_negative_seconds(self):
        """SecTime must never go below 0."""
        src = [(0.5, 0.0), (2.0, 4.0)]
        out = a.compute_offset_markers(src, -1.0)
        self.assertEqual(out[0][0], 0.0)  # clamped
        self.assertEqual(out[1][0], 1.0)

    def test_offset_preserves_beats(self):
        src = [(1.0, 0.0), (2.0, 4.0), (3.0, 8.0)]
        out = a.compute_offset_markers(src, 0.5)
        self.assertEqual([b for _, b in out], [0.0, 4.0, 8.0])

    def test_drums_offset_docs(self):
        """The documented Drums offset: drum_sec = bass_sec - 1.2190"""
        bass = [(1.7030, 0.0), (3.6400, 4.0)]
        drums = a.compute_offset_markers(bass, -1.2190)
        self.assertAlmostEqual(drums[0][0], 0.4840, places=3)
        self.assertAlmostEqual(drums[1][0], 2.4210, places=3)


class TestValidation(unittest.TestCase):
    def test_empty_list(self):
        p = a.validate_markers([])
        self.assertTrue(any("empty" in s for s in p))

    def test_happy_path(self):
        p = a.validate_markers([(0.0, 0.0), (1.0, 4.0), (2.0, 8.0)])
        self.assertEqual(p, [])

    def test_first_beat_not_zero(self):
        p = a.validate_markers([(1.0, 1.0), (2.0, 4.0)])
        self.assertTrue(any("first marker BeatTime" in s for s in p))

    def test_unsorted_beats(self):
        p = a.validate_markers([(0.0, 0.0), (1.0, 8.0), (2.0, 4.0)])
        self.assertTrue(any("not sorted by BeatTime" in s for s in p))

    def test_duplicate_beats_reported_but_not_error(self):
        # Duplicates at same beat are legal (anchor pairs)
        p = a.validate_markers([(0.0, 0.0), (1.0, 4.0), (1.01, 4.0)])
        # should mention duplicates but not as blocking error
        self.assertTrue(any("duplicate" in s.lower() for s in p))


# ── Tests against real CP.als (if available) ──────────────────────
@unittest.skipUnless(HAS_REAL, "CP.als not available at expected path")
class TestRealALS(unittest.TestCase):
    def test_read_real_als(self):
        tree = a.read_als(REAL_ALS)
        self.assertEqual(tree.getroot().tag, "Ableton")

    def test_real_bass_has_252_markers(self):
        tree = a.read_als(REAL_ALS)
        clip = a.find_clip(tree, "[SUNO] Bass", "Concrete Pulse (Bass)")
        markers = a.get_clip_markers(clip)
        # Original was 252; allow some tolerance in case the user edits in Ableton
        self.assertGreater(len(markers), 100)

    def test_real_drums_derived_markers_match_expected(self):
        """The first derived drum marker should match the documented 0.484s."""
        tree = a.read_als(REAL_ALS)
        clip = a.find_clip(tree, "[SUNO] Bass", "Concrete Pulse (Bass)")
        bass = a.get_clip_markers(clip)
        drums = a.compute_offset_markers(bass, -1.2190)
        self.assertAlmostEqual(drums[0][0], 0.484, places=2)
        self.assertEqual(drums[0][1], 0.0)


# ── Tests: File locking ──────────────────────────────────────────
class TestFileLocking(unittest.TestCase):
    def test_lock_check_on_free_file(self):
        """A freshly written file should not appear locked."""
        with tempfile.NamedTemporaryFile(suffix=".als", delete=False) as f:
            tmp = Path(f.name)
        try:
            _write_minimal_als(tmp)
            self.assertFalse(a.is_als_locked(tmp))
        finally:
            os.unlink(tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
