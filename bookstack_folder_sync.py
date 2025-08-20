#!/usr/bin/env python3
"""
BookStack Content Sync (env-driven, folder-based) with:
- Two-digit filename/folder prefixes used for ordering (not names)
- Title derived ONLY from filename (prefix removed; case preserved)
- Image inlining (Markdown image refs -> data URIs)
- Smart update: skip updating a page when content is unchanged; still update priority if needed

Folder rules:
- Root *.md files -> pages in the book
- First-level subfolders -> chapters; their *.md -> pages in those chapters
- Deeper nesting ignored

Env (via .env or environment):
  BOOKSTACK_BASE_URL
  BOOKSTACK_TOKEN_ID
  BOOKSTACK_TOKEN_SECRET
  BOOKSTACK_BOOK_NAME
Optional:
  CONTENT_DIR=/path/to/content   (default: ./<BOOKSTACK_BOOK_NAME> next to script)
  BOOKSTACK_INSECURE=1           (disable TLS verify & suppress warnings)
  BOOKSTACK_CA_CERT=/path/to/ca.pem
"""

import os
import re
import sys
import base64
import mimetypes
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

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
# --------------------------------------------

# Requests (install if missing)
try:
    import requests
except ImportError:
    import subprocess, sys as _sys
    subprocess.check_call([_sys.executable, "-m", "pip", "install", "requests"])
    import requests


# --------------------- Prefix & naming helpers ---------------------

TWO_DIGIT_PREFIX = re.compile(r"^\s*(\d{2})[\s\-_]+")

def strip_two_digit_prefix(name: str) -> Tuple[int, str]:
    m = TWO_DIGIT_PREFIX.match(name)
    if m:
        num = int(m.group(1))
        rest = name[m.end():].strip()
        return num, rest
    return float('inf'), name.strip()

def title_from_filename(filename: str) -> Tuple[int, str]:
    """
    Title from filename ONLY (prefix removed, _ and - -> spaces, casing preserved).
    """
    stem = Path(filename).stem
    order, rest = strip_two_digit_prefix(stem)
    rest = rest.replace('_', ' ').replace('-', ' ').strip()
    return order, rest if rest else stem


# --------------------- Markdown image inlining ---------------------

MD_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

def to_data_uri(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    ext = path.suffix.lower()
    if ext not in IMG_EXTS:
        return None
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }.get(ext, "application/octet-stream")
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"

def resolve_image(ref: str, page_dir: Path, content_root: Path) -> Optional[Path]:
    cand = (page_dir / ref).resolve()
    if cand.exists():
        return cand
    cand = (content_root / ref).resolve()
    if cand.exists():
        return cand
    return None

def inline_images(markdown: str, page_dir: Path, content_root: Path) -> str:
    def _replace(m: re.Match) -> str:
        alt_text = m.group(1)
        ref = m.group(2).replace("%20", " ")
        img_path = resolve_image(ref, page_dir, content_root)
        if img_path:
            data_uri = to_data_uri(img_path)
            if data_uri:
                return f"![{alt_text}]({data_uri})"
        return m.group(0)
    return MD_IMAGE_RE.sub(_replace, markdown)


# --------------------- Content helpers ---------------------

def getenv_required(key: str) -> str:
    v = os.getenv(key)
    if not v:
        print(f"Missing required environment variable: {key}", file=sys.stderr)
        sys.exit(2)
    return v

