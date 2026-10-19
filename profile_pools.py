"""
Shared device fingerprint pools, used by both generate_profiles.py (random
bulk generation) and the GUI's fingerprint editor (dropdown-driven manual
selection). One source of truth means the two can never drift apart or
allow a mismatched combo.

Two different modelling approaches, deliberately:
- Desktop OSes (Windows, macOS): GPU and hardware/screen are picked
  independently (cartesian) — any GPU legitimately pairs with any monitor
  and any RAM amount on a real PC.
- Mobile OSes (Android, iOS): each entry is a whole REAL DEVICE bundle
  (chip, GPU, screen, RAM all fixed together) — a specific phone always has
  the exact same screen and chipset in real life, so picking these
  independently would produce impossible combinations.

IMPORTANT CAVEAT ON iOS: real Chrome on iPhone/iPad is actually a WebKit
wrapper (Apple requires this — no browser on iOS may use its own engine),
not Chromium. Since this tool can only launch real Chromium, an iOS profile
is claiming a UA that inherently contradicts the engine actually running —
a structural mismatch, not something fixable by better values. It's
included because it was asked for, but it's a meaningfully weaker spoof
than every other platform here, which are all genuinely Chromium under the
hood. Android is NOT affected by this — real Android Chrome is Chromium,
same as desktop, so it's just as structurally sound as Windows/macOS.
"""

# ============================================================
# Windows
# ============================================================
WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
WINDOWS_PLATFORM = "Win32"
WINDOWS_FONTS = ["Arial", "Calibri", "Cambria", "Segoe UI", "Times New Roman", "Verdana", "Consolas"]

WINDOWS_GPUS = [
    {"label": "NVIDIA GeForce GTX 1050 Ti", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1050 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce GTX 1650", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce GTX 1660", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce GTX 1660 Super", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 2060", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 2060 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 2070", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 2070 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 3050", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3050 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 3060", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 3060 Ti", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 3070", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 3080", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 3090", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3090 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 4060", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 4060 Ti", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 4070", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 4070 Ti", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 4080", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4080 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "NVIDIA GeForce RTX 4090", "vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "Intel UHD Graphics 620", "vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "Intel UHD Graphics 630", "vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "Intel UHD Graphics 730", "vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 730 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "Intel UHD Graphics 770", "vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "Intel Iris Xe Graphics", "vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "Intel Arc A380", "vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) Arc(TM) A380 Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "Intel Arc A750", "vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) Arc(TM) A750 Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "Intel Arc A770", "vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) Arc(TM) A770 Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon RX 570", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 570 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon RX 580", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon RX 5700 XT", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 5700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon RX 6600", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon RX 6700 XT", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon RX 6800 XT", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon RX 7600", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 7600 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon RX 7800 XT", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 7800 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon Vega 8 (integrated)", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon(TM) Vega 8 Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon 680M (integrated)", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon(TM) 680M Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"label": "AMD Radeon 780M (integrated)", "vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon(TM) 780M Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
]

# ============================================================
# macOS
# ============================================================
# Real Chrome on Apple Silicon Macs still reports "Intel Mac OS X" in the
# UA string for compatibility (Rosetta-era holdover Chrome kept) — this is
# NOT a bug, it's accurate to real Mac browsers even with an M-series chip.
MACOS_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
MACOS_PLATFORM = "MacIntel"
MACOS_FONTS = ["Helvetica Neue", "Arial", "Times New Roman", "SF Pro", "Menlo", "Courier New"]
MACOS_GPUS = [
    {"label": "Apple M1", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)"},
    {"label": "Apple M1 Pro", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M1 Pro, Unspecified Version)"},
    {"label": "Apple M1 Max", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M1 Max, Unspecified Version)"},
    {"label": "Apple M2", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)"},
    {"label": "Apple M2 Pro", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M2 Pro, Unspecified Version)"},
    {"label": "Apple M2 Max", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M2 Max, Unspecified Version)"},
    {"label": "Apple M3", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)"},
    {"label": "Apple M3 Pro", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Pro, Unspecified Version)"},
    {"label": "Apple M3 Max", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Max, Unspecified Version)"},
    {"label": "Apple M4", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)"},
    {"label": "Apple M4 Pro", "vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M4 Pro, Unspecified Version)"},
]

# ============================================================
# Android — real Chromium, structurally sound to spoof
# ============================================================
ANDROID_FONTS = ["Roboto", "Noto Sans", "Droid Sans", "Droid Sans Mono", "Noto Color Emoji"]
ANDROID_PLATFORM = "Linux armv8l"

