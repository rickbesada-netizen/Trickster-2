"""Offline tests: no platform requests or browser sessions."""
import tempfile
from pathlib import Path
import unittest

from fleet_scheduler import machine_layout, profile_partition, select_daily_clips, FleetController


def campaigns():
    return [
        {"id": f"campaign-{i}", "creator_url": "https://example.test/creator",
         "clips": [{"id": f"{i}-{k}", "href": f"/clip/{i}/{k}", "duration_seconds": 12}
                   for k in range(100)]}
        for i in range(10)
    ]


class FleetTests(unittest.TestCase):
    def test_layout(self):
        layout = machine_layout()
        self.assertEqual(len(layout), 13)
        self.assertEqual(sum(x["count"] for x in layout), 1000)
        self.assertEqual(sum(x["max_workers"] for x in layout), 180)
        self.assertEqual(layout[0]["count"], 133)
        self.assertEqual(layout[2]["count"], 67)
        self.assertEqual(layout[-1]["count"], 66)

    def test_no_profile_duplication_across_machines(self):
        profiles = list(range(1, 1001))
        groups = [profile_partition(profiles, i)[0] for i in range(13)]
        self.assertEqual(sorted(p for group in groups for p in group), profiles)
        self.assertEqual(set(groups[0]) & set(groups[1]), set())

    def test_daily_campaign_randomisation(self):
        items = campaigns()
        a = select_daily_clips("profile1", items, "2026-11-15")
        b = select_daily_clips("profile1", items, "2026-11-15")
        c = select_daily_clips("profile2", items, "2026-11-15")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 100)
        self.assertEqual(len({(x["campaign_id"], x["id"]) for x in a}), 100)
        self.assertEqual(len({x["campaign_id"] for x in a}), 10)

    def test_unconfigured_controller_refuses_to_run(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = FleetController(Path(directory) / "missing.json")
            result = controller.start()
            self.assertFalse(result["ok"])
            self.assertFalse(controller.status()["active"])


if __name__ == "__main__":
    unittest.main()
