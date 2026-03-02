#!/bin/bash
#!/usr/bin/env bash
set -eu

# Force C locale to avoid multibyte warnings from sort/grep/sed
export LC_ALL=C

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ROBOTS_DIR="./robots"
BADWORDS="./badwords/badwords.txt"
EXACT_BADWORDS="./badwords/exact_badwords.txt"
WORKING_DIR="./working"
TEMP=$(mktemp)
MIN_COUNT=4

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
for f in "$BADWORDS" "$EXACT_BADWORDS"; do
  [[ -f "$f" ]] || { echo "Missing: $f" >&2; exit 1; }
  sed -i 's/\r$//' "$f"
done

for d in "$ROBOTS_DIR"; do
  [[ -d "$d" ]] || { echo "Missing directory: $d" >&2; exit 1; }
done

mkdir -p "$WORKING_DIR"

# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------
draw_progress() {
  local current=$1 total=$2 width=40
  local filled=$(( total > 0 ? current * width / total : 0 ))
  (( filled > width )) && filled=$width
  printf -v bar "%${filled}s" ""; bar=${bar// /#}
  printf -v spc "%$((width - filled))s" ""
  printf "\r[%s%s] (%d/%d)" "$bar" "$spc" "$current" "$total"
}

# ---------------------------------------------------------------------------
# Remove robots which are known to have a lot of trash entries
# ---------------------------------------------------------------------------
rm -f "$ROBOTS_DIR"/tripadvisor.*.txt
rm -f "$ROBOTS_DIR"/tamgrt.com.txt
rm -f "$ROBOTS_DIR"/booking.*.txt
rm -f "$ROBOTS_DIR"/activehotels.com.txt
rm -f "$ROBOTS_DIR"/next.*.txt
rm -f "$ROBOTS_DIR"/nextdirect.*.txt
rm -f "$ROBOTS_DIR"/hotelscombined.*.txt
rm -f "$ROBOTS_DIR"/kayak.*.txt
rm -f "$ROBOTS_DIR"/momondo.*.txt
rm -f "$ROBOTS_DIR"/mundi.*.txt
rm -f "$ROBOTS_DIR"/swoodoo.*.txt
rm -f "$ROBOTS_DIR"/checkfelix.com.txt

# ---------------------------------------------------------------------------
# Step 1: Parse robots.txt files -> one cleaned file per domain
# ---------------------------------------------------------------------------
echo "=== Step 1: Parsing robots.txt files ==="
PARSED_DIR="$WORKING_DIR/parsed_robots"
rm -rf "$PARSED_DIR"; mkdir -p "$PARSED_DIR"

robots_files=()
while IFS= read -r -d '' f; do
  robots_files+=("$f")
done < <(find "$ROBOTS_DIR" -type f -name '*.txt' -print0)

total=${#robots_files[@]}
i=0
for f in "${robots_files[@]}"; do
  i=$((i + 1))
  draw_progress "$i" "$total"

  domain="$(basename "$f" .txt)"
  outfile="$PARSED_DIR/${domain}.txt"

# Extract Allow/Disallow paths from all robots.txt files
  grep -hEi '^\s*((Dis)?Allow:|Noindex:)\s' "$f" \
  | sed -E 's/^\s*((Dis)?Allow:|Noindex:)\s*//i' \
  | tr '/' '\n' \
  | sed -E '
      s/[[:space:]]+$//     # Remove whitespace
      s/\?.*//              # Remove query strings
      /\*/d                 # Remove lines with asterisks
      s/\$+$//              # Remove $ anchors
      /$domain/d            # Remove domain lines
      /-$/d                 # Remove lines ending with minus
      /^([a-zA-Z]|[0-9])$/d # Remove lines with just one character
  ' \
  | grep -P '^[A-Za-z0-9/._~-]+$' \
  | awk 'BEGIN{IGNORECASE=0} /^[[:upper:]][^[:upper:]]*$/ {print tolower($0); next} {print}' \
  | grep -v '^\s*$' \
  | sed -E '
      /\.(png|jpe?g|gif|bmp|svg|ico|webp|pif)$/Id
      /\.(woff2?|ttf|otf|eot|swf|tiff?|tex)$/Id
      /\.(map|s?css)$/Id
      /\.(mp3|mp4|aac|avif?|mov|mkv|wav|webm|ogg|flac|mpeg|mpg|flv)$/Id
      /\.(pdf|doc|docx|xls|xlsx|ppt|pptx)$/Id
      /\.(m?js|rb|java|vue|py(thon)?|dll|pl|egg|mo|po|cs|resx|ascx)$/Id
      /\.(class|com|exe|ram|scr|snp|ajax)$/Id
      /^[^.]/ s/\.(html?|php|phtml|as(px|hx|mx|p)|jspx?|cgi|cfm)$/\.%EXT%/I
    ' \
  | sort -u \
  > "$outfile"

  [[ -s "$outfile" ]] || rm -f "$outfile"
done

# ---------------------------------------------------------------------------
# Step 2: Aggregate and count
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 2: Aggregating entries ==="

UNFILTERED=$(mktemp)
cat "$PARSED_DIR"/*.txt \
  | sort \
  | uniq -c \
  | sort -nr \
  | awk '$1 >= 10' \
  > "$UNFILTERED"

TOTAL_RAW=$(wc -l < "$UNFILTERED")
echo "[*] Extracted $TOTAL_RAW unique entries."

# ---------------------------------------------------------------------------
# Step 3: Clean each parsed file
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 3: Cleaning parsed entries ==="

grep -Ev -- '--[0-9a-zA-Z]' "$UNFILTERED" \
  | grep -Ev '^\s*[0-9]*\s*\.\.$' \
  | grep -Ev '([-_].*){3,}' \
  | grep -Evi '^\s*[0-9]*\s*[a-z]{2}[-_][a-z]{2}/?$' \
  | grep -Evi -f <(sed -E 's#^[[:space:]]*[0-9]*[[:space:]]*##' "$BADWORDS") \
  | grep -Evi -f <(sed 's#^#^[[:space:]]*[0-9]+[[:space:]]+#; s#$#/?$#' "$EXACT_BADWORDS") \
  | sed -E '
      /^[[:space:]]*[0-9]*[[:space:]]*[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/d
      /^[[:space:]]*[0-9]*[[:space:]]*[a-fA-F0-9]{20,}?$/d
      /^[[:space:]]*[0-9]*[[:space:]]*((al|ag|at|ak|af|ae|ad|ac|ab)[0-9]{4}|e[0-9]{5}|su[0-9]{6})/d
      /^[[:space:]]*[0-9]*[[:space:]]*[-_][0-9]{1,2}$/d
      /^[[:space:]]*[0-9]*[[:space:]]*-[0-9]-[0-9]$/d
      /^[[:space:]]*[0-9]*[[:space:]]*\.\.$/d
      /^[[:space:]]*[0-9]*[[:space:]]*_?_$/d
      /^[[:space:]]*[0-9]*[[:space:]]*[^[:alnum:]]$/d
      /^[[:space:]]*[0-9]*[[:space:]]*(tar|sql)\.(gz|bz2|xz|zst)$/d
    ' \
  > "all_counted.txt"

# ---------------------------------------------------------------------------
# Step 4: Create Burp-format lists (files + directories)
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 4: Creating Burp-format lists ==="

sed -E 's/^[[:space:]]*[0-9]+[[:space:]]+//' "./all_counted.txt" > "./dirsearch-robots.txt"

grep -E '.\.[a-zA-Z0-9%]{2,}$' ./dirsearch-robots.txt \
  > "./burp-robots-files.txt"

grep -Fxv -f ./burp-robots-files.txt .dirsearch-robots.txt \
  > "./burp-robots-directories.txt"

TOTAL_ENTRIES=$(wc -l < "./dirsearch-robots.txt")
FILES_COUNT=$(wc -l < "./burp-robots-files.txt")
DIRS_COUNT=$(wc -l < "./burp-robots-directories.txt")

rm -rf "$WORKING_DIR/"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
FINAL=$(wc -l < "$OUTPUT")
echo ""
echo "=== Done ==="
echo "  dirsearch-robots.txt         - combined list ($TOTAL_ENTRIES entries)"
echo "  burp-robots-files.txt        - files only ($FILES_COUNT entries)"
echo "  burp-robots-directories.txt  - directories only ($DIRS_COUNT entries)"
echo "  all_counted.txt              - full counts for analysis (>= 10)"