def _android_ua(model: str, android_ver: str) -> str:
    return (f"Mozilla/5.0 (Linux; Android {android_ver}; {model}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36")

ANDROID_PHONES = [
    {"label": "Google Pixel 6", "ua": _android_ua("Pixel 6", "14"), "gpu_vendor": "Qualcomm", "gpu_renderer": "ANGLE (Qualcomm, Adreno (TM) 660, OpenGL ES 3.2)", "viewport": {"width": 412, "height": 915}, "hardware_concurrency": 8, "device_memory": 8, "device_scale_factor": 2.625},
    {"label": "Google Pixel 7", "ua": _android_ua("Pixel 7", "14"), "gpu_vendor": "Qualcomm", "gpu_renderer": "ANGLE (Qualcomm, Adreno (TM) 730, OpenGL ES 3.2)", "viewport": {"width": 412, "height": 915}, "hardware_concurrency": 8, "device_memory": 8, "device_scale_factor": 2.625},
    {"label": "Google Pixel 8 Pro", "ua": _android_ua("Pixel 8 Pro", "14"), "gpu_vendor": "Google", "gpu_renderer": "ANGLE (Google, Mali-G715-Immortalis MC10, OpenGL ES 3.2)", "viewport": {"width": 448, "height": 998}, "hardware_concurrency": 9, "device_memory": 12, "device_scale_factor": 3.0},
    {"label": "Samsung Galaxy S22", "ua": _android_ua("SM-S901B", "13"), "gpu_vendor": "Qualcomm", "gpu_renderer": "ANGLE (Qualcomm, Adreno (TM) 730, OpenGL ES 3.2)", "viewport": {"width": 360, "height": 780}, "hardware_concurrency": 8, "device_memory": 8, "device_scale_factor": 3.0},
    {"label": "Samsung Galaxy S23", "ua": _android_ua("SM-S911B", "14"), "gpu_vendor": "Qualcomm", "gpu_renderer": "ANGLE (Qualcomm, Adreno (TM) 740, OpenGL ES 3.2)", "viewport": {"width": 360, "height": 780}, "hardware_concurrency": 8, "device_memory": 8, "device_scale_factor": 3.0},
    {"label": "Samsung Galaxy S24 Ultra", "ua": _android_ua("SM-S928B", "14"), "gpu_vendor": "Qualcomm", "gpu_renderer": "ANGLE (Qualcomm, Adreno (TM) 750, OpenGL ES 3.2)", "viewport": {"width": 412, "height": 883}, "hardware_concurrency": 8, "device_memory": 12, "device_scale_factor": 3.5},
    {"label": "Samsung Galaxy A54", "ua": _android_ua("SM-A546B", "14"), "gpu_vendor": "ARM", "gpu_renderer": "ANGLE (ARM, Mali-G68 MC4, OpenGL ES 3.2)", "viewport": {"width": 393, "height": 851}, "hardware_concurrency": 8, "device_memory": 6, "device_scale_factor": 2.75},
    {"label": "OnePlus 11", "ua": _android_ua("CPH2449", "14"), "gpu_vendor": "Qualcomm", "gpu_renderer": "ANGLE (Qualcomm, Adreno (TM) 740, OpenGL ES 3.2)", "viewport": {"width": 412, "height": 919}, "hardware_concurrency": 8, "device_memory": 16, "device_scale_factor": 3.0},
    {"label": "Xiaomi 13", "ua": _android_ua("2211133C", "14"), "gpu_vendor": "Qualcomm", "gpu_renderer": "ANGLE (Qualcomm, Adreno (TM) 740, OpenGL ES 3.2)", "viewport": {"width": 412, "height": 915}, "hardware_concurrency": 8, "device_memory": 8, "device_scale_factor": 2.875},
    {"label": "Motorola Edge 40", "ua": _android_ua("motorola edge 40", "13"), "gpu_vendor": "MediaTek", "gpu_renderer": "ANGLE (ARM, Mali-G68 MC4, OpenGL ES 3.2)", "viewport": {"width": 412, "height": 919}, "hardware_concurrency": 8, "device_memory": 8, "device_scale_factor": 2.625},
]

