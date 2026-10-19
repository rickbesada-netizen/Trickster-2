"""
Supabase cloud sync for the antidetect browser starter.

Local JSON files in profiles/ stay the source of truth for actually
launching a profile (launcher.py is untouched). This module is a bridge:
"pull" downloads your org's profiles from Supabase and writes them as local
JSON files; "push" uploads local JSON files up to Supabase. Config sync
(push_profiles/pull_profiles) is manual by design — nothing there runs
automatically or silently overwrites files.

Session sync (push_session/pull_session) is different: automatic, by
design, so a login on one device is there the next time that profile
launches on any device signed into the same org — see the comment above
those methods for what's actually synced and why, and the Storage bucket
that needs to exist first.

Setup (one-time):
    1. Run supabase/schema.sql in your Supabase project's SQL Editor.
    2. Copy gui/cloud_config.example.json to gui/cloud_config.json and fill
       in your project's URL and anon key (Supabase Dashboard -> Project
       Settings -> API).
    3. pip install supabase
    4. For session sync: create a private Storage bucket named
       "profile-sessions" (Dashboard -> Storage -> New bucket).
"""

import json
import platform
import random
import time
import uuid
import string
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx
from supabase import create_client, Client, ClientOptions

SESSION_BUCKET = "profile-sessions"
MACHINE_MARKER = ".trickster_machine"


def machine_id() -> str:
    """Identifies THIS computer (and Windows/Mac user). Chromium encrypts cookies
    and saved passwords with a key that only exists on the computer + Windows
    account that made them, so the raw profile files from another computer
    cannot be read here."""
    try:
        user = Path.home().name
    except Exception:
        user = ""
    return f"{platform.system()}|{platform.node()}|{uuid.getnode()}|{user}"

# Folders directly under a profile's Default/ dir that are safe to skip
# when syncing session data — regenerable caches, never session/login
# state. See push_session/pull_session below for why this is an
# exclude-list rather than naming the exact files that matter.
_SESSION_EXCLUDE_DIRS = {
    "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnWebGPUCache",
    "GrShaderCache", "ShaderCache", "blob_storage",
}


