"""
Generate a batch of internally-consistent fingerprint profiles.

Each profile picks an OS bucket first (Windows or macOS), then samples
UA/platform/GPU/fonts/hardware/screen all from within that bucket, so
nothing contradicts itself the way individual fields would if randomised
independently (e.g. never a Windows UA with a macOS GPU string).

Usage:
    python generate_profiles.py --count 50
    python generate_profiles.py --count 50 --proxies proxies.json

proxies.json (optional), if given, should be a list like:
    [
      {"server": "http://host1:port", "username": "user1", "password": "pass1"},
      {"server": "http://host2:port", "username": "user2", "password": "pass2"}
    ]
Proxies are assigned round-robin across generated profiles. Without this
file, every profile gets the placeholder proxy block (fill in manually,
or re-run with --proxies once you have a list).
"""

"""
Generate a batch of internally-consistent fingerprint profiles.

Each profile picks an OS bucket first (Windows, macOS, Android, or iOS),
then samples UA/platform/GPU/fonts/hardware/screen all from within that
bucket, so nothing contradicts itself the way individual fields would if
randomised independently (e.g. never a Windows UA with a macOS GPU string,
or a phone screen size paired with desktop RAM). Desktop platforms mix GPU
and hardware/screen independently (any real PC can pair any GPU with any
monitor); mobile platforms use whole real-device bundles instead, since a
specific phone always has one fixed chip+screen combination in real life.

Usage:
    python generate_profiles.py --count 50
    python generate_profiles.py --count 50 --proxies proxies.json

proxies.json (optional), if given, should be a list like:
    [
      {"server": "http://host1:port", "username": "user1", "password": "pass1"},
      {"server": "http://host2:port", "username": "user2", "password": "pass2"}
    ]
Proxies are assigned round-robin across generated profiles. Without this
file, every profile gets the placeholder proxy block (fill in manually,
or re-run with --proxies once you have a list).
"""

import argparse
import json
import random
from pathlib import Path

from profile_pools import PLATFORMS, DEVICE_CLASSES, LOCALES, hardware_options

PLACEHOLDER_PROXY = {"server": "http://your-proxy-host:port", "username": "your-proxy-user", "password": "your-proxy-pass"}

# Windows most common, then macOS, then mobile — adjust to match whatever
# mix you actually need; this is just a reasonable general-purpose default.
OS_WEIGHTS = {"windows": 0.55, "macos": 0.15, "android": 0.22, "ios": 0.08}


def make_profile(index: int, used_seeds: set) -> dict:
    os_choice = random.choices(list(OS_WEIGHTS.keys()), weights=list(OS_WEIGHTS.values()))[0]
    plat = PLATFORMS[os_choice]
    device_class = random.choice(plat["device_classes"])
    locale = random.choice(LOCALES)

    seed = random.randint(100000, 999999)
    while seed in used_seeds:
        seed = random.randint(100000, 999999)
    used_seeds.add(seed)

    profile_id = f"profile_{index:03d}_{os_choice}_{device_class}"

    base = {
        "profile_id": profile_id,
        "locale": locale["locale"],
        "timezone_id": locale["timezone_id"],
        "geolocation": locale["geolocation"],
        "canvas_seed": seed,
        "proxy": dict(PLACEHOLDER_PROXY),
        "storage_state_path": f"profiles/{profile_id}_state.json",
    }

    if plat["kind"] == "desktop":
        cls = DEVICE_CLASSES[device_class]
        gpu = random.choice(plat["gpus"])
        width, height = random.choice(cls["viewport"])
        base.update({
            "user_agent": plat["ua"],
            "platform": plat["platform"],
            "fonts": plat["fonts"],
            "webgl_vendor": gpu["vendor"],
            "webgl_renderer": gpu["renderer"],
            "viewport": {"width": width, "height": height},
            "hardware_concurrency": random.choice(cls["hardware_concurrency"]),
            "device_memory": random.choice(cls["device_memory"]),
            "is_mobile": False,
            "has_touch": False,
            "device_scale_factor": 1,
        })
    else:  # mobile: whole real-device bundle, nothing mixed independently
        device = random.choice(plat["devices"][device_class])
        base.update({
            "user_agent": device["ua"],
            "platform": plat["platform"],
            "fonts": plat["fonts"],
            "webgl_vendor": device["gpu_vendor"],
            "webgl_renderer": device["gpu_renderer"],
            "viewport": device["viewport"],
            "hardware_concurrency": device["hardware_concurrency"],
            "device_memory": device["device_memory"],
            "is_mobile": True,
            "has_touch": True,
            "device_scale_factor": device["device_scale_factor"],
        })

    return base


def generate(count: int, output_dir="profiles", proxies=None, seed=None) -> str:
    """The actual generation logic, callable directly (used by the GUI so
    it doesn't need to spawn a separate Python process — important once
    this is a frozen .exe, where sys.executable is the exe itself, not a
    real Python interpreter). The CLI's main() is a thin wrapper around
    this same function, so both stay in sync automatically."""
    if seed is not None:
        random.seed(seed)

    if proxies is not None and not proxies:
        proxies = None  # empty list treated same as "none supplied"

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    used_seeds = set()
    for i in range(1, count + 1):
        profile = make_profile(i, used_seeds)
        if proxies:
            profile["proxy"] = proxies[(i - 1) % len(proxies)]
        out_path = out_dir / f"{profile['profile_id']}.json"
        with open(out_path, "w") as f:
            json.dump(profile, f, indent=2)

    proxy_note = f"assigned from {len(proxies)} proxies (round-robin)" if proxies else "placeholder — fill in manually or re-run with --proxies"
    return f"Generated {count} profiles in {out_dir}/ ({proxy_note})"


def main():
    parser = argparse.ArgumentParser(description="Generate a batch of consistent fingerprint profiles")
    parser.add_argument("--count", type=int, default=50, help="Number of profiles to generate (default: 50)")
    parser.add_argument("--proxies", type=str, default=None, help="Path to a JSON list of proxy configs to assign round-robin")
    parser.add_argument("--output-dir", type=str, default="profiles", help="Where to write profile JSON files (default: profiles)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed, for reproducible generation")
    args = parser.parse_args()

    proxies = None
    if args.proxies:
        with open(args.proxies, "r") as f:
            proxies = json.load(f)
        if not proxies:
            print("Warning: proxies file is empty, using placeholder proxy for all profiles.")

    message = generate(args.count, output_dir=args.output_dir, proxies=proxies, seed=args.seed)
    print(message)


if __name__ == "__main__":
    main()
