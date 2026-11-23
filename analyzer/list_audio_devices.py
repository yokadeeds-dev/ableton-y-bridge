# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Lists the WASAPI loopback devices the analyzer can measure.

Put a part of the wanted device's name into ``audio.device_name_filter`` in
config.json; with an empty filter the analyzer takes the first device listed.
"""
import sys


def list_devices():
    import pyaudiowpatch as pyaudio

    audio = pyaudio.PyAudio()
    try:
        print("\nWASAPI loopback devices\n")
        print(f"{'Idx':<5} {'Name':<55} {'Ch':<4} Rate")
        print("-" * 75)
        for device in audio.get_loopback_device_info_generator():
            print(f"[{device['index']:<3}] {device['name'][:55]:<55} "
                  f"{device['maxInputChannels']:<4} {int(device['defaultSampleRate'])} Hz")
    finally:
        audio.terminate()
    print("\nSet audio.device_name_filter in config.json to a part of one of these names.")


if __name__ == "__main__":
    try:
        list_devices()
    except Exception as problem:  # noqa: BLE001 - report and exit
        print(f"Error: {problem}")
        print("Install the analyzer packages: python -m pip install -r analyzer/requirements.txt")
        sys.exit(1)
