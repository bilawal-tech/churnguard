from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from silver.settings import SilverSettings, load_silver_settings


@dataclass(frozen=True)
class GoldSettings:
    project_root: Path
    silver_dir: Path
    gold_dir: Path
    silver_settings: SilverSettings


def load_gold_settings(
    silver_settings: SilverSettings | None = None,
) -> GoldSettings:
    silver = silver_settings or load_silver_settings()
    return GoldSettings(
        project_root=silver.project_root,
        silver_dir=silver.silver_dir,
        gold_dir=silver.project_root / "data" / "gold",
        silver_settings=silver,
    )
