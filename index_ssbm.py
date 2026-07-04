import sys
import io
import os
import json
import re
import argparse
from db_manager import SSBMDatabase

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Helper to parse month/year from filename like "jan2002"
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

def parse_edition_info(filename):
    basename = os.path.basename(filename).lower()
    # Find patterns like jan2002 or january2002
    match = re.search(r'([a-z]{3,9})[-_]?(\d{4})', basename)
    if match:
        month_str, year_str = match.groups()
        month = MONTH_MAP.get(month_str[:3], 1)
        year = int(year_str)
        month_name = month_str.capitalize()
        title = f"SSBM {month_name} {year}"
        return title, year, month
    return "SSBM Edition", 2000, 1

def index_json_file(json_path, db_path="ssbm_archive.db"):
    if not os.path.exists(json_path):
        print(f"Error: JSON file not found at {json_path}")
        return False
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    db = SSBMDatabase(db_path)
    
    # Infer metadata
    inferred_title, year, month = parse_edition_info(json_path)
    
    # Check if JSON contains metadata title or total_pages
    metadata = data.get("metadata", {})
    pdf_path = metadata.get("path", "")
    total_pages = data.get("total_pages", len(data.get("pages", [])))
    
    # Edition ID: extract from filename or use a hash/clean string
    edition_id, _ = os.path.splitext(os.path.basename(json_path))
    edition_id = edition_id.replace("_extracted", "")
    
    print(f"Indexing edition '{edition_id}' in database...")
    db.insert_edition(
        edition_id=edition_id,
        title=inferred_title,
        pdf_path=pdf_path,
        year=year,
        month=month,
        total_pages=total_pages
    )
    
    pages = data.get("pages", [])
    indexed_pages_count = 0
    
    for page in pages:
        page_number = page.get("page_number")
        blocks = page.get("blocks", [])
        
        # Concatenate text from blocks to form the page's full text
        texts = []
        for block in blocks:
            text = block.get("text", "").strip()
            if text:
                texts.append(text)
                
        full_text = "\n\n".join(texts)
        
        db.insert_page(
            edition_id=edition_id,
            page_number=page_number,
            full_text=full_text,
            blocks_list=blocks
        )
        indexed_pages_count += 1
        
    db.close()
    print(f"Successfully indexed {indexed_pages_count} pages for edition '{inferred_title}'!")
    return True

def main():
    parser = argparse.ArgumentParser(description="SSBM Telugu Archival Indexer")
    parser.add_argument("json_path", help="Path to the extracted SSBM JSON file")
    parser.add_argument("-d", "--database", default="ssbm_archive.db", help="Path to SQLite database file")
    
    args = parser.parse_args()
    index_json_file(args.json_path, args.database)

if __name__ == "__main__":
    main()
