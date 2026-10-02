"""Dev-only HTML search UI — Catalog (P1) default + Full text (P2) + year scope."""
from __future__ import annotations

import argparse
import html
import json
import re
import sys

from flask import Flask, request

from db_manager import SSBMDatabase

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

app = Flask(__name__)
DB_PATH = "ssbm_archive.db"

PAGE = """<!doctype html>
<html lang="te">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>SSBM Search (dev)</title>
  <style>
    :root {
      --bg: #f7f3ea;
      --ink: #1c1917;
      --muted: #57534e;
      --card: #fffdf8;
      --line: #e7e0d4;
      --accent: #0f3d2e;
      --accent2: #c45c26;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Noto Sans Telugu", "Gautami", "Akshar Unicode", system-ui, sans-serif;
      background:
        radial-gradient(1200px 500px at 10% -10%, #efe6d4 0%, transparent 60%),
        var(--bg);
      color: var(--ink);
      line-height: 1.55;
    }
    header { padding: 28px 20px 8px; max-width: 960px; margin: 0 auto; }
    header h1 { margin: 0; font-size: 1.6rem; }
    header p { margin: 6px 0 0; color: var(--muted); font-size: 0.95rem; }
    main { max-width: 960px; margin: 0 auto; padding: 12px 20px 48px; }
    .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
    .tabs a {
      padding: 8px 14px; border-radius: 999px; text-decoration: none;
      border: 1px solid var(--line); color: var(--ink); background: #fff;
    }
    .tabs a.active { background: var(--accent); color: #fff; border-color: var(--accent); }
    form.search {
      display: grid; gap: 10px; grid-template-columns: 1fr 1fr;
      background: var(--card); border: 1px solid var(--line);
      border-radius: 14px; padding: 16px;
    }
    form.search .full { grid-column: 1 / -1; }
    label { display: block; font-size: 0.8rem; color: var(--muted); margin-bottom: 4px; }
    input[type=text], input[type=number], select {
      width: 100%; padding: 10px 12px; border: 1px solid var(--line);
      border-radius: 8px; font: inherit; font-size: 1.05rem; background: #fff;
    }
    .actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    button {
      background: var(--accent); color: #fff; border: 0; border-radius: 8px;
      padding: 10px 16px; font: inherit; cursor: pointer;
    }
    a.secondary {
      padding: 10px 16px; border-radius: 8px; text-decoration: none;
      border: 1px solid #0f3d2e; color: #0f3d2e; display: inline-block;
    }
    .check { display: flex; align-items: center; gap: 8px; font-size: 0.95rem; }
    .meta { color: var(--muted); font-size: 0.9rem; margin: 16px 0 8px; }
    .hit {
      background: var(--card); border: 1px solid var(--line);
      border-radius: 12px; padding: 14px 16px; margin: 10px 0;
    }
    .hit h2 { margin: 0 0 6px; font-size: 1.15rem; }
    .hit .row { color: var(--muted); font-size: 0.9rem; margin-bottom: 8px; }
    .kind {
      display: inline-block; font-size: 0.75rem; padding: 2px 8px;
      border-radius: 999px; background: #e8f0ec; color: var(--accent); margin-right: 6px;
    }
    .snippet { font-size: 1.02rem; white-space: pre-wrap; word-break: break-word; }
    .snippet b { color: var(--accent2); }
    details { margin-top: 8px; }
    details summary { cursor: pointer; color: var(--accent); }
    .body {
      margin-top: 8px; padding: 10px; background: #fff; border-radius: 8px;
      border: 1px dashed var(--line); white-space: pre-wrap; max-height: 320px;
      overflow: auto; font-size: 0.98rem;
    }
    .empty { padding: 24px; color: var(--muted); }
    @media (max-width: 700px) { form.search { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>SSBM Search <span style="opacity:.55;font-weight:500;font-size:.85rem">(dev)</span></h1>
    <p>P1 Catalog · P2 Full text · scope by decade or year (uses publish_year)</p>
  </header>
  <main>
    <div class="tabs">
      <a class="__TAB_CAT__" href="?mode=catalog&q=__Q_RAW__&scope=__SCOPE_RAW__">Catalog (P1)</a>
      <a class="__TAB_FT__" href="?mode=fulltext&q=__Q_RAW__&scope=__SCOPE_RAW__">Full text (P2)</a>
    </div>
    <form class="search" method="get" action="/">
      <input type="hidden" name="mode" value="__MODE__"/>
      <div class="full">
        <label for="q">Query</label>
        <input id="q" name="q" type="text" value="__Q__" placeholder="సాయిమాట / ప్రేమ / editor" autofocus/>
      </div>
      <div>
        <label for="scope">Scope</label>
        <select id="scope" name="scope">
          __SCOPE_OPTIONS__
        </select>
      </div>
      <div>
        <label for="kind">Catalog kind</label>
        <select id="kind" name="kind">
          <option value="" __KIND_ALL__>All</option>
          <option value="heading" __KIND_H__>Heading</option>
          <option value="author" __KIND_A__>Author</option>
          <option value="series" __KIND_S__>Series</option>
        </select>
      </div>
      <div>
        <label for="limit">Limit</label>
        <input id="limit" name="limit" type="number" min="1" max="100" value="__LIMIT__"/>
      </div>
      <div class="full check">
        <input id="exact" name="exact" type="checkbox" value="1" __EXACT__/>
        <label for="exact" style="margin:0">Exact word only</label>
      </div>
      <div class="full actions">
        <button type="submit">Search</button>
        <a class="secondary" href="/">Clear</a>
      </div>
    </form>
    __RESULTS__
  </main>
</body>
</html>
"""


