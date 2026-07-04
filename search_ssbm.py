import sys
import io
import argparse
from db_manager import SSBMDatabase

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def print_search_results(results, query):
    if not results:
        print(f"\nNo results found for query: '{query}'")
        return
        
    print(f"\nSearch results for: '{query}' (Found {len(results)} matches)")
    print("=" * 80)
    
    for idx, r in enumerate(results):
        print(f"{idx+1}. {r['edition_title']} | Page {r['page_number']}")
        print(f"   Snippet: {r['snippet'].strip()}")
        print("-" * 80)

def main():
    parser = argparse.ArgumentParser(description="SSBM Telugu Archival Search Engine")
    parser.add_argument("query", help="Telugu search keyword or FTS query expression")
    parser.add_argument("-d", "--database", default="ssbm_archive.db", help="Path to SQLite database file")
    parser.add_argument("-l", "--limit", type=int, default=10, help="Maximum number of search results to return")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print full text of matching pages")
    
    args = parser.parse_args()
    
    db = SSBMDatabase(args.database)
    results = db.search(args.query, limit=args.limit)
    db.close()
    
    if args.verbose:
        if not results:
            print(f"No results found for query: '{args.query}'")
            return
        for idx, r in enumerate(results):
            print(f"\n=== MATCH {idx+1}: {r['edition_title']} (Page {r['page_number']}) ===")
            print(r['full_text'])
            print("=" * 80)
    else:
        print_search_results(results, args.query)

if __name__ == "__main__":
    main()
