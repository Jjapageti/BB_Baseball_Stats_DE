from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED_ARRAYS = ("teams", "matches", "standings", "batting", "pitching")
DATASETS = (
    {
        "name": "Landesliga Baseball",
        "source": ROOT / "bsm_league_data" / "landesliga_2026" / "combined.json",
        "target": ROOT / "data" / "landesliga_2026.json",
        "fetcher": "landesliga_data_fetcher_vscode.py",
    },
    {
        "name": "Verbandsliga Baseball",
        "source": ROOT / "bsm_league_data" / "verbandsliga_2026" / "combined.json",
        "target": ROOT / "data" / "verbandsliga_2026.json",
        "fetcher": "verbandsliga_data_fetcher_vscode.py",
    },
)


def validate_combined(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data.get("league"), dict):
        raise ValueError(f"{path}: league fehlt")
    for key in REQUIRED_ARRAYS:
        if not isinstance(data.get(key), list):
            raise ValueError(f"{path}: Array {key} fehlt")
    return data


def sync_dataset(dataset: dict) -> bool:
    source: Path = dataset["source"]
    target: Path = dataset["target"]
    if not source.exists():
        print(f"[ÜBERSPRUNGEN] {dataset['name']}")
        print(f"  Zuerst {dataset['fetcher']} ausführen.")
        return False
    data = validate_combined(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    print(f"[OK] {dataset['name']}")
    print(f"  {source}")
    print(f"  → {target}")
    print(
        f"  Teams {len(data['teams'])} · Spiele {len(data['matches'])} · "
        f"Batter {len(data['batting'])} · Pitcher {len(data['pitching'])}"
    )
    return True


def main() -> None:
    print("Website-Daten werden synchronisiert …\n")
    synced = sum(sync_dataset(dataset) for dataset in DATASETS)
    print(f"\nFertig: {synced}/{len(DATASETS)} Ligen synchronisiert.")


if __name__ == "__main__":
    main()
