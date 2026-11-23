"""Navigation in Live's browser: roots, paths, URI lookup, name search."""

from .errors import NOT_FOUND, CommandError
from .liveaccess import peek

# (attribute on Live's browser object, label shown to clients)
ROOTS = (
    ("instruments", "Instruments"),
    ("sounds", "Sounds"),
    ("drums", "Drums"),
    ("audio_effects", "Audio Effects"),
    ("midi_effects", "MIDI Effects"),
    ("max_for_live", "Max for Live"),
    ("plugins", "Plug-Ins"),
    ("clips", "Clips"),
    ("samples", "Samples"),
    ("packs", "Packs"),
    ("user_library", "User Library"),
    ("current_project", "Current Project"),
)

# Which root a URI most likely lives under, by the word after "query:".
_URI_HOME = {
    "synths": "instruments",
    "sounds": "sounds",
    "drums": "drums",
    "audiofx": "audio_effects",
    "midifx": "midi_effects",
    "m4l": "max_for_live",
    "maxforlive": "max_for_live",
    "plugins": "plugins",
    "clips": "clips",
    "samples": "samples",
    "livepacks": "packs",
    "userlibrary": "user_library",
}


def _squash(text):
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def roots(browser):
    """Existing root folders as a list of (key, label, item)."""
    found = []
    for key, label in ROOTS:
        item = peek(browser, key)
        if item is not None:
            found.append((key, label, item))
    return found


def children(item):
    kids = peek(item, "children")
    if kids is None:
        return []
    try:
        return list(kids)
    except Exception:
        return []


def describe(item, with_children_flag=True):
    info = {
        "name": peek(item, "name", "?"),
        "uri": peek(item, "uri"),
        "is_folder": bool(peek(item, "is_folder", False)),
        "is_device": bool(peek(item, "is_device", False)),
        "is_loadable": bool(peek(item, "is_loadable", False)),
    }
    if with_children_flag and not info["is_folder"]:
        info["is_folder"] = bool(children(item)) and not info["is_loadable"]
    return info


def root_by_name(browser, name):
    wanted = _squash(name)
    available = roots(browser)
    for key, label, item in available:
        if wanted in (_squash(key), _squash(label)):
            return key, label, item
    raise CommandError(
        NOT_FOUND,
        "unknown browser category '%s'" % name,
        available_categories=[key for key, _label, _item in available],
    )


def walk(browser, path):
    """Follow 'category/folder/sub' and return (item, canonical path)."""
    parts = [p for p in str(path).replace("\\", "/").split("/") if p.strip()]
    if not parts:
        raise CommandError(NOT_FOUND, "empty browser path",
                           available_categories=[k for k, _l, _i in roots(browser)])
    key, _label, item = root_by_name(browser, parts[0])
    trail = [key]
    for part in parts[1:]:
        wanted = part.strip().lower()
        match = None
        for child in children(item):
            if str(peek(child, "name", "")).lower() == wanted:
                match = child
                break
        if match is None:
            raise CommandError(
                NOT_FOUND,
                "'%s' not found under '%s'" % (part, "/".join(trail)),
                nearby=[peek(c, "name", "?") for c in children(item)][:40],
            )
        item = match
        trail.append(peek(item, "name", part))
    return item, "/".join(trail)


def _ordered_roots(browser, uri):
    """Roots with the likely home of ``uri`` first."""
    home = None
    text = str(uri)
    if text.startswith("query:"):
        head = text[6:].split("#", 1)[0].split(":", 1)[0]
        home = _URI_HOME.get(_squash(head))
    available = roots(browser)
    available.sort(key=lambda entry: 0 if entry[0] == home else 1)
    return [item for _key, _label, item in available]


def find_by_uri(browser, uri, node_budget=60000, max_depth=9):
    """Locate the browser item with exactly this URI.

    Depth-first, but children whose own URI is a prefix of the target are
    visited first, because Live builds item URIs by extending the folder's.
    Returns None when the budget is used up or nothing matches.
    """
    target = str(uri)
    budget = [node_budget]

    def search(item, depth):
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        if peek(item, "uri") == target:
            return item
        if depth >= max_depth:
            return None
        likely, others = [], []
        for child in children(item):
            child_uri = peek(child, "uri") or ""
            if child_uri == target:
                return child
            if child_uri and target.startswith(child_uri):
                likely.append(child)
            elif not peek(child, "is_loadable", False) or peek(child, "is_folder", False):
                others.append(child)
        for child in likely + others:
            hit = search(child, depth + 1)
            if hit is not None:
                return hit
        return None

    for root in _ordered_roots(browser, target):
        hit = search(root, 0)
        if hit is not None:
            return hit
    return None


def require_by_uri(browser, uri):
    item = find_by_uri(browser, uri)
    if item is None:
        raise CommandError(NOT_FOUND, "no browser item has the URI '%s'" % uri)
    return item


def search_names(start_items, needle, limit=20, max_depth=6, loadable_only=True,
                 node_budget=40000):
    """Items below ``start_items`` whose name contains ``needle``."""
    wanted = str(needle).lower()
    hits = []
    budget = [node_budget]

    def visit(item, depth, trail):
        if len(hits) >= limit or budget[0] <= 0:
            return
        budget[0] -= 1
        name = str(peek(item, "name", ""))
        loadable = bool(peek(item, "is_loadable", False))
        if wanted in name.lower() and (loadable or not loadable_only):
            hits.append({
                "name": name,
                "uri": peek(item, "uri"),
                "is_loadable": loadable,
                "folder": "/".join(trail),
            })
        if depth < max_depth:
            for child in children(item):
                visit(child, depth + 1, trail + [name])

    for item in start_items:
        visit(item, 0, [])
    return hits
