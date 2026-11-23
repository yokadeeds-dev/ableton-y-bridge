"""Devices on tracks: loading, parameters, removal, special cases."""

from .. import browsing
from ..errors import BAD_PARAMS, NOT_FOUND, UNSUPPORTED, CommandError
from ..liveaccess import peek, same, still_there
from ..registry import (
    DESTRUCTIVE,
    READ,
    REVERSIBLE,
    Bool,
    Float,
    Int,
    Raw,
    Text,
    command,
)

_EQ_MODES = {0: "Stereo", 1: "L/R", 2: "M/S"}


def _parameter(device, name):
    """Find a device parameter by name, case-insensitively."""
    wanted = str(name).strip().lower()
    partial = []
    for parameter in device.parameters:
        current = parameter.name.lower()
        if current == wanted:
            return parameter
        if wanted and wanted in current:
            partial.append(parameter)
    if len(partial) == 1:
        return partial[0]
    raise CommandError(
        NOT_FOUND,
        "device '%s' has no parameter '%s'" % (device.name, name),
        available=[p.name for p in device.parameters][:200],
    )


def _write(live, device, parameter, value, where):
    low, high = float(parameter.min), float(parameter.max)
    if not low <= value <= high:
        raise CommandError(
            BAD_PARAMS,
            "'%s' accepts %s..%s, got %s" % (parameter.name, low, high, value),
        )
    if not peek(parameter, "is_enabled", True):
        raise CommandError(UNSUPPORTED,
                           "'%s' is currently controlled elsewhere and cannot be set"
                           % parameter.name)
    before = parameter.value
    shown_before = _display(parameter)
    parameter.value = value
    live.record_value("%s on %s: %s: %s -> %s" % (
        device.name, where, parameter.name, shown_before, _display(parameter)),
        parameter, "value", before, label="'%s'" % parameter.name)
    return {
        "param": parameter.name,
        "value": parameter.value,
        "display": _display(parameter),
        "previous_display": shown_before,
        "min": low,
        "max": high,
    }


def _display(parameter):
    try:
        return str(parameter.str_for_value(parameter.value))
    except Exception:
        return str(round(parameter.value, 4))


def _load_onto(live, strip, uri):
    """Select ``strip`` and let the browser load the item with ``uri`` there."""
    item = browsing.require_by_uri(live.browser, uri)
    if not peek(item, "is_loadable", False):
        raise CommandError(BAD_PARAMS, "'%s' is a folder, not something loadable" % item.name)
    present = list(strip.devices)
    before = [device.name for device in present]
    live.song.view.selected_track = strip
    live.browser.load_item(item)
    after = [device.name for device in strip.devices]
    added = [device for device in strip.devices if still_there(device, present) < 0]
    if added and len(after) == len(before) + len(added):
        def valid():
            if all(still_there(device, strip.devices) >= 0 for device in added):
                return None
            return "the loaded device is no longer on '%s'" % strip.name

        def undo():
            for device in added:
                strip.delete_device(still_there(device, strip.devices))
            return {"removed_devices": len(added)}

        live.record("Loaded '%s' onto '%s'" % (item.name, strip.name), undo, valid)
    else:
        # Something was replaced (an instrument swaps the old one out): the
        # previous device cannot be brought back from here.
        live.record("Loaded '%s' onto '%s' (replaced what was there)"
                    % (item.name, strip.name), kind="live_undo")
    return {
        "loaded": True,
        "item_name": item.name,
        "uri": uri,
        "track_name": strip.name,
        "devices_before": before,
        "devices_after": after,
        "new_devices": [device.name for device in added],
    }


@command("load_browser_item", zone=REVERSIBLE,
         summary="Load a browser item (instrument, effect, preset) onto a track by URI",
         params=[Int("track_index"), Text("item_uri", None), Text("uri", None)],
         timeout=45.0, aliases=("load_instrument_or_effect",))
def load_browser_item(live, track_index, item_uri, uri):
    chosen = item_uri or uri
    if not chosen:
        raise CommandError(BAD_PARAMS, "missing parameter 'item_uri'")
    return _load_onto(live, live.track(track_index), chosen)


@command("load_device_on_master", zone=REVERSIBLE,
         summary="Load a browser item onto the master track",
         params=[Text("item_uri")], timeout=45.0)
def load_device_on_master(live, item_uri):
    return _load_onto(live, live.song.master_track, item_uri)


@command("load_device_on_return", zone=REVERSIBLE,
         summary="Load a browser item onto a return track",
         params=[Int("return_index"), Text("item_uri")], timeout=45.0)
