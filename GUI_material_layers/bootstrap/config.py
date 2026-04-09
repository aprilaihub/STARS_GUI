from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    base_dir: Path
    working_db_path: Path
    recipe_db_path: Path

    @classmethod
    def default(cls, base_dir: str | Path | None = None) -> "AppConfig":
        root = Path(base_dir) if base_dir else Path(__file__).resolve().parents[1]
        project_root = root.parent
        return cls(
            base_dir=root,
            working_db_path=root / "db" / "Manufacture_Process_Database.db",
            recipe_db_path=project_root / "Database_NEW_V2.db",
        )
