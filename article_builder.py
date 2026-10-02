"""Build article records from TOC + page blocks; export JSON/Markdown."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from author_tagger import tag_article_authors
from catalog_builder import build_catalog_entries, export_catalog
from qa_metrics import article_review_flags
from telugu_normalize import normalize_telugu_text
from toc_parser import parse_edition_toc

_CONTINUATION = re.compile(r"ఇంకావుంది")
_MASTHEAD = re.compile(
    r"^(జనవరి|ఫిబ్రవరి|మార్చి|ఏప్రిల్|మే|జూన్|జూలై|ఆగస్టు|సెప్టెంబర్|అక్టోబర్|నవంబర్|డిసెంబర్)\s+\d{4}$"
)


def _is_noise_block(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if t in {"సంపుటి 1", "సంపుటి  1"} or t.startswith("సంపుటి"):
        return len(t) < 20
    if t.startswith("సంచిక") and len(t) < 20:
        return True
    if "బాలవికాస్" in t and len(t) < 40 and "\n" not in t:
        return True
    if _MASTHEAD.match(t):
        return True
    return False


def _blocks_for_pages(
    pages: list[dict],
    start: int,
    end: int,
    skip_pages: set[int] | None = None,
) -> list[dict]:
    out = []
    skip_pages = skip_pages or set()
    for p in pages:
        pn = p["page_number"]
        if pn in skip_pages:
            continue
        if start <= pn <= end:
            for b in p.get("blocks", []):
                text = (b.get("text") or "").strip()
                if _is_noise_block(text):
                    continue
                bb = dict(b)
                bb["page_number"] = pn
                out.append(bb)
    return out


def _load_series_aliases(path: str | None = None) -> dict[str, str]:
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "series_aliases.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("aliases", {})
    except OSError:
        return {}


def normalize_series(title: str | None, hint: str | None, aliases: dict[str, str]) -> str | None:
    raw = hint or title or ""
    for key, canon in aliases.items():
        if key in raw:
            return canon
    return hint


def _strip_leading_noise_lines(text: str) -> str:
    lines = text.splitlines()
    while lines and _is_noise_block(lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def _body_from_blocks(blocks: list[dict], exclude_right_as_body: bool = False) -> str:
    parts = []
    for b in blocks:
        if exclude_right_as_body and b.get("type") == "right_subheading":
            continue
        t = _strip_leading_noise_lines((b.get("text") or "").strip())
        if t and not _is_noise_block(t):
            parts.append(normalize_telugu_text(t))
    return "\n\n".join(parts)


def _make_article(
    *,
    article_id: str,
    title: str,
    start: int,
    end: int,
    series: str | None,
    authors: list,
    author_sources: list,
    body: str,
    continuation_of: str | None,
    toc_index: int,
    images: list,
    confidence: float,
    review_flags: list,
    kind: str = "article",
) -> dict:
    return {
        "id": article_id,
        "title": title,
        "start_page": start,
        "end_page": end,
        "series": series,
        "authors": authors,
        "author_sources": author_sources,
        "body_unicode": body,
        "continuation_of": continuation_of,
        "toc_index": toc_index,
        "images": images,
        "confidence": confidence,
        "review_flags": review_flags,
        "kind": kind,
    }


def _images_for_pages(extracted: dict, start: int, end: int) -> list[dict]:
    imgs = []
    for im in extracted.get("images", []):
        pn = im.get("page_number")
        if pn is not None and start <= pn <= end:
            imgs.append(im)
    # Also from page.images
    if not imgs:
        for p in extracted.get("pages", []):
            if start <= p["page_number"] <= end:
                imgs.extend(p.get("images") or [])
    return imgs


def _slug(title: str, toc_index: int) -> str:
    # Keep Telugu; sanitize path chars
    safe = re.sub(r'[<>:"/\\|?*]', "", title)
    safe = re.sub(r"\s+", "_", safe.strip())[:60]
    return f"{toc_index:02d}_{safe or 'article'}"


def build_articles(extracted: dict[str, Any]) -> dict[str, Any]:
    aliases = _load_series_aliases()
    toc = parse_edition_toc(extracted)
    pages = extracted.get("pages", [])
    total_pages = extracted.get("total_pages") or len(pages)
    qa_summary = extracted.get("qa_summary") or {}
    layout_flagged = qa_summary.get("flagged_pages") or []

    page_widths = {p["page_number"]: p.get("width") for p in pages}
    articles: list[dict] = []
    flags_global = list(toc.get("flags") or [])

    entries = toc.get("entries") or []
    toc_page_set = set(toc.get("toc_pages") or [])

    def _front_matter_article(start: int, end: int) -> dict:
        # Include all pages in range (masthead English lives outside TOC spine)
        blocks = _blocks_for_pages(pages, start, end, skip_pages=set())
        body = _body_from_blocks(blocks)
        return _make_article(
            article_id="00_front_matter",
            title="Edition front matter",
            start=start,
            end=end,
            series=None,
            authors=[],
            author_sources=[],
            body=body,
            continuation_of=None,
            toc_index=0,
            images=_images_for_pages(extracted, start, end),
            confidence=0.85,
            review_flags=[],
            kind="front_matter",
        )

    if not entries:
        flags_global.append("needs_review")
        flags_global.append("toc_parse_failed")
        body_blocks = _blocks_for_pages(pages, 1, total_pages, skip_pages=toc_page_set)
        body = _body_from_blocks(body_blocks)
        articles.append(
            _make_article(
                article_id="00_full_edition",
                title=extracted.get("metadata", {}).get("title") or "Untitled",
                start=1,
                end=total_pages,
                series=None,
                authors=[],
                author_sources=[],
                body=body,
                continuation_of=None,
                toc_index=0,
                images=_images_for_pages(extracted, 1, total_pages),
                confidence=0.3,
                review_flags=["needs_review", "toc_parse_failed"],
            )
        )
    else:
        first_start = min(int(e["start_page"]) for e in entries)
        if first_start > 1:
            articles.append(_front_matter_article(1, first_start - 1))

        for e in entries:
            start = int(e["start_page"])
            end = int(e.get("end_page") or total_pages)
            end = min(end, total_pages)
            start = max(1, min(start, total_pages))
            if end < start:
                end = start

            blocks = _blocks_for_pages(pages, start, end, skip_pages=toc_page_set)
            body = _body_from_blocks(blocks)
            width = page_widths.get(start)
            auth = tag_article_authors(
                blocks, body, page_width=width, toc_title=e.get("title")
            )
            series = normalize_series(e.get("title"), e.get("series"), aliases)

            cont = None
            if _CONTINUATION.search(body):
                cont = "continued_marker"

            art_pages = list(range(start, end + 1))
            author_conf = auth["author_confidence"]
            if not auth["authors"]:
                author_conf = 1.0

            rflags = article_review_flags(
                body,
                layout_flagged_pages=layout_flagged,
                article_pages=art_pages,
                toc_title=e.get("title"),
                found_title=e.get("title"),
                author_confidence=author_conf,
            )

            conf = 0.9
            if rflags:
                conf = 0.55
            if "empty_body" in rflags:
                conf = 0.2

            articles.append(
                _make_article(
                    article_id=_slug(e["title"], e["toc_index"]),
                    title=e["title"],
                    start=start,
                    end=end,
                    series=series,
                    authors=auth["authors"],
                    author_sources=auth["author_sources"],
                    body=body,
                    continuation_of=cont,
                    toc_index=e["toc_index"],
                    images=_images_for_pages(extracted, start, end),
                    confidence=conf,
                    review_flags=rflags,
                )
            )

        last_end = max(int(e.get("end_page") or total_pages) for e in entries)
        if last_end < total_pages:
            blocks = _blocks_for_pages(pages, last_end + 1, total_pages, skip_pages=toc_page_set)
            body = _body_from_blocks(blocks)
            if body.strip():
                articles.append(
                    _make_article(
                        article_id="99_back_matter",
                        title="Edition back matter",
                        start=last_end + 1,
                        end=total_pages,
                        series=None,
                        authors=[],
                        author_sources=[],
                        body=body,
                        continuation_of=None,
                        toc_index=999,
                        images=_images_for_pages(extracted, last_end + 1, total_pages),
                        confidence=0.7,
                        review_flags=[],
                        kind="back_matter",
                    )
                )

    return {
        "toc": toc,
        "articles": articles,
        "flags": list(dict.fromkeys(flags_global)),
    }


def export_edition_archive(
    extracted: dict[str, Any],
    edition_id: str,
    out_dir: str,
    year: int | None = None,
    month: int | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    art_dir = os.path.join(out_dir, "articles")
    if os.path.isdir(art_dir):
        for name in os.listdir(art_dir):
            if name.endswith(".json") or name.endswith(".md"):
                try:
                    os.remove(os.path.join(art_dir, name))
                except OSError:
                    pass
    os.makedirs(art_dir, exist_ok=True)

    built = build_articles(extracted)
    toc = built["toc"]

    edition_doc = {
        "id": edition_id,
        "title": title or extracted.get("metadata", {}).get("title") or edition_id,
        "pdf_path": extracted.get("pdf_path") or extracted.get("metadata", {}).get("path"),
        "publish_year": year,
        "publish_month": month,
        "volume": toc.get("volume"),
        "issue": toc.get("issue"),
        "total_pages": extracted.get("total_pages"),
        "toc_pages": toc.get("toc_pages"),
        "qa_summary": extracted.get("qa_summary"),
        "flags": built["flags"] + list((extracted.get("qa_summary") or {}).get("flags") or []),
        "article_ids": [a["id"] for a in built["articles"]],
    }
    edition_doc["flags"] = list(dict.fromkeys(edition_doc["flags"]))

    with open(os.path.join(out_dir, "edition.json"), "w", encoding="utf-8") as f:
        json.dump(edition_doc, f, ensure_ascii=False, indent=2)

    with open(os.path.join(out_dir, "qa_report.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "edition_id": edition_id,
                "qa_summary": extracted.get("qa_summary"),
                "page_qa": extracted.get("page_qa"),
                "toc_flags": toc.get("flags"),
                "articles_needing_review": [
                    {"id": a["id"], "title": a["title"], "flags": a["review_flags"]}
                    for a in built["articles"]
                    if a.get("review_flags")
                ],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    for a in built["articles"]:
        article_path = os.path.join(art_dir, f"{a['id']}.json")
        with open(article_path, "w", encoding="utf-8") as f:
            json.dump({**a, "edition_id": edition_id}, f, ensure_ascii=False, indent=2)

        md_path = os.path.join(art_dir, f"{a['id']}.md")
        authors = ", ".join(a.get("authors") or [])
        fm = [
            "---",
            f'title: "{a["title"].replace(chr(34), "")}"',
            f"edition: {edition_id}",
            f"pages: {a['start_page']}-{a['end_page']}",
            f'series: "{(a.get("series") or "").replace(chr(34), "")}"',
            f'authors: "{authors.replace(chr(34), "")}"',
            f"confidence: {a.get('confidence')}",
            f"flags: {json.dumps(a.get('review_flags') or [], ensure_ascii=False)}",
            "---",
            "",
            a.get("body_unicode") or "",
            "",
        ]
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(fm))

    catalog_entries = build_catalog_entries(
        edition_id, built["articles"], extracted=extracted
    )
    export_catalog(out_dir, edition_id, catalog_entries)
    edition_doc["catalog_count"] = len(catalog_entries)
    with open(os.path.join(out_dir, "edition.json"), "w", encoding="utf-8") as f:
        json.dump(edition_doc, f, ensure_ascii=False, indent=2)

    return {
        "edition": edition_doc,
        "articles": built["articles"],
        "catalog": catalog_entries,
    }
