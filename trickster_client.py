"""
Trickster local API client - the same shape as ixBrowser's Python client, so scripts
written for ixBrowser are easy to move over.

    from trickster_client import TricksterClient
    with TricksterClient(token="paste it from the app's API panel") as c:
        info = c.open_profile(14)          # -> {"debugging_address": "127.0.0.1:51234", "ws": ...}
        if info is None:
            print(c.code, c.message)       # failures return None, details here
        c.close_profile(14)

Every method returns the data on success (True when there is none) and None on failure
(then c.code / c.message say why). The token also reads from TRICKSTER_API_TOKEN.
Default address: http://127.0.0.1:53200/api/v2/  (change the port in the app's API panel).
"""
import json
import os
import urllib.error
import urllib.request


class TricksterClient:
    def __init__(self, target="127.0.0.1", port=53200, token=None, timeout=120):
        self.base = f"http://{target}:{port}/api/v2/"
        self.token = token or os.environ.get("TRICKSTER_API_TOKEN", "")
        self.timeout = timeout
        self.code = 0
        self.message = ""
        self.total = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def close(self):
        pass

    # ---- plumbing ----
    def _call(self, action, **body):
        body = {k: v for k, v in body.items() if v is not None}
        req = urllib.request.Request(self.base + action, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode())
            except Exception:  # noqa: BLE001
                payload = {"error": {"code": e.code, "message": str(e)}}
        except Exception as e:  # noqa: BLE001
            self.code, self.message = -1, f"couldn't reach Trickster: {e}"
            return None
        err = payload.get("error")
        if err:
            self.code, self.message = err.get("code", -1), err.get("message", "")
            return None
        self.code, self.message = 0, ""
        data = payload.get("data")
        return True if data is None else data

    def _list(self, action, **body):
        data = self._call(action, **body)
        if isinstance(data, dict) and "list" in data:
            self.total = data.get("total", len(data["list"]))
            return data["list"]
        return data

    # ---- profiles ----
    def ping(self): return self._call("ping")
    def get_profile_list(self, name=None, group=None, page=1, limit=50): return self._list("profile-list", name=name, group=group, page=page, limit=limit)
    def get_opened_profile_list(self): return self._list("profile-opened-list")
    def get_native_opened_profile_list(self): return self._list("native-client-profile-opened-list")
    def open_profile(self, profile_id, url=None, headless=False): return self._call("profile-open", profile_id=profile_id, url=url, headless=headless)
    def open_profile_with_random_fingerprint(self, profile_id, url=None): return self._call("profile-open-with-random-fingerprint", profile_id=profile_id, url=url)
    def open_profiles_in_batches(self, profiles, headless=False): return self._call("profile-open-batch", profiles=profiles, headless=headless)
    def close_profile(self, profile_id): return self._call("profile-close", profile_id=profile_id)
    def close_profile_in_batches(self, profile_id): return self._call("profile-close-in-batches", profile_id=profile_id)
    def close_all_profiles(self): return self._call("profile-close-all")
    def reset_profile_open_state(self, profile_id): return self._call("profile-open-state-reset", profile_id=profile_id)
    def arrange_tile_opened_profile(self, columns=None): return self._call("profile-opened-list-arrange-tile", columns=columns)
    def create_profile(self, count=1, group=None, url=None): return self._call("profile-create", count=count, group=group, url=url)
    def create_profile_by_copying(self, profile_id, count=1): return self._call("profile-copy", profile_id=profile_id, count=count)
    def update_profile(self, profile_id, **fields): return self._call("profile-update", profile_id=profile_id, **fields)
    def delete_profile(self, profile_id): return self._call("profile-delete", profile_id=profile_id)
    def empty_recycle_bin(self): return self._call("empty-recycle-bin")
    def random_profile_fingerprint(self, profile_id): return self._call("profile-random-fingerprint-configuration", profile_id=profile_id)
    def update_profile_groups_in_batches(self, profile_id, group): return self._call("profile-update-groups-in-batches", profile_id=profile_id, group=group)
    def get_profile_cookie(self, profile_id): return self._call("profile-get-cookies", profile_id=profile_id)
    def update_profile_cookie(self, profile_id, cookie): return self._call("profile-update-cookies", profile_id=profile_id, cookie=cookie)
    def clear_profile_cache(self, profile_id): return self._call("profile-clear-cache", profile_id=profile_id)
    def clear_profile_cache_and_cookies(self, profile_id): return self._call("profile-clear-cache-and-cookies", profile_id=profile_id)
    def clear_profile_cache_keep_extensions(self, profile_id): return self._call("profile-clear-cache-keep-extensions", profile_id=profile_id)
    def clear_profile_saved_user_password(self, profile_id): return self._call("profile-clear-saved-user-password", profile_id=profile_id)

    # ---- proxies ----
    def update_profile_to_custom_proxy_mode(self, profile_id, proxy): return self._call("profile-update-proxy", profile_id=profile_id, proxy=proxy)
    def bulk_assign_proxies(self, text): return self._call("proxy-bulk-assign", text=text)

    # ---- groups ----
    def get_group_list(self): return self._list("group-list")
    def create_group(self, name): return self._call("group-create", name=name)
    def update_group(self, group, name): return self._call("group-update", group=group, name=name)
    def delete_group(self, group): return self._call("group-delete", group=group)