def load_device_on_return(live, return_index, item_uri):
    return _load_onto(live, live.return_track(return_index), item_uri)


@command("get_device_parameters", zone=READ,
         summary="All parameters of a device with value, display text and range",
         params=[Int("track_index", 0), Int("device_index", 0), Bool("use_master", False),
                 Bool("use_return", False), Int("return_index", 0)])
def get_device_parameters(live, track_index, device_index, use_master, use_return, return_index):
    strip, label = live.strip(track_index, use_master, use_return, return_index)
    device = live.device(strip, device_index)
    rows = []
    for index, parameter in enumerate(device.parameters):
        rows.append({
            "index": index,
            "name": parameter.name,
            "value": round(float(parameter.value), 6),
            "display_value": _display(parameter),
            "min": round(float(parameter.min), 6),
            "max": round(float(parameter.max), 6),
            "is_quantized": bool(peek(parameter, "is_quantized", False)),
            "is_enabled": bool(peek(parameter, "is_enabled", True)),
        })
    return {
        "device": device.name,
        "device_class": peek(device, "class_name", ""),
        "track": label,
        "parameter_count": len(rows),
        "parameters": rows,
    }


@command("set_device_parameter", zone=REVERSIBLE,
         summary="Set a device parameter by name (raw value in the parameter's range)",
         params=[Int("track_index", 0), Int("device_index", 0), Text("param_name"),
                 Float("value"), Bool("use_master", False), Bool("use_return", False),
                 Int("return_index", 0)])
def set_device_parameter(live, track_index, device_index, param_name, value,
                         use_master, use_return, return_index):
    strip, label = live.strip(track_index, use_master, use_return, return_index)
    device = live.device(strip, device_index)
    result = _write(live, device, _parameter(device, param_name), value, label)
    result.update({"device": device.name, "track": label})
    return result


@command("set_return_device_parameter", zone=REVERSIBLE,
         summary="Set a parameter of a device on a return track",
         params=[Int("return_index"), Int("device_index", 0), Text("param_name"), Float("value")])
def set_return_device_parameter(live, return_index, device_index, param_name, value):
    strip = live.return_track(return_index)
    device = live.device(strip, device_index)
    result = _write(live, device, _parameter(device, param_name), value, strip.name)
    result.update({"device": device.name, "track": strip.name})
    return result


@command("delete_device", zone=DESTRUCTIVE, undo="live",
         summary="Remove a device from a track, a return track or the master",
         params=[Int("track_index", 0), Int("device_index", 0), Bool("use_master", False),
                 Bool("use_return", False), Int("return_index", 0)])
def delete_device(live, track_index, device_index, use_master, use_return, return_index):
    strip, label = live.strip(track_index, use_master, use_return, return_index)
    device = live.device(strip, device_index)
    name = device.name
    strip.delete_device(device_index)
    live.record("Deleted device '%s' from %s" % (name, label), kind="live_undo")
    return {
        "deleted_device": name,
        "device_index": device_index,
        "track": label,
        "remaining_devices": [d.name for d in strip.devices],
    }


@command("set_eq_mode", zone=REVERSIBLE,
         summary="EQ Eight processing mode: 0 Stereo, 1 L/R, 2 M/S",
         params=[Int("track_index", 0), Int("device_index", 0), Int("mode"),
                 Bool("use_master", False)])
def set_eq_mode(live, track_index, device_index, mode, use_master):
    if mode not in _EQ_MODES:
        raise CommandError(BAD_PARAMS, "mode must be 0 (Stereo), 1 (L/R) or 2 (M/S)")
    strip, label = live.strip(track_index, use_master)
    device = live.device(strip, device_index)
    if peek(device, "global_mode") is None:
        raise CommandError(UNSUPPORTED, "'%s' is not an EQ Eight" % device.name)
    before = int(device.global_mode)
    device.global_mode = mode
    live.record_value("%s on %s: mode %s -> %s" % (
        device.name, label, _EQ_MODES.get(before, before), _EQ_MODES[mode]),
        device, "global_mode", before, label="the EQ mode")
    return {"device": device.name, "track": label,
            "mode": int(device.global_mode), "mode_name": _EQ_MODES[int(device.global_mode)]}


def _routing_name(entry):
    return str(peek(entry, "display_name", entry))


