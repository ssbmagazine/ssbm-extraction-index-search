"""Index extracted pages and article archive folders into SQLite."""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

from db_manager import SSBMDatabase

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_edition_info(filename: str):
    basename = os.path.basename(filename).lower()
    match = re.search(r"([a-z]{3,9})[-_]?(\d{4})", basename)
    if match:
        month_str, year_str = match.groups()
        month = MONTH_MAP.get(month_str[:3], 1)
        year = int(year_str)
        month_name = month_str.capitalize()
        title = f"SSBM {month_name} {year}"
        return title, year, month
    return "SSBM Edition", 2000, 1


def index_json_file(json_path: str, db_path: str = "ssbm_archive.db"):
    if not os.path.exists(json_path):
        print(f"Error: JSON file not found at {json_path}")
        return False

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    db = SSBMDatabase(db_path)
    inferred_title, year, month = parse_edition_info(json_path)
    metadata = data.get("metadata", {})
    pdf_path = data.get("pdf_path") or metadata.get("path", "")
    total_pages = data.get("total_pages", len(data.get("pages", [])))

    edition_id, _ = os.path.splitext(os.path.basename(json_path))
    edition_id = edition_id.replace("_extracted", "")

    print(f"Indexing edition '{edition_id}' pages...")
    db.insert_edition(
        edition_id=edition_id,
        title=inferred_title,
        pdf_path=pdf_path,
        year=year,
        month=month,
        total_pages=total_pages,
        qa=data.get("qa_summary"),
        flags=(data.get("qa_summary") or {}).get("flags"),
    )

    for page in data.get("pages", []):
        page_number = page.get("page_number")
        blocks = page.get("blocks", [])
        texts = [b.get("text", "").strip() for b in blocks if b.get("text", "").strip()]
        full_text = "\n\n".join(texts)
        db.insert_page(edition_id, page_number, full_text, blocks)

    db.close()
    print(f"Indexed pages for '{inferred_title}'.")
    return True


def index_archive_edition(edition_dir: str, db_path: str = "ssbm_archive.db"):
    edition_json = os.path.join(edition_dir, "edition.json")
    if not os.path.exists(edition_json):
        print(f"No edition.json in {edition_dir}")
        return False

    with open(edition_json, encoding="utf-8") as f:
        edition = json.load(f)

    db = SSBMDatabase(db_path)
    edition_id = edition["id"]
    db.insert_edition(
        edition_id=edition_id,
        title=edition.get("title") or edition_id,
        pdf_path=edition.get("pdf_path"),
        year=edition.get("publish_year"),
        month=edition.get("publish_month"),
        total_pages=edition.get("total_pages"),
        volume=edition.get("volume"),
        issue=edition.get("issue"),
        qa=edition.get("qa_summary"),
        flags=edition.get("flags"),
    )

    # Re-index articles cleanly
    db.delete_articles_for_edition(edition_id)
    db.delete_catalog_for_edition(edition_id)
    art_dir = os.path.join(edition_dir, "articles")
    count = 0
    if os.path.isdir(art_dir):
        for name in sorted(os.listdir(art_dir)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(art_dir, name), encoding="utf-8") as f:
                article = json.load(f)
            db.insert_article(edition_id, article)
            count += 1

    catalog_path = os.path.join(edition_dir, "catalog.json")
    cat_count = 0
    if os.path.exists(catalog_path):
        with open(catalog_path, encoding="utf-8") as f:
            cat = json.load(f)
        for entry in cat.get("entries") or []:
            db.insert_catalog_entry(entry)
            cat_count += 1
    elif os.path.exists(os.path.join(edition_dir, "raw_extract.json")):
        # Build catalog on the fly if missing
        from catalog_builder import build_catalog_entries, export_catalog

        with open(os.path.join(edition_dir, "raw_extract.json"), encoding="utf-8") as f:
            raw = json.load(f)
        arts = []
        if os.path.isdir(art_dir):
            for name in sorted(os.listdir(art_dir)):
                if name.endswith(".json"):
                    with open(os.path.join(art_dir, name), encoding="utf-8") as f:
                        arts.append(json.load(f))
        entries = build_catalog_entries(edition_id, arts, extracted=raw)
        export_catalog(edition_dir, edition_id, entries)
        for entry in entries:
            db.insert_catalog_entry(entry)
            cat_count += 1

    # Also index pages from raw extract if present
    raw_path = os.path.join(edition_dir, "raw_extract.json")
    if os.path.exists(raw_path):
        with open(raw_path, encoding="utf-8") as f:
            data = json.load(f)
        for page in data.get("pages", []):
            blocks = page.get("blocks", [])
            texts = [b.get("text", "").strip() for b in blocks if b.get("text", "").strip()]
            db.insert_page(
                edition_id,
                page.get("page_number"),
                "\n\n".join(texts),
                blocks,
            )

    db.close()
    print(f"Indexed {count} articles, {cat_count} catalog entries for {edition_id}")
    return True


def main():
    parser = argparse.ArgumentParser(description="SSBM Archival Indexer")
    parser.add_argument("path", help="Extracted JSON path OR archive edition directory")
    parser.add_argument("-d", "--database", default="ssbm_archive.db")
    args = parser.parse_args()

    if os.path.isdir(args.path):
        index_archive_edition(args.path, args.database)
    else:
        index_json_file(args.path, args.database)


if __name__ == "__main__":
    main()
