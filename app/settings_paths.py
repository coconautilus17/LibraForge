"""Where user-editable settings files live.

Next to the shipped defaults in config/ unless LIBRAFORGE_SETTINGS_DIR is set. The
end-user compose file points that at a named volume, so saved settings survive
image upgrades (config/ itself is part of the image and is replaced on upgrade)."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def settings_dir() -> Path:
    override = os.environ.get("LIBRAFORGE_SETTINGS_DIR", "").strip()
    return Path(override) if override else PROJECT_ROOT / "config"


def user_settings_file(name: str) -> Path:
    return settings_dir() / name
