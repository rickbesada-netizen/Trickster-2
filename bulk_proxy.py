"""
Pure parsing/matching logic behind the GUI's "Bulk assign proxies" box.

Kept out of gui/app.py (no pywebview / GUI imports) so it can be unit tested
on its own - see tests/test_bulk_proxy.py.

What was going wrong before:
  * The "NO." column in the profile list is the row position (1, 2, 3 ... in
    the same sorted order as the table), but bulk assign matched a bare
    number against the number inside the filename (profile_014_...). Those
    are different numbers: row 14 is not profile_014. So "14,..." landed on
    the wrong profile (or none). A bare number now means the NO. you see.
  * A line whose target matched nothing used to fall through to the
    round-robin pool and save a garbage proxy (server "http://14") onto
    every other profile. Now it is reported and skipped.

Line formats (freely mixable):

  Targeted - "<target>, <proxy>" (a comma, tab or space after the target):
      14,isp.decodo.com:10001:user:pass         the profile in row NO. 14
      no14,...                                  same
      14-16,isp.decodo.com:10001:user:pass      rows 14, 15 and 16, same proxy
      profile_014,host:port:user:pass           every profile whose FILENAME
                                                number is 14 (all variants)
      profile_014_windows_desktop,...           that exact profile (.json ok)

  Round-robin - just a proxy, spread over every profile not targeted above.

  A proxy can be written as any of:
      host:port:user:pass          (Decodo etc. export format)
      user:pass@host:port
      http://host:port,user,pass   (server,user,pass)
      http://user:pass@host:port
      host:port                    (no auth)
  with an optional scheme (http, https, socks5, socks5h, socks4).
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.\-]*)://", re.I)
ALLOWED_SCHEMES = {"http", "https", "socks4", "socks5", "socks5h"}

# A leading target, followed by a comma / tab / whitespace and then the proxy:
#   14   no14   no.14   14-16        -> row NO. (what the table shows)
#   profile_014   profile_014_windows_desktop[.json]   -> by filename
LINE_TARGET_RE = re.compile(
    r"^\s*(?P<target>"
    r"profile_[A-Za-z0-9_\-]+(?:\.json)?"
    r"|(?:no\.?)?\d+(?:\s*-\s*\d+)?"
    r")\s*(?:,|\t|\s)\s*(?P<proxy>\S.*?)\s*$",
    re.I,
)


def mask(line: str) -> str:
    """Hides the password part of a proxy line for display in error messages."""
    line = re.sub(r"(://[^:/@\s,]+:)[^@\s,]+(@)", r"\1***\2", line)
    # host:port:user:pass  ->  host:port:user:***
    line = re.sub(r"((?:^|[,\s])[^:,\s]+:\d+:[^:,\s]+:)[^,\s]+", r"\1***", line)
    # server,user,pass -> server,user,***
    line = re.sub(r"(^|,)([^,]*,[^,]*,)[^,]+$", r"\1\2***", line)
    return line


def parse_proxy_string(s: str) -> Optional[Dict[str, str]]:
    """Returns {"server","username","password"} or None if it isn't a usable proxy."""
    s = (s or "").strip().strip('"').strip("'")
    if not s:
        return None

    scheme = "http"
    m = SCHEME_RE.match(s)
    if m:
        scheme = m.group(1).lower()
        if scheme not in ALLOWED_SCHEMES:
            return None
        s = s[m.end():]

    username = password = ""
    host_port = ""

    if "," in s:
        # server,username,password   (server may be host:port or user:pass@host:port)
        parts = [p.strip() for p in s.split(",")]
        if len(parts) > 3:
            return None
        host_port = parts[0]
        username = parts[1] if len(parts) > 1 else ""
        password = parts[2] if len(parts) > 2 else ""
    elif "@" in s:
        creds, _, host_port = s.rpartition("@")
        username, _, password = creds.partition(":")
    else:
        pieces = s.split(":")
        if len(pieces) == 2:
            host_port = s
        elif len(pieces) >= 4:
            # host:port:username:password (password may itself contain ':')
            host_port = pieces[0] + ":" + pieces[1]
            username = pieces[2]
            password = ":".join(pieces[3:])
        else:
            return None

    if "@" in host_port:  # user:pass@host:port inside the server part
        creds, _, host_port = host_port.rpartition("@")
        u, _, p = creds.partition(":")
        username = username or u
        password = password or p

    host, sep, port = host_port.rpartition(":")
    if not sep or not host or not port.isdigit() or not (0 < int(port) < 65536):
        return None
    if re.search(r"[\s/]", host):
        return None

    return {"server": f"{scheme}://{host}:{int(port)}", "username": username, "password": password}


