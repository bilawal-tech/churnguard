import hashlib
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(name="config.yaml"):
    """config/ folder se settings file padhta hai."""
    path = ROOT / "config" / name
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_id(prefix, width, n):
    """make_id('T', 5, 1) -> 'T00001'"""
    return f"{prefix}{n:0{width}d}"


def tower_id(cfg, n):
    return make_id(cfg["ids"]["tower_prefix"], cfg["ids"]["tower_width"], n)


def customer_id(cfg, n):
    return make_id(cfg["ids"]["customer_prefix"], cfg["ids"]["customer_width"], n)


def make_rng(global_seed, *parts):
    """Har entity ka apna random generator.
    Seed global seed aur entity ki pehchan (jaise 'tower', 'T00001') se banta hai,
    is liye ginti badalne par purani entities ka data nahi badalta."""
    text = "|".join([str(global_seed)] + [str(p) for p in parts])
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big")
    return np.random.default_rng(seed)