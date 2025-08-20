#!/usr/bin/env python3
"""
Update all pages in a BookStack book to set a tag.

- Scope is limited by BOOKSTACK_BOOK_NAME (required).
- Loads BookStack credentials from .env or environment variables.
- TLS handled by BOOKSTACK_INSECURE=1 or BOOKSTACK_CA_CERT=/path/to/ca.pem.
- Dry run option: BOOKSTACK_DRY_RUN=1 (shows what would happen).

The tag is defined below as GLOBAL variables (not from env).
"""

import os
import sys
import time
from typing import Optional, Dict, Any, List

# ---------------- Tag Config -----------------
TAG_NAME = "Status"
TAG_VALUE = "Draft"
# ---------------------------------------------

# --- Load environment from .env if present ---
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    try:
        import subprocess, sys as _sys
        subprocess.check_call([_sys.executable, "-m", "pip", "install", "python-dotenv"])
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        load_dotenv = None

if 'load_dotenv' in globals() and load_dotenv:
    load_dotenv()
# ---------------------------------------------

try:
    import requests
except ImportError:
    import subprocess, sys as _sys
    subprocess.check_call([_sys.executable, "-m", "pip", "install", "requests"])
    import requests

DRY_RUN = os.getenv("BOOKSTACK_DRY_RUN", "0").lower() in ("1","true","yes")

BASE_URL = os.getenv("BOOKSTACK_BASE_URL")
TOKEN_ID = os.getenv("BOOKSTACK_TOKEN_ID")
TOKEN_SECRET = os.getenv("BOOKSTACK_TOKEN_SECRET")
BOOK_NAME = os.getenv("BOOKSTACK_BOOK_NAME", "").strip()

if not BASE_URL or not TOKEN_ID or not TOKEN_SECRET or not BOOK_NAME:
    print("Missing required env: BOOKSTACK_BASE_URL / BOOKSTACK_TOKEN_ID / BOOKSTACK_TOKEN_SECRET / BOOKSTACK_BOOK_NAME", file=sys.stderr)
    sys.exit(2)

# TLS
verify = True
ca_cert = os.getenv("BOOKSTACK_CA_CERT")
insecure = os.getenv("BOOKSTACK_INSECURE", "0").lower() in ("1","true","yes")
if ca_cert:
    verify = ca_cert
elif insecure:
    verify = False
    print("[!] TLS verification DISABLED (BOOKSTACK_INSECURE=1). Use only for testing.", file=sys.stderr)

session = requests.Session()
session.headers.update({
    "Authorization": f"Token {TOKEN_ID}:{TOKEN_SECRET}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "BookStack-TagUpdater/1.1-fixed"
})
session.verify = verify

def req(method: str, path: str, *, params=None, json=None) -> Dict[str, Any]:
    url = f"{BASE_URL.rstrip('/')}{path}"
    for attempt in range(5):
        resp = session.request(method, url, params=params, json=json, timeout=30)
        if resp.status_code == 429:
            time.sleep(0.5 * (attempt + 1))
            continue
        if 200 <= resp.status_code < 300:
            return resp.json() if resp.text.strip() else {}
        if 500 <= resp.status_code < 600 and attempt < 4:
            time.sleep(0.5 * (attempt + 1))
            continue
        raise RuntimeError(f"{method} {path} failed [{resp.status_code}]: {resp.text}")
    raise RuntimeError(f"{method} {path} failed after retries")

def find_book_exact(name: str) -> Optional[Dict[str, Any]]:
    data = req("GET", "/api/books", params={"filter[name:like]": name, "count": 500})
    for b in data.get("data", []):
        if b.get("name") == name:
            return b
    return None

def iter_pages(book_id: Optional[int] = None):
    """Yield pages, optionally filtered by book_id, handling pagination."""
    offset = 0
    count = 100
    while True:
        params = {"count": count, "offset": offset}
        if book_id is not None:
            params["filter[book_id]"] = book_id
        data = req("GET", "/api/pages", params=params)
        items = data.get("data", [])
        if not items:
            break
        for item in items:
            yield item
        offset += len(items)
        if len(items) < count:
            break

def get_page(page_id: int) -> Dict[str, Any]:
    return req("GET", f"/api/pages/{page_id}")

def update_page_tags(page: Dict[str, Any]) -> bool:
    """Upsert TAG_NAME=TAG_VALUE. Returns True if an update is needed."""
    tags = page.get("tags", [])
    need_update = True
    new_tags = []
    found = False
    for t in tags:
        if t.get("name") == TAG_NAME:
            found = True
            if t.get("value") == TAG_VALUE:
                need_update = False
            new_tags.append({"name": TAG_NAME, "value": TAG_VALUE})
        else:
            new_tags.append({"name": t.get("name", ""), "value": t.get("value")})
    if not found:
        new_tags.append({"name": TAG_NAME, "value": TAG_VALUE})
    if not need_update and found:
        return False
    if DRY_RUN:
        print(f"[DRY] Would set tag {TAG_NAME}={TAG_VALUE} on page '{page.get('name')}' (id={page.get('id')})")
        return False
    body = {"tags": new_tags}
    req("PUT", f"/api/pages/{page['id']}", json=body)
    return True

def main():
    book = find_book_exact(BOOK_NAME)
    if not book:
        print(f"Error: Book '{BOOK_NAME}' not found. Set BOOKSTACK_BOOK_NAME correctly.", file=sys.stderr)
        sys.exit(3)
    book_id = book["id"]
    print(f"[=] Targeting pages within book '{BOOK_NAME}' (id={book_id})")

    updated = 0
    checked = 0
    for p in iter_pages(book_id=book_id):
        checked += 1
        full = get_page(p["id"])
        if update_page_tags(full):
            updated += 1
            print(f"[+] Tagged page: {full.get('name')} (id={full.get('id')}) -> {TAG_NAME}={TAG_VALUE}")
        else:
            print(f"[=] No change: {full.get('name')} (id={full.get('id')})")

    print(f"[✓] Done. Checked {checked} page(s); updated {updated}.")

if __name__ == "__main__":
    main()
