"""Devices and Live's browser."""

from __future__ import annotations

from typing import Optional

from ..coerce import BoolLike, FloatLike, IntLike, opt_int, to_bool, to_float, to_int
from ..core import DESTRUCTIVE, READ, REVERSIBLE, live, tool
from ..link import LiveError


def _loaded_text(result: dict, where: str) -> str:
    new = result.get("new_devices") or []
    if new:
        return f"Loaded '{result['item_name']}' onto {where}; new device(s): {', '.join(new)}."
    chain = ", ".join(result.get("devices_after") or []) or "none"
    return (f"Loaded '{result['item_name']}' onto {where}. "
            f"Devices there now: {chain}.")


@tool(REVERSIBLE)
def load_instrument_or_effect(track_index: IntLike, uri: str) -> str:
    """Load an instrument, effect or preset from Live's browser onto a track.

    Get the URI from get_browser_items_at_path or search_vst. An instrument
    replaces the track's instrument; effects are appended to the chain.

    - track_index: track number, counting from 0
    - uri: browser URI of the item, e.g. 'query:Synths#Operator'
    """
    index = to_int(track_index, "track_index")
    result = live.call("load_browser_item", track_index=index, item_uri=uri)
    return _loaded_text(result, f"track {index} '{result['track_name']}'")


@tool(REVERSIBLE)
def load_device_on_master(uri: str) -> str:
    """Load a device from Live's browser onto the master track.

    - uri: browser URI of the device, e.g. 'query:AudioFx#Limiter'
    """
    return _loaded_text(live.call("load_device_on_master", item_uri=uri), "the master track")


@tool(REVERSIBLE)
def load_device_on_return(return_index: IntLike, uri: str) -> str:
    """Load a device from Live's browser onto a return track.

    - return_index: 0 = Return A, 1 = Return B, ...
    - uri: browser URI of the device, e.g. 'query:AudioFx#Reverb'
    """
    result = live.call("load_device_on_return",
                       return_index=to_int(return_index, "return_index"), item_uri=uri)
    return _loaded_text(result, f"return track '{result['track_name']}'")


@tool(REVERSIBLE)
def load_drum_kit(track_index: IntLike, rack_uri: str, kit_path: str) -> str:
    """Load a Drum Rack and then a kit preset from a browser folder into it.

    - track_index: number (from 0) of a MIDI track
    - rack_uri: browser URI of the empty Drum Rack ('query:Drums#Drum%20Rack' style)
    - kit_path: browser folder to take the first loadable kit from,
                e.g. 'drums/acoustic'
    """
    index = to_int(track_index, "track_index")
    live.call("load_browser_item", track_index=index, item_uri=rack_uri)
    folder = live.call("get_browser_items_at_path", path=kit_path)
    kits = [item for item in folder.get("items", []) if item.get("is_loadable")]
    if not kits:
        return (f"Drum Rack loaded on track {index}, but '{kit_path}' holds nothing "
                "loadable. No kit was loaded.")
    live.call("load_browser_item", track_index=index, item_uri=kits[0]["uri"])
    return f"Drum Rack with kit '{kits[0]['name']}' loaded on track {index}."


@tool(READ)
def get_device_parameters(track_index: IntLike = 0, device_index: IntLike = 0,
                          use_master: BoolLike = False, use_return: BoolLike = False,
                          return_index: IntLike = 0) -> str:
    """List all parameters of a device: name, displayed value, raw value, range.

    Read this before set_device_parameter; values are set in the raw range
    shown in brackets. Plug-ins can have hundreds of parameters.

    - track_index: track number, counting from 0 (ignored with use_master / use_return)
    - device_index: position in the device chain, 0 = first
    - use_master: read from the master track
    - use_return: read from a return track, chosen by return_index
    - return_index: 0 = Return A, 1 = Return B, ...
    """
    result = live.call("get_device_parameters",
                       track_index=to_int(track_index, "track_index"),
                       device_index=to_int(device_index, "device_index"),
                       use_master=to_bool(use_master, "use_master"),
                       use_return=to_bool(use_return, "use_return"),
                       return_index=to_int(return_index, "return_index"))
    rows = [f"{result['device']} on {result['track']}: {result['parameter_count']} parameters"]
    for p in result["parameters"]:
        locked = "" if p.get("is_enabled", True) else " (locked)"
        rows.append(f"[{p['index']}] {p['name']} = {p['display_value']} "
                    f"| raw {p['value']:.4f} [{p['min']:g}..{p['max']:g}]{locked}")
    return "\n".join(rows)


