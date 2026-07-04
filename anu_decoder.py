import os
import json
import re

class AnuToUnicodeDecoder:
    def __init__(self, mappings_path=None):
        self.POLLU = "్"
        self.ZWNJ = "‌"
        
        if not mappings_path:
            # Default to the path in the telugu-encoder workspace directory
            mappings_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "telugu-encoder",
                "u2a7mappings.json"
            )
            
        with open(mappings_path, "r", encoding="utf-8") as f:
            self.mappings_data = json.load(f)
            
        # Build reversed mapping engines for both layouts
        self.engines = {
            "anu6": self._build_engine("unicode2Anu6", "unicode2Anu6_vattu", "unicode2Anu6_gunintam"),
            "anu7": self._build_engine("unicode2Anu7", "unicode2Anu7_vattu", "unicode2Anu7_gunintam")
        }
        self._inject_overrides()

    def _build_engine(self, base_key, vattu_key, gunintam_key):
        mapping = {}
        
        base_map = self.mappings_data.get(base_key, {})
        vattu_map = self.mappings_data.get(vattu_key, {})
        gunintam_map = self.mappings_data.get(gunintam_key, {})
        
        # Reverse and merge mappings: Anu-string -> { text: UnicodeText, type: type_str }
        def add_entries(source_map, type_str):
            for uni_char, raw_val in source_map.items():
                if not raw_val:
                    continue
                raw_str = str(raw_val)
                
                # Check for vowelsign type override in base
                current_type = type_str
                if type_str == "base" and len(uni_char) > 0:
                    cp = ord(uni_char[0])
                    if 3134 <= cp <= 3148: # ా to ౌ
                        current_type = "vowelsign"
                        
                # Exclude digits range
                if len(uni_char) > 0:
                    cp = ord(uni_char[0])
                    if 3174 <= cp <= 3183: # Telugu digits
                        continue
                        
                # Resolve duplicate mapping collisions (prefer standard characters)
                if raw_str in mapping:
                    existing = mapping[raw_str]["text"]
                    if "ౘ" in existing and "చ" in uni_char:
                        pass
                    elif "ౘ" in uni_char:
                        continue
                    if "ౙ" in existing and "జ" in uni_char:
                        pass
                    elif "ౙ" in uni_char:
                        continue
                    if raw_str == "^Î:" and uni_char == "ధః":
                        continue

                mapping[raw_str] = {
                    "text": uni_char,
                    "type": current_type
                }
                
        add_entries(base_map, "base")
        add_entries(vattu_map, "vattu")
        add_entries(gunintam_map, "gunintam")
        
        # Sort keys by length descending to match longest glyphs first
        sorted_keys = sorted(mapping.keys(), key=len, reverse=True)
        max_len = len(sorted_keys[0]) if sorted_keys else 0
        
        return {
            "mapping": mapping,
            "keys": sorted_keys,
            "max_len": max_len
        }

    def _inject_overrides(self):
        overrides = {
            "\x71\xb6": {"text": "మీ", "type": "gunintam"},       # q¶ -> మీ
            "\xf9": {"text": "ొ", "type": "vowelsign"},          # ù -> ొ
            "\u0192\x8f\u2019": {"text": "భ", "type": "base"},  # ƒ\x8f’ -> భ
            "\u0192\x8f": {"text": "భ", "type": "base"},         # ƒ\x8f -> భ
            "\u0192": {"text": "భ", "type": "base"},             # ƒ -> భ
            "\x77": {"text": "రా", "type": "base"},              # w -> రా
            "\x6c": {"text": "ి", "type": "vowelsign"},          # l -> ి
            "\xc7": {"text": "హ", "type": "base"},               # Ç -> హ
            "\xab": {"text": "త", "type": "base"},               # « -> త
            "\x62": {"text": "్లీ", "type": "gunintam"},          # b -> ్లీ
            
            # Vowelsign and layout fixes
            "\xb0": {"text": "ు", "type": "vowelsign"},           # ° -> ు
            "\u03bc": {"text": "ు", "type": "vowelsign"},        # μ -> ు
            "\u00b5": {"text": "ు", "type": "vowelsign"},        # µ -> ు
            
            # Sha-family overrides for Priyaanka font
            "\x77\x9f": {"text": "ష", "type": "base"},            # w\x9f -> ష
            "\x77\xbe": {"text": "షి", "type": "gunintam"},        # w¾ -> షి
            "\x77\xee": {"text": "షీ", "type": "gunintam"},        # wî -> షీ
            
            # Suffix override for rayabadina
            "_È¤": {"text": "డిన", "type": "base"},              # _È¤ -> డిన
        }
        
        engine = self.engines["anu6"]
        for raw_str, val in overrides.items():
            engine["mapping"][raw_str] = val
            if raw_str not in engine["keys"]:
                engine["keys"].append(raw_str)
                
        # Re-sort keys by length descending
        engine["keys"] = sorted(engine["keys"], key=len, reverse=True)
        engine["max_len"] = len(engine["keys"][0]) if engine["keys"] else 0

    def _macroman_to_cp1252_char(self, b):
        try:
            return bytes([b]).decode('cp1252')
        except UnicodeDecodeError:
            # Map undefined control bytes directly to their Latin-1 control character codepoints
            return chr(b)

    def transcode_from_macroman(self, text):
        # Normalize characters that PyMuPDF decodes differently from python's mac_roman (e.g. U+0394 Delta -> U+2206 Increment)
        normalization = {
            "\u0394": "\u2206",
        }
        transcoded = []
        for char in text:
            char = normalization.get(char, char)
            try:
                # Encode character to byte using mac_roman
                b = char.encode('mac_roman')
                # Decode byte using cp1252 / latin1 hybrid mapping
                transcoded.append(self._macroman_to_cp1252_char(b[0]))
            except Exception:
                # Fallback to original character
                transcoded.append(char)
        return "".join(transcoded)

    def decode(self, text, layout="anu6"):
        if not text:
            return ""
            
        # Transcode text from PDF MacRoman representation to ANSI (Windows-1252) representation
        processed_text = self.transcode_from_macroman(text)
        
        # Get active engine
        engine = self.engines.get(layout, self.engines["anu6"])
        mapping = engine["mapping"]
        keys = engine["keys"]
        max_len = engine["max_len"]
        
        # Standardize spaces and ligatures
        if layout == "anu7":
            processed_text = processed_text.replace("\u008f", " ").replace("\u00ad", "TT").replace("\u00c5\u00a3", "Å£")
        
        e = "" # consonant accumulator
        n = "" # vowelsign accumulator
        s = "" # ra-vattu accumulator
        v = "" # vattu accumulator
        o = False # ZWNJ / trailing halant flag
        
        u = 0
        a = len(processed_text)
        
        while u < a:
            matched = False
            # Greedy matching for mapped strings
            for c in range(min(max_len, a - u), 0, -1):
                chunk = processed_text[u:u+c]
                l = mapping.get(chunk)
                
                if l:
                    text_val = l["text"]
                    type_val = l["type"]
                    
                    if type_val == "vattu" and text_val != "ర":
                        e += self.POLLU + text_val
                    else:
                        # Side-effect buffer flushing matching Suresh's JS logic
                        # i.e., whenever we match anything other than vattu (not ర), we flush v and n
                        if v:
                            e += self.POLLU + v
                            v = ""
                            s = ""
                        if n:
                            e += n
                            n = ""
                            
                        if type_val == "vowelsign":
                            n += text_val
                        elif type_val == "gunintam":
                            if o:
                                e += self.POLLU + self.ZWNJ
                                o = False
                                
                            chars = list(text_val)
                            if len(chars) > 1:
                                if chars[-1] == self.POLLU:
                                    chars.pop()
                                    o = True
                                for char in chars:
                                    cp = ord(char)
                                    if (3134 <= cp <= 3148) or (3073 <= cp <= 3075) or (3170 <= cp <= 3171) or cp == 3157 or cp == 3158:
                                        n += char
                                    else:
                                        e += char
                            else:
                                e += text_val
                                n = ""
                                
                            if s:
                                v += s
                                s = ""
                        elif type_val == "vattu" and text_val == "ర":
                            s += text_val
                        else:
                            o = False
                            e += text_val
                            
                    u += c
                    matched = True
                    break
                    
            if not matched:
                if v:
                    e += self.POLLU + v
                    v = ""
                    s = ""
                if n:
                    e += n
                    n = ""
                if o:
                    e += self.POLLU
                    o = False
                e += processed_text[u]
                u += 1
                
        # Flush remaining buffers
        if v:
            e += self.POLLU + v
        if n:
            e += n
        if o:
            e += self.POLLU
            
        # Post-replacements matching web app's postprocessing
        final_output = e
        if layout == "anu7":
            final_output = final_output.replace("\u00c5\u00a3", "క").replace("{", "ట")
        
        # Legacy reordering helpers for lingering combinations if any
        # ee-matra, ai-matra, and ra-vattu reordering across consonant clusters
        final_output = re.sub(r"¿([క-హౘ-ౚౠ-ౡ](?:్[క-హౘ-ౚౠ-ౡ])*[ా-ౄె-ౌౕౖఁ-ః]*)", r"\1ే", final_output)
        final_output = re.sub(r"Ã([క-హౘ-ౚౠ-ౡ](?:్[క-హౘ-ౚౠ-ౡ])*[ా-ౄె-ౌౕౖఁ-ః]*)", r"\1ె", final_output)
        final_output = re.sub(r"„([క-హౘ-ౚౠ-ౡ](?:్[క-హౘ-ౚౠ-ౡ])*[ా-ౄె-ౌౕౖఁ-ః]*)", r"\1్ర", final_output)
        
        # Linguistic normalization reordering: consonant + vowel + halant + vattu -> consonant + halant + vattu + vowel
        final_output = re.sub(r"([క-హౘ-ౚ])([ా-ౄె-ౌౕౖ])్([క-హౘ-ౚ])", r"\1్\3\2", final_output)
        
        final_output = final_output.replace("Ð", "-")
        return final_output

if __name__ == "__main__":
    d = AnuToUnicodeDecoder()
    sample = "„¿Ñ=∞"
    print("Sample Anu6:", sample)
    print("Decoded Anu6:", d.decode(sample, "anu6"))
