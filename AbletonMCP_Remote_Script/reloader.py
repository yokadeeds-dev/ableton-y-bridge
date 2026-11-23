"""Loading and hot reloading of everything that is not bridge core.

Core modules (listed in `CORE`) hold the running socket server, the gate and
the control surface object; they stay as loaded until Live restarts. All
other modules of the package - the support modules and everything under
``handlers/`` - can be replaced while Live runs. A reload is all or nothing:
if any module fails to import, the previous modules and the previous register
stay in service.
"""

import hashlib
import importlib
import os
import pkgutil
import sys
import time

from . import registry as _registry

PACKAGE = __name__.rsplit(".", 1)[0]
CORE = ("errors", "registry", "gate", "wire", "hub", "surface", "reloader", "settings")
HANDLER_PACKAGE = "handlers"
CONTEXT_MODULE = "liveaccess"


def package_dir():
    return os.path.dirname(os.path.abspath(__file__))


def source_files():
    """All .py files of the package as (relative path, absolute path)."""
    root = package_dir()
    found = []
    for folder, subfolders, names in os.walk(root):
        subfolders[:] = [s for s in subfolders if s != "__pycache__" and not s.startswith(".")]
        for name in names:
            if name.endswith(".py"):
                full = os.path.join(folder, name)
                found.append((os.path.relpath(full, root).replace(os.sep, "/"), full))
    found.sort()
    return found


def fingerprint(only_core=False):
    """Short hash over the package sources plus the newest modification time."""
    digest = hashlib.sha1()
    newest = 0.0
    count = 0
    for relative, full in source_files():
        is_core = "/" not in relative and relative[:-3] in CORE + ("__init__",)
        if only_core and not is_core:
            continue
        try:
            with open(full, "rb") as handle:
                body = handle.read()
            newest = max(newest, os.path.getmtime(full))
        except OSError:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(body.replace(b"\r\n", b"\n"))
        count += 1
    return {"hash": digest.hexdigest()[:12], "newest_mtime": int(newest), "files": count}


def _reloadable_names():
    """Dotted names of all replaceable modules, support modules first."""
    root = package_dir()
    support = []
    for _finder, name, is_package in pkgutil.iter_modules([root]):
        if is_package or name in CORE:
            continue
        support.append("%s.%s" % (PACKAGE, name))
    handler_root = "%s.%s" % (PACKAGE, HANDLER_PACKAGE)
    handlers = [handler_root]
    for _finder, name, _is_package in pkgutil.iter_modules([os.path.join(root, HANDLER_PACKAGE)]):
        handlers.append("%s.%s" % (handler_root, name))
    return sorted(support) + handlers[:1] + sorted(handlers[1:])


class Loaded(object):
    """Result of a load: the register plus the context class handlers get."""

    def __init__(self, registry, context_class, modules, core_hash):
        self.registry = registry
        self.context_class = context_class
        self.modules = modules
        self.core_hash = core_hash
        self.loaded_at = time.time()


def load():
    """Import all replaceable modules afresh and return a `Loaded`.

    Used for the first load and for every hot reload. On failure the module
    table is put back the way it was and the exception propagates.
    """
    names = _reloadable_names()
    wanted = set(names)
    parent = sys.modules.get(PACKAGE)
    shelved = {}
    for name in list(sys.modules):
        if name in wanted:
            shelved[name] = sys.modules.pop(name)
    importlib.invalidate_caches()
    fresh = _registry.Registry()
    previous_target = _registry.collect_into(fresh)
    try:
        for name in names:
            importlib.import_module(name)
        context_class = getattr(sys.modules["%s.%s" % (PACKAGE, CONTEXT_MODULE)], "LiveCtx")
    except BaseException:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(shelved)
        if parent is not None:
            for name, module in shelved.items():
                tail = name[len(PACKAGE) + 1:]
                if "." not in tail:
                    setattr(parent, tail, module)
        raise
    finally:
        _registry.collect_into(previous_target)
    short = [name[len(PACKAGE) + 1:] for name in names]
    return Loaded(fresh, context_class, short, fingerprint(only_core=True)["hash"])