def read_markdown(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")


# --------------------- API Client ---------------------

class BookStackClient:
    def __init__(self, base_url: str, token_id: str, token_secret: str, verify=True, rate_limit_sleep: float = 0.5):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {token_id}:{token_secret}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "BookStack-FolderSync/1.4"
        })
        self.session.verify = verify
        self.rate_limit_sleep = rate_limit_sleep

    def _request(self, method: str, path: str, *, params: Dict[str, Any] = None, json: Dict[str, Any] = None) -> Dict[str, Any]:
        import time as _time
        url = f"{self.base_url}{path}"
        for attempt in range(5):
            resp = self.session.request(method, url, params=params, json=json, timeout=60)
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

    # Books
    def find_book_exact(self, name: str) -> Optional[Dict[str, Any]]:
        data = self._request("GET", "/api/books", params={"filter[name:like]": name, "count": 500})
        for b in data.get("data", []):
            if b.get("name") == name:
                return b
        return None

    # Chapters
    def find_chapter(self, book_id: int, name: str) -> Optional[Dict[str, Any]]:
        data = self._request("GET", "/api/chapters", params={"filter[book_id]": book_id, "filter[name:like]": name, "count": 500})
        for c in data.get("data", []):
            if c.get("name") == name and c.get("book_id") == book_id:
                return c
        return None

    def create_chapter(self, book_id: int, name: str, description: str = "", priority: Optional[int] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"book_id": book_id, "name": name}
        if description:
            body["description"] = description
        if priority is not None:
            body["priority"] = priority
        return self._request("POST", "/api/chapters", json=body)

    def update_chapter(self, chapter_id: int, **fields) -> Dict[str, Any]:
        return self._request("PUT", f"/api/chapters/{chapter_id}", json=fields)

    # Pages
    def find_page(self, *, book_id: int, chapter_id: Optional[int], name: str) -> Optional[Dict[str, Any]]:
        params = {"filter[book_id]": book_id, "filter[name:like]": name, "count": 500}
        if chapter_id:
            params["filter[chapter_id]"] = chapter_id
        data = self._request("GET", "/api/pages", params=params)
        for p in data.get("data", []):
            if p.get("name") == name and p.get("book_id") == book_id and (chapter_id is None or p.get("chapter_id") == chapter_id):
                return p
        return None

    def get_page(self, page_id: int) -> Dict[str, Any]:
        # Try to fetch markdown; some BookStack versions return 'markdown' by default.
        # If not present, we'll get 'html' and compare rendered HTML instead.
        return self._request("GET", f"/api/pages/{page_id}")

    def create_page(self, *, book_id: int, chapter_id: Optional[int], name: str, markdown: str, priority: Optional[int] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": name, "markdown": markdown}
        if chapter_id:
            body["chapter_id"] = chapter_id
        else:
            body["book_id"] = book_id
        if priority is not None:
            body["priority"] = priority
        return self._request("POST", "/api/pages", json=body)

    def update_page(self, page_id: int, **fields) -> Dict[str, Any]:
        return self._request("PUT", f"/api/pages/{page_id}", json=fields)


# --------------------- Compare helpers ---------------------

def render_markdown_to_html(md: str) -> Optional[str]:
    """
    Render Markdown to HTML for comparison fallback when 'markdown' is not returned by the API.
    Returns None if we cannot render (package not available).
    """
    try:
        import markdown as mdlib  # type: ignore
    except Exception:
        # try installing on the fly
        try:
            import subprocess, sys as _sys
            subprocess.check_call([_sys.executable, "-m", "pip", "install", "markdown"])
            import markdown as mdlib  # type: ignore
        except Exception:
            return None
    # Basic rendering; BookStack's parser differs, but good enough for "no-change" heuristic
    return mdlib.markdown(md, extensions=[])

def contents_equal(new_markdown: str, existing_page: Dict[str, Any]) -> bool:
    """
    Compare our new Markdown against the existing page content.
    Prefer comparing markdown-to-markdown; otherwise compare rendered HTML.
    """
    # 1) Direct markdown field
    existing_md = existing_page.get("markdown")
    if isinstance(existing_md, str):
        # Normalize trivial differences (strip trailing whitespace)
        a = new_markdown.strip()
        b = existing_md.strip()
        return a == b

    # 2) Fallback: compare HTML
    existing_html = existing_page.get("html")
    if isinstance(existing_html, str):
        rendered = render_markdown_to_html(new_markdown)
        if rendered is None:
            # Can't render; assume different to be safe
            return False
        # Light normalization
        return rendered.strip() == existing_html.strip()

    # 3) Unknown shape -> assume different
    return False


# --------------------- Discovery ---------------------

def collect_content(content_dir: Path) -> Tuple[
    List[Tuple[int, str, Path]],
    List[Tuple[int, str, List[Tuple[int, str, Path]]]]
]:
    """
    Return:
      - root_pages: [(order, display_title, file_path), ...]
      - chapters:   [(chapter_order, chapter_name, [(page_order, display_title, file_path), ...]), ...]
    """
    root_pages: List[Tuple[int, str, Path]] = []
    chapters: List[Tuple[int, str, List[Tuple[int, str, Path]]]] = []

    # Root-level pages
    for p in content_dir.glob("*.md"):
        order, display = title_from_filename(p.name)
        root_pages.append((order, display, p))

    # Chapters = first-level directories
    chapter_dirs = [d for d in content_dir.iterdir() if d.is_dir()]
    chapter_dirs.sort(key=lambda d: (strip_two_digit_prefix(d.name)[0], strip_two_digit_prefix(d.name)[1].lower()))
    for sub in chapter_dirs:
        ch_order, ch_name = strip_two_digit_prefix(sub.name)
        ch_name = ch_name if ch_name else sub.name
        chapter_files = [f for f in sub.glob("*.md")]
        chapter_files.sort(key=lambda f: (title_from_filename(f.name)[0], title_from_filename(f.name)[1].lower()))
        page_items: List[Tuple[int, str, Path]] = []
        for f in chapter_files:
            p_order, p_name = title_from_filename(f.name)
            page_items.append((p_order, p_name, f))
        if page_items:
            chapters.append((ch_order, ch_name, page_items))

    root_pages.sort(key=lambda t: (t[0], t[1].lower()))
    chapters.sort(key=lambda t: (t[0], t[1].lower()))
    return root_pages, chapters


# --------------------- Main Sync ---------------------

def main():
    base_url = getenv_required("BOOKSTACK_BASE_URL")
    token_id = getenv_required("BOOKSTACK_TOKEN_ID")
    token_secret = getenv_required("BOOKSTACK_TOKEN_SECRET")
    book_name = getenv_required("BOOKSTACK_BOOK_NAME")

    # TLS setup
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
        except Exception:
            pass
        print("[!] TLS verification DISABLED (BOOKSTACK_INSECURE=1). HTTPS warnings suppressed.", file=sys.stderr)

    # Determine content dir
    script_dir = Path(__file__).resolve().parent
    content_dir_env = os.getenv("CONTENT_DIR", "").strip()
    content_root = Path(content_dir_env).expanduser().resolve() if content_dir_env else (script_dir / book_name).resolve()

    if not content_root.exists() or not content_root.is_dir():
        print(f"Content folder not found: {content_root}", file=sys.stderr)
        sys.exit(2)

    # Connect API
    client = BookStackClient(base_url, token_id, token_secret, verify=verify)

    # Verify book exists
    book = client.find_book_exact(book_name)
    if not book:
        print(f"Error: Book '{book_name}' not found. Create it first (exact name required).", file=sys.stderr)
        sys.exit(3)
    book_id = book["id"]
    print(f"[=] Target book: {book_name} (id={book_id})")
    print(f"[=] Content source: {content_root}")

    # Collect content
    root_pages, chapters = collect_content(content_root)

    # ----- Upsert root-level pages -----
    priority = 1
    for _, page_title, file_path in root_pages:
        raw_md = read_markdown(file_path)
        transformed_md = inline_images(raw_md, page_dir=file_path.parent, content_root=content_root)

        existing = client.find_page(book_id=book_id, chapter_id=None, name=page_title)
        if not existing:
            print(f"[+] Creating page (book root): {page_title}")
            client.create_page(book_id=book_id, chapter_id=None, name=page_title, markdown=transformed_md, priority=priority)
        else:
            # fetch full page for content comparison
            full = client.get_page(existing["id"])
            same = contents_equal(transformed_md, full)
            if same:
                # content is the same; update only if priority changed
                if existing.get("priority") != priority:
                    print(f"[~] No content change; updating priority only: {page_title} -> {priority}")
                    client.update_page(existing["id"], priority=priority)
                else:
                    print(f"[=] No change: {page_title}")
            else:
                print(f"[=] Updating page (book root): {page_title}")
                client.update_page(existing["id"], markdown=transformed_md, priority=priority)
        priority += 1

    # ----- Upsert chapters & their pages -----
    chapter_order = 1
    for ch_order, chapter_name, page_items in chapters:
        chapter = client.find_chapter(book_id, chapter_name)
        if not chapter:
            print(f"[+] Creating chapter: {chapter_name}")
            chapter = client.create_chapter(book_id, chapter_name, description="", priority=chapter_order)
        else:
            if chapter.get("priority") != chapter_order:
                print(f"[~] Updating chapter order: {chapter_name} -> {chapter_order}")
                client.update_chapter(chapter["id"], priority=chapter_order)
            else:
                print(f"[=] Chapter order OK: {chapter_name}")
        chapter_order += 1

        page_order = 1
        for _, page_title, file_path in page_items:
            raw_md = read_markdown(file_path)
            transformed_md = inline_images(raw_md, page_dir=file_path.parent, content_root=content_root)

            existing = client.find_page(book_id=book_id, chapter_id=chapter["id"], name=page_title)
            if not existing:
                print(f"    [+] Creating page: {chapter_name} / {page_title}")
                client.create_page(book_id=book_id, chapter_id=chapter["id"], name=page_title, markdown=transformed_md, priority=page_order)
            else:
                full = client.get_page(existing["id"])
                same = contents_equal(transformed_md, full)
                if same:
                    if existing.get("priority") != page_order:
                        print(f"    [~] No content change; updating priority only: {page_title} -> {page_order}")
                        client.update_page(existing["id"], priority=page_order)
                    else:
                        print(f"    [=] No change: {chapter_name} / {page_title}")
                else:
                    print(f"    [=] Updating page: {chapter_name} / {page_title}")
                    client.update_page(existing["id"], markdown=transformed_md, priority=page_order)
            page_order += 1

    print("[✓] Sync complete.")

if __name__ == "__main__":
    main()
