#!/usr/bin/env python3
"""
List BookStack users grouped & sorted by role.

Uses the SAME env-driven connection settings as the sync script:
  Required:
    BOOKSTACK_BASE_URL
    BOOKSTACK_TOKEN_ID
    BOOKSTACK_TOKEN_SECRET
  Optional:
    BOOKSTACK_INSECURE=1         (disable TLS verify & suppress warnings)
    BOOKSTACK_CA_CERT=/path/to/ca.pem
    OUTPUT=bookstack_users_by_role.csv
"""

import os
import sys
import csv
from typing import Dict, Any, List, Optional

# --- Optional .env support (same as your script) ---
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# --- Requests (same lib your script uses) ---
try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

def getenv_required(key: str) -> str:
    v = os.getenv(key)
    if not v:
        print(f"Missing required environment variable: {key}", file=sys.stderr)
        sys.exit(2)
    return v

class BookStackClient:
    def __init__(self, base_url: str, token_id: str, token_secret: str, verify=True, rate_limit_sleep: float = 0.5):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {token_id}:{token_secret}",
            "Accept": "application/json",
            "User-Agent": "BookStack-UsersByRole/1.0"
        })
        self.session.verify = verify
        self.rate_limit_sleep = rate_limit_sleep

    def _request(self, method: str, path: str, *, params: Dict[str, Any] = None) -> Dict[str, Any]:
        import time as _time
        url = f"{self.base_url}{path}"
        for attempt in range(5):
            resp = self.session.request(method, url, params=params, timeout=60)
            if resp.status_code == 429:
                _time.sleep(self.rate_limit_sleep * (attempt + 1))
                continue
            if 200 <= resp.status_code < 300:
                return resp.json() if resp.text.strip() else {}
            if 500 <= resp.status_code < 600 and attempt < 4:
                _time.sleep(self.rate_limit_sleep * (attempt + 1))
                continue
            raise RuntimeError(f"{method} {path} failed [{resp.status_code}]: {resp.text}")
        raise RuntimeError(f"{method} {path} failed after retries")

    def list_users(self, count: int = 100) -> list[dict]:
        users, page = [], 1
        while True:
            j = self._request("GET", "/api/users",
                            params={"count": count, "page": page, "include": "roles"})
            data = j.get("data", [])
            print(f"[=] Fetched page {page} ({len(data)} users)")
            if not data:
                break
            users.extend(data)

            if len(data) < count or not j.get("next"):
                break
            page += 1

        # Fallback enrich: if roles look empty, fetch details per user
        need_enrich = any(u.get("roles") in (None, [],) for u in users)
        if need_enrich:
            print("[~] Roles empty for some users; enriching from /api/users/{id} …")
            enriched = []
            for u in users:
                ud = self._request("GET", f"/api/users/{u['id']}")
                u["roles"] = ud.get("roles", u.get("roles", []))
                enriched.append(u)
            users = enriched
        return users


def main():
    base_url   = getenv_required("BOOKSTACK_BASE_URL")
    token_id   = getenv_required("BOOKSTACK_TOKEN_ID")
    token_sec  = getenv_required("BOOKSTACK_TOKEN_SECRET")
    out_path   = os.getenv("OUTPUT", "bookstack_users_by_role.csv")

    # TLS handling identical to your script
    verify = True
    ca_cert = os.getenv("BOOKSTACK_CA_CERT")
    insecure = os.getenv("BOOKSTACK_INSECURE", "0").lower() in ("1", "true", "yes")
    if ca_cert:
        verify = ca_cert
    elif insecure:
        verify = False
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            print("[!] TLS verification DISABLED (BOOKSTACK_INSECURE=1). HTTPS warnings suppressed.", file=sys.stderr)
        except Exception:
            pass

    client = BookStackClient(base_url, token_id, token_sec, verify=verify)

    users = client.list_users()

    # Flatten to role rows (one row per (role,user)); handle users with no roles
    rows: List[Dict[str, Any]] = []
    for u in users:
        roles = (u.get("roles") or [])
        if roles:
            for r in roles:
                rows.append({
                    "Role": r.get("display_name") or r.get("name") or str(r.get("id")),
                    "User Name": u.get("name", ""),
                    "Email": u.get("email", ""),
                    "User ID": u.get("id", ""),
                })
        else:
            rows.append({
                "Role": "(No role)",
                "User Name": u.get("name", ""),
                "Email": u.get("email", ""),
                "User ID": u.get("id", ""),
            })

    # Sort by role then name
    rows.sort(key=lambda r: ((r["Role"] or "").lower(), (r["User Name"] or "").lower()))

    # Write CSV
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Role", "User Name", "Email", "User ID"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"[✓] Wrote {out_path} (rows: {len(rows)})")

    # Pretty grouped summary to console
    print("\n=== Summary (grouped by role) ===")
    last_role: Optional[str] = None
    for r in rows:
        role = r["Role"]
        if role != last_role:
            print(f"\n-- {role} --")
            last_role = role
        print(f"  {r['User Name']}  <{r['Email']}>")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        sys.exit(1)
