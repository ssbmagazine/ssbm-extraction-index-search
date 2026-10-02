"""Layout coverage and Telugu glyph-composition quality metrics."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

# Telugu consonants (including archaic)
_TELUGU_CONSONANT = r"[క-హౘ-ౚ]"
# Combining vowel signs / anusvara etc.
_TELUGU_MATRA = r"[ా-ౄె-ౌౕౖఁ-ః]"
# Independent vowels that often appear when a gunintam map was missed
_TELUGU_INDEPENDENT_VOWEL = r"[అ-ఌఎ-ఐఒ-ఔ]"

# Latin / leftover Anu bytes that survived decode (excluding whitespace/punct commonly kept)
_LATIN_LEFTOVER = re.compile(r"[A-Za-z\u0080-\u024F\u0370-\u03FF\u2000-\u206F\u20A0-\u20CF]")

# Consonant immediately followed by independent vowel (split look) — rare in correct Telugu
_SPLIT_INDEPENDENT = re.compile(rf"({_TELUGU_CONSONANT})({_TELUGU_INDEPENDENT_VOWEL})")

# Orphan combining mark at start of token / after space / after punctuation
_ORPHAN_MATRA = re.compile(rf"(^|[\s\u200c\u200d.,;:!?\-—–\"'()])({_TELUGU_MATRA})")

# Consonant + space + matra (decoder left them apart)
_SPLIT_SPACE_MATRA = re.compile(rf"({_TELUGU_CONSONANT})\s+({_TELUGU_MATRA})")
# Consonant + space + virama+consonant (లక్ష ్మ)
_SPLIT_VIRAMA = re.compile(rf"({_TELUGU_CONSONANT})\s+(్{_TELUGU_CONSONANT})")


def analyze_text_glyphs(text: str) -> dict[str, Any]:
    if not text:
        return {
            "char_count": 0,
            "latin_leftover_count": 0,
            "latin_samples": [],
            "split_matra_count": 0,
            "split_samples": [],
            "orphan_matra_count": 0,
        }

    latin_matches = _LATIN_LEFTOVER.findall(text)
    split_indep = _SPLIT_INDEPENDENT.findall(text)
    split_space = _SPLIT_SPACE_MATRA.findall(text)
    split_virama = _SPLIT_VIRAMA.findall(text)
    orphan = _ORPHAN_MATRA.findall(text)

    split_samples = []
    for a, b in (split_indep + split_space + split_virama)[:20]:
        split_samples.append(f"{a}{b}")

    latin_counter = Counter(latin_matches)
    return {
        "char_count": len(text),
        "latin_leftover_count": len(latin_matches),
        "latin_samples": [c for c, _ in latin_counter.most_common(15)],
        "split_matra_count": len(split_indep) + len(split_space) + len(split_virama),
        "split_virama_count": len(split_virama),
        "split_samples": split_samples[:15],
        "orphan_matra_count": len(orphan),
    }


def page_layout_coverage(
    raw_text_span_count: int,
    kept_span_count: int,
    raw_text_block_count: int,
    kept_block_count: int,
    dropped_by_header_footer: int,
) -> dict[str, Any]:
    span_drop = 0.0
    if raw_text_span_count > 0:
        span_drop = 1.0 - (kept_span_count / raw_text_span_count)

    flags = []
    # High drop after filters (excluding expected header/footer) is suspicious
    body_raw = max(raw_text_span_count - dropped_by_header_footer, 1)
    body_kept_ratio = kept_span_count / body_raw if body_raw else 1.0
    if body_kept_ratio < 0.75 and raw_text_span_count > 10:
        flags.append("layout_gap")

    return {
        "raw_text_spans": raw_text_span_count,
        "kept_spans": kept_span_count,
        "raw_text_blocks": raw_text_block_count,
        "kept_blocks": kept_block_count,
        "dropped_header_footer_spans": dropped_by_header_footer,
        "span_drop_rate": round(span_drop, 4),
        "body_kept_ratio": round(body_kept_ratio, 4),
        "flags": flags,
    }


def merge_edition_qa(page_reports: list[dict[str, Any]]) -> dict[str, Any]:
    latin = 0
    split = 0
    orphan = 0
    chars = 0
    layout_flags = 0
    latin_counter: Counter = Counter()
    split_counter: Counter = Counter()
    flagged_pages: list[int] = []

    for pr in page_reports:
        g = pr.get("glyphs", {})
        latin += g.get("latin_leftover_count", 0)
        split += g.get("split_matra_count", 0)
        orphan += g.get("orphan_matra_count", 0)
        chars += g.get("char_count", 0)
        for s in g.get("latin_samples", []):
            latin_counter[s] += 1
        for s in g.get("split_samples", []):
            split_counter[s] += 1
        layout = pr.get("layout", {})
        if layout.get("flags"):
            layout_flags += 1
            flagged_pages.append(pr.get("page_number"))

    flags = []
    if chars > 0 and (latin / chars) > 0.02:
        flags.append("unmapped_glyph")
    if chars > 0 and (split / max(chars, 1)) > 0.005:
        flags.append("glyph_split_matra")
    if layout_flags:
        flags.append("layout_gap")
    if flags:
        flags.append("needs_review")

    return {
        "total_chars": chars,
        "latin_leftover_count": latin,
        "latin_leftover_rate": round(latin / chars, 6) if chars else 0.0,
        "split_matra_count": split,
        "orphan_matra_count": orphan,
        "pages_with_layout_flags": layout_flags,
        "flagged_pages": flagged_pages,
        "top_latin_samples": [c for c, _ in latin_counter.most_common(20)],
        "top_split_samples": [c for c, _ in split_counter.most_common(20)],
        "flags": flags,
    }


def article_review_flags(
    body: str,
    layout_flagged_pages: list[int] | None = None,
    article_pages: list[int] | None = None,
    toc_title: str | None = None,
    found_title: str | None = None,
    author_confidence: float = 1.0,
) -> list[str]:
    flags: list[str] = []
    g = analyze_text_glyphs(body or "")
    if g["latin_leftover_count"] > 5:
        flags.append("unmapped_glyph")
    if g["split_matra_count"] > 2:
        flags.append("glyph_split_matra")
    if layout_flagged_pages and article_pages:
        if any(p in layout_flagged_pages for p in article_pages):
            flags.append("layout_gap")
    if toc_title and found_title:
        # rough mismatch: very short overlap
        if toc_title.strip() and found_title.strip():
            if toc_title.strip()[:8] not in found_title and found_title.strip()[:8] not in toc_title:
                flags.append("toc_mismatch")
    if author_confidence < 0.5:
        flags.append("author_uncertain")
    if not (body or "").strip():
        flags.append("empty_body")
    if flags:
        flags.append("needs_review")
    return list(dict.fromkeys(flags))
