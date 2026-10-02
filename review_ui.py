"""Local review UI for doubtful articles (side-by-side PDF page vs extract)."""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile

from flask import Flask, redirect, render_template_string, request, send_file, url_for

from db_manager import SSBMDatabase

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass

app = Flask(__name__)
DB_PATH = "ssbm_archive.db"
ARCHIVE_ROOT = "archive"

PAGE_TMPL = """
<!doctype html>
<html lang="te">
<head>
  <meta charset="utf-8"/>
  <title>SSBM Review UI</title>
  <style>
    body { font-family: "Noto Sans Telugu", "Gautami", sans-serif; margin: 0; background: #f6f4ef; color: #222; }
    header { background: #1f3a2e; color: #fff; padding: 12px 20px; }
    header a { color: #cfe8d8; margin-right: 12px; }
    main { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px; }
    .panel { background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 12px; min-height: 70vh; }
    .queue { padding: 16px; }
    table { width: 100%; border-collapse: collapse; background: #fff; }
    th, td { border-bottom: 1px solid #eee; padding: 8px; text-align: left; font-size: 14px; }
    .flags { color: #a33; font-size: 12px; }
    img.page { max-width: 100%; border: 1px solid #ccc; }
    textarea { width: 100%; height: 320px; font-size: 15px; }
    input[type=text] { width: 100%; padding: 6px; margin: 4px 0 10px; }
    button { background: #1f3a2e; color: #fff; border: 0; padding: 8px 14px; border-radius: 4px; cursor: pointer; margin-right: 8px; }
    .meta { font-size: 13px; color: #555; margin-bottom: 8px; }
  </style>
</head>
<body>
  <header>
    <strong>SSBM Review</strong>
    <a href="{{ url_for('queue') }}">Queue</a>
  </header>
  {% block body %}{% endblock %}
</body>
</html>
"""

QUEUE_TMPL = PAGE_TMPL.replace(
    "{% block body %}{% endblock %}",
    """
  <div class="queue">
    <h2>Needs review ({{ items|length }})</h2>
    <table>
      <tr><th>Edition</th><th>Article</th><th>Pages</th><th>Confidence</th><th>Flags</th></tr>
      {% for it in items %}
      <tr>
        <td>{{ it.edition_id }}</td>
        <td><a href="{{ url_for('review_article', edition_id=it.edition_id, article_id=it.article_id) }}">{{ it.title }}</a></td>
        <td>{{ it.start_page }}–{{ it.end_page }}</td>
        <td>{{ '%.2f'|format(it.confidence or 0) }}</td>
        <td class="flags">{{ (it.review_flags or [])|join(', ') }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>
""",
)

REVIEW_TMPL = PAGE_TMPL.replace(
    "{% block body %}{% endblock %}",
    """
  <main>
    <div class="panel">
      <h3>PDF page {{ page }}</h3>
      <div class="meta">{{ edition_id }} / {{ article_id }}</div>
      {% if page_image %}
        <img class="page" src="{{ page_image }}" alt="page"/>
      {% else %}
        <p>No PDF preview (missing pdf_path or page).</p>
      {% endif %}
      <form method="get">
        <label>Page</label>
        <input type="number" name="page" value="{{ page }}" min="1"/>
        <button type="submit">Show page</button>
      </form>
    </div>
    <div class="panel">
      <h3>Extract</h3>
      <form method="post">
        <label>Title</label>
        <input type="text" name="title" value="{{ title }}"/>
        <label>Authors (comma-separated)</label>
        <input type="text" name="authors" value="{{ authors }}"/>
        <label>Series</label>
        <input type="text" name="series" value="{{ series or '' }}"/>
        <label>Body</label>
        <textarea name="body">{{ body }}</textarea>
        <p class="flags">Flags: {{ flags }}</p>
        <button name="action" value="save" type="submit">Save</button>
        <button name="action" value="accept" type="submit">Accept (clear needs_review)</button>
      </form>
    </div>
  </main>
""",
)


