# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Remote Script package for Ableton Live.

Install by copying this folder to ``User Library/Remote Scripts/AbletonMCP``
and choosing "AbletonMCP" as a control surface in Live's MIDI preferences.
``create_instance`` is the entry point Live looks for in every Remote Script.
"""


def create_instance(c_instance):
    from .surface import BridgeSurface

    return BridgeSurface(c_instance)
