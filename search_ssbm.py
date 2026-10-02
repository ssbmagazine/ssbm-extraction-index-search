"""CLI search: P1 catalog (default) + P2 full-text."""
from __future__ import annotations

import argparse
import sys

from db_manager import SSBMDatabase

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def print_catalog(results, label: str):
    if not results:
        print(f"\nNo catalog results for: {label}")
        return
    print(f"\nCatalog results ({len(results)}): {label}")
    print("=" * 80)
    for idx, r in enumerate(results):
        y, m = r.get("publish_year"), r.get("publish_month")
        ed = r.get("edition_title") or r.get("edition_id")
        if y:
            ed = f"{ed} ({y}-{m:02d})" if m else f"{ed} ({y})"
        print(f"{idx + 1}. [{r.get('kind')}] {r.get('text')}")
        print(
            f"   {ed} | page {r.get('page')} | article: {r.get('article_title') or r.get('article_id')}"
        )
        print("-" * 80)


def print_article_results(results, label: str):
    if not results:
        print(f"\nNo full-text results for: {label}")
        return
    print(f"\nFull-text results ({len(results)}): {label}")
    print("=" * 80)
    for idx, r in enumerate(results):
        authors = ", ".join(r.get("authors") or []) or "—"
        series = r.get("series") or "—"
        pages = f"{r.get('start_page')}-{r.get('end_page')}"
        edition = r.get("edition_title") or r.get("edition_id")
        y, m = r.get("publish_year"), r.get("publish_month")
        ed_meta = f"{edition}"
        if y:
            ed_meta += f" ({y}-{m:02d})" if m else f" ({y})"
        print(f"{idx + 1}. {r['title']}")
        print(f"   Edition: {ed_meta} | Pages: {pages}")
        print(f"   Authors: {authors} | Series: {series}")
        print(f"   Snippet: {(r.get('snippet') or '').strip()}")
        print("-" * 80)


def main():
    parser = argparse.ArgumentParser(description="SSBM dual search (catalog + full-text)")
    parser.add_argument("query", nargs="?", default=None, help="Search query")
    parser.add_argument("-d", "--database", default="ssbm_archive.db")
    parser.add_argument("-l", "--limit", type=int, default=15)
    parser.add_argument(
        "--mode",
        choices=["catalog", "fulltext", "both"],
        default="catalog",
        help="P1 catalog (default), P2 fulltext, or both",
    )
    parser.add_argument("--kind", choices=["heading", "author", "series"], default=None)
    parser.add_argument("--author", help="Filter full-text by author")
    parser.add_argument("--title", help="Filter full-text by title")
    parser.add_argument("--series", help="Filter full-text by series")
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Exact word/token match (disables trigram substring)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if not any([args.query, args.author, args.title, args.series]):
        parser.error("Provide a query and/or --author/--title/--series")

    db = SSBMDatabase(args.database)

    if args.mode in ("catalog", "both") and args.query:
        cat = db.search_catalog(
            args.query, kind=args.kind, exact=args.exact, limit=args.limit
        )
        print_catalog(cat, args.query)

    if args.mode in ("fulltext", "both") or (
        args.mode == "catalog" and not args.query and (args.author or args.title or args.series)
    ):
        results = db.search_articles(
            query_str=args.query,
            author=args.author,
            title=args.title,
            series=args.series,
            limit=args.limit,
            exact=args.exact,
        )
        if args.verbose:
            for idx, r in enumerate(results):
                print(
                    f"\n=== {idx + 1}: {r['title']} ({r['edition_id']} "
                    f"p{r['start_page']}-{r['end_page']}) ==="
                )
                print(r.get("body") or "")
        else:
            label_parts = []
            if args.query:
                label_parts.append(args.query)
            if args.exact:
                label_parts.append("exact")
            if args.author:
                label_parts.append(f"author={args.author}")
            print_article_results(results, " | ".join(label_parts) or "filters")

    db.close()


if __name__ == "__main__":
    main()