@tool(REVERSIBLE)
def set_device_parameter(track_index: IntLike, device_index: IntLike, param_name: str,
                         value: FloatLike, use_master: BoolLike = False) -> str:
    """Set one parameter of a device on a track or on the master.

    - track_index: track number, counting from 0 (ignored with use_master)
    - device_index: position in the device chain, 0 = first
    - param_name: parameter name as listed by get_device_parameters
                  (case-insensitive)
    - value: raw value inside the parameter's range; plug-in parameters
             usually run 0.0 to 1.0
    - use_master: target the master track
    """
    result = live.call("set_device_parameter",
                       track_index=to_int(track_index, "track_index"),
                       device_index=to_int(device_index, "device_index"),
                       param_name=param_name, value=to_float(value, "value"),
                       use_master=to_bool(use_master, "use_master"))
    return (f"{result['device']} on {result['track']}: {result['param']} = "
            f"{result['display']} (raw {result['value']:.4f}).")


@tool(REVERSIBLE)
def set_return_device_parameter(return_index: IntLike, device_index: IntLike,
                                param_name: str, value: FloatLike) -> str:
    """Set one parameter of a device on a return track.

    - return_index: 0 = Return A, 1 = Return B, ...
    - device_index: position in the device chain, 0 = first
    - param_name: parameter name as listed by get_device_parameters
    - value: raw value inside the parameter's range
    """
    result = live.call("set_return_device_parameter",
                       return_index=to_int(return_index, "return_index"),
                       device_index=to_int(device_index, "device_index"),
                       param_name=param_name, value=to_float(value, "value"))
    return (f"{result['device']} on {result['track']}: {result['param']} = "
            f"{result['display']} (raw {result['value']:.4f}).")


@tool(DESTRUCTIVE)
def delete_device(track_index: IntLike, device_index: IntLike, use_master: BoolLike = False,
                  use_return: BoolLike = False, return_index: IntLike = 0,
                  confirm: BoolLike = False) -> str:
    """Remove a device from a track, a return track or the master.

    With use_return the target is chosen by return_index, NOT by
    track_index; always pass return_index explicitly then.

    - track_index: track number, counting from 0 (ignored with use_master / use_return)
    - device_index: position in the device chain, 0 = first
    - use_master: target the master track
    - use_return: target a return track
    - return_index: 0 = Return A, 1 = Return B, ...
    - confirm: must be true for the tool to run. Ask the user first; do not
               set it on your own initiative.
    """
    result = live.call("delete_device",
                       track_index=to_int(track_index, "track_index"),
                       device_index=to_int(device_index, "device_index"),
                       use_master=to_bool(use_master, "use_master"),
                       use_return=to_bool(use_return, "use_return"),
                       return_index=to_int(return_index, "return_index"))
    left = ", ".join(result["remaining_devices"]) or "none"
    return f"Removed '{result['deleted_device']}' from {result['track']}. Left: {left}."


@tool(REVERSIBLE)
def set_eq_mode(track_index: IntLike, device_index: IntLike, mode: IntLike,
                use_master: BoolLike = False) -> str:
    """Set the processing mode of an EQ Eight.

    - track_index: track number, counting from 0 (ignored with use_master)
    - device_index: position of the EQ Eight in the chain
    - mode: 0 = Stereo, 1 = L/R, 2 = M/S
    - use_master: target the master track
    """
    result = live.call("set_eq_mode", track_index=to_int(track_index, "track_index"),
                       device_index=to_int(device_index, "device_index"),
                       mode=to_int(mode, "mode"), use_master=to_bool(use_master, "use_master"))
    return f"{result['device']} on {result['track']} is in {result['mode_name']} mode."


