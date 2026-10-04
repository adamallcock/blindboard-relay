#!/usr/bin/env python3
# Vendored from benchkit@0.3.10 (sha256:76a9461a0ee28304). Do not hand-edit; run 'benchkit sync' to update.
"""Verify references.bib against the arXiv Atom API.

For every entry with an eprint id: fetch canonical title + authors,
compare with the bib, and (with --apply) fix author lists that are
placeholders ('Anonymous' / bare 'and others') using the canonical list
(first three authors + 'and others'). Title mismatches are reported for
manual review, never auto-applied.

Network: read-only GETs against export.arxiv.org, chunked (10 ids/call),
10s between chunks, and 429s retried with a 45s/90s/135s/180s backoff —
stay polite to the arXiv API."""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_BIB = Path(__file__).resolve().parents[1] / "paper" / "references.bib"
NS = {"a": "http://www.w3.org/2005/Atom"}
USER_AGENT = "benchkit-bib-verify/1.0"


def fetch(ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 10):
        chunk = ids[i : i + 10]
        url = "http://export.arxiv.org/api/query?id_list=" + ",".join(chunk) + f"&max_results={len(chunk)}"
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=60) as r:
                    tree = ET.fromstring(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 4:
                    time.sleep(45 * (attempt + 1))
                    continue
                raise
        for entry in tree.findall("a:entry", NS):
            eid = entry.findtext("a:id", "", NS)
            m = re.search(r"abs/([0-9.]+)", eid)
            if not m:
                continue
            title = re.sub(r"\s+", " ", entry.findtext("a:title", "", NS)).strip()
            authors = [a.findtext("a:name", "", NS) for a in entry.findall("a:author", NS)]
            out[m.group(1)] = {"title": title, "authors": authors}
        time.sleep(10)
    return out


def bibtex_authors(names: list[str]) -> str:
    def flip(n: str) -> str:
        parts = n.strip().split()
        return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else n
    head = [flip(n) for n in names[:3]]
    return " and ".join(head) + (" and others" if len(names) > 3 else "")


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _entry_end(lines: list[str], start: int) -> int:
    """Index of the physical line that closes the @entry{...} opened at `start`
    (brace-balanced). Returns `start` for a one-line entry."""
    depth = 0
    for j in range(start, len(lines)):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth <= 0:
            return j
    return len(lines) - 1


def iter_entries(lines: list[str]):
    """Yield (start_idx, end_idx, flat_text) per @type{...} entry, tolerating both
    one-line-per-entry and one-field-per-line bib formats. `flat_text` is the entry
    collapsed to a single line with 'field = {' spacing normalized to 'field={'."""
    i, n = 0, len(lines)
    while i < n:
        if not lines[i].lstrip().startswith("@"):
            i += 1
            continue
        end = _entry_end(lines, i)
        joined = " ".join(part.strip() for part in lines[i : end + 1])
        yield i, end, re.sub(r"\s*=\s*\{", "={", joined)
        i = end + 1


def parse_entries(lines: list[str]) -> list[tuple[int, str, str, str, str]]:
    """(start_line_idx, key, eprint, title, author) for each arXiv entry.

    Tolerates both the one-line-per-entry convention and human-formatted
    (one-field-per-line) bibs: each entry is brace-balanced and flattened before
    field extraction, so a multi-line entry is matched, not silently skipped.
    """
    entries = []
    for start, _end, flat in iter_entries(lines):
        m = re.match(r"@\w+\{([^,]+),", flat)
        if not m or "eprint={" not in flat:
            continue
        eprint_m = re.search(r"eprint=\{([0-9.]+)\}", flat)
        if not eprint_m:
            continue
        title = re.search(r"title=\{(.+?)\}\s*,", flat)
        author = re.search(r"author=\{(.+?)\}\s*,", flat)
        entries.append((
            start,
            m.group(1).strip(),
            eprint_m.group(1),
            title.group(1) if title else "",
            author.group(1) if author else "",
        ))
    return entries


def verification_looked(bib_text: str, matched_entries: int) -> bool:
    """False when the bib plainly carries arXiv eprints but the parser matched none
    -- i.e. verification silently did not run. Guards the multi-line no-op: a bib
    with `eprint={...}` fields that yields zero parsed entries has not been checked."""
    expected = len(re.findall(r"eprint\s*=\s*\{", bib_text))
    return not (expected > 0 and matched_entries == 0)


def apply_author_fix(lines: list[str], start_idx: int, new_author: str) -> bool:
    """Rewrite the author={...} field of the entry starting at start_idx, in place.
    Works for one-line and multi-line entries; returns whether a line changed."""
    for j in range(start_idx, _entry_end(lines, start_idx) + 1):
        if re.search(r"author\s*=\s*\{", lines[j]):
            lines[j] = re.sub(
                r"(author\s*=\s*\{).*?(\}\s*,?)",
                lambda mm: f"{mm.group(1)}{new_author}{mm.group(2)}",
                lines[j],
                count=1,
            )
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--bib", type=Path, default=DEFAULT_BIB,
                        help="path to references.bib (default: <repo>/paper/references.bib)")
    args = parser.parse_args()

    if not args.bib.exists():
        print(f"error: bib file not found: {args.bib}", file=sys.stderr)
        raise SystemExit(2)
    text = args.bib.read_text()
    lines = text.splitlines()
    entries = parse_entries(lines)

    # Prove the parser looked: a bib with eprint fields that matched zero entries
    # means verification did not run (the classic multi-line silent no-op). Fail
    # loudly here, before the network fetch, rather than report an empty pass.
    if not verification_looked(text, len(entries)):
        expected = len(re.findall(r"eprint\s*=\s*\{", text))
        print(f"FAIL: bib has {expected} eprint field(s) but the parser matched 0 "
              f"entries -- bib verification did not run (multi-line parse failure?).",
              file=sys.stderr)
        return 1

    canon = fetch([e[2] for e in entries])
    fixed = mismatches = missing = 0
    for i, key, eprint, title, author in entries:
        c = canon.get(eprint)
        if not c:
            print(f"MISSING  {key} (arXiv:{eprint}) — not returned by API")
            missing += 1
            continue
        bib_t = norm_title(re.sub(r"[{}]", "", title))
        api_t = norm_title(c["title"])
        if bib_t and api_t and bib_t not in api_t and api_t not in bib_t:
            print(f"TITLE?   {key}: bib='{title[:60]}' api='{c['title'][:60]}'")
            mismatches += 1
        placeholder = "Anonymous" in author or author.strip() in ("and others", "")
        first_bib = re.sub(r"[{}]", "", author.split(" and ")[0]).split(",")[0].strip().lower()
        first_api = c["authors"][0].split()[-1].lower() if c["authors"] else ""
        wrong_first = bool(first_bib) and bool(first_api) and first_bib != first_api and not placeholder
        if placeholder or wrong_first:
            new_auth = bibtex_authors(c["authors"])
            tag = "FIX-PLACEHOLDER" if placeholder else "FIX-WRONG-FIRST"
            print(f"{tag:16s} {key}: -> {new_auth[:80]}")
            if args.apply and apply_author_fix(lines, i, new_auth):
                fixed += 1
    if args.apply:
        args.bib.write_text("\n".join(lines) + "\n")
    print(f"\n{len(entries)} arXiv entries | fixed {fixed} | title-mismatches {mismatches} | missing {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
