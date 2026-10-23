"""Checkpoint and resume management for the simulator runtime."""
import hashlib
import json


class ConfigMismatchError(Exception):
    pass


def config_fingerprint(cfg):
    ids = cfg["ids"]
    parts = {
        "seed": cfg["seed"],
        "start_date": str(cfg["start_date"]),
        "customer_prefix": ids["customer_prefix"],
        "customer_width": ids["customer_width"],
        "tower_prefix": ids["tower_prefix"],
        "tower_width": ids["tower_width"],
    }
    text = json.dumps(parts, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Checkpoint:
    def __init__(self, store, cfg):
        self.store = store
        self.fingerprint = config_fingerprint(cfg)

    def start(self):
        """Return the band index to start from (0 for a new run)."""
        saved = self.store.get_meta("config_hash")
        if saved is None:
            with self.store.transaction():
                self.store.set_meta("config_hash", self.fingerprint)
                self.store.set_meta("index", 0)
                self.store.set_meta("next_customer_no", 1)
            return 0
        if saved != self.fingerprint:
            raise ConfigMismatchError(
                "Config badal gayi hai (seed, start_date ya ids). "
                "Purana data in values se bana tha. "
                "Naye sire se shuru karna hai to state/ delete karo."
            )
        return int(self.store.get_meta("index", 0))

    def next_customer_no(self):
        return int(self.store.get_meta("next_customer_no", 1))

    def save(self, index, next_customer_no):
        """Call inside the main loop's transaction, with the state writes."""
        self.store.set_meta("index", index)
        self.store.set_meta("next_customer_no", next_customer_no)