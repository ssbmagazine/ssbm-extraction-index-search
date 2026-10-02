"""Build P1 catalog entries: heading / author / series from TOC + layout."""
from __future__ import annotations

import json
import os
import re
from typing import Any

_SERIES_NUM = re.compile(r"(?:సంచిక|సంఖ్య|no\.?|#)\s*(\d+)", re.I)
_SERIES_NUM_TAIL = re.compile(r"[-–—]?\s*(\d+)\s*$")


def load_series_catalog(path: str | None = None) -> list[str]:
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "series_catalog.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("series") or [])
    except OSError:
        return []


def _match_series(text: str, catalog: list[str]) -> tuple[str | None, int | None]:
    t = (text or "").strip()
    if not t:
        return None, None
    for name in sorted(catalog, key=len, reverse=True):
        if name and name in t:
            num = None
            m = _SERIES_NUM.search(t) or _SERIES_NUM_TAIL.search(t.replace(name, "").strip())
            if m:
                try:
                    num = int(m.group(1))
                except ValueError:
                    num = None
            return name, num
    return None, None


def build_catalog_entries(
    edition_id: str,
    articles: list[dict],
    extracted: dict[str, Any] | None = None,
) -> list[dict]:
    """Emit catalog rows for headings, authors, series."""
    catalog = load_series_catalog()
    entries: list[dict] = []
    eid_counter = 0

    def add(**kwargs):
        nonlocal eid_counter
        eid_counter += 1
        row = {
            "id": f"{edition_id}-cat-{eid_counter:04d}",
            "edition_id": edition_id,
            **kwargs,
        }
        entries.append(row)

    pages_by_num = {}
    if extracted:
        for p in extracted.get("pages") or []:
            pages_by_num[p["page_number"]] = p

    for art in articles:
        aid = art["id"]
        title = (art.get("title") or "").strip()
        if title and art.get("kind") not in ("front_matter", "back_matter"):
            add(
                article_id=aid,
                kind="heading",
                text=title,
                page=art.get("start_page"),
                alignment="center",
                source="toc",
                series_number=None,
            )

        series = art.get("series")
        if series:
            add(
                article_id=aid,
                kind="series",
                text=series,
                page=art.get("start_page"),
                alignment="center",
                source="toc_or_alias",
                series_number=None,
            )

        for author in art.get("authors") or []:
            add(
                article_id=aid,
                kind="author",
                text=author,
                page=art.get("end_page") or art.get("start_page"),
                alignment="right",
                source="autotag",
                series_number=None,
            )

        # Layout scan on start page: series above heading, right authors
        start = art.get("start_page")
        page = pages_by_num.get(start) if start else None
        if not page:
            continue
        width = page.get("width") or 600
        blocks = page.get("blocks") or []
        heading_y = None
        for b in blocks:
            if b.get("type") == "heading" or (
                b.get("alignment") == "center"
                and title
                and title[:8] in (b.get("text") or "")
            ):
                heading_y = b["bbox"][1]
                break

        for b in blocks:
            text = (b.get("text") or "").strip()
            if not text or len(text) > 80:
                continue
            bbox = b.get("bbox") or [0, 0, 0, 0]
            y0 = bbox[1]
            alignment = b.get("alignment") or "left"
            if b.get("type") == "right_subheading" or alignment == "right":
                if text not in (art.get("authors") or []) and len(text) < 50:
                    # may already be tagged; still ok as catalog signal
                    if not any(
                        e["kind"] == "author" and e["text"] == text and e["article_id"] == aid
                        for e in entries
                    ):
                        add(
                            article_id=aid,
                            kind="author",
                            text=text.split("\n")[0].strip(),
                            page=start,
                            alignment="right",
                            source="layout_right",
                            series_number=None,
                        )
            # Series candidates above heading
            if heading_y is not None and y0 < heading_y - 2:
                sname, snum = _match_series(text, catalog)
                if sname:
                    if not any(
                        e["kind"] == "series"
                        and e["article_id"] == aid
                        and e["text"] == sname
                        for e in entries
                    ):
                        add(
                            article_id=aid,
                            kind="series",
                            text=sname,
                            page=start,
                            alignment=alignment,
                            source="layout_above_heading",
                            series_number=snum,
                        )
            else:
                sname, snum = _match_series(text, catalog)
                if sname and sname != series and alignment in ("left", "center"):
                    if not any(
                        e["kind"] == "series"
                        and e["article_id"] == aid
                        and e["text"] == sname
                        for e in entries
                    ):
                        add(
                            article_id=aid,
                            kind="series",
                            text=sname,
                            page=start,
                            alignment=alignment,
                            source="layout_match",
                            series_number=snum,
                        )

    return entries


def export_catalog(edition_dir: str, edition_id: str, entries: list[dict]) -> str:
    path = os.path.join(edition_dir, "catalog.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"edition_id": edition_id, "entries": entries},
            f,
            ensure_ascii=False,
            indent=2,
        )
    return path