def _profile_number(stem: str) -> Optional[int]:
    m = re.match(r"profile_(\d+)_", stem, re.I)
    return int(m.group(1)) if m else None


def resolve_target(target: str, profile_paths: List[Path]) -> Tuple[List[Path], Optional[str]]:
    """Every profile file a target refers to, plus an explanation if none.

    profile_paths MUST be in the same order as the table (so row NO. n is
    profile_paths[n-1])."""
    t = target.strip()
    if t.lower().endswith(".json"):
        t = t[:-5]
    tl = t.lower()

    # Exact profile name ("profile_014_windows_desktop").
    exact = [p for p in profile_paths if p.stem.lower() == tl]
    if exact:
        return exact, None

    # By filename number: "profile_014" or "profile_014_windows" (prefix).
    if tl.startswith("profile_"):
        m = re.fullmatch(r"profile_(\d+)(?:_(.+))?", tl)
        if m:
            n, rest = int(m.group(1)), m.group(2)
            hits = []
            for p in profile_paths:
                if _profile_number(p.stem) != n:
                    continue
                suffix = re.sub(r"^profile_\d+_", "", p.stem, flags=re.I).lower()
                if rest is None or suffix == rest or suffix.startswith(rest + "_"):
                    hits.append(p)
            if hits:
                return hits, None
        return [], f"no profile named '{target}'"

    # Row NO.: "14", "no14", "no.14", or a range "14-16".
    m = re.fullmatch(r"(?:no\.?)?(\d+)(?:\s*-\s*(\d+))?", tl)
    if m:
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if lo > hi:
            lo, hi = hi, lo
        total = len(profile_paths)
        if lo < 1 or hi > total:
            return [], f"NO. {lo if lo < 1 or lo > total else hi} doesn't exist (the list has {total} profiles)"
        return profile_paths[lo - 1:hi], None

    return [], f"no profile matches '{target}'"


def plan_bulk_assign(text: str, profile_paths: List[Path]):
    """Works out what would be written (profile_paths in table order: row NO. n = profile_paths[n-1]), without touching any files.

    Returns (targeted, round_robin_pool, errors) where
      targeted         = {Path: proxy_dict}   (later lines win on conflicts)
      round_robin_pool = [proxy_dict, ...]
      errors           = [(line_number, masked_line, reason), ...]
    """
    targeted: Dict[Path, Dict[str, str]] = {}
    pool: List[Dict[str, str]] = []
    errors: List[Tuple[int, str, str]] = []

    text = (text or "").lstrip("﻿").strip()

    if text.startswith("["):
        try:
            items = json.loads(text)
        except json.JSONDecodeError as e:
            return {}, [], [(0, "(JSON list)", f"invalid JSON: {e}")]
        for i, item in enumerate(items, 1):
            if isinstance(item, dict) and item.get("server"):
                proxy = parse_proxy_string(item["server"])
                if proxy:
                    proxy["username"] = item.get("username", proxy["username"]) or ""
                    proxy["password"] = item.get("password", proxy["password"]) or ""
                    pool.append(proxy)
                    continue
            elif isinstance(item, str):
                proxy = parse_proxy_string(item)
                if proxy:
                    pool.append(proxy)
                    continue
            errors.append((i, "(JSON item)", "not a usable proxy"))
        return {}, pool, errors

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().strip("﻿")
        if not line or line.startswith("#"):
            continue

        m = LINE_TARGET_RE.match(line)
        if m:
            target, proxy_part = m.group("target"), m.group("proxy")
            proxy = parse_proxy_string(proxy_part)
            if proxy is None:
                errors.append((lineno, mask(line), "couldn't read the proxy part (expected host:port:user:pass or server,user,pass)"))
                continue
            matches, why = resolve_target(target, profile_paths)
            if not matches:
                errors.append((lineno, mask(line), why or f"no profile matches '{target}'"))
                continue
            for p in matches:
                targeted[p] = proxy
            continue

        proxy = parse_proxy_string(line)
        if proxy is None:
            errors.append((lineno, mask(line), "not a recognisable proxy"))
            continue
        pool.append(proxy)

    return targeted, pool, errors


def resolve_many(text: str, profile_paths: List[Path]) -> Tuple[List[Path], List[str]]:
    """For "open these" boxes: "14", "3-8", "1, 5, 20-25", names, mixed.
    Separators: comma, semicolon, whitespace. Returns (paths in the order
    given, de-duplicated; human-readable problems)."""
    paths: List[Path] = []
    problems: List[str] = []
    for token in re.split(r"[,;\s]+", (text or "").strip()):
        if not token:
            continue
        found, why = resolve_target(token, profile_paths)
        if not found:
            problems.append(why or f"no profile matches '{token}'")
            continue
        for p in found:
            if p not in paths:
                paths.append(p)
    return paths, problems
