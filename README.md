# BookStack Folder Sync

Lightweight script to sync a local folder of Markdown files into a BookStack book (pages + chapters) using the BookStack API.

This repo includes the main script `bookstack_folder_sync.py` which is env-driven and uses filename prefixes for ordering, inlines images as data URIs, and performs smart updates (skip updating when content is unchanged, but still update ordering/priority).

## Quick plan / checklist

- Identify and set required environment variables
- Prepare content folder (root `.md` files and first-level folders for chapters)
- Run the script (PowerShell examples included)

## Requirements

- Python 3.7+
- `uv` for fast dependency management

First, ensure the environment is set up:

```powershell
# Install uv if not already installed
# winget install astral-sh.uv

# Sync dependencies and set up the environment
uv sync

# Run with uv (automatically manages dependencies)
uv run bookstack_folder_sync.py
```

## Environment variables

Required:

- `BOOKSTACK_BASE_URL` — e.g. `https://bookstack.example.com` (no trailing slash required)
- `BOOKSTACK_TOKEN_ID` — API token id
- `BOOKSTACK_TOKEN_SECRET` — API token secret
- `BOOKSTACK_BOOK_NAME` — Exact name of the BookStack book to sync into

Optional:

- `CONTENT_DIR` — Path to your content folder. Default: a folder named exactly as `BOOKSTACK_BOOK_NAME` placed next to the script.
- `BOOKSTACK_INSECURE` — Set to `1`, `true`, or `yes` to disable TLS verification (suppresses warnings). Use only for trusted networks/testing.
- `BOOKSTACK_CA_CERT` — Path to a CA cert file to use for TLS verification (overrides `BOOKSTACK_INSECURE`).

The script also supports a `.env` file (via `python-dotenv`) — place it next to the script and include the same variables there.

Example `.env`:

```
BOOKSTACK_BASE_URL=https://bookstack.example.com
BOOKSTACK_TOKEN_ID=abcd1234
BOOKSTACK_TOKEN_SECRET=verysecret
BOOKSTACK_BOOK_NAME=Data & Knowledge Management Guide
CONTENT_DIR=
BOOKSTACK_INSECURE=0
```

If `CONTENT_DIR` is empty, the script resolves the content folder to `./<BOOKSTACK_BOOK_NAME>` next to the script.

### TLS / insecure mode

If your BookStack server uses a self-signed or otherwise invalid TLS certificate you can disable certificate verification by setting `BOOKSTACK_INSECURE=1` in your `.env` (or environment). This is useful for local or test installations where HTTPS is not fully set up.

Warning: disabling TLS verification removes protection against man-in-the-middle attacks. Use `BOOKSTACK_INSECURE=1` only for testing or on trusted networks. A safer option is to provide the server's CA certificate via `BOOKSTACK_CA_CERT`.

## Content layout and filename rules

- Root-level `*.md` files (inside `CONTENT_DIR`) become pages in the book root.
- First-level subdirectories become chapters; their `*.md` files become pages inside that chapter.
- Deeper nesting (subfolders of chapter folders) is ignored.
- Ordering is controlled by two-digit prefixes on filenames and folder names, e.g.:

```
01 Introduction.md           -> title: "Introduction", priority/order: 1
02_Getting-Started.md        -> title: "Getting Started"
03-Advanced Topics.md        -> title: "Advanced Topics"
10 Appendix/                -> chapter with prefix 10
```

- The page title is derived from the filename only (prefix removed). Underscores and hyphens are converted to spaces; case is preserved.

### Example folder structure

Here's an example content tree (place this folder next to `bookstack_folder_sync.py` or set `CONTENT_DIR`):

```
Data & Knowledge Management Guide/
├─ 01 Introduction.md
├─ 02 SharePoint.md
├─ 03 Network Drives (Legacy).md
├─ 04 BookStack (Knowledge Base).md
├─ 05 Central Image Repository.md
├─ images/
│  └─ test.png
└─ 10 Appendix/
	├─ 01 Extra Resources.md
	└─ 02 Troubleshooting.md
```

Notes:
- Files at the top level become pages in the book root.
- `10 Appendix/` is a chapter (first-level folder); its `*.md` files become pages inside that chapter.
- `images/` can hold shared images which will be inlined where referenced.

## Image handling

- Markdown image references (e.g. `![alt](images/pic.png)`) are replaced with data URIs when the referenced image exists. The script resolves image paths relative to the page file and the content root.
- Supported image extensions: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`.

Notes:
- If an image is missing or an unsupported type, the original Markdown reference is left unchanged.

## Safe update behavior

- The script compares new Markdown to the existing page. If content is unchanged it will skip updating the page body and only update priority/order if needed.
- Comparison prefers the `markdown` field returned by the API; when absent, it renders Markdown to HTML (requires `markdown` package) and compares HTML as a fallback.

## How to run

First, sync the environment, then set your environment variables (or use a `.env` file) and run with `uv`:

```powershell
# Sync dependencies and set up environment
uv sync

# Set environment variables
$env:BOOKSTACK_BASE_URL = 'https://bookstack.example.com';
$env:BOOKSTACK_TOKEN_ID = 'your-id';
$env:BOOKSTACK_TOKEN_SECRET = 'your-secret';
$env:BOOKSTACK_BOOK_NAME = 'Data & Knowledge Management Guide';

# Run with uv
uv run bookstack_folder_sync.py

# Or with custom CONTENT_DIR
$env:CONTENT_DIR = 'G:\\path\\to\\content';
uv run bookstack_folder_sync.py
```

On Unix-like shells (for reference):

```bash
# Sync dependencies first
uv sync

# Then run with environment variables
BOOKSTACK_BASE_URL=https://bookstack.example.com \
BOOKSTACK_TOKEN_ID=your-id \
BOOKSTACK_TOKEN_SECRET=your-secret \
BOOKSTACK_BOOK_NAME='Data & Knowledge Management Guide' \
uv run bookstack_folder_sync.py
```

## Exit codes and common errors

- Exit code `2`: Missing required environment variables or content folder not found.
- Exit code `3`: Target Book not found (create the Book in BookStack first; name must match exactly).
- Network/API exceptions will raise an error; check the printed message for the HTTP status and response body.

If TLS verification fails, either provide `BOOKSTACK_CA_CERT` or set `BOOKSTACK_INSECURE=1` (not recommended for production).

## Troubleshooting

- If encountering issues, ensure `uv` is properly installed:

```powershell
# Install uv if not already installed
winget install astral-sh.uv
# Or via pip
pip install uv
```

- If pages are created with unexpected titles, ensure filenames follow the 2-digit prefix convention and that the remainder of the filename is the desired title.

## Example workflow

1. Create a folder named `Data & Knowledge Management Guide` next to `bookstack_folder_sync.py`.
2. Add `01 Introduction.md`, `02 SharePoint.md`, etc. Optionally create a folder `10 Appendix` and add `01 Extra.md` inside it.
3. Create a `.env` with the required API variables or export them in your shell.
4. Set up the environment: `uv sync`
5. Run the script: `uv run bookstack_folder_sync.py`

## License

MIT
