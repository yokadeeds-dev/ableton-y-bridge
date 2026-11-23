"""Listet alle verfügbaren Audio-Devices auf — hilft bei der Zoom L-12 Konfiguration"""
import sounddevice as sd
import sys

def list_devices():
    devices = sd.query_devices()
    print("\n=== VERFÜGBARE AUDIO DEVICES ===\n")
    print(f"{'Idx':<5} {'Name':<45} {'In':<5} {'Out':<5} {'Rate'}")
    print("-" * 75)
    for i, d in enumerate(devices):
        marker = ""
        name_lower = d['name'].lower()
        if any(k in name_lower for k in ['zoom', 'l-12', 'l12']):
            marker = " ← ZOOM L-12"
        elif any(k in name_lower for k in ['stereo mix', 'loopback']):
            marker = " ← LOOPBACK"
        print(f"[{i:<3}] {d['name']:<45} {d['max_input_channels']:<5} {d['max_output_channels']:<5} {int(d['default_samplerate'])} Hz{marker}")
    
    print(f"\nDefault Input:  [{sd.default.device[0]}] {devices[sd.default.device[0]]['name']}")
    print(f"Default Output: [{sd.default.device[1]}] {devices[sd.default.device[1]]['name']}")
    print("\nFür Audio Analyzer: Das Zoom L-12 (oder Stereo Mix) als Input-Device verwenden.")

if __name__ == "__main__":
    try:
        list_devices()
    except Exception as e:
        print(f"Fehler: {e}")
        print("Bitte sounddevice installieren: pip install sounddevice")
