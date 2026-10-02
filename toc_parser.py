"""Parse విషయాలు / TOC pages from decoded edition extracts."""
from __future__ import annotations

import re
from typing import Any

TOC_MARKERS = ("విషయాలు", "పుట సంఖ్య", "క్రమసంఖ్య", "ఈ సంచికలో")
SERIES_MARKERS = ("సీరియల్", "సీరియలు", "serial")

# Entry like: title dots/spaces page_number  OR title\npage on next line (already flattened)
_ENTRY_INLINE = re.compile(
    r"^\s*(\d+)\s*[.،.]?\s*(.+?)\s*(?:\.{2,}|\s{2,}|\.+)\s*(\d+)\s*$"
)
_ENTRY_TITLE_ONLY = re.compile(r"^\s*(\d+)\s*[.،.]?\s*(.+?)\s*$")
_PAGE_ONLY = re.compile(r"^\s*(\d{1,3})\s*$")

_VOLUME = re.compile(r"సంపుటి\s*(\d+)")
_ISSUE = re.compile(r"సంచిక\s*(\d+)")


def _page_plain_text(page: dict) -> str:
    parts = []
    for b in page.get("blocks", []):
        t = (b.get("text") or "").strip()
        if t:
            parts.append(t)
    return "\n".join(parts)


def score_toc_page(text: str) -> int:
    score = 0
    for m in TOC_MARKERS:
        if m in text:
            score += 3
    # Numbered lines suggest TOC
    numbered = len(re.findall(r"^\s*\d+\s*[.]", text, re.M))
    score += min(numbered, 10)
    return score


def find_toc_pages(pages: list[dict]) -> list[int]:
    scored = []
    for p in pages:
        text = _page_plain_text(p)
        s = score_toc_page(text)
        if s >= 6:
            scored.append((s, p["page_number"], text))
    scored.sort(reverse=True)
    if not scored:
        return []
    # Keep top page(s) if close in score (multi-page TOC rare)
    best = scored[0][0]
    return [pn for s, pn, _ in scored if s >= best - 2]


def _clean_title(title: str) -> str:
    title = title.strip()
    title = re.sub(r"\s*\.{2,}\s*$", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip(" .…")


def _detect_series(title: str) -> str | None:
    lower = title
    for m in SERIES_MARKERS:
        if m in lower:
            # Prefer text before series marker as series name when patterned
            base = re.split(r"\.{2,}|\(", title)[0].strip(" .")
            return base or title
    # Known recurring columns (seed list; extended via series_aliases)
    seeds = (
        "తెలుసుకుందాం",
        "తెలుసుకుందామా",
        "విద్యార్థులారా",
        "స్వామి సందేశం",
        "స్వామి సూక్తులు",
        "సాయిమాట",
        "పద్య సూక్తి",
        "మన చారిత్రక",
        "బొమ్మల కథ",
        "స్వామి కథ",
        "నీతి కథలు",
        "విజ్ఞానం",
        "స్వామితో నా అనుభవం",
    )
    for s in seeds:
        if s in title:
            return s
    return None


def parse_toc_entries(text: str) -> list[dict[str, Any]]:
    """Parse TOC body into ordered entries with start pages.

    Supports:
    - inline: ``1. Title ..... 3``
    - title+page: ``1. Title`` / ``3``
    - split three lines: ``1.`` / ``Title`` / ``3`` (common in PageMaker extracts)
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    skip_exact = {
        "క్రమసంఖ్య",
        "విషయాలు",
        "పుట సంఖ్య",
        "ఈ సంచికలో . . . . .",
        "ఈ సంచికలో",
    }
    monthish = (
        "జనవరి",
        "ఫిబ్రవరి",
        "మార్చి",
        "ఏప్రిల్",
        "మే",
        "జూన్",
        "జూలై",
        "ఆగస్టు",
        "సెప్టెంబర్",
        "అక్టోబర్",
        "నవంబర్",
        "డిసెంబర్",
    )
    entries: list[dict[str, Any]] = []
    i = 0
    index_only = re.compile(r"^\s*(\d{1,2})\s*[.،.]?\s*$")

    while i < len(lines):
        line = lines[i]
        if line in skip_exact or line.startswith("సంపుటి") or line.startswith("సంచిక"):
            i += 1
            continue
        if any(m in line for m in monthish) and len(line) < 40:
            i += 1
            continue
        if "మాసపత్రిక" in line or line.startswith("శ్రీ సత్యసాయి"):
            i += 1
            continue

        m = _ENTRY_INLINE.match(line)
        if m:
            idx, title, page = m.group(1), _clean_title(m.group(2)), int(m.group(3))
            entries.append(
                {
                    "toc_index": int(idx),
                    "title": title,
                    "start_page": page,
                    "series": _detect_series(title),
                }
            )
            i += 1
            continue

        m2 = _ENTRY_TITLE_ONLY.match(line)
        if m2 and i + 1 < len(lines) and _PAGE_ONLY.match(lines[i + 1]):
            title_part = _clean_title(m2.group(2))
            if title_part:
                idx = int(m2.group(1))
                page = int(_PAGE_ONLY.match(lines[i + 1]).group(1))
                entries.append(
                    {
                        "toc_index": idx,
                        "title": title_part,
                        "start_page": page,
                        "series": _detect_series(title_part),
                    }
                )
                i += 2
                continue

        # Three-line: "1." / "Title" / "3"
        m3 = index_only.match(line)
        if m3 and i + 2 < len(lines):
            maybe_title = lines[i + 1]
            maybe_page = lines[i + 2]
            if (
                not index_only.match(maybe_title)
                and not _PAGE_ONLY.match(maybe_title)
                and _PAGE_ONLY.match(maybe_page)
                and len(maybe_title) >= 2
            ):
                idx = int(m3.group(1))
                title = _clean_title(maybe_title)
                page = int(_PAGE_ONLY.match(maybe_page).group(1))
                # Ignore trailing footer page numbers that look like TOC after real entries
                if page <= 200:
                    entries.append(
                        {
                            "toc_index": idx,
                            "title": title,
                            "start_page": page,
                            "series": _detect_series(title),
                        }
                    )
                    i += 3
                    continue

        i += 1

    for j, e in enumerate(entries):
        if j + 1 < len(entries):
            e["end_page"] = max(e["start_page"], entries[j + 1]["start_page"] - 1)
        else:
            e["end_page"] = None
    return entries


def extract_volume_issue(text: str) -> tuple[int | None, int | None]:
    vol = _VOLUME.search(text)
    iss = _ISSUE.search(text)
    return (
        int(vol.group(1)) if vol else None,
        int(iss.group(1)) if iss else None,
    )


def parse_edition_toc(extracted: dict[str, Any]) -> dict[str, Any]:
    pages = extracted.get("pages", [])
    toc_page_nums = find_toc_pages(pages)
    if not toc_page_nums:
        return {
            "toc_pages": [],
            "entries": [],
            "volume": None,
            "issue": None,
            "flags": ["toc_missing"],
        }

    texts = []
    for p in pages:
        if p["page_number"] in toc_page_nums:
            texts.append(_page_plain_text(p))
    combined = "\n".join(texts)
    volume, issue = extract_volume_issue(combined)
    entries = parse_toc_entries(combined)
    total_pages = extracted.get("total_pages") or len(pages)
    for e in entries:
        if e.get("end_page") is None:
            e["end_page"] = total_pages
    flags = []
    if not entries:
        flags.append("toc_parse_failed")
    return {
        "toc_pages": toc_page_nums,
        "entries": entries,
        "volume": volume,
        "issue": issue,
        "flags": flags,
    }
