import hashlib
import json
import os
import time


class DiskCache(object):
    def __init__(self, directory):
        self.directory = directory

    def _path(self, key):
        return os.path.join(self.directory, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")

    def get(self, key, ttl):
        try:
            with open(self._path(key), "r") as fh:
                entry = json.load(fh)
            if time.time() - entry["t"] <= ttl:
                return entry["v"]
        except (IOError, OSError, ValueError, KeyError):
            pass
        return None

    def set(self, key, value):
        try:
            os.makedirs(self.directory, exist_ok=True)
            with open(self._path(key), "w") as fh:
                json.dump({"t": time.time(), "v": value}, fh)
        except (IOError, OSError, TypeError):
            pass
