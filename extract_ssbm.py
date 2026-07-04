import fitz  # PyMuPDF
import sys
import io
import os
import json
import argparse
from anu_decoder import AnuToUnicodeDecoder

# Reconfigure stdout to use UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def is_telugu_font(font_name):
    if not font_name:
        return False
    font_lower = font_name.lower()
    # Known Telugu font names in Priyaanka/Anu Script families
    telugu_keywords = ["priyaanka", "ajantha", "brahma", "manupama", "royankee"]
    return any(kw in font_lower for kw in telugu_keywords)

def extract_pdf_to_structured_text(pdf_path, output_format="json", header_threshold=140, footer_threshold=710):
    if not os.path.exists(pdf_path):
        print(f"Error: File not found at {pdf_path}")
        return None
        
    doc = fitz.open(pdf_path)
    decoder = AnuToUnicodeDecoder()
    
    extracted_data = {
        "metadata": doc.metadata,
        "total_pages": len(doc),
        "pages": []
    }
    
    # Track unique fonts for report
    unique_fonts = set()
    
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_width = page.rect.width
        page_height = page.rect.height
        center_x = page_width / 2.0
        
        # Get page fonts
        for f in page.get_fonts():
            unique_fonts.add(f[3])
            
        # Extract structured text using 'dict' to access spans and font information
        page_dict = page.get_text("dict")
        
        page_content = {
            "page_number": page_idx + 1,
            "blocks": []
        }
        
        for block_no, b in enumerate(page_dict.get("blocks", [])):
            # Skip non-text blocks (type 1 is image, 0 is text)
            if b.get("type") != 0:
                continue
                
            x0, y0, x1, y1 = b.get("bbox")
            
            # Filter headers and footers based on vertical threshold coordinates
            if y0 < header_threshold:
                continue
            if y1 > footer_threshold:
                continue
                
            lines = b.get("lines", [])
            block_text_parts = []
            
            for line in lines:
                line_parts = []
                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    font_name = span.get("font", "")
                    
                    if is_telugu_font(font_name):
                        decoded_span = decoder.decode(span_text, layout="anu6")
                    else:
                        # Keep English / Symbol fonts verbatim
                        decoded_span = span_text
                        
                    line_parts.append(decoded_span)
                
                line_text = "".join(line_parts)
                block_text_parts.append(line_text)
                
            decoded_text = "\n".join(block_text_parts)
            cleaned_decoded = decoded_text.strip()
            if not cleaned_decoded:
                continue
                
            # Simple heuristic classification for Title / Headings:
            # 1. Block is center-aligned (center of block is near the page center)
            # 2. Block has few characters or lines
            block_center_x = (x0 + x1) / 2.0
            is_centered = abs(block_center_x - center_x) < 40.0
            line_count = len(lines)
            
            is_heading = is_centered and line_count <= 2 and len(cleaned_decoded) < 60
            
            block_data = {
                "block_no": block_no,
                "bbox": [x0, y0, x1, y1],
                "type": "heading" if is_heading else "paragraph",
                "text": cleaned_decoded
            }
            page_content["blocks"].append(block_data)
            
        extracted_data["pages"].append(page_content)
        
    extracted_data["detected_fonts"] = list(unique_fonts)
    return extracted_data

def save_to_text(data, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"SSBM Magazine Archival Export\n")
        f.write(f"Title: {data['metadata'].get('title', 'Unknown')}\n")
        f.write(f"Total Pages: {data['total_pages']}\n")
        f.write(f"Detected Fonts: {', '.join(data['detected_fonts'])}\n")
        f.write("=" * 60 + "\n\n")
        
        for page in data["pages"]:
            f.write(f"--- Page {page['page_number']} ---\n\n")
            for block in page["blocks"]:
                if block["type"] == "heading":
                    f.write(f"[HEADING] {block['text']}\n\n")
                else:
                    # Write body paragraph
                    f.write(f"{block['text']}\n\n")
            f.write("\n")

def main():
    parser = argparse.ArgumentParser(description="SSBM Telugu PDF Text Extractor POC")
    parser.add_argument("pdf_path", help="Path to the Telugu PDF file")
    parser.add_argument("-o", "--output", help="Path to save the output file")
    parser.add_argument("-f", "--format", choices=["json", "txt"], default="txt", help="Output format (json or txt)")
    
    args = parser.parse_args()
    
    output_path = args.output
    if not output_path:
        base_name, _ = os.path.splitext(args.pdf_path)
        output_path = f"{base_name}_extracted.{args.format}"
        
    print(f"Extracting {args.pdf_path}...")
    data = extract_pdf_to_structured_text(args.pdf_path)
    
    if data:
        if args.format == "json":
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            save_to_text(data, output_path)
        print(f"Successfully extracted and saved to: {output_path}")

if __name__ == "__main__":
    main()
