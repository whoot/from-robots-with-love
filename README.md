# From Robots With Love

A [Burp Professional](https://portswigger.net/burp/pro) and [dirsearch](https://github.com/maurosoria/dirsearch) optimized wordlist for content discovery, built by scraping and analyzing `/robots.txt` from the [top 100k most visited domains](https://radar.cloudflare.com/domains) in February 2026.

## Wordlists

| File | Tool | Description |
|------|------|-------------|
| `dirsearch-robots.txt` | dirsearch | Combined wordlist with `%EXT%` placeholders for dirsearch's extension handling |
| `burp-robots-files.txt` | Burp Suite | Files only (required by Burp's Content Discovery) |
| `burp-robots-directories.txt` | Burp Suite | Directories only (required by Burp's Content Discovery) |

The underlying content is the same - the Burp lists are simply the dirsearch list split into files and directories.

## Usage

### Basic usage

The wordlist contains one entry per line and is optimized for recursive scanning:

```bash
python3 dirsearch.py --random-agent -u https://target.com \
  -w dirsearch-robots.txt \
  --recursive -R 3
```

### Using extensions (recommended)

The wordlist uses `%EXT%` placeholders for server-side files. Define extensions based on the target stack to keep scans efficient and avoid testing irrelevant file types:

```bash
python3 dirsearch.py --random-agent -u https://target.com \
  -w dirsearch-robots.txt \
  --recursive -R 3 \
  -e php,html
```

### Case variations

The wordlist is primarily lowercase. Let dirsearch handle case transformations automatically:

```bash
python3 dirsearch.py -u https://target.com \
  -w dirsearch-robots.txt \
  --recursive -R 3 \
  -e php \
  --capital
```

### Tips

- Choose extensions based on the target stack to avoid unnecessary requests.
- Adjust case transformations depending on the target environment.
- Use recursion for deeper discovery.
- Refer to the [dirsearch](https://github.com/maurosoria/dirsearch?tab=readme-ov-file#options) and [Burp](https://portswigger.net/burp/documentation/desktop/tools/engagement-tools/content-discovery) documentation for additional tuning options.

## Motivation

In pentests, a common question is: *Which wordlist should I use for content discovery?*

For many testers, the go-to choice is [SecLists / Discovery / Web-Content](https://github.com/danielmiessler/SecLists/tree/master/Discovery/Web-Content). However, many of those wordlists come with practical limitations:

- **Outdated coverage** - some lists are 3-9 years old and don't reflect modern applications and technologies.
- **Redundant extensions** - entries like `file.php`, `file.html`, `file.json` test the same path with every extension, most of which won't exist on the target.
- **Overlap between lists** - the same paths appear across multiple wordlists, leading to duplicate requests.
- **Noisy entries** - static assets (e.g. JavaScript files) and questionable entries (looking at you, `raft-*.txt`) add bulk without value.

The result is unnecessary requests, increased brute-force time, and less focused testing.

## Approach

This project aims to create a universal and (relatively) compact wordlist that captures the most common directories and files while leveraging dirsearch's built-in features.

1. Crawl `/robots.txt` from the top 100,000 most visited domains.
2. Extract and clean paths from `Disallow`/`Allow` directives.
3. Remove noise (see below).
4. Sort entries by frequency of occurrence across domains.

### Filtering

To reduce noise and improve scan efficiency, the following categories are removed:

- Sex-related terms
- Non-English/German language-specific words
- Site-specific or highly contextual paths (e.g. product filter URLs from individual shops)
- Language and country codes
- City and brand names
- Static content (JavaScript files, images, fonts, etc.)
- Entries that don't meaningfully contribute to discovery