def get_db():
    return SSBMDatabase(DB_PATH)


@app.route("/")
def queue():
    db = get_db()
    items = db.list_review_queue(limit=300)
    db.close()
    return render_template_string(QUEUE_TMPL, items=items)


@app.route("/review/<edition_id>/<path:article_id>", methods=["GET", "POST"])
def review_article(edition_id, article_id):
    db = get_db()
    art = db.get_article(edition_id, article_id)
    if not art:
        db.close()
        return "Not found", 404

    if request.method == "POST":
        title = request.form.get("title") or art["title"]
        series = request.form.get("series") or ""
        body = request.form.get("body") or ""
        authors_raw = request.form.get("authors") or ""
        authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
        flags = json.loads(art.get("review_flags_json") or "[]")
        action = request.form.get("action")
        if action == "accept":
            flags = [f for f in flags if f != "needs_review"]
            conf = 0.95
        else:
            conf = art.get("confidence") or 0.7
        db.update_article_fields(
            edition_id,
            article_id,
            title=title,
            series=series or None,
            body=body,
            authors_json=json.dumps(authors, ensure_ascii=False),
            review_flags_json=json.dumps(flags, ensure_ascii=False),
            confidence=conf,
        )
        # Mirror to archive JSON if present
        art_path = os.path.join(ARCHIVE_ROOT, edition_id, "articles", f"{article_id}.json")
        if os.path.exists(art_path):
            with open(art_path, encoding="utf-8") as f:
                data = json.load(f)
            data["title"] = title
            data["series"] = series or None
            data["body_unicode"] = body
            data["authors"] = authors
            data["review_flags"] = flags
            data["confidence"] = conf
            with open(art_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        db.close()
        return redirect(url_for("review_article", edition_id=edition_id, article_id=article_id))

    page = int(request.args.get("page") or art.get("start_page") or 1)
    authors = ", ".join(json.loads(art.get("authors_json") or "[]"))
    flags = ", ".join(json.loads(art.get("review_flags_json") or "[]"))
    page_image = url_for("pdf_page_image", edition_id=edition_id, page=page)
    html = render_template_string(
        REVIEW_TMPL,
        edition_id=edition_id,
        article_id=article_id,
        title=art.get("title"),
        authors=authors,
        series=art.get("series"),
        body=art.get("body") or "",
        flags=flags,
        page=page,
        page_image=page_image,
    )
    db.close()
    return html


@app.route("/pdf/<edition_id>/page/<int:page>.png")
def pdf_page_image(edition_id, page):
    db = get_db()
    cursor = db.conn.cursor()
    cursor.execute("SELECT pdf_path FROM editions WHERE id = ?", (edition_id,))
    row = cursor.fetchone()
    db.close()
    if not row or not row[0] or not os.path.exists(row[0]):
        # try archive edition.json
        ej = os.path.join(ARCHIVE_ROOT, edition_id, "edition.json")
        pdf_path = None
        if os.path.exists(ej):
            with open(ej, encoding="utf-8") as f:
                pdf_path = json.load(f).get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            return "PDF missing", 404
    else:
        pdf_path = row[0]

    import fitz

    doc = fitz.open(pdf_path)
    if page < 1 or page > len(doc):
        doc.close()
        return "Bad page", 404
    pix = doc[page - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    pix.save(tmp.name)
    doc.close()
    return send_file(tmp.name, mimetype="image/png")


def main():
    global DB_PATH, ARCHIVE_ROOT
    parser = argparse.ArgumentParser(description="SSBM review UI")
    parser.add_argument("-d", "--database", default="ssbm_archive.db")
    parser.add_argument("--archive", default="archive")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    DB_PATH = args.database
    ARCHIVE_ROOT = args.archive
    print(f"Review UI at http://{args.host}:{args.port}/  (db={DB_PATH})")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
