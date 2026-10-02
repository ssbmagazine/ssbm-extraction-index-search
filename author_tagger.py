"""Author auto-tagging from right-aligned subheadings and dash attributions."""
from __future__ import annotations

import re
from typing import Any

_DASH_AUTHOR = re.compile(
    r"(?m)^\s*[-–—]{1,2}\s*([^\n\-–—]{2,60}?)\s*\.?\s*$"
)
_INLINE_DASH = re.compile(
    r"[-–—]{1,2}\s*((?:శ్రీమతి|శ్రీ|సా\.?|డా\.?|కుమారి)?\s*[ఁ-౿A-Za-z. ]{2,40})\s*\.?\s*$"
)

# Reject obvious non-authors
_REJECT = re.compile(
    r"(ఇంకావుంది|నీతి|భావం|Printed|Published|సంపాదక|జవాబు|క్విజ్)",
    re.I,
)


def _clean_author_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"^[-–—\s]+", "", name)
    name = name.strip(" .,-–—")
    return name


def _is_plausible_author(name: str) -> bool:
    name = _clean_author_name(name)
    if len(name) < 2 or len(name) > 50:
        return False
    if _REJECT.search(name):
        return False
    if name.isdigit():
        return False
    if name in {"వినోదం", "విజ్ఞానం", "భావం"}:
        return False
    return True


def authors_from_trailing_dashes(text: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    tail_lines = lines[-12:]
    tail = "\n".join(tail_lines)
    for m in _DASH_AUTHOR.finditer(tail):
        name = _clean_author_name(m.group(1))
        if _is_plausible_author(name):
            found.append(
                {
                    "name": name,
                    "source": "trailing_dash",
                    "confidence": 0.85,
                }
            )
    for ln in tail_lines[-4:]:
        m = _INLINE_DASH.search(ln)
        if m and re.match(r"^[-–—]", ln.strip()):
            name = _clean_author_name(m.group(1))
            if _is_plausible_author(name) and not any(a["name"] == name for a in found):
                found.append(
                    {"name": name, "source": "trailing_dash", "confidence": 0.8}
                )
    return found


def authors_from_right_subheadings(
    blocks: list[dict],
    page_width: float | None = None,
) -> list[dict[str, Any]]:
    """Short right-aligned blocks near the top of an article (byline)."""
    found: list[dict[str, Any]] = []
    # Prefer blocks already classified
    candidates = [b for b in blocks if b.get("type") == "right_subheading"]
    if not candidates and page_width:
        for b in blocks:
            bbox = b.get("bbox") or [0, 0, 0, 0]
            x0, y0, x1, y1 = bbox
            text = (b.get("text") or "").strip()
            if not text or text.count("\n") > 1:
                continue
            if len(text) > 50:
                continue
            if x0 > page_width * 0.55:
                candidates.append(b)

    for b in candidates[:3]:
        text = (b.get("text") or "").strip()
        name = _clean_author_name(text.split("\n")[0])
        if _is_plausible_author(name):
            found.append(
                {
                    "name": name,
                    "source": "right_subheading",
                    "confidence": 0.75,
                    "bbox": b.get("bbox"),
                }
            )
    return found


def merge_authors(*groups: list[dict[str, Any]]) -> tuple[list[str], list[dict], float]:
    """Return unique author names, source records, and max confidence."""
    by_name: dict[str, dict] = {}
    for group in groups:
        for a in group:
            name = _clean_author_name(a["name"])
            if not _is_plausible_author(name):
                continue
            rec = dict(a)
            rec["name"] = name
            prev = by_name.get(name)
            if not prev or rec.get("confidence", 0) > prev.get("confidence", 0):
                by_name[name] = rec
    records = list(by_name.values())
    names = [r["name"] for r in records]
    conf = max((r.get("confidence", 0) for r in records), default=1.0)
    return names, records, conf


def authors_from_toc_title(title: str) -> list[dict[str, Any]]:
    """Occasionally TOC embeds an author after dots (e.g. …శ్రీమతి లలితమ్మ)."""
    if not title:
        return []
    m = re.search(
        r"(?:\.{2,}|…)\s*((?:శ్రీమతి|శ్రీ|డా\.?|సా\.?)[^.]{2,40})$",
        title.strip(),
    )
    if not m:
        return []
    name = _clean_author_name(m.group(1))
    if _is_plausible_author(name):
        return [{"name": name, "source": "toc_title", "confidence": 0.7}]
    return []


def tag_article_authors(
    article_blocks: list[dict],
    body_text: str,
    page_width: float | None = None,
    toc_title: str | None = None,
) -> dict[str, Any]:
    right = authors_from_right_subheadings(article_blocks, page_width)
    dashes = authors_from_trailing_dashes(body_text)
    from_toc = authors_from_toc_title(toc_title or "")
    names, sources, conf = merge_authors(right, dashes, from_toc)
    return {
        "authors": names,
        "author_sources": sources,
        "author_confidence": conf,
    }