ANDROID_TABLETS = [
    {"label": "Samsung Galaxy Tab S8", "ua": _android_ua("SM-X706B", "13"), "gpu_vendor": "Qualcomm", "gpu_renderer": "ANGLE (Qualcomm, Adreno (TM) 730, OpenGL ES 3.2)", "viewport": {"width": 800, "height": 1280}, "hardware_concurrency": 8, "device_memory": 8, "device_scale_factor": 2.0},
    {"label": "Samsung Galaxy Tab S9", "ua": _android_ua("SM-X710", "14"), "gpu_vendor": "Qualcomm", "gpu_renderer": "ANGLE (Qualcomm, Adreno (TM) 740, OpenGL ES 3.2)", "viewport": {"width": 800, "height": 1280}, "hardware_concurrency": 8, "device_memory": 8, "device_scale_factor": 2.0},
    {"label": "Lenovo Tab P11", "ua": _android_ua("Lenovo TB350FU", "13"), "gpu_vendor": "MediaTek", "gpu_renderer": "ANGLE (ARM, Mali-G57 MC3, OpenGL ES 3.2)", "viewport": {"width": 800, "height": 1266}, "hardware_concurrency": 8, "device_memory": 6, "device_scale_factor": 1.5},
]

# ============================================================
# iOS — see the module-level caveat docstring: weaker spoof, Chrome on
# real iOS is WebKit-based, not Chromium, so this is an inherent mismatch
# no matter what values are chosen.
# ============================================================
IOS_FONTS = ["Helvetica Neue", "San Francisco", "Times New Roman", "Courier New", "Arial"]
IOS_PLATFORM = "iPhone"

def _ios_ua(device: str, ios_ver: str) -> str:
    # Real iOS Chrome UA uses "CriOS" and is WebKit under the hood — this
    # string looks the part but the engine actually running (Chromium) is
    # not what a real device with this UA would be running.
    return (f"Mozilla/5.0 ({device}; CPU iPhone OS {ios_ver} like Mac OS X) "
            f"AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/128.0.0.0 Mobile/15E148 Safari/604.1")

IOS_PHONES = [
    {"label": "iPhone 13 (weak spoof)", "ua": _ios_ua("iPhone14,5", "17_5"), "gpu_vendor": "Apple", "gpu_renderer": "ANGLE (Apple, Apple A15 GPU, OpenGL ES 3.2)", "viewport": {"width": 390, "height": 844}, "hardware_concurrency": 6, "device_memory": 4, "device_scale_factor": 3.0},
    {"label": "iPhone 14 (weak spoof)", "ua": _ios_ua("iPhone14,7", "17_5"), "gpu_vendor": "Apple", "gpu_renderer": "ANGLE (Apple, Apple A15 GPU, OpenGL ES 3.2)", "viewport": {"width": 390, "height": 844}, "hardware_concurrency": 6, "device_memory": 6, "device_scale_factor": 3.0},
    {"label": "iPhone 15 (weak spoof)", "ua": _ios_ua("iPhone15,4", "17_5"), "gpu_vendor": "Apple", "gpu_renderer": "ANGLE (Apple, Apple A16 GPU, OpenGL ES 3.2)", "viewport": {"width": 393, "height": 852}, "hardware_concurrency": 6, "device_memory": 6, "device_scale_factor": 3.0},
    {"label": "iPhone 15 Pro (weak spoof)", "ua": _ios_ua("iPhone16,1", "17_5"), "gpu_vendor": "Apple", "gpu_renderer": "ANGLE (Apple, Apple A17 Pro GPU, OpenGL ES 3.2)", "viewport": {"width": 393, "height": 852}, "hardware_concurrency": 6, "device_memory": 8, "device_scale_factor": 3.0},
]

IOS_TABLETS = [
    {"label": "iPad Air (weak spoof)", "ua": _ios_ua("iPad13,16", "17_5"), "gpu_vendor": "Apple", "gpu_renderer": "ANGLE (Apple, Apple M1 GPU, OpenGL ES 3.2)", "viewport": {"width": 820, "height": 1180}, "hardware_concurrency": 8, "device_memory": 8, "device_scale_factor": 2.0},
    {"label": "iPad Pro 12.9 (weak spoof)", "ua": _ios_ua("iPad14,5", "17_5"), "gpu_vendor": "Apple", "gpu_renderer": "ANGLE (Apple, Apple M2 GPU, OpenGL ES 3.2)", "viewport": {"width": 1024, "height": 1366}, "hardware_concurrency": 8, "device_memory": 16, "device_scale_factor": 2.0},
]

