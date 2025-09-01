#!/usr/bin/env python3
"""
BookStack Folder Downloader (env-driven, folder-based)

Mirrors the structure used by bookstack_folder_sync.py, but in reverse:
- Creates a local folder named after the book (or OUTPUT_DIR)
- Root-level pages become Markdown files in the root folder
- First-level chapters become directories; their pages become Markdown files inside
- Two-digit (at least) numeric prefixes reflect item priority for ordering
- Preserves page & chapter title casing in names (strip prefix on upload)

Env (via .env or environment):
  BOOKSTACK_BASE_URL
  BOOKSTACK_TOKEN_ID
  BOOKSTACK_TOKEN_SECRET
  BOOKSTACK_BOOK_NAME
Optional:
  OUTPUT_DIR=/path/to/output     (default: ./<BOOKSTACK_BOOK_NAME> next to script)
  BOOKSTACK_INSECURE=1           (disable TLS verify & suppress warnings)
  BOOKSTACK_CA_CERT=/path/to/ca.pem
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# --- Load environment from .env if present (same behavior as sync) ---
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

# Requests (install if missing)
try:
    import requests
except ImportError:
    import subprocess, sys as _sys
    subprocess.check_call([_sys.executable, "-m", "pip", "install", "requests"])
    import requests


# --------------------- Helpers ---------------------

INVALID_FS_CHARS = re.compile(r"[\\/:*?\"<>|]")

def getenv_required(key: str) -> str:
    v = os.getenv(key)
    if not v:
        print(f"Missing required environment variable: {key}", file=sys.stderr)
        sys.exit(2)
    return v

def sanitize_name(name: str) -> str:
    """
    Make a safe filename/folder name while preserving human-readability & case.
    - Replace illegal characters on Windows/macOS/Linux with underscore
    - Collapse whitespace
    - Trim trailing dots/spaces (Windows limitation)
    """
    name = INVALID_FS_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Avoid problematic trailing characters on Windows
    name = name.rstrip(" .")
    if not name:
        name = "untitled"
    return name

def prefixed_name(priority: Optional[int], title: str) -> str:
    """
    Build a display name with a two-digit (or wider) prefix from priority.
    If priority is None, omit prefix.
    """
    safe = sanitize_name(title)
    if priority is None:
        return safe
    # pad to at least 2 digits; allow more for large values without truncation
    n = str(priority)
    if len(n) < 2:
        n = n.zfill(2)
    return f"{n} {safe}"

def write_text_if_changed(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            current = path.read_text(encoding="utf-8")
            if current == content:
                return "no-change"
        except Exception:
            pass
    path.write_text(content, encoding="utf-8")
    return "written" if path.exists() else "error"


# --------------------- HTML -> Markdown ---------------------

def _try_markdownify(html: str) -> Optional[str]:
    try:
        from markdownify import markdownify as md  # type: ignore
    except Exception:
        # Attempt install on the fly; ignore failure silently
        try:
            import subprocess, sys as _sys
            subprocess.check_call([_sys.executable, "-m", "pip", "install", "markdownify"])
            from markdownify import markdownify as md  # type: ignore
        except Exception:
            return None
    try:
        # Use ATX-style headings (#, ##), fenced code blocks, dash bullets
        text = md(html, heading_style="ATX")
        return text
    except Exception:
        return None

def _try_html2text(html: str) -> Optional[str]:
    try:
        import html2text  # type: ignore
    except Exception:
        try:
            import subprocess, sys as _sys
            subprocess.check_call([_sys.executable, "-m", "pip", "install", "html2text"])
            import html2text  # type: ignore
        except Exception:
            return None
    try:
        h = html2text.HTML2Text()
        h.body_width = 0            # do not wrap lines
        h.unicode_snob = True
        h.ignore_images = False
        h.ignore_emphasis = False
        h.ignore_links = False
        h.protect_links = True
        h.single_line_break = True
        text = h.handle(html)
        return text
    except Exception:
        return None

_HTML_TAG_RE = re.compile(r"<[^>]+>")

def _basic_strip_html(html: str) -> str:
    # Very basic fallback: remove tags, keep text; not ideal but better than raw HTML
    # Convert <br> and <p> to line breaks first
    s = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", html)
    s = re.sub(r"(?i)</\s*p\s*>", "\n\n", s)
    s = re.sub(r"(?i)<\s*p[^>]*>", "", s)
    # Remove remaining tags
    s = _HTML_TAG_RE.sub("", s)
    # Unescape basic entities
    try:
        import html as _html
        s = _html.unescape(s)
    except Exception:
        pass
    # Normalize whitespace
    s = re.sub(r"\r\n|\r", "\n", s)
    s = re.sub(r"\n\n\n+", "\n\n", s)
    return s.strip() + "\n"

def _preprocess_callouts(html: str) -> str:
    """
    Detect elements with class "callout" and wrap their content in
    a <blockquote><p>[!TYPE]</p>…</blockquote> structure so downstream
    HTML->Markdown converters render proper admonitions, preserving callouts.
    """
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        try:
            import subprocess, sys as _sys
            subprocess.check_call([_sys.executable, "-m", "pip", "install", "beautifulsoup4"])
            from bs4 import BeautifulSoup  # type: ignore
        except Exception:
            # If BS4 not available, return original HTML
            return html

    soup = BeautifulSoup(html, "html.parser")

    def classify_callout(classes: List[str]) -> str:
        priority = [
            ("danger", "DANGER"),
            ("warning", "WARNING"),
            ("success", "SUCCESS"),
            ("tip", "TIP"),
            ("info", "INFO"),
            ("note", "NOTE"),
        ]
        lc = [c.lower() for c in classes]
        for k, v in priority:
            if k in lc:
                return v
        return "INFO"

    callout_nodes = soup.find_all(lambda tag: isinstance(tag.get("class"), list) and any(c.lower() == "callout" for c in tag.get("class", [])))
    for node in callout_nodes:
        classes = node.get("class", [])
        ctype = classify_callout(classes)

        # Create blockquote wrapper
        bq = soup.new_tag("blockquote")
        head_p = soup.new_tag("p")
        head_p.string = f"[!{ctype}]"
        bq.append(head_p)

        # Move node children into blockquote
        for child in list(node.children):
            bq.append(child.extract())

        # Replace original node
        node.replace_with(bq)

    return str(soup)

def html_to_markdown(html: str) -> str:
    """
    Convert HTML to Markdown using best-available method:
      1) markdownify (best quality)
      2) html2text (good quality)
      3) basic tag stripping fallback
    Also performs light post-processing to reduce extra blank lines.
    """
    # Preprocess HTML to preserve callouts as admonition-style blockquotes
    html = _preprocess_callouts(html)

    def _ensure_blankline_before_callouts(md_text: str) -> str:
        lines = md_text.splitlines()
        out: List[str] = []
        callout_re = re.compile(r"^\s*>\s*\[![A-Za-z]+\]")
        for line in lines:
            if callout_re.match(line):
                if out and out[-1].strip() != "":
                    out.append("")
            out.append(line)
        return "\n".join(out).rstrip() + "\n"

    for fn in (_try_markdownify, _try_html2text):
        md = fn(html)
        if isinstance(md, str) and md.strip():
            # light normalization
            md = re.sub(r"\s+$", "", md, flags=re.MULTILINE)
            md = re.sub(r"\n\n\n+", "\n\n", md)
            md = md.strip() + "\n"
            md = _ensure_blankline_before_callouts(md)
            return md
    return _basic_strip_html(html)


# --------------------- API Client ---------------------

class BookStackClient:
    def __init__(self, base_url: str, token_id: str, token_secret: str, verify=True, rate_limit_sleep: float = 0.5):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {token_id}:{token_secret}",
            "Accept": "application/json",
            "User-Agent": "BookStack-FolderDownload/1.0"
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

    # Pagination helper
    def _list_all(self, path: str, params: Optional[Dict[str, Any]] = None, count: int = 100) -> List[Dict[str, Any]]:
        params = dict(params or {})
        page = 1
        items: List[Dict[str, Any]] = []
        while True:
            p = dict(params)
            p.update({"count": count, "page": page})
            j = self._request("GET", path, params=p)
            data = j.get("data", [])
            items.extend(data)
            if len(data) < count or not j.get("next"):
                break
            page += 1
        return items

    # Books
    def find_book_exact(self, name: str) -> Optional[Dict[str, Any]]:
        data = self._request("GET", "/api/books", params={"filter[name:like]": name, "count": 500})
        for b in data.get("data", []):
            if b.get("name") == name:
                return b
        return None

    # Chapters
    def list_chapters(self, book_id: int) -> List[Dict[str, Any]]:
        items = self._list_all(
            "/api/chapters",
            params={"filter[book_id]": book_id}
        )
        # sort by priority then name (case-insensitive)
        items.sort(key=lambda c: (c.get("priority") or 0, (c.get("name") or "").lower()))
        return items

    # Pages
    def list_pages_root(self, book_id: int) -> List[Dict[str, Any]]:
        items = self._list_all(
            "/api/pages",
            params={"filter[book_id]": book_id}
        )
        # Keep only those not in a chapter (chapter_id is null/None)
        root_items = [p for p in items if not p.get("chapter_id")]
        root_items.sort(key=lambda p: (p.get("priority") or 0, (p.get("name") or "").lower()))
        return root_items

    def list_pages_in_chapter(self, chapter_id: int) -> List[Dict[str, Any]]:
        items = self._list_all(
            "/api/pages",
            params={"filter[chapter_id]": chapter_id}
        )
        items.sort(key=lambda p: (p.get("priority") or 0, (p.get("name") or "").lower()))
        return items

    def get_page(self, page_id: int) -> Dict[str, Any]:
        return self._request("GET", f"/api/pages/{page_id}")


# --------------------- Main Download ---------------------

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

    # Determine output dir
    script_dir = Path(__file__).resolve().parent
    out_dir_env = os.getenv("OUTPUT_DIR", "").strip()
    out_root = Path(out_dir_env).expanduser().resolve() if out_dir_env else (script_dir / book_name).resolve()

    client = BookStackClient(base_url, token_id, token_secret, verify=verify)

    # Verify book exists
    book = client.find_book_exact(book_name)
    if not book:
        print(f"Error: Book '{book_name}' not found. Use exact name.", file=sys.stderr)
        sys.exit(3)
    book_id = book["id"]
    print(f"[=] Source book: {book_name} (id={book_id})")
    print(f"[=] Output folder: {out_root}")

    # Root pages
    root_pages = client.list_pages_root(book_id)
    for p in root_pages:
        title = p.get("name") or f"Page-{p.get('id')}"
        prio = p.get("priority")
        filename = prefixed_name(prio, title) + ".md"
        file_path = out_root / filename

        full = client.get_page(p["id"])  # get markdown/html
        md = full.get("markdown")
        content: str
        if isinstance(md, str) and md.strip():
            content = md
        else:
            html = (full.get("html") or "").strip()
            content = html_to_markdown(html) if html else ""

        status = write_text_if_changed(file_path, content)
        if status == "no-change":
            print(f"[=] No change: {filename}")
        else:
            print(f"[+] Wrote: {filename}")

    # Chapters and their pages
    chapters = client.list_chapters(book_id)
    for ch in chapters:
        ch_title = ch.get("name") or f"Chapter-{ch.get('id')}"
        ch_prio = ch.get("priority")
        ch_dir = out_root / prefixed_name(ch_prio, ch_title)
        ch_dir.mkdir(parents=True, exist_ok=True)
        print(f"[=] Chapter: {ch_dir.name}")

        ch_pages = client.list_pages_in_chapter(ch["id"])
        for p in ch_pages:
            title = p.get("name") or f"Page-{p.get('id')}"
            prio = p.get("priority")
            filename = prefixed_name(prio, title) + ".md"
            file_path = ch_dir / filename

            full = client.get_page(p["id"])  # get markdown/html
            md = full.get("markdown")
            if isinstance(md, str) and md.strip():
                content = md
            else:
                html = (full.get("html") or "").strip()
                content = html_to_markdown(html) if html else ""

            status = write_text_if_changed(file_path, content)
            if status == "no-change":
                print(f"    [=] No change: {filename}")
            else:
                print(f"    [+] Wrote: {filename}")

    print("[✓] Download complete.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        sys.exit(1)
