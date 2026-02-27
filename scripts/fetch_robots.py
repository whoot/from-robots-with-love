#!/usr/bin/env python3
"""
Fetch robots.txt from top domains.

Usage:
    python fetch_robots.py domains.txt [--workers 20] [--timeout 5]

Features:
  - Resume: skips domains that already have a file in robots/
  - Graceful shutdown on Ctrl+C
  - HTTPS+HTTP probed in parallel
"""

import argparse
import asyncio
import logging
import re
import signal
import sys
from pathlib import Path

REQUIRED_PACKAGES = {"aiohttp": "aiohttp"}

def check_dependencies():
    missing = []
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(import_name) is None:
            missing.append(pip_name)
    if missing:
        print(f"Missing required packages: {', '.join(missing)}")
        print(f"Install with:  pip3 install {' '.join(missing)}")
        sys.exit(1)

check_dependencies()

import aiohttp

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
ROBOTS_DIR = Path("./robots")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_domains(path: str) -> list[str]:
    domains = []
    with open(path) as f:
        for line in f:
            d = line.strip()
            if d and not d.startswith("#"):
                d = re.sub(r"^https?://", "", d)
                d = d.rstrip("/")
                domains.append(d)
    return domains


def already_fetched() -> set[str]:
    if not ROBOTS_DIR.exists():
        return set()
    return {p.stem for p in ROBOTS_DIR.glob("*.txt")}


# ---------------------------------------------------------------------------
# Fetching – HTTPS and HTTP in parallel
# ---------------------------------------------------------------------------
# Result: "saved" | "http_404" | "empty" | "html" | "invalid" | "failed"
async def _try_scheme(
    session: aiohttp.ClientSession, domain: str, scheme: str, timeout: int
) -> tuple[str | None, int | None]:
    """Returns (body_or_none, status_code_or_none)."""
    url = f"{scheme}://{domain}/robots.txt"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=True,
            ssl=False,
        ) as resp:
            if resp.status == 200:
                ct = resp.headers.get("content-type", "")
                if "text" in ct or "octet" in ct or not ct:
                    return (await resp.text(errors="replace"), 200)
            return (None, resp.status)
    except Exception:
        return (None, None)


async def fetch_robots(
    session: aiohttp.ClientSession, domain: str, timeout: int
) -> tuple[str | None, str]:
    """Returns (body_or_none, outcome) where outcome is a stats key."""
    tasks = [
        asyncio.create_task(_try_scheme(session, domain, s, timeout))
        for s in ("https", "http")
    ]
    best_body = None
    got_any_status = None
    for coro in asyncio.as_completed(tasks):
        body, status = await coro
        if status is not None:
            got_any_status = status
        if body is not None:
            for t in tasks:
                t.cancel()
            # Classify content
            stripped = body.strip()
            if not stripped:
                return (None, "empty")
            if stripped.startswith("<!") or stripped.startswith("<html"):
                return (None, "html")
            if not any(kw in stripped.lower() for kw in ("user-agent", "disallow", "allow", "sitemap")):
                return (None, "invalid")
            return (body, "saved")

    # No body – why?
    if got_any_status is not None:
        return (None, "http_404")  # server responded, just no robots.txt
    return (None, "failed")  # network error


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------
def draw_progress(done: int, total: int, saved: int, width: int = 40):
    filled = int(width * done / total) if total > 0 else 0
    bar = "#" * filled + " " * (width - filled)
    print(f"\r[{bar}] {done}/{total}  (saved: {saved})", end="", flush=True)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
async def worker(
    sem: asyncio.Semaphore,
    session: aiohttp.ClientSession,
    domain: str,
    total: int,
    timeout: int,
    stats: dict,
    shutdown: asyncio.Event,
):
    if shutdown.is_set():
        return

    async with sem:
        if shutdown.is_set():
            return

        body, outcome = await fetch_robots(session, domain, timeout)

        stats[outcome] += 1

        if outcome == "saved" and body:
            out = ROBOTS_DIR / f"{domain}.txt"
            out.write_text(body, encoding="utf-8")

        stats["done"] += 1
        draw_progress(stats["done"], total, stats["saved"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main(domains_file: str, workers: int, timeout: int):
    ROBOTS_DIR.mkdir(parents=True, exist_ok=True)

    all_domains = load_domains(domains_file)
    done_set = already_fetched()

    domains = [d for d in all_domains if d not in done_set]
    skipped = len(all_domains) - len(domains)
    total = len(domains)

    log.info(
        "Domains: %d total, %d already fetched → %d to do  (workers=%d, timeout=%ds)\n",
        len(all_domains), skipped, total, workers, timeout,
    )

    if total == 0:
        log.info("Nothing to do.")
        return

    stats = {
        "saved": 0, "failed": 0, "empty": 0,
        "html": 0, "invalid": 0, "http_404": 0, "done": 0,
    }

    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: _request_shutdown(shutdown))
        except NotImplementedError:
            signal.signal(sig, lambda s, f: _request_shutdown(shutdown))

    sem = asyncio.Semaphore(workers)
    connector = aiohttp.TCPConnector(limit=workers, enable_cleanup_closed=True)
    async with aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": UA},
    ) as session:
        tasks = [
            asyncio.create_task(
                worker(sem, session, domain, total, timeout, stats, shutdown)
            )
            for domain in domains
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    # Summary
    print("\r" + " " * 70)
    if shutdown.is_set():
        print("\nInterrupted – progress saved. Re-run to resume.")
    else:
        print("\n✓ Done!")
    print(f"\n")
    print(f"  Saved:    {stats['saved']}  (+ {skipped} from previous runs)")
    print(f"  No robots: {stats['http_404']}")
    print(f"  Failed:   {stats['failed']} (network error / timeout)")
    print(f"  Empty:    {stats['empty']}")
    print(f"  HTML:     {stats['html']} (soft 404)")
    print(f"  Invalid:  {stats['invalid']} (no robots directives)")
    print(f"  Total:    {skipped + stats['saved']} / {len(all_domains)} domains have robots.txt")
    print(f"\nOutput: {ROBOTS_DIR}/")


def _request_shutdown(shutdown: asyncio.Event):
    if shutdown.is_set():
        log.warning("\nForce quit.")
        sys.exit(1)
    log.warning("\n\nShutting down gracefully (Ctrl+C again to force) ...")
    shutdown.set()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Fetch robots.txt from domains")
    p.add_argument("domains", help="Path to domains list")
    p.add_argument("--workers", type=int, default=20, help="Concurrent requests (default: 20)")
    p.add_argument("--timeout", type=int, default=5, help="HTTP timeout in seconds (default: 5)")
    args = p.parse_args()

    asyncio.run(main(args.domains, args.workers, args.timeout))