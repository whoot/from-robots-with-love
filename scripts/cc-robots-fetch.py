#!/usr/bin/env python3
"""
Downloads and parses the latest Common Crawl robotstxt WARC files.

Steps:
  1. Fetch https://commoncrawl.org/latest-crawl to find the current crawl ID
  2. Download robotstxt.paths.gz and extract the file list
  3. Download all WARC files sequentially
  4. Parse each WARC file and extract valid robots.txt responses
  5. Save each result as {domain}.txt in the output directory
"""

import argparse
import gzip
import io
import re
import sys
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests
from tqdm import tqdm

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL         = "https://data.commoncrawl.org"
LATEST_CRAWL_URL = "https://commoncrawl.org/latest-crawl"
DOWNLOAD_DIR     = Path("./robotstxt_files")
PARSED_DIR       = Path("./robots_parsed")
PARALLEL_JOBS    = 4
MAX_RETRIES      = 3
USER_AGENT       = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
# ──────────────────────────────────────────────────────────────────────────────

VALID_CONTENT_TYPES = ("text/plain", "text/x-robots")
VALID_STATUS_CODES  = {200}
ROBOTS_DIRECTIVE_RE = re.compile(
    r'^(user-agent|disallow|allow|sitemap|noindex)\s*:', re.I | re.M
)

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


# ── Output helpers ────────────────────────────────────────────────────────────
def step(n: int, total: int, msg: str):
    print(f"\n[{n}/{total}] {msg}")

def ok(msg: str):
    print(f"\033[32m✔\033[0m  {msg}")


# ── Step 1: Resolve latest crawl ID ───────────────────────────────────────────
def get_crawl_id() -> tuple[str, str]:
    resp = SESSION.get(LATEST_CRAWL_URL, timeout=30)
    resp.raise_for_status()

    blog_url_m = re.search(
        r'href="(https://commoncrawl\.org/blog/[^"]*crawl-archive-now-available)"',
        resp.text,
    )
    if not blog_url_m:
        raise RuntimeError("Could not find blog URL on latest crawl page.")

    crawl_id_m = re.search(r'CC-MAIN-\d{4}-\d{2}', resp.text)
    if not crawl_id_m:
        raise RuntimeError("Could not determine crawl ID.")

    return crawl_id_m.group(0), blog_url_m.group(1)


# ── Step 2: Download and extract robotstxt.paths.gz ───────────────────────────
def get_paths_list(crawl_id: str) -> list[str]:
    url = f"{BASE_URL}/crawl-data/{crawl_id}/robotstxt.paths.gz"
    resp = SESSION.get(url, timeout=60)
    resp.raise_for_status()
    with gzip.open(io.BytesIO(resp.content), "rt") as f:
        return [line.strip() for line in f if line.strip()]


# ── Step 3: Download a single WARC file ───────────────────────────────────────
def download_file(path: str) -> Path:
    url  = f"{BASE_URL}/{path}"
    dest = DOWNLOAD_DIR / Path(path).name
    if dest.exists():
        return dest

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = SESSION.get(url, timeout=120, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
            return dest
        except Exception as e:
            if dest.exists():
                dest.unlink()
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** attempt)

    return dest


# ── Step 4 + 5: Parse a WARC file and write out robots.txt files ──────────────
def sanitize(domain: str) -> str:
    return re.sub(r'[^\w.\-]', '_', domain)


def is_meaningful(body: str) -> bool:
    return bool(re.search(
        r'^(allow|disallow|noindex)\s*:\s*(?!/*\s*$)\S',
        body, re.I | re.M
    ))