@tool(REVERSIBLE)
def set_sidechain_routing(target_track_index: IntLike, device_index: IntLike,
                          source_track_index: Optional[IntLike] = None,
                          use_master_target: BoolLike = False,
                          use_return_target: BoolLike = False,
                          return_target_index: IntLike = 0) -> str:
    """Switch on a device's sidechain and feed it from another track.

    Works for Live devices that expose their sidechain input (Compressor,
    Glue Compressor, Gate, Auto Filter ...). Only the device is touched;
    track routings stay as they are.

    - target_track_index: track carrying the device (ignored with the
                          master / return switches)
    - device_index: position of the device in the chain
    - source_track_index: track to listen to; omit to only switch the
                          sidechain on
    - use_master_target: the device sits on the master track
    - use_return_target: the device sits on a return track
    - return_target_index: which return track (0 = A)
    """
    result = live.call("set_sidechain_routing",
                       target_track_index=to_int(target_track_index, "target_track_index"),
                       device_index=to_int(device_index, "device_index"),
                       source_track_index=opt_int(source_track_index, "source_track_index"),
                       use_master_target=to_bool(use_master_target, "use_master_target"),
                       use_return_target=to_bool(use_return_target, "use_return_target"),
                       return_target_index=to_int(return_target_index, "return_target_index"))
    parts = [f"{result['device']} on {result['target_track']}:",
             "sidechain switched on" if result["sidechain_param_found"]
             else "no sidechain switch found"]
    if result.get("routing_set"):
        parts.append(f"input set to '{result['set_to']}'")
    elif result.get("source_track"):
        parts.append(f"input NOT set to '{result['source_track']}'")
    text = ", ".join(parts[1:])
    answer = f"{parts[0]} {text}."
    if result.get("note"):
        answer += " " + result["note"]
    if result.get("available_sources"):
        answer += " Available: " + ", ".join(result["available_sources"]) + "."
    return answer


@tool(READ)
def search_vst(name: str) -> str:
    """Search the Plug-Ins section of Live's browser by name.

    Returns names and URIs; load a hit with load_instrument_or_effect.

    - name: plug-in name or part of it ('Pro-Q', 'Serum')
    """
    result = live.call("search_vst", name=name)
    if not result["count"]:
        return f"No plug-in matches '{name}'. Check the spelling in Live's browser."
    rows = [f"{result['count']} plug-in(s) matching '{name}':"]
    for hit in result["results"]:
        rows.append(f"  {hit['name']}  [{hit['folder']}]")
        rows.append(f"    uri: {hit['uri']}")
    return "\n".join(rows)


@tool(READ)
def get_browser_tree(category_type: str = "all") -> str:
    """Show the categories of Live's browser and their first folder level.

    Use the printed paths with get_browser_items_at_path to go deeper.

    - category_type: 'all' or one of instruments, sounds, drums,
                     audio_effects, midi_effects, max_for_live, plugins,
                     clips, samples, packs, user_library, current_project
    """
    result = live.call("get_browser_tree", category_type=category_type)
    rows = [f"Browser ({result['total_folders']} folders listed)"]

    def render(node: dict, depth: int) -> None:
        more = " ..." if node.get("has_more") else ""
        rows.append(f"{'  ' * depth}- {node['name']}  (path: {node['path']}){more}")
        for child in node.get("children", []):
            render(child, depth + 1)

    for category in result["categories"]:
        render(category, 0)
    return "\n".join(rows)


@tool(READ)
def get_browser_items_at_path(path: str, limit: IntLike = 50, offset: IntLike = 0) -> str:
    """List the contents of a folder in Live's browser.

    - path: 'category/folder/subfolder', e.g. 'audio_effects/Reverb' or
            'plugins/VST3'. Categories as in get_browser_tree.
    - limit: how many entries to return; 0 returns all
    - offset: entries to skip, for paging through large folders

    Each line shows F (folder) or L (loadable), the name and the URI.
    """
    count, skip = to_int(limit, "limit"), to_int(offset, "offset")
    try:
        result = live.call("get_browser_items_at_path", path=path, offset=skip,
                           limit=count if count > 0 else None)
    except LiveError as problem:
        nearby = problem.details.get("nearby") or problem.details.get("available_categories")
        if nearby:
            return f"{problem}. Available here: {', '.join(str(n) for n in nearby)}"
        raise
    shown, total = result["returned"], result["total_count"]
    head = f"{result['path']}  ({result.get('uri') or 'no uri'})"
    if skip + shown < total:
        head += f"\n{shown} of {total} entries from {skip}; next page: offset={skip + shown}"
    else:
        head += f"\n{shown} entries" + (f" (from {skip} of {total})" if skip else "")
    rows = [head]
    for item in result["items"]:
        kind = "L" if item.get("is_loadable") else "F"
        rows.append(f"  [{kind}] {item['name']} | {item.get('uri') or ''}")
    return "\n".join(rows)
