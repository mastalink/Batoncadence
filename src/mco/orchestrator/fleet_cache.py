"""Five-second, per-client fleet caches with coalesced refreshes."""

from copy import deepcopy
import threading
from time import monotonic
from weakref import WeakKeyDictionary

TTL_SECONDS = 5.0
_clients = WeakKeyDictionary()
_clients_lock = threading.Lock()


class _Entry:
    def __init__(self):
        self.lock = threading.Lock()
        self.expires = 0.0
        self.key = None
        self.value = None


def cached_fleet(db, namespace, key, load):
    # Transactional readers must not retain or consume uncommitted snapshots.
    if getattr(getattr(db, "_thread", None), "depth", 0):
        return load()
    try:
        with _clients_lock:
            entries = _clients.setdefault(db, {})
            entry = entries.setdefault(namespace, _Entry())
    except TypeError:
        # Some third-party DB adapters do not support weak references.
        return load()
    # One refreshing caller per store/namespace, no cross-store serialization.
    with entry.lock:
        if entry.key != key or monotonic() >= entry.expires:
            value = load()
            entry.value = deepcopy(value)
            entry.key = key
            entry.expires = monotonic() + TTL_SECONDS
        return deepcopy(entry.value)