# ============================================================
# Platform registry — single source both generators/GUI iterate over
# ============================================================
PLATFORMS = {
    "windows": {"label": "Windows", "kind": "desktop", "ua": WINDOWS_UA, "platform": WINDOWS_PLATFORM, "fonts": WINDOWS_FONTS, "gpus": WINDOWS_GPUS, "device_classes": ["desktop", "laptop"]},
    "macos": {"label": "macOS", "kind": "desktop", "ua": MACOS_UA, "platform": MACOS_PLATFORM, "fonts": MACOS_FONTS, "gpus": MACOS_GPUS, "device_classes": ["desktop", "laptop"]},
    "android": {"label": "Android", "kind": "mobile", "platform": ANDROID_PLATFORM, "fonts": ANDROID_FONTS, "device_classes": ["phone", "tablet"], "devices": {"phone": ANDROID_PHONES, "tablet": ANDROID_TABLETS}},
    "ios": {"label": "iOS (weak spoof — see caveat)", "kind": "mobile", "platform": IOS_PLATFORM, "fonts": IOS_FONTS, "device_classes": ["phone", "tablet"], "devices": {"phone": IOS_PHONES, "tablet": IOS_TABLETS}},
}

# --- Device classes for desktop-kind platforms (cartesian: any GPU + any
# hardware/screen combo is plausible on a real PC) ---
DEVICE_CLASSES = {
    "desktop": {
        "label": "Desktop",
        "hardware_concurrency": [8, 12, 16],
        "device_memory": [16, 32],
        "viewport": [(1920, 1080), (2560, 1440), (1920, 1200)],
    },
    "laptop": {
        "label": "Laptop",
        "hardware_concurrency": [4, 6, 8],
        "device_memory": [8, 16],
        "viewport": [(1366, 768), (1440, 900), (1536, 864), (1920, 1080)],
    },
}


def hardware_options(device_class: str):
    """Every (cores, ram, viewport) combo for a desktop-kind device class —
    used to populate the GUI's 'Hardware' dropdown for Windows/macOS."""
    cls = DEVICE_CLASSES[device_class]
    options = []
    for cores in cls["hardware_concurrency"]:
        for ram in cls["device_memory"]:
            for width, height in cls["viewport"]:
                options.append({
                    "hardware_concurrency": cores,
                    "device_memory": ram,
                    "viewport": {"width": width, "height": height},
                    "label": f"{cores} cores · {ram}GB RAM · {width}×{height}",
                })
    return options