def _esc(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def parse_scope(scope: str | None) -> tuple[int | None, int | None]:
    """Map UI scope to year_from/year_to. No schema change — filters publish_year."""
    if not scope:
        return None, None
    scope = scope.strip()
    if scope in ("", "all"):
        return None, None
    m = re.fullmatch(r"(\d{4})s", scope)
    if m:
        decade = int(m.group(1))
        return decade, decade + 9
    if re.fullmatch(r"\d{4}", scope):
        y = int(scope)
        return y, y
    return None, None


def _scope_options_html(selected: str, years: list[int]) -> str:
    opts = [('all', 'All years')]
    decades = sorted({(y // 10) * 10 for y in years})
    for d in decades:
        opts.append((f"{d}s", f"{d}s ({d}–{d + 9})"))
    for y in years:
        opts.append((str(y), str(y)))
    parts = []
    for value, label in opts:
        sel = " selected" if value == (selected or "all") else ""
        parts.append(f'<option value="{_esc(value)}"{sel}>{_esc(label)}</option>')
    return "\n".join(parts)


def _fmt_catalog(results: list) -> str:
    if not results:
        return '<p class="empty">No catalog results.</p>'
    parts = [f'<p class="meta">{len(results)} catalog result(s)</p>']
    for r in results:
        y, m = r.get("publish_year"), r.get("publish_month")
        ed = r.get("edition_title") or r.get("edition_id") or ""
        if y:
            ed = f"{ed} ({y}-{m:02d})" if m else f"{ed} ({y})"
        parts.append(
            f"""
            <article class="hit">
              <h2><span class="kind">{_esc(r.get('kind'))}</span>{_esc(r.get('text'))}</h2>
              <div class="row">{_esc(ed)} · page {r.get('page')} · article: {_esc(r.get('article_title') or r.get('article_id'))}</div>
            </article>
            """
        )
    return "\n".join(parts)


def _fmt_fulltext(results: list) -> str:
    if not results:
        return '<p class="empty">No full-text results.</p>'
    parts = [f'<p class="meta">{len(results)} full-text result(s)</p>']
    for r in results:
        authors = ", ".join(r.get("authors") or []) or "—"
        series = r.get("series") or "—"
        y, m = r.get("publish_year"), r.get("publish_month")
        ed = r.get("edition_title") or r.get("edition_id") or ""
        if y:
            ed = f"{ed} ({y}-{m:02d})" if m else f"{ed} ({y})"
        pages = f"{r.get('start_page')}–{r.get('end_page')}"
        snippet = r.get("snippet") or ""
        safe_snip = (
            html.escape(snippet)
            .replace("&lt;b&gt;", "<b>")
            .replace("&lt;/b&gt;", "</b>")
        )
        body = _esc(r.get("body") or "")
        parts.append(
            f"""
            <article class="hit">
              <h2>{_esc(r.get('title'))}</h2>
              <div class="row">{_esc(ed)} · pages {pages} · authors: {_esc(authors)} · series: {_esc(series)}</div>
              <div class="snippet">{safe_snip}</div>
              <details>
                <summary>Full article text</summary>
                <div class="body">{body}</div>
              </details>
            </article>
            """
        )
    return "\n".join(parts)


@app.route("/")
def search_page():
    q = (request.args.get("q") or "").strip()
    mode = (request.args.get("mode") or "catalog").strip()
    kind = (request.args.get("kind") or "").strip() or None
    scope = (request.args.get("scope") or "all").strip()
    exact = request.args.get("exact") == "1"
    try:
        limit = max(1, min(100, int(request.args.get("limit") or 20)))
    except ValueError:
        limit = 20

    year_from, year_to = parse_scope(scope)
    db = SSBMDatabase(DB_PATH)
    years = db.list_years()

    results_html = '<p class="empty">Enter a query and search.</p>'
    if q:
        if mode == "fulltext":
            results_html = _fmt_fulltext(
                db.search_articles(
                    query_str=q,
                    limit=limit,
                    exact=exact,
                    year_from=year_from,
                    year_to=year_to,
                )
            )
        else:
            results_html = _fmt_catalog(
                db.search_catalog(
                    q,
                    kind=kind,
                    exact=exact,
                    limit=limit,
                    year_from=year_from,
                    year_to=year_to,
                )
            )
    db.close()

    page = (
        PAGE.replace("__MODE__", _esc(mode))
        .replace("__Q__", _esc(q))
        .replace("__Q_RAW__", _esc(q))
        .replace("__SCOPE_RAW__", _esc(scope))
        .replace("__SCOPE_OPTIONS__", _scope_options_html(scope, years))
        .replace("__LIMIT__", str(limit))
        .replace("__RESULTS__", results_html)
        .replace("__TAB_CAT__", "active" if mode != "fulltext" else "")
        .replace("__TAB_FT__", "active" if mode == "fulltext" else "")
        .replace("__EXACT__", "checked" if exact else "")
        .replace("__KIND_ALL__", "selected" if not kind else "")
        .replace("__KIND_H__", "selected" if kind == "heading" else "")
        .replace("__KIND_A__", "selected" if kind == "author" else "")
        .replace("__KIND_S__", "selected" if kind == "series" else "")
    )
    return page


@app.get("/api/search")
def api_search():
    mode = request.args.get("mode") or "catalog"
    q = request.args.get("q") or ""
    scope = request.args.get("scope") or "all"
    year_from, year_to = parse_scope(scope)
    db = SSBMDatabase(DB_PATH)
    exact = request.args.get("exact") == "1"
    limit = int(request.args.get("limit") or 20)
    if mode == "fulltext":
        results = db.search_articles(
            query_str=q or None,
            limit=limit,
            exact=exact,
            year_from=year_from,
            year_to=year_to,
        )
    else:
        results = db.search_catalog(
            q,
            kind=request.args.get("kind"),
            exact=exact,
            limit=limit,
            year_from=year_from,
            year_to=year_to,
        )
    db.close()
    return app.response_class(
        json.dumps(results, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
    )


def main():
    global DB_PATH
    parser = argparse.ArgumentParser(description="SSBM HTML search UI (dev)")
    parser.add_argument("-d", "--database", default="ssbm_archive.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5056)
    args = parser.parse_args()
    DB_PATH = args.database
    print(f"Search UI: http://{args.host}:{args.port}/  (db={DB_PATH})")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