def _zip_session_dir(default_dir: Path, zip_path: Path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in default_dir.rglob("*"):
            if item.is_dir():
                continue
            rel = item.relative_to(default_dir)
            if rel.parts and rel.parts[0] in _SESSION_EXCLUDE_DIRS:
                continue
            try:
                zf.write(item, rel)
            except (OSError, PermissionError):
                continue  # e.g. a file still locked by Chromium at the instant of zipping — skip it, not fatal

# Same reasoning as launcher.py/app.py: the bundled default cloud_config.json
# lives in the (ephemeral, temp-extracted) resource dir once frozen, but
# session tokens must persist across runs, so they go next to the .exe
# instead. CONFIG_PATH checks beside the exe FIRST (lets someone override
# the bundled default by dropping their own file there) and falls back to
# the bundled one, so it works out of the box either way.
if getattr(sys, "frozen", False):
    _RESOURCE_DIR = Path(sys._MEIPASS) / "gui"
    _WRITABLE_DIR = Path(sys.executable).parent
else:
    _RESOURCE_DIR = Path(__file__).parent
    _WRITABLE_DIR = Path(__file__).parent

_writable_config = _WRITABLE_DIR / "cloud_config.json"
CONFIG_PATH = _writable_config if _writable_config.exists() else _RESOURCE_DIR / "cloud_config.json"
SESSION_PATH = _WRITABLE_DIR / ".cloud_session.json"  # gitignored in dev — local only either way


class CloudSync:
    def __init__(self):
        self.client: Client | None = None
        self.user = None
        self.org_id = None
        self.role = None

    def _load_config(self):
        if not CONFIG_PATH.exists():
            raise RuntimeError(
                f"Missing {CONFIG_PATH.name} — copy cloud_config.example.json to "
                "cloud_config.json and fill in your Supabase URL + anon key."
            )
        return json.loads(CONFIG_PATH.read_text())

    def _get_client(self) -> Client:
        if self.client is None:
            print("[cloud] _get_client: loading config...", flush=True)
            config = self._load_config()
            print(f"[cloud] _get_client: config loaded, url={config.get('supabase_url')}", flush=True)
            # A hung/unreachable network call here used to be able to
            # freeze the entire app window indefinitely (pywebview blocks
            # its native message loop while an API call is in flight) —
            # the default timeout for these calls is 120 seconds, easily
            # long enough to look completely frozen. A short, explicit
            # timeout means a network problem fails fast with an error
            # message instead of hanging the whole app.
            options = ClientOptions(
                postgrest_client_timeout=10,
                storage_client_timeout=10,
                httpx_client=httpx.Client(timeout=10),
            )
            print("[cloud] _get_client: calling create_client...", flush=True)
            self.client = create_client(config["supabase_url"], config["supabase_anon_key"], options=options)
            print("[cloud] _get_client: create_client returned", flush=True)
        return self.client

    def sign_up(self, email: str, password: str):
        print("[cloud] sign_up: getting client...", flush=True)
        client = self._get_client()
        print("[cloud] sign_up: client ready, calling auth.sign_up...", flush=True)
        result = client.auth.sign_up({"email": email, "password": password})
        print("[cloud] sign_up: auth.sign_up returned", flush=True)
        return result

    def sign_in(self, email: str, password: str):
        print("[cloud] sign_in: getting client...", flush=True)
        client = self._get_client()
        print("[cloud] sign_in: client ready, calling auth.sign_in_with_password...", flush=True)
        result = client.auth.sign_in_with_password({"email": email, "password": password})
        print("[cloud] sign_in: auth call returned, loading org...", flush=True)
        self.user = result.user
        self._load_org_id()
        print("[cloud] sign_in: org loaded, saving session...", flush=True)
        self._save_session(result.session.access_token, result.session.refresh_token)
        print("[cloud] sign_in: done", flush=True)
        return result

    def try_restore_session(self) -> bool:
        """Called on app startup — if a session was saved from a previous
        run, restores it without needing email/password again. Returns
        True if restored successfully."""
        print("[cloud] try_restore_session: checking for saved session...", flush=True)
        if not SESSION_PATH.exists():
            print("[cloud] try_restore_session: no saved session file", flush=True)
            return False
        try:
            tokens = json.loads(SESSION_PATH.read_text())
            print("[cloud] try_restore_session: getting client...", flush=True)
            client = self._get_client()
            print("[cloud] try_restore_session: client ready, calling auth.set_session...", flush=True)
            result = client.auth.set_session(tokens["access_token"], tokens["refresh_token"])
            print("[cloud] try_restore_session: auth call returned, loading org...", flush=True)
            self.user = result.user
            self._load_org_id()
            # Refreshed tokens may differ from what we started with — save them back.
            self._save_session(result.session.access_token, result.session.refresh_token)
            print("[cloud] try_restore_session: done, restored successfully", flush=True)
            return True
        except Exception as e:
            print(f"[cloud] try_restore_session: failed with {type(e).__name__}: {e}", flush=True)
            # Saved session expired/invalid — fall back to requiring sign-in again.
            self.sign_out()
            return False

    def sign_out(self):
        self.user = None
        self.org_id = None
        self.role = None
        if SESSION_PATH.exists():
            SESSION_PATH.unlink()

    def _save_session(self, access_token: str, refresh_token: str):
        SESSION_PATH.write_text(json.dumps({
            "access_token": access_token,
            "refresh_token": refresh_token,
        }))

    def _load_org_id(self):
        client = self._get_client()
        print("[cloud] _load_org_id: querying memberships table...", flush=True)
        response = client.table("memberships").select("org_id, role").limit(1).execute()
        print("[cloud] _load_org_id: query returned", flush=True)
        if response.data:
            self.org_id = response.data[0]["org_id"]
            self.role = response.data[0]["role"]
        else:
            raise RuntimeError(
                "No organization found for this user — the signup trigger in "
                "schema.sql may not have run. Check Supabase logs."
            )

    def is_signed_in(self) -> bool:
        return self.user is not None and self.org_id is not None

    def pull_profiles(self, local_dir: Path) -> int:
        """Downloads every profile for the current org and writes each as a
        local JSON file (profiles/<profile_id>.json), overwriting any local
        file with the same name. Returns the number of profiles pulled."""
        if not self.is_signed_in():
            raise RuntimeError("Not signed in")

        client = self._get_client()
        response = client.table("browser_profiles").select("*").eq("org_id", self.org_id).execute()

        local_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for row in response.data:
            profile = dict(row["config"])
            profile["proxy"] = row["proxy"]
            profile["profile_id"] = row["profile_id"]
            out_path = local_dir / f"{row['profile_id']}.json"
            out_path.write_text(json.dumps(profile, indent=2))
            count += 1
        return count

    def push_profiles(self, local_dir: Path) -> int:
        """Uploads every local profile JSON file to Supabase, upserting by
        (org_id, profile_id) — an existing cloud row with the same
        profile_id gets overwritten with the local version. Returns the
        number of profiles pushed."""
        if not self.is_signed_in():
            raise RuntimeError("Not signed in")

        client = self._get_client()
        rows = []
        for path in sorted(local_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            profile_id = data.get("profile_id", path.stem)
            proxy = data.pop("proxy", {})
            rows.append({
                "org_id": self.org_id,
                "profile_id": profile_id,
                "config": data,
                "proxy": proxy,
            })

        if not rows:
            return 0

        client.table("browser_profiles").upsert(rows, on_conflict="org_id,profile_id").execute()
        return len(rows)

    # --- Session sync (cookies/logins, NOT config) ---
    #
    # push_profiles/pull_profiles above sync the small fingerprint config
    # JSON through a database table, and are manual by design (a Push/Pull
    # button). Session sync is a different kind of thing entirely — the
    # actual browser profile data (cookies, Local Storage, IndexedDB,
    # saved logins: whatever makes a site remember you're signed in) —
    # stored as a zip in Supabase Storage rather than the database, and
    # automatic: pulled right before a profile launches, pushed right
    # after it closes, so a login made on one device is there the next
    # time that profile opens on any device signed into the same org.
    #
    # Requires a Storage bucket named SESSION_BUCKET to exist in the
    # Supabase project already (Dashboard -> Storage -> New bucket,
    # private, not public) — this isn't created automatically from here,
    # same reason the schema.sql tables aren't: no code path can set up
    # infrastructure in a Supabase project it doesn't have dashboard
    # access to.
    #
    # Only Default/ (the actual per-profile data) is synced, never the
    # browser-wide folders alongside it (updater metadata, shared crash
    # reports — irrelevant to any specific profile's session). Within
    # Default/, _SESSION_EXCLUDE_DIRS is skipped: regenerable caches, not
    # session state, that would otherwise bloat every sync for no benefit.
    # Everything else under Default/ is included — an exclude-list rather
    # than naming exact files to keep (Cookies, Login Data, etc.)
    # deliberately, since exactly which files hold session state has
    # shifted between Chromium versions before (cookies moved into a
    # Network/ subfolder at one point) and likely will again.

    def push_session(self, profile_id: str, user_data_dir):
        """Best-effort: callers should treat a failure here as non-fatal —
        a profile closing successfully should never be blocked by a sync
        problem afterward."""
        if not self.is_signed_in():
            print(f"[cloud] push_session: skipped for {profile_id} — not signed in.")
            return
        user_data_dir = Path(user_data_dir)
        default_dir = user_data_dir / "Default"
        if not default_dir.exists():
            print(f"[cloud] push_session: skipped for {profile_id} — no Default/ dir at {default_dir} "
                  "(profile never actually launched/wrote any data yet?).")
            return
        try:
            client = self._get_client()
            # ignore_cleanup_errors=True: on Windows, something (commonly
            # antivirus/Defender briefly scanning a just-written zip, or a
            # file the previous Chromium process hadn't fully released
            # yet) can hold a transient lock on this temp file right as
            # Python tries to delete it — seen in testing as a
            # PermissionError traceback dumped at app shutdown, from
            # Python's own safety-net cleanup for temp dirs. The actual
            # upload above already completed by that point (success is
            # already logged before this cleanup runs) — this only
            # affects whether the leftover temp file gets deleted, not
            # whether the sync itself worked, so it's safe to just not
            # treat that failure as an error.
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                zip_path = Path(tmp) / f"{profile_id}.zip"
                _zip_session_dir(default_dir, zip_path)
                # Local State lives OUTSIDE Default/ (one level up, at the
                # root of user_data_dir) — easy to miss, but it holds the
                # encryption key Chrome's Local State/os_crypt uses to
                # decrypt saved passwords in Default/Login Data. Without
                # it, a restored profile shows the right account/email
                # (that part's unencrypted, stored elsewhere) but every
                # saved password silently fails to decrypt — confirmed by
                # testing: exactly that half-restored behavior. Appended
                # into the zip at its own top-level name, deliberately not
                # under "Default/", so it extracts back to the right place
                # (one level up from Default/) on restore.
                local_state = user_data_dir / "Local State"
                with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zf:
                    if local_state.exists():
                        zf.write(local_state, "Local State")
                    zf.writestr(MACHINE_MARKER, machine_id())
                size_kb = zip_path.stat().st_size / 1024
                storage_path = f"{self.org_id}/{profile_id}.zip"
                client.storage.from_(SESSION_BUCKET).upload(
                    storage_path, zip_path.read_bytes(),
                    {"content-type": "application/zip", "upsert": "true"},
                )
                print(f"[cloud] push_session: uploaded {profile_id} ({size_kb:.0f} KB) to {storage_path}")
        except Exception as e:
            print(f"[cloud] push_session: couldn't sync {profile_id}: {e}")

    def pull_session(self, profile_id: str, user_data_dir):
        """Best-effort: a profile with nothing saved in the cloud yet
        (normal for its very first launch anywhere) should still open
        normally — this silently does nothing in that case rather than
        raising, same as any other sync failure here."""
        if not self.is_signed_in():
            print(f"[cloud] pull_session: skipped for {profile_id} — not signed in.")
            return
        try:
            client = self._get_client()
            storage_path = f"{self.org_id}/{profile_id}.zip"
            data = client.storage.from_(SESSION_BUCKET).download(storage_path)
        except Exception as e:
            print(f"[cloud] pull_session: nothing to restore for {profile_id} "
                  f"(no cloud session yet, or unreachable): {e}")
            return  # nothing saved for this profile yet, or genuinely unreachable — either way, just launch fresh

        user_data_dir = Path(user_data_dir)
        default_dir = user_data_dir / "Default"
        try:
            default_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                zip_path = Path(tmp) / f"{profile_id}.zip"
                zip_path.write_bytes(data)
                # Extract member-by-member rather than extractall() — a
                # relaunch can happen moments after the previous Chromium
                # process closed, and Windows can still be holding a file
                # lock on something (Account Web Data etc.) for a brief
                # window after that. extractall() aborts the WHOLE restore
                # on the first such locked file; skipping just that one
                # file and continuing means everything else still gets
                # restored, and losing one still-transient file isn't as
                # bad as losing the entire session over it.
                skipped = []
                with zipfile.ZipFile(zip_path) as zf:
                    names = zf.namelist()
                    came_from = zf.read(MACHINE_MARKER).decode("utf-8", "replace") if MACHINE_MARKER in names else None
                    if came_from != machine_id():
                        # Saved on a different computer (or an older version that didn't
                        # record which). Its encrypted cookies/passwords can't be read
                        # here, and its "Local State" would overwrite this computer's own
                        # key and break what IS working. The logins travel separately
                        # (see pull_state/push_state), so leave this computer's own
                        # profile files alone.
                        print(f"[cloud] pull_session: {profile_id} was saved on another computer - "
                              "not copying its raw files here (logins come from the portable session instead).")
                        return
                    for member in names:
                        if member == MACHINE_MARKER:
                            continue
                        # "Local State" is stored at the zip's top level
                        # (see push_session) and belongs at the root of
                        # user_data_dir, one level up from Default/ —
                        # everything else in the zip is Default/'s own
                        # contents and extracts under default_dir as usual.
                        target_dir = user_data_dir if member == "Local State" else default_dir
                        try:
                            zf.extract(member, target_dir)
                        except OSError as e:
                            skipped.append(member)
                            print(f"[cloud] pull_session: skipped locked/unwritable file "
                                  f"{member} for {profile_id}: {e}")
                restored_note = f", skipped {len(skipped)} locked file(s)" if skipped else ""
                print(f"[cloud] pull_session: restored {profile_id} ({len(data) / 1024:.0f} KB) "
                      f"into {default_dir}{restored_note}")
        except (zipfile.BadZipFile, OSError) as e:
            print(f"[cloud] pull_session: couldn't restore {profile_id}: {e}")

    # --- Portable login session (works across computers) ---
    #
    # The raw profile folder above only works on the SAME computer. This part
    # saves the logins themselves (cookies) in plain form, taken from the live
    # browser at close, so another computer can load them into its own profile.

    def _state_path(self, profile_id: str) -> str:
        return f"{self.org_id}/{profile_id}.state.json"

    def push_state(self, profile_id: str, user_data_dir, state: dict):
        if not self.is_signed_in() or not state or not state.get("cookies"):
            return
        try:
            saved_at = time.time()
            payload = {"saved_at": saved_at, "machine": machine_id(), "cookies": state["cookies"]}
            client = self._get_client()
            client.storage.from_(SESSION_BUCKET).upload(
                self._state_path(profile_id), json.dumps(payload).encode("utf-8"),
                {"content-type": "application/json", "upsert": "true"},
            )
            Path(user_data_dir).mkdir(parents=True, exist_ok=True)
            (Path(user_data_dir) / ".trickster_synced_at").write_text(str(saved_at))
            print(f"[cloud] push_state: saved {len(state['cookies'])} cookies for {profile_id}")
        except Exception as e:
            print(f"[cloud] push_state: couldn't save logins for {profile_id}: {e}")

    def pull_state(self, profile_id: str, user_data_dir):
        """Returns the cookie list to load, or None when there's nothing newer
        than what this computer already has."""
        if not self.is_signed_in():
            return None
        try:
            data = self._get_client().storage.from_(SESSION_BUCKET).download(self._state_path(profile_id))
            payload = json.loads(data.decode("utf-8"))
        except Exception as e:
            print(f"[cloud] pull_state: nothing saved yet for {profile_id} ({e.__class__.__name__})")
            return None
        mine = 0.0
        try:
            mine = float((Path(user_data_dir) / ".trickster_synced_at").read_text())
        except Exception:
            pass
        if payload.get("saved_at", 0) <= mine:
            return None  # this computer already has the newest copy
        cookies = payload.get("cookies") or None
        if cookies:
            try:  # remember that we now have this version, so it isn't re-applied next time
                Path(user_data_dir).mkdir(parents=True, exist_ok=True)
                (Path(user_data_dir) / ".trickster_synced_at").write_text(str(payload["saved_at"]))
            except Exception:
                pass
        return cookies

    # --- Team management ---

    def list_members(self):
        """Every member of the current org, with email looked up from
        user_directory (two separate queries, not a PostgREST embed —
        memberships and user_directory both FK to auth.users but not to
        each other, so automatic relationship embedding doesn't apply)."""
        if not self.is_signed_in():
            raise RuntimeError("Not signed in")
        client = self._get_client()

        memberships = client.table("memberships").select("*").eq("org_id", self.org_id).execute().data
        user_ids = [m["user_id"] for m in memberships]
        directory = {}
        if user_ids:
            rows = client.table("user_directory").select("*").in_("id", user_ids).execute().data
            directory = {r["id"]: r["email"] for r in rows}

        return [
            {
                "user_id": m["user_id"],
                "email": directory.get(m["user_id"], "(unknown)"),
                "role": m["role"],
                "is_you": m["user_id"] == self.user.id,
            }
            for m in memberships
        ]

    def create_invite(self, role: str) -> str:
        """Creates an invite code for the given role ('admin' or 'staff')
        and returns it. Only owners/admins can do this — enforced by an
        RLS policy, not just app-layer logic, so this fails cleanly (raises)
        if the current user isn't permitted rather than silently no-op'ing."""
        if not self.is_signed_in():
            raise RuntimeError("Not signed in")
        client = self._get_client()
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        client.table("invites").insert({
            "org_id": self.org_id,
            "code": code,
            "role": role,
            "created_by": self.user.id,
        }).execute()
        return code

    def redeem_invite(self, code: str):
        """Joins the org an invite code belongs to, replacing whatever org
        the caller was previously in (see redeem_invite() in
        team_management.sql for exactly what that means and why)."""
        if self.user is None:
            raise RuntimeError("Not signed in")
        client = self._get_client()
        result = client.rpc("redeem_invite", {"invite_code": code}).execute()
        response = result.data
        if response.get("ok"):
            self._load_org_id()  # org changed — refresh cached org_id/role
        return response

    def update_member_role(self, user_id: str, role: str):
        if not self.is_signed_in():
            raise RuntimeError("Not signed in")
        client = self._get_client()
        client.table("memberships").update({"role": role}).eq("org_id", self.org_id).eq("user_id", user_id).execute()

    def remove_member(self, user_id: str):
        if not self.is_signed_in():
            raise RuntimeError("Not signed in")
        client = self._get_client()
        client.table("memberships").delete().eq("org_id", self.org_id).eq("user_id", user_id).execute()
