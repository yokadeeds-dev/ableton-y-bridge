"""Read access to Live's browser."""

from .. import browsing
from ..errors import BAD_PARAMS, CommandError
from ..registry import READ, Int, Text, command


def _folder_tree(item, depth, path, counter):
    """Folders below ``item`` down to ``depth`` levels (loadable leaves left out)."""
    node = browsing.describe(item)
    node["path"] = path
    node["children"] = []
    counter[0] += 1
    kids = browsing.children(item)
    if depth <= 0:
        node["has_more"] = any(browsing.children(k) for k in kids[:50])
        return node
    for kid in kids:
        if counter[0] >= 400:
            node["has_more"] = True
            break
        if browsing.children(kid):
            name = browsing.peek(kid, "name", "?")
            node["children"].append(_folder_tree(kid, depth - 1, path + "/" + name, counter))
    return node


@command("get_browser_tree", zone=READ,
         summary="Browser categories and their folders down to a given depth",
         params=[Text("category_type", "all"), Int("depth", 1)], timeout=45.0)
def get_browser_tree(live, category_type, depth):
    available = browsing.roots(live.browser)
    if str(category_type).strip().lower() in ("all", "", "*"):
        chosen = available
    else:
        chosen = [browsing.root_by_name(live.browser, category_type)]
    counter = [0]
    depth = max(0, min(depth, 4))
    categories = []
    for key, label, item in chosen:
        node = _folder_tree(item, depth, key, counter)
        node["name"] = label
        categories.append(node)
    return {
        "type": category_type,
        "depth": depth,
        "categories": categories,
        "total_folders": counter[0],
        "available_categories": [key for key, _label, _item in available],
    }


@command("get_browser_categories", zone=READ,
         summary="Top-level browser categories",
         params=[Text("category_type", "all")])
def get_browser_categories(live, category_type):
    rows = []
    for key, label, item in browsing.roots(live.browser):
        row = browsing.describe(item)
        row.update({"key": key, "name": label})
        rows.append(row)
    return {"categories": rows}


def _listing(live, path, limit, offset):
    item, canonical = browsing.walk(live.browser, path)
    rows = [browsing.describe(child) for child in browsing.children(item)]
    total = len(rows)
    start = max(0, offset)
    page = rows[start:] if limit is None or limit <= 0 else rows[start:start + limit]
    head = browsing.describe(item)
    head.update({
        "path": canonical,
        "items": page,
        "total_count": total,
        "returned": len(page),
        "offset": start,
        "limit": limit,
    })
    return head


@command("get_browser_items_at_path", zone=READ,
         summary="Contents of a browser folder given as 'category/folder/sub'",
         params=[Text("path"), Int("limit", None), Int("offset", 0)], timeout=45.0)
def get_browser_items_at_path(live, path, limit, offset):
    return _listing(live, path, limit, offset)


@command("get_browser_items", zone=READ,
         summary="Contents of a browser folder, optionally only folders or loadable items",
         params=[Text("path", ""), Text("item_type", "all")], timeout=45.0)
def get_browser_items(live, path, item_type):
    if not path.strip():
        return get_browser_categories(live, "all")
    listing = _listing(live, path, None, 0)
    wanted = item_type.strip().lower()
    if wanted in ("folder", "folders"):
        listing["items"] = [row for row in listing["items"] if row["is_folder"]]
    elif wanted in ("loadable", "device", "devices"):
        listing["items"] = [row for row in listing["items"] if row["is_loadable"]]
    elif wanted not in ("all", ""):
        raise CommandError(BAD_PARAMS, "item_type must be all, folders or loadable")
    listing["returned"] = len(listing["items"])
    return listing


@command("get_browser_item", zone=READ,
         summary="Look up one browser item by URI or by path",
         params=[Text("uri", None), Text("path", None)], timeout=45.0)
def get_browser_item(live, uri, path):
    if not uri and not path:
        raise CommandError(BAD_PARAMS, "give uri or path")
    item = browsing.find_by_uri(live.browser, uri) if uri else None
    canonical = None
    if item is None and path:
        item, canonical = browsing.walk(live.browser, path)
    if item is None:
        return {"found": False, "uri": uri, "path": path}
    return {"found": True, "uri": uri, "path": canonical or path, "item": browsing.describe(item)}