@command("set_sidechain_routing", zone=REVERSIBLE,
         summary="Switch a device's sidechain on and feed it from another track",
         params=[Int("target_track_index", 0), Int("device_index", 0),
                 Int("source_track_index", None), Bool("use_master_target", False),
                 Bool("use_return_target", False), Int("return_target_index", 0)])
def set_sidechain_routing(live, target_track_index, device_index, source_track_index,
                          use_master_target, use_return_target, return_target_index):
    strip, label = live.strip(target_track_index, use_master_target, use_return_target,
                              return_target_index)
    device = live.device(strip, device_index)
    result = {"device": device.name, "target_track": label,
              "sidechain_param_found": False, "routing_set": False, "source_track": None}
    switch, switch_before = None, None
    for parameter in device.parameters:
        if parameter.name.strip().lower() in ("s/c on", "sidechain on", "sidechain"):
            switch, switch_before = parameter, parameter.value
            parameter.value = parameter.max
            result["sidechain_param_found"] = True
            break
    routing_before = peek(device, "input_routing_type")
    chosen = None
    if source_track_index is None:
        result["note"] = "no source given; only the sidechain switch was set"
    else:
        source = live.track(source_track_index)
        result["source_track"] = source.name
        choices = peek(device, "available_input_routing_types")
        if choices is None:
            result["note"] = ("this device does not expose its sidechain input to the API; "
                              "choose the source in the device's sidechain section in Live")
        else:
            choices = list(choices)
            names = [_routing_name(c) for c in choices]
            wanted = source.name.strip().lower()
            for choice, name in zip(choices, names):
                # Live lists tracks as "<number>-<name>" or just "<name>".
                head, _dash, tail = name.partition("-")
                bare = tail if tail and head.isdigit() else name
                if bare.strip().lower() == wanted or name.strip().lower() == wanted:
                    chosen = choice
                    break
            if chosen is None:
                result["available_sources"] = names[:60]
                result["note"] = "source track is not among the sidechain inputs of this device"
            else:
                device.input_routing_type = chosen
                result["routing_set"] = True
                result["set_to"] = _routing_name(chosen)
    if switch is None and chosen is None:
        live.quiet()
        return result

    def valid():
        try:
            if switch is not None and not same(switch.value, switch.max):
                return "the sidechain switch was changed since"
            if chosen is not None and _routing_name(device.input_routing_type) != result["set_to"]:
                return "the sidechain input was changed since"
        except Exception:
            return "the device no longer exists"
        return None

    def undo():
        if chosen is not None and routing_before is not None:
            device.input_routing_type = routing_before
        if switch is not None:
            switch.value = switch_before
        return {"restored": "sidechain"}

    live.record("%s on %s: sidechain on%s" % (
        device.name, label, ", input '%s'" % result["set_to"] if chosen is not None else ""),
        undo, valid)
    return result


def _plugin_folders(live):
    plugins = peek(live.browser, "plugins")
    if plugins is None:
        raise CommandError(UNSUPPORTED, "this Live has no Plug-Ins category in the browser")
    return plugins


@command("search_vst", zone=READ,
         summary="Find plug-ins in Live's browser by (part of) their name",
         params=[Text("name"), Int("limit", 20)], timeout=45.0)
def search_vst(live, name, limit):
    if not name.strip():
        raise CommandError(BAD_PARAMS, "name is empty")
    hits = browsing.search_names([_plugin_folders(live)], name.strip(),
                                 limit=max(1, min(limit, 100)))
    return {"query": name, "count": len(hits), "results": hits}


@command("load_vst_plugin", zone=REVERSIBLE,
         summary="Find a plug-in by name and load it onto a track ('master' allowed)",
         params=[Text("plugin_name"), Raw("track_index", 0), Text("plugin_type", "vst3")],
         timeout=60.0)
def load_vst_plugin(live, plugin_name, track_index, plugin_type):
    root = _plugin_folders(live)
    preferred = [c for c in browsing.children(root)
                 if plugin_type.lower() in str(peek(c, "name", "")).lower()]
    hits = browsing.search_names(preferred or [root], plugin_name, limit=1)
    if not hits and preferred:
        hits = browsing.search_names([root], plugin_name, limit=1)
    if not hits:
        raise CommandError(NOT_FOUND, "no plug-in matches '%s'" % plugin_name)
    if str(track_index).strip().lower() == "master":
        strip = live.song.master_track
    else:
        try:
            strip = live.track(int(track_index))
        except (TypeError, ValueError):
            raise CommandError(BAD_PARAMS, "track_index must be a number or 'master'")
    return _load_onto(live, strip, hits[0]["uri"])
