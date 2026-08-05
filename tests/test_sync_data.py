import json
import tempfile
import unittest
from pathlib import Path

import sync_data


class SyncDataTests(unittest.TestCase):
    def test_validate_combined_accepts_site_schema(self):
        payload = {
            "league": {"name": "Test League"},
            "teams": [],
            "matches": [],
            "standings": [],
            "batting": [],
            "pitching": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "combined.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(sync_data.validate_combined(path)["league"]["name"], "Test League")

    def test_sync_dataset_copies_valid_json(self):
        payload = {
            "league": {"name": "Test League"},
            "teams": [{"id": 1}],
            "matches": [],
            "standings": [],
            "batting": [],
            "pitching": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.json"
            target = root / "data" / "target.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            result = sync_data.sync_dataset({
                "name": "Test League",
                "source": source,
                "target": target,
                "fetcher": "test_fetcher.py",
            })
            self.assertTrue(result)
            self.assertTrue(target.exists())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["teams"][0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
