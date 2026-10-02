"""SQLite schema: editions, pages, articles, catalog, dual FTS (exact + trigram)."""
from __future__ import annotations

import json
import sqlite3


def _telugu_tokenchars() -> str:
    return "".join(chr(c) for c in range(0x0C00, 0x0C80))


class SSBMDatabase:
    def __init__(self, db_path: str = "ssbm_archive.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.create_tables()

    def get_connection(self):
        return self.conn

    def create_tables(self):
        cursor = self.conn.cursor()
        telugu_tokenchars = _telugu_tokenchars()

        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS editions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            pdf_path TEXT,
            publish_year INTEGER,
            publish_month INTEGER,
            volume INTEGER,
            issue INTEGER,
            total_pages INTEGER,
            qa_json TEXT,
            flags_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        )
        cols = {r[1] for r in cursor.execute("PRAGMA table_info(editions)").fetchall()}
        for col, decl in (
            ("volume", "INTEGER"),
            ("issue", "INTEGER"),
            ("qa_json", "TEXT"),
            ("flags_json", "TEXT"),
        ):
            if col not in cols:
                cursor.execute(f"ALTER TABLE editions ADD COLUMN {col} {decl};")

        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edition_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            full_text TEXT NOT NULL,
            blocks_json TEXT NOT NULL,
            FOREIGN KEY(edition_id) REFERENCES editions(id) ON DELETE CASCADE,
            UNIQUE(edition_id, page_number)
        );
        """
        )

        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT NOT NULL,
            edition_id TEXT NOT NULL,
            title TEXT NOT NULL,
            start_page INTEGER,
            end_page INTEGER,
            series TEXT,
            authors_json TEXT,
            author_sources_json TEXT,
            body TEXT NOT NULL,
            continuation_of TEXT,
            toc_index INTEGER,
            images_json TEXT,
            confidence REAL,
            review_flags_json TEXT,
            PRIMARY KEY (edition_id, id),
            FOREIGN KEY(edition_id) REFERENCES editions(id) ON DELETE CASCADE
        );
        """
        )

        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS catalog_entries (
            id TEXT PRIMARY KEY,
            edition_id TEXT NOT NULL,
            article_id TEXT,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            page INTEGER,
            alignment TEXT,
            source TEXT,
            series_number INTEGER,
            FOREIGN KEY(edition_id) REFERENCES editions(id) ON DELETE CASCADE
        );
        """
        )

        cursor.execute(
            f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            page_id UNINDEXED,
            edition_id UNINDEXED,
            page_number UNINDEXED,
            content,
            tokenize="unicode61 tokenchars '{telugu_tokenchars}'"
        );
        """
        )

        # Exact / metadata-oriented article FTS
        cursor.execute(
            f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            edition_id UNINDEXED,
            article_id UNINDEXED,
            title,
            authors,
            series,
            content,
            tokenize="unicode61 tokenchars '{telugu_tokenchars}'"
        );
        """
        )

        # P2 substring-friendly body index
        cursor.execute(
            """
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_body_fts USING fts5(
            edition_id UNINDEXED,
            article_id UNINDEXED,
            content,
            tokenize='trigram'
        );
        """
        )

        cursor.execute(
            f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS catalog_fts USING fts5(
            entry_id UNINDEXED,
            edition_id UNINDEXED,
            article_id UNINDEXED,
            kind UNINDEXED,
            text,
            tokenize="unicode61 tokenchars '{telugu_tokenchars}'"
        );
        """
        )

        # Pages triggers
        cursor.execute(
            """
        CREATE TRIGGER IF NOT EXISTS pages_after_insert AFTER INSERT ON pages BEGIN
            INSERT INTO pages_fts(page_id, edition_id, page_number, content)
            VALUES (new.id, new.edition_id, new.page_number, new.full_text);
        END;
        """
        )
        cursor.execute(
            """
        CREATE TRIGGER IF NOT EXISTS pages_after_delete AFTER DELETE ON pages BEGIN
            DELETE FROM pages_fts WHERE page_id = old.id;
        END;
        """
        )
        cursor.execute(
            """
        CREATE TRIGGER IF NOT EXISTS pages_after_update AFTER UPDATE ON pages BEGIN
            UPDATE pages_fts SET content = new.full_text WHERE page_id = old.id;
        END;
        """
        )

        cursor.execute(
            """
        CREATE TRIGGER IF NOT EXISTS articles_after_insert AFTER INSERT ON articles BEGIN
            INSERT INTO articles_fts(edition_id, article_id, title, authors, series, content)
            VALUES (
                new.edition_id, new.id, new.title,
                COALESCE(new.authors_json, '[]'),
                COALESCE(new.series, ''),
                new.body
            );
            INSERT INTO articles_body_fts(edition_id, article_id, content)
            VALUES (new.edition_id, new.id, new.body);
        END;
        """
        )
        cursor.execute(
            """
        CREATE TRIGGER IF NOT EXISTS articles_after_delete AFTER DELETE ON articles BEGIN
            DELETE FROM articles_fts
            WHERE edition_id = old.edition_id AND article_id = old.id;
            DELETE FROM articles_body_fts
            WHERE edition_id = old.edition_id AND article_id = old.id;
        END;
        """
        )
        cursor.execute(
            """
        CREATE TRIGGER IF NOT EXISTS articles_after_update AFTER UPDATE ON articles BEGIN
            DELETE FROM articles_fts
            WHERE edition_id = old.edition_id AND article_id = old.id;
            DELETE FROM articles_body_fts
            WHERE edition_id = old.edition_id AND article_id = old.id;
            INSERT INTO articles_fts(edition_id, article_id, title, authors, series, content)
            VALUES (
                new.edition_id, new.id, new.title,
                COALESCE(new.authors_json, '[]'),
                COALESCE(new.series, ''),
                new.body
            );
            INSERT INTO articles_body_fts(edition_id, article_id, content)
            VALUES (new.edition_id, new.id, new.body);
        END;
        """
        )

        cursor.execute(
            """
        CREATE TRIGGER IF NOT EXISTS catalog_after_insert AFTER INSERT ON catalog_entries BEGIN
            INSERT INTO catalog_fts(entry_id, edition_id, article_id, kind, text)
            VALUES (new.id, new.edition_id, new.article_id, new.kind, new.text);
        END;
        """
        )
        cursor.execute(
            """
        CREATE TRIGGER IF NOT EXISTS catalog_after_delete AFTER DELETE ON catalog_entries BEGIN
            DELETE FROM catalog_fts WHERE entry_id = old.id;
        END;
        """
        )
        cursor.execute(
            """
        CREATE TRIGGER IF NOT EXISTS catalog_after_update AFTER UPDATE ON catalog_entries BEGIN
            DELETE FROM catalog_fts WHERE entry_id = old.id;
            INSERT INTO catalog_fts(entry_id, edition_id, article_id, kind, text)
            VALUES (new.id, new.edition_id, new.article_id, new.kind, new.text);
        END;
        """
        )

        self.conn.commit()

    def insert_edition(
        self,
        edition_id,
        title,
        pdf_path,
        year,
        month,
        total_pages,
        volume=None,
        issue=None,
        qa=None,
        flags=None,
    ):
        cursor = self.conn.cursor()
        cursor.execute(
            """
        INSERT INTO editions (
            id, title, pdf_path, publish_year, publish_month, volume, issue,
            total_pages, qa_json, flags_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,
            pdf_path=excluded.pdf_path,
            publish_year=excluded.publish_year,
            publish_month=excluded.publish_month,
            volume=excluded.volume,
            issue=excluded.issue,
            total_pages=excluded.total_pages,
            qa_json=excluded.qa_json,
            flags_json=excluded.flags_json;
        """,
            (
                edition_id,
                title,
                pdf_path,
                year,
                month,
                volume,
                issue,
                total_pages,
                json.dumps(qa or {}, ensure_ascii=False),
                json.dumps(flags or [], ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def insert_page(self, edition_id, page_number, full_text, blocks_list):
        cursor = self.conn.cursor()
        blocks_json = json.dumps(blocks_list, ensure_ascii=False)
        cursor.execute(
            """
        INSERT INTO pages (edition_id, page_number, full_text, blocks_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(edition_id, page_number) DO UPDATE SET
            full_text=excluded.full_text,
            blocks_json=excluded.blocks_json;
        """,
            (edition_id, page_number, full_text, blocks_json),
        )
        self.conn.commit()

    def delete_articles_for_edition(self, edition_id: str):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM articles WHERE edition_id = ?;", (edition_id,))
        self.conn.commit()

    def delete_catalog_for_edition(self, edition_id: str):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM catalog_entries WHERE edition_id = ?;", (edition_id,))
        self.conn.commit()

    def insert_article(self, edition_id: str, article: dict):
        cursor = self.conn.cursor()
        authors = article.get("authors") or []
        cursor.execute(
            """
        INSERT INTO articles (
            id, edition_id, title, start_page, end_page, series,
            authors_json, author_sources_json, body, continuation_of,
            toc_index, images_json, confidence, review_flags_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(edition_id, id) DO UPDATE SET
            title=excluded.title,
            start_page=excluded.start_page,
            end_page=excluded.end_page,
            series=excluded.series,
            authors_json=excluded.authors_json,
            author_sources_json=excluded.author_sources_json,
            body=excluded.body,
            continuation_of=excluded.continuation_of,
            toc_index=excluded.toc_index,
            images_json=excluded.images_json,
            confidence=excluded.confidence,
            review_flags_json=excluded.review_flags_json;
        """,
            (
                article["id"],
                edition_id,
                article.get("title") or "",
                article.get("start_page"),
                article.get("end_page"),
                article.get("series"),
                json.dumps(authors, ensure_ascii=False),
                json.dumps(article.get("author_sources") or [], ensure_ascii=False),
                article.get("body_unicode") or "",
                article.get("continuation_of"),
                article.get("toc_index"),
                json.dumps(article.get("images") or [], ensure_ascii=False),
                article.get("confidence"),
                json.dumps(article.get("review_flags") or [], ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def insert_catalog_entry(self, entry: dict):
        cursor = self.conn.cursor()
        cursor.execute(
            """
        INSERT INTO catalog_entries (
            id, edition_id, article_id, kind, text, page, alignment, source, series_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            article_id=excluded.article_id,
            kind=excluded.kind,
            text=excluded.text,
            page=excluded.page,
            alignment=excluded.alignment,
            source=excluded.source,
            series_number=excluded.series_number;
        """,
            (
                entry["id"],
                entry["edition_id"],
                entry.get("article_id"),
                entry["kind"],
                entry["text"],
                entry.get("page"),
                entry.get("alignment"),
                entry.get("source"),
                entry.get("series_number"),
            ),
        )
        self.conn.commit()

    def delete_edition(self, edition_id):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM editions WHERE id = ?;", (edition_id,))
        self.conn.commit()

    def search(self, query_str, limit=10):
        cursor = self.conn.cursor()
        cursor.execute(
            """
        SELECT
            fts.page_id, fts.edition_id, fts.page_number,
            ed.title AS edition_title,
            snippet(pages_fts, 3, '<b>', '</b>', '...', 15),
            bm.full_text
        FROM pages_fts fts
        JOIN editions ed ON ed.id = fts.edition_id
        JOIN pages bm ON bm.id = fts.page_id
        WHERE pages_fts MATCH ?
        ORDER BY rank LIMIT ?;
        """,
            (query_str, limit),
        )
        return [
            {
                "page_id": r[0],
                "edition_id": r[1],
                "page_number": r[2],
                "edition_title": r[3],
                "snippet": r[4],
                "full_text": r[5],
            }
            for r in cursor.fetchall()
        ]

    def list_years(self) -> list[int]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT publish_year FROM editions
            WHERE publish_year IS NOT NULL
            ORDER BY publish_year
            """
        )
        return [int(r[0]) for r in cursor.fetchall()]

    @staticmethod
    def _year_clause(alias: str, year_from: int | None, year_to: int | None):
        parts = []
        params: list = []
        if year_from is not None:
            parts.append(f"{alias}.publish_year >= ?")
            params.append(year_from)
        if year_to is not None:
            parts.append(f"{alias}.publish_year <= ?")
            params.append(year_to)
        return parts, params

    def search_catalog(
        self,
        query_str: str,
        kind: str | None = None,
        exact: bool = False,
        limit: int = 30,
        year_from: int | None = None,
        year_to: int | None = None,
    ):
        cursor = self.conn.cursor()
        if not query_str:
            return []
        if exact:
            fts_q = f'"{query_str}"'
        elif not query_str.endswith("*") and " " not in query_str.strip():
            fts_q = f"{query_str}*"
        else:
            fts_q = query_str

        year_parts, year_params = self._year_clause("ed", year_from, year_to)

        sql = """
        SELECT
            c.id, c.edition_id, c.article_id, c.kind, c.text, c.page,
            c.alignment, c.source, c.series_number,
            ed.title, ed.publish_year, ed.publish_month,
            a.title
        FROM catalog_fts
        JOIN catalog_entries c ON c.id = catalog_fts.entry_id
        JOIN editions ed ON ed.id = c.edition_id
        LEFT JOIN articles a ON a.edition_id = c.edition_id AND a.id = c.article_id
        WHERE catalog_fts MATCH ?
        """
        params: list = [fts_q]
        if kind:
            sql += " AND c.kind = ?"
            params.append(kind)
        for p in year_parts:
            sql += f" AND {p}"
        params.extend(year_params)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        try:
            cursor.execute(sql, params)
        except sqlite3.OperationalError:
            sql = """
            SELECT
                c.id, c.edition_id, c.article_id, c.kind, c.text, c.page,
                c.alignment, c.source, c.series_number,
                ed.title, ed.publish_year, ed.publish_month,
                a.title
            FROM catalog_entries c
            JOIN editions ed ON ed.id = c.edition_id
            LEFT JOIN articles a ON a.edition_id = c.edition_id AND a.id = c.article_id
            WHERE c.text LIKE ?
            """
            params = [f"%{query_str}%"]
            if kind:
                sql += " AND c.kind = ?"
                params.append(kind)
            for p in year_parts:
                sql += f" AND {p}"
            params.extend(year_params)
            sql += " LIMIT ?"
            params.append(limit)
            cursor.execute(sql, params)

        return [
            {
                "entry_id": r[0],
                "edition_id": r[1],
                "article_id": r[2],
                "kind": r[3],
                "text": r[4],
                "page": r[5],
                "alignment": r[6],
                "source": r[7],
                "series_number": r[8],
                "edition_title": r[9],
                "publish_year": r[10],
                "publish_month": r[11],
                "article_title": r[12],
            }
            for r in cursor.fetchall()
        ]

    def search_articles(
        self,
        query_str: str | None = None,
        author: str | None = None,
        title: str | None = None,
        series: str | None = None,
        limit: int = 20,
        exact: bool = False,
        year_from: int | None = None,
        year_to: int | None = None,
    ):
        cursor = self.conn.cursor()
        year_parts, year_params = self._year_clause("ed", year_from, year_to)
        year_sql = "".join(f" AND {p}" for p in year_parts)

        # Author/title/series filters without free-text → LIKE / catalog-ish
        if not query_str and (author or title or series):
            clauses = ["1=1"]
            params: list = []
            if author:
                clauses.append("a.authors_json LIKE ?")
                params.append(f"%{author}%")
            if title:
                clauses.append("a.title LIKE ?")
                params.append(f"%{title}%")
            if series:
                clauses.append("a.series LIKE ?")
                params.append(f"%{series}%")
            clauses.extend(year_parts)
            params.extend(year_params)
            params.append(limit)
            cursor.execute(
                f"""
                SELECT
                    a.edition_id, a.id, a.title, a.authors_json, a.series,
                    a.start_page, a.end_page, ed.title, ed.publish_year, ed.publish_month,
                    substr(a.body, 1, 160), a.body, a.review_flags_json, a.confidence
                FROM articles a
                JOIN editions ed ON ed.id = a.edition_id
                WHERE {" AND ".join(clauses)}
                LIMIT ?
                """,
                params,
            )
            rows = cursor.fetchall()
        elif query_str and exact:
            fts_q = query_str if " " in query_str else f'"{query_str}"'
            try:
                cursor.execute(
                    f"""
                    SELECT
                        a.edition_id, a.id, a.title, a.authors_json, a.series,
                        a.start_page, a.end_page, ed.title, ed.publish_year, ed.publish_month,
                        snippet(articles_fts, 5, '<b>', '</b>', '...', 20),
                        a.body, a.review_flags_json, a.confidence
                    FROM articles_fts
                    JOIN articles a
                      ON a.edition_id = articles_fts.edition_id AND a.id = articles_fts.article_id
                    JOIN editions ed ON ed.id = a.edition_id
                    WHERE articles_fts MATCH ?
                    {year_sql}
                    ORDER BY rank LIMIT ?
                    """,
                    [fts_q, *year_params, limit],
                )
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                rows = []
        elif query_str:
            try:
                cursor.execute(
                    f"""
                    SELECT
                        a.edition_id, a.id, a.title, a.authors_json, a.series,
                        a.start_page, a.end_page, ed.title, ed.publish_year, ed.publish_month,
                        snippet(articles_body_fts, 2, '<b>', '</b>', '...', 20),
                        a.body, a.review_flags_json, a.confidence
                    FROM articles_body_fts
                    JOIN articles a
                      ON a.edition_id = articles_body_fts.edition_id
                     AND a.id = articles_body_fts.article_id
                    JOIN editions ed ON ed.id = a.edition_id
                    WHERE articles_body_fts MATCH ?
                    {year_sql}
                    ORDER BY rank LIMIT ?
                    """,
                    [query_str, *year_params, limit],
                )
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                cursor.execute(
                    f"""
                    SELECT
                        a.edition_id, a.id, a.title, a.authors_json, a.series,
                        a.start_page, a.end_page, ed.title, ed.publish_year, ed.publish_month,
                        substr(a.body, 1, 160), a.body, a.review_flags_json, a.confidence
                    FROM articles a
                    JOIN editions ed ON ed.id = a.edition_id
                    WHERE (a.body LIKE ? OR a.title LIKE ?)
                    {year_sql}
                    LIMIT ?
                    """,
                    [f"%{query_str}%", f"%{query_str}%", *year_params, limit],
                )
                rows = cursor.fetchall()
        else:
            return []

        results = []
        for row in rows:
            authors = json.loads(row[3] or "[]")
            if author and author not in json.dumps(authors, ensure_ascii=False):
                continue
            if title and title not in (row[2] or ""):
                continue
            if series and series not in (row[4] or ""):
                continue
            y = row[8]
            if year_from is not None and (y is None or y < year_from):
                continue
            if year_to is not None and (y is None or y > year_to):
                continue
            results.append(
                {
                    "edition_id": row[0],
                    "article_id": row[1],
                    "title": row[2],
                    "authors": authors,
                    "series": row[4],
                    "start_page": row[5],
                    "end_page": row[6],
                    "edition_title": row[7],
                    "publish_year": row[8],
                    "publish_month": row[9],
                    "snippet": row[10],
                    "body": row[11],
                    "review_flags": json.loads(row[12] or "[]"),
                    "confidence": row[13],
                }
            )
            if len(results) >= limit:
                break
        return results

    def list_review_queue(self, limit: int = 200):
        cursor = self.conn.cursor()
        cursor.execute(
            """
        SELECT edition_id, id, title, start_page, end_page, review_flags_json, confidence
        FROM articles
        WHERE review_flags_json LIKE '%needs_review%'
           OR review_flags_json LIKE '%glyph%'
           OR review_flags_json LIKE '%layout%'
           OR confidence < 0.6
        ORDER BY confidence ASC
        LIMIT ?;
        """,
            (limit,),
        )
        return [
            {
                "edition_id": r[0],
                "article_id": r[1],
                "title": r[2],
                "start_page": r[3],
                "end_page": r[4],
                "review_flags": json.loads(r[5] or "[]"),
                "confidence": r[6],
            }
            for r in cursor.fetchall()
        ]

    def get_article(self, edition_id: str, article_id: str):
        cursor = self.conn.cursor()
        cursor.execute(
            """
        SELECT a.*, e.pdf_path, e.title
        FROM articles a
        JOIN editions e ON e.id = a.edition_id
        WHERE a.edition_id = ? AND a.id = ?;
        """,
            (edition_id, article_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cursor.description]
        data = dict(zip(cols, row))
        for key in ("authors_json", "author_sources_json", "images_json", "review_flags_json"):
            if key in data and data[key]:
                try:
                    data[key.replace("_json", "")] = json.loads(data[key])
                except json.JSONDecodeError:
                    pass
        return data

    def update_article_fields(self, edition_id: str, article_id: str, **fields):
        allowed = {
            "title",
            "series",
            "body",
            "authors_json",
            "review_flags_json",
            "confidence",
            "start_page",
            "end_page",
        }
        sets = []
        vals = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = ?")
            vals.append(v)
        if not sets:
            return False
        vals.extend([edition_id, article_id])
        cursor = self.conn.cursor()
        cursor.execute(
            f"UPDATE articles SET {', '.join(sets)} WHERE edition_id = ? AND id = ?;",
            vals,
        )
        self.conn.commit()
        return True

    def close(self):
        self.conn.close()
