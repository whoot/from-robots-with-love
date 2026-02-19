# Trust Me Im A Robot
A [dirsearch](https://github.com/maurosoria/dirsearch) optimized wordlist scraped from the [top 100k most visited domains](https://radar.cloudflare.com/domains).

## Usage
The wordlist is optimized for use with dirsearch, especially its extension handling and case transformation features.

For best results:
- Choose extensions based on the target stack to avoid testing unnecessary file types.
- Use recursion for deeper discovery.
- Adjust case transformations depending on the target environment.
- Look into the [dirsearch documentation](https://github.com/maurosoria/dirsearch?tab=readme-ov-file#options) and select more parameters according to your needs.

### Basic usage
Since the wordlist contains one entry per line, it is optimized for recursive scanning (shown here with a maximum depth of 3):
```
python3 dirsearch.py --random-agent -u https://target.com -w trust-me-im-a-robot.txt --recursive -R 3
```

### Using extensions (recommended)

The wordlist uses generic entries and `%EXT%` placeholders where applicable.
You should define relevant extensions depending on the target technology.
```
python3 dirsearch.py --random-agent -u https://target.com \
  -w trust-me-im-a-robot.txt \
  --recursive -R 3 \
  -e php,html
```

This avoids testing irrelevant file types and keeps scans efficient.

### Case variations

The wordlist is primarily lowercase.
You can let dirsearch handle case variations automatically:
```
python3 dirsearch.py -u https://target.com \
  -w trust-me-im-a-robot.txt \
  --recursive -R 3 \
  -e php \
  --capital
```

## Why
In pentests, a common question is: *Which wordlist(s) should I use for (hidden) content discovery?* \
For many testers, the first choice is probably [SecLists / Discovery / Web-Content](https://github.com/danielmiessler/SecLists/tree/master/Discovery/Web-Content). \
However, many of the wordlists included there have certain limitations that can lead to practical challenges during testing:

- Modern software and current technologies are often not adequately represented, as some wordlists are already 3 to 9 years old.
- Multiple wordlists contain identical or very similar entries (like `file.php`, `file.html`, `file.json`, ...) so you will always test files that are unlikely to exist (e.g. PHP files on non-PHP applications).
- The same paths/files are tested multiple times across different wordlists.
- Some lists include static content that may not be relevant (e.g. JavaScript files) or contain, let’s say, 'unwanted' entries (looking at you, `raft-*.txt`!).

The result is unnecessary requests, increased brute-force time, and less focused testing.

## Approach
I wanted to address this by creating a universal and relatively compact wordlist that contains the most common directories and files while leveraging dirsearch’s built-in functionality.

- Crawl the top 100,000 most visited domains and collect `/robots.txt` entries.
- Parse, normalize, and filter the extracted paths.
- Sort entries based on frequency of occurrence.
- Selectively include still relevant entries from SecLists.
- Keep the list clean, focused, and optimized for modern content discovery.


### Filtering

To improve usability and reduce noise, the dataset was cleaned by removing entries that are typically not useful for content discovery, including:

- Sex-related terms
- Language-specific words (except English and German)
- Website-specific or highly contextual paths
- Language codes
- Country and city names
- Brand names
- Static content (primarily JavaScript files)
- Other entries that do not meaningfully contribute to discovery
