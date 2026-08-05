import unittest

import verbandsliga_data_fetcher_vscode as module


class VerbandsligaFetcherTests(unittest.TestCase):
    def test_league_metadata_is_fixed_for_2026(self):
        meta = module.build_league_meta()
        self.assertEqual(meta["id"], 6205)
        self.assertEqual(meta["acronym"], "VLBB")
        self.assertEqual(meta["season"], 2026)
        self.assertFalse(meta["merged"])

    def test_build_combined_payload_matches_site_schema(self):
        teams = [{"id": 1, "name": "Team A", "acronym": "AAA"}]
        matches = []
        standings = []
        batting = []
        pitching = []
        payload = module.build_combined_payload(
            generated_at="2026-08-04T00:00:00+00:00",
            teams=teams,
            matches=matches,
            standings=standings,
            batting=batting,
            pitching=pitching,
        )
        self.assertEqual(payload["counts"]["teams"], 1)
        for key in ("teams", "matches", "standings", "batting", "pitching"):
            self.assertIsInstance(payload[key], list)

    def test_standings_are_calculated_from_played_matches(self):
        teams = [
            {"id": 1, "name": "Team A", "acronym": "AAA"},
            {"id": 2, "name": "Team B", "acronym": "BBB"},
        ]
        matches = [{
            "id": 9,
            "state": "played",
            "home_runs": 7,
            "away_runs": 3,
            "home_league_entry": {"id": 1},
            "away_league_entry": {"id": 2},
        }]
        rows = module.compute_combined_standings(matches, teams)
        self.assertEqual(rows[0]["league_entry_id"], 1)
        self.assertEqual(rows[0]["wins"], 1)
        self.assertEqual(rows[1]["losses"], 1)


if __name__ == "__main__":
    unittest.main()
