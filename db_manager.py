import sqlite3
import json
import os

class SSBMDatabase:
    def __init__(self, db_path="ssbm_archive.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.create_tables()

    def get_connection(self):
        return self.conn

    def create_tables(self):
        cursor = self.conn.cursor()
        
        # 1. Table for editions metadata
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS editions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            pdf_path TEXT,
            publish_year INTEGER,
            publish_month INTEGER,
            total_pages INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # 2. Table for page content
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edition_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            full_text TEXT NOT NULL,
            blocks_json TEXT NOT NULL,
            FOREIGN KEY(edition_id) REFERENCES editions(id) ON DELETE CASCADE,
            UNIQUE(edition_id, page_number)
        );
        """)
        
        # Define Telugu tokenchars (U+0C00 to U+0C7F) to prevent splitting on vowel signs/viramas
        telugu_tokenchars = "".join(chr(c) for c in range(0x0c00, 0x0c80))
        
        # 3. FTS5 Virtual Table for full-text search
        cursor.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            page_id UNINDEXED,
            edition_id UNINDEXED,
            page_number UNINDEXED,
            content,
            tokenize="unicode61 tokenchars '{telugu_tokenchars}'"
        );
        """)
        
        # 4. Triggers to auto-synchronize FTS index with main pages table
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS pages_after_insert AFTER INSERT ON pages BEGIN
            INSERT INTO pages_fts(page_id, edition_id, page_number, content)
            VALUES (new.id, new.edition_id, new.page_number, new.full_text);
        END;
        """)
        
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS pages_after_delete AFTER DELETE ON pages BEGIN
            DELETE FROM pages_fts WHERE page_id = old.id;
        END;
        """)
        
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS pages_after_update AFTER UPDATE ON pages BEGIN
            UPDATE pages_fts
            SET content = new.full_text
            WHERE page_id = old.id;
        END;
        """)
        
        self.conn.commit()

    def insert_edition(self, edition_id, title, pdf_path, year, month, total_pages):
        cursor = self.conn.cursor()
        cursor.execute("""
        INSERT INTO editions (id, title, pdf_path, publish_year, publish_month, total_pages)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,
            pdf_path=excluded.pdf_path,
            publish_year=excluded.publish_year,
            publish_month=excluded.publish_month,
            total_pages=excluded.total_pages;
        """, (edition_id, title, pdf_path, year, month, total_pages))
        self.conn.commit()

    def insert_page(self, edition_id, page_number, full_text, blocks_list):
        cursor = self.conn.cursor()
        blocks_json = json.dumps(blocks_list, ensure_ascii=False)
        cursor.execute("""
        INSERT INTO pages (edition_id, page_number, full_text, blocks_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(edition_id, page_number) DO UPDATE SET
            full_text=excluded.full_text,
            blocks_json=excluded.blocks_json;
        """, (edition_id, page_number, full_text, blocks_json))
        self.conn.commit()

    def delete_edition(self, edition_id):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM editions WHERE id = ?;", (edition_id,))
        self.conn.commit()

    def search(self, query_str, limit=10):
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT 
            fts.page_id,
            fts.edition_id,
            fts.page_number,
            ed.title AS edition_title,
            snippet(pages_fts, 3, '<b>', '</b>', '...', 15) AS highlighted_snippet,
            bm.full_text
        FROM pages_fts fts
        JOIN editions ed ON ed.id = fts.edition_id
        JOIN pages bm ON bm.id = fts.page_id
        WHERE pages_fts MATCH ?
        ORDER BY rank
        LIMIT ?;
        """, (query_str, limit))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                "page_id": row[0],
                "edition_id": row[1],
                "page_number": row[2],
                "edition_title": row[3],
                "snippet": row[4],
                "full_text": row[5]
            })
        return results

    def close(self):
        self.conn.close()