def parse_warc(warc_path: Path) -> int:
    try:
        with gzip.open(warc_path, "rt", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except Exception as e:
        log.warning("Could not read %s: %s", warc_path, e)
        return 0

    records = re.split(r'(?=WARC/1\.[01]\r?\n)', content)
    request_uris: dict[str, str] = {}
    written = 0

    for rec in records:
        if not rec.strip():
            continue

        m_type = re.search(r'WARC-Type:\s*(\S+)', rec, re.I)
        if not m_type:
            continue
        warc_type = m_type.group(1).lower()

        m_id  = re.search(r'WARC-Record-ID:\s*<([^>]+)>', rec, re.I)
        m_uri = re.search(r'WARC-Target-URI:\s*(\S+)', rec, re.I)

        if warc_type == "request" and m_id and m_uri:
            request_uris[m_id.group(1)] = m_uri.group(1)
            continue

        if warc_type != "response":
            continue

        m_conc = re.search(r'WARC-Concurrent-To:\s*<([^>]+)>', rec, re.I)
        uri = (
            request_uris.get(m_conc.group(1)) if m_conc else None
        ) or (m_uri.group(1) if m_uri else None)

        if not uri:
            continue

        domain = urlparse(uri).hostname
        if not domain:
            continue

        parts = re.split(r'\r?\n\r?\n', rec, maxsplit=2)
        if len(parts) < 3:
            continue
        http_head, body = parts[1], parts[2].strip()

        status_m = re.match(r'HTTP/[\d.]+ (\d+)', http_head)
        if not status_m or int(status_m.group(1)) not in VALID_STATUS_CODES:
            continue

        ct_m = re.search(r'Content-Type:\s*([^\r\n;]+)', http_head, re.I)
        ct   = ct_m.group(1).strip().lower() if ct_m else ""
        if not any(ct.startswith(v) for v in VALID_CONTENT_TYPES):
            continue

        if not ROBOTS_DIRECTIVE_RE.search(body):
            continue

        if not is_meaningful(body):
            continue

        out_path = PARSED_DIR / f"{sanitize(domain)}.txt"
        out_path.write_text(body, encoding="utf-8")
        written += 1

    return written


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Download and parse Common Crawl robotstxt WARC files.")
    parser.add_argument("-l", "--limit", type=int, default=None, metavar="N",
                        help="Only download the first N files (default: all)")
    args = parser.parse_args()

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)

    TOTAL_STEPS = 3

    # Step 1
    step(1, TOTAL_STEPS, "Resolving latest crawl ID …")
    crawl_id, _ = get_crawl_id()
    paths = get_paths_list(crawl_id)
    if args.limit is not None:
        paths = paths[:args.limit]
    ok(f"Crawl: {crawl_id}")

    # Step 2
    step(2, TOTAL_STEPS, "Downloading WARC files …")
    warc_files: list[Path] = []
    failed_dl = 0
    fmt = "{percentage:3.0f}%|{bar:30}| {n_fmt}/{total_fmt} [{elapsed}]"
    with tqdm(total=len(paths), bar_format=fmt, leave=True) as bar:
        for path in paths:
            try:
                warc_files.append(download_file(path))
            except Exception as e:
                failed_dl += 1
                log.error("Download failed for %s: %s", path, e)
            bar.update(1)
    ok(f"{len(warc_files)} files ready  ({failed_dl} failed)")

    # Step 3
    step(3, TOTAL_STEPS, f"Parsing WARC files  [{PARALLEL_JOBS} workers] …")
    total_written = 0
    failed_parse = 0
    with ThreadPoolExecutor(max_workers=PARALLEL_JOBS) as pool:
        futures = {pool.submit(parse_warc, wf): wf for wf in warc_files}
        with tqdm(total=len(futures), bar_format=fmt, leave=True) as bar:
            for fut in as_completed(futures):
                bar.update(1)
                try:
                    total_written += fut.result()
                except Exception as e:
                    failed_parse += 1
                    log.error("Parsing failed for %s: %s", futures[fut], e)
    ok(f"{total_written:,} robots.txt files extracted")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Aborted.")
        sys.exit(0)
    except Exception as e:
        log.critical("Fatal error: %s", e)
        sys.exit(1)
