"""Run: python -m unittest tests.test_bulk_proxy   (from the project root)"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bulk_proxy as bp

PROFILES = Path(__file__).resolve().parent.parent / "profiles"


def fake_paths(names):
    return [Path("/x") / f"{n}.json" for n in names]


class ResolveMany(unittest.TestCase):
    def test_mixed(self):
        paths = fake_paths([f"profile_{i:03d}_windows_desktop" for i in range(1, 31)])
        got, bad = bp.resolve_many("14, 3-5;20  3 profile_030_windows_desktop 99", paths)
        self.assertEqual([p.stem[8:11] for p in got], ["014", "003", "004", "005", "020", "030"])
        self.assertEqual(len(bad), 1)
        self.assertIn("99", bad[0])

    def test_empty(self):
        self.assertEqual(bp.resolve_many("  ", fake_paths(["profile_001_a"])), ([], []))


class ParseProxy(unittest.TestCase):
    def test_decodo_colon_format(self):
        self.assertEqual(
            bp.parse_proxy_string("isp.decodo.com:10001:sp7td89vu2:VeS_504pTiRlidk8gi"),
            {"server": "http://isp.decodo.com:10001", "username": "sp7td89vu2", "password": "VeS_504pTiRlidk8gi"},
        )

    def test_password_with_colon(self):
        self.assertEqual(bp.parse_proxy_string("h.com:1:u:pa:ss")["password"], "pa:ss")

    def test_other_formats(self):
        self.assertEqual(bp.parse_proxy_string("http://h.com:8080,u,p"),
                         {"server": "http://h.com:8080", "username": "u", "password": "p"})
        self.assertEqual(bp.parse_proxy_string("u:p@h.com:8080")["server"], "http://h.com:8080")
        self.assertEqual(bp.parse_proxy_string("socks5://u:p@h.com:1080")["server"], "socks5://h.com:1080")
        self.assertEqual(bp.parse_proxy_string("h.com:8080")["username"], "")

    def test_rejects_garbage(self):
        for bad in ["", "14", "hello", "h.com:notaport:u:p", "h.com:99999:u:p", "ftp://h.com:1"]:
            self.assertIsNone(bp.parse_proxy_string(bad), bad)


class Plan(unittest.TestCase):
    def setUp(self):
        # Row NO. 1..6 in table order.
        self.paths = fake_paths([
            "profile_001_android_tablet",   # NO. 1
            "profile_001_windows_desktop",  # NO. 2
            "profile_002_macos_laptop",     # NO. 3
            "profile_002_windows_desktop",  # NO. 4
            "profile_003_windows_desktop",  # NO. 5
            "profile_100_windows_laptop",   # NO. 6
        ])

    def stems(self, t):
        return sorted(p.stem for p in t)

    def test_bare_number_is_the_row_no(self):
        for tgt in ["4", "04", "no4", "no.4", "NO4"]:
            t, pool, err = bp.plan_bulk_assign(f"{tgt},isp.decodo.com:10001:u:p", self.paths)
            self.assertEqual(self.stems(t), ["profile_002_windows_desktop"], tgt)
            self.assertFalse(pool); self.assertFalse(err)

    def test_row_is_not_filename_number(self):
        # Row 2 is profile_001_windows_desktop, NOT anything numbered 002.
        t, _, _ = bp.plan_bulk_assign("2,h.com:1:u:p", self.paths)
        self.assertEqual(self.stems(t), ["profile_001_windows_desktop"])

    def test_range(self):
        t, _, e = bp.plan_bulk_assign("3-5,h.com:1:u:p", self.paths)
        self.assertEqual(self.stems(t), ["profile_002_macos_laptop", "profile_002_windows_desktop", "profile_003_windows_desktop"])
        self.assertFalse(e)

    def test_filename_number_hits_all_variants(self):
        t, _, e = bp.plan_bulk_assign("profile_001,h.com:1:u:p", self.paths)
        self.assertEqual(self.stems(t), ["profile_001_android_tablet", "profile_001_windows_desktop"])

    def test_full_name_and_prefix(self):
        for tgt in ["profile_002_windows_desktop", "profile_002_windows_desktop.json", "profile_002_windows"]:
            t, _, e = bp.plan_bulk_assign(f"{tgt},h.com:1:u:p", self.paths)
            self.assertEqual(self.stems(t), ["profile_002_windows_desktop"], tgt)

    def test_row_out_of_range_is_error_not_round_robin(self):
        for tgt in ["7", "0", "99", "5-9"]:
            t, pool, err = bp.plan_bulk_assign(f"{tgt},h.com:1:u:p", self.paths)
            self.assertFalse(t, tgt); self.assertFalse(pool, tgt)
            self.assertEqual(len(err), 1, tgt)
            self.assertIn("doesn't exist", err[0][2])
            self.assertNotIn("u:p", err[0][1])  # password masked

    def test_unknown_name_is_error(self):
        t, pool, err = bp.plan_bulk_assign("profile_999,h.com:1:u:p", self.paths)
        self.assertFalse(t); self.assertFalse(pool); self.assertEqual(len(err), 1)

    def test_comma_proxy_without_target_is_round_robin(self):
        t, pool, err = bp.plan_bulk_assign("http://h.com:80,u,p", self.paths)
        self.assertFalse(t); self.assertEqual(len(pool), 1); self.assertFalse(err)

    def test_numeric_ip_not_mistaken_for_target(self):
        t, pool, err = bp.plan_bulk_assign("1.2.3.4:8080:u:p", self.paths)
        self.assertFalse(t); self.assertEqual(pool[0]["server"], "http://1.2.3.4:8080")

    def test_crlf_bom_blank_lines_whitespace_separator(self):
        txt = "\ufeff1,h.com:1:u:p\r\n\r\n2 h.com:2:u:p\r\n# comment\r\n"
        t, pool, err = bp.plan_bulk_assign(txt, self.paths)
        self.assertEqual(len(t), 2); self.assertFalse(err)

    def test_user_example_exact(self):
        txt = ("14,isp.decodo.com:10001:sp7td89vu2:VeS_504pTiRlidk8gi\n"
               "15,isp.decodo.com:10002:sp7td89vu2:VeS_504pTiRlidk8gi\n"
               "16,isp.decodo.com:10003:sp7td89vu2:VeS_504pTiRlidk8gi")
        paths = fake_paths([f"profile_{i:03d}_windows_desktop" for i in range(1, 21)])
        t, pool, err = bp.plan_bulk_assign(txt, paths)
        self.assertFalse(err); self.assertFalse(pool)
        by = {p.stem: v["server"] for p, v in t.items()}
        self.assertEqual(by, {
            "profile_014_windows_desktop": "http://isp.decodo.com:10001",
            "profile_015_windows_desktop": "http://isp.decodo.com:10002",
            "profile_016_windows_desktop": "http://isp.decodo.com:10003",
        })


@unittest.skipUnless(PROFILES.exists(), "no profiles dir")
class RealProfiles(unittest.TestCase):
    def test_rows_14_15_16_in_real_list(self):
        paths = sorted(PROFILES.glob("*.json"))  # same order as the GUI table
        txt = ("14,isp.decodo.com:10001:sp7td89vu2:VeS_504pTiRlidk8gi\n"
               "15,isp.decodo.com:10002:sp7td89vu2:VeS_504pTiRlidk8gi\n"
               "16,isp.decodo.com:10003:sp7td89vu2:VeS_504pTiRlidk8gi")
        t, pool, err = bp.plan_bulk_assign(txt, paths)
        self.assertFalse(err); self.assertFalse(pool)
        self.assertEqual(sorted(p.name for p in t), sorted([paths[13].name, paths[14].name, paths[15].name]))
        self.assertEqual(t[paths[13]]["server"], "http://isp.decodo.com:10001")
        self.assertEqual(t[paths[15]]["server"], "http://isp.decodo.com:10003")


if __name__ == "__main__":
    unittest.main()