# ============================================================
# Locale pool (timezone/locale/geolocation must stay together)
# ============================================================
# NOT matched to any proxy automatically — after generating, align each
# profile's timezone/locale with wherever its assigned proxy actually
# exits, same as you'd check manually with a single profile.
LOCALES = [
    {"label": "Melbourne, AU", "locale": "en-AU", "timezone_id": "Australia/Melbourne", "geolocation": {"latitude": -37.8136, "longitude": 144.9631}},
    {"label": "Sydney, AU", "locale": "en-AU", "timezone_id": "Australia/Sydney", "geolocation": {"latitude": -33.8688, "longitude": 151.2093}},
    {"label": "Brisbane, AU", "locale": "en-AU", "timezone_id": "Australia/Brisbane", "geolocation": {"latitude": -27.4698, "longitude": 153.0251}},
    {"label": "Perth, AU", "locale": "en-AU", "timezone_id": "Australia/Perth", "geolocation": {"latitude": -31.9505, "longitude": 115.8605}},
    {"label": "Adelaide, AU", "locale": "en-AU", "timezone_id": "Australia/Adelaide", "geolocation": {"latitude": -34.9285, "longitude": 138.6007}},
    {"label": "Canberra, AU", "locale": "en-AU", "timezone_id": "Australia/Sydney", "geolocation": {"latitude": -35.2809, "longitude": 149.1300}},
    {"label": "Hobart, AU", "locale": "en-AU", "timezone_id": "Australia/Hobart", "geolocation": {"latitude": -42.8821, "longitude": 147.3272}},
    {"label": "Auckland, NZ", "locale": "en-NZ", "timezone_id": "Pacific/Auckland", "geolocation": {"latitude": -36.8485, "longitude": 174.7633}},
    {"label": "Wellington, NZ", "locale": "en-NZ", "timezone_id": "Pacific/Auckland", "geolocation": {"latitude": -41.2865, "longitude": 174.7762}},
    {"label": "London, UK", "locale": "en-GB", "timezone_id": "Europe/London", "geolocation": {"latitude": 51.5074, "longitude": -0.1278}},
    {"label": "Manchester, UK", "locale": "en-GB", "timezone_id": "Europe/London", "geolocation": {"latitude": 53.4808, "longitude": -2.2426}},
    {"label": "Edinburgh, UK", "locale": "en-GB", "timezone_id": "Europe/London", "geolocation": {"latitude": 55.9533, "longitude": -3.1883}},
    {"label": "Dublin, IE", "locale": "en-IE", "timezone_id": "Europe/Dublin", "geolocation": {"latitude": 53.3498, "longitude": -6.2603}},
    {"label": "Berlin, DE", "locale": "de-DE", "timezone_id": "Europe/Berlin", "geolocation": {"latitude": 52.5200, "longitude": 13.4050}},
    {"label": "Paris, FR", "locale": "fr-FR", "timezone_id": "Europe/Paris", "geolocation": {"latitude": 48.8566, "longitude": 2.3522}},
    {"label": "Amsterdam, NL", "locale": "nl-NL", "timezone_id": "Europe/Amsterdam", "geolocation": {"latitude": 52.3676, "longitude": 4.9041}},
    {"label": "Madrid, ES", "locale": "es-ES", "timezone_id": "Europe/Madrid", "geolocation": {"latitude": 40.4168, "longitude": -3.7038}},
    {"label": "Rome, IT", "locale": "it-IT", "timezone_id": "Europe/Rome", "geolocation": {"latitude": 41.9028, "longitude": 12.4964}},
    {"label": "New York, US", "locale": "en-US", "timezone_id": "America/New_York", "geolocation": {"latitude": 40.7128, "longitude": -74.0060}},
    {"label": "Los Angeles, US", "locale": "en-US", "timezone_id": "America/Los_Angeles", "geolocation": {"latitude": 34.0522, "longitude": -118.2437}},
    {"label": "Chicago, US", "locale": "en-US", "timezone_id": "America/Chicago", "geolocation": {"latitude": 41.8781, "longitude": -87.6298}},
    {"label": "Miami, US", "locale": "en-US", "timezone_id": "America/New_York", "geolocation": {"latitude": 25.7617, "longitude": -80.1918}},
    {"label": "Seattle, US", "locale": "en-US", "timezone_id": "America/Los_Angeles", "geolocation": {"latitude": 47.6062, "longitude": -122.3321}},
    {"label": "Dallas, US", "locale": "en-US", "timezone_id": "America/Chicago", "geolocation": {"latitude": 32.7767, "longitude": -96.7970}},
    {"label": "Denver, US", "locale": "en-US", "timezone_id": "America/Denver", "geolocation": {"latitude": 39.7392, "longitude": -104.9903}},
    {"label": "Toronto, CA", "locale": "en-CA", "timezone_id": "America/Toronto", "geolocation": {"latitude": 43.6532, "longitude": -79.3832}},
    {"label": "Vancouver, CA", "locale": "en-CA", "timezone_id": "America/Vancouver", "geolocation": {"latitude": 49.2827, "longitude": -123.1207}},
    {"label": "Singapore, SG", "locale": "en-SG", "timezone_id": "Asia/Singapore", "geolocation": {"latitude": 1.3521, "longitude": 103.8198}},
    {"label": "Tokyo, JP", "locale": "ja-JP", "timezone_id": "Asia/Tokyo", "geolocation": {"latitude": 35.6762, "longitude": 139.6503}},
    {"label": "Hong Kong, HK", "locale": "en-HK", "timezone_id": "Asia/Hong_Kong", "geolocation": {"latitude": 22.3193, "longitude": 114.1694}},
    {"label": "Seoul, KR", "locale": "ko-KR", "timezone_id": "Asia/Seoul", "geolocation": {"latitude": 37.5665, "longitude": 126.9780}},
    {"label": "Mumbai, IN", "locale": "en-IN", "timezone_id": "Asia/Kolkata", "geolocation": {"latitude": 19.0760, "longitude": 72.8777}},
    {"label": "Dubai, AE", "locale": "en-AE", "timezone_id": "Asia/Dubai", "geolocation": {"latitude": 25.2048, "longitude": 55.2708}},
    {"label": "Johannesburg, ZA", "locale": "en-ZA", "timezone_id": "Africa/Johannesburg", "geolocation": {"latitude": -26.2041, "longitude": 28.0473}},
]
