import re
import sys
import io

class PriyaankaDecoder:
    def __init__(self):
        # Mapping rules from Priyaanka font characters/glyhps to Telugu Unicode.
        # Order: Longer raw sequences must be replaced first.
        # We sort them dynamically by length of raw string in descending order.
        self.rules = [
            # Words & Phrases (known multi-character maps)
            ("[#=i", "జనవరి"),
            ("J@∞=O\\˜", "అటువంటి"),
            ("xiﬁÑ¶¨∞ﬂ=ÚQÍ", "నిర్విఘ్నముగా"),
            ("xiﬁÑ¶¨∞ﬂO", "నిర్విఘ్నం"),
            ("J#∞„QÆÇ≤ÏOÑ¨Ù=Ú", "అనుగ్రహింపుము"),
            ("K«∞<åﬂ#∞", "చున్నాను"),
            ("[~°∞QÆ∞#@∞¡", "జరుగునట్లు"),
            ("ã¨=∞„Ñ¨Éèí", "సమప్రభ"),
            ("HÍˆ~º+¨μ", "కార్యేషు"),
            ("ã¨~°ﬁ^•", "సర్వదా"),
            ("ã¨~°ﬁ", "సర్వ"),
            ("„áê~°÷#", "ప్రార్థన"),
            ("=„Hõ`«∞O_»", "వక్రతుండ"),
            ("=∞Ç¨\uf8ffHÍÜ«∞", "మహాకాయ"),
            ("ã¨∂~°ºHÀ\\˜", "సూర్యకోటి"),
            ("ã¨∂~°∞ºÅ", "సూర్యుల"),
            ("HõÅ\"å_»∞", "కలవాడు"),
            ("qâ◊ﬁ=Ú", "విశ్వము"),
            ("#O`«\\˜x", "నంతటిని"),
            ("W=Ú_»∞ÛH˘x#", "ఇముడ్చుకొనిన"),
            ("â◊s~°=Ú", "శరీరము"),
            ("HÀ\\˜", "కోటి"),
            ("HÍOntÀ", "కాంతితో"),
            ("ã¨=∂#\"≥∞ÿ#", "సమానమైన"),
            ("„Ñ¨HÍâ◊=Ú", "ప్రకాశము"),
            ("#=∞ã¨¯iOK«∞", "నమస్కరించు"),
            ("QÆ}Ñ¨u", "గణపతి"),
            ("=OHõ~°", "వంకర"),
            ("uiy#", "తిరిగిన"),
            ("`˘O_»=Ú", "తొండము"),
            
            # Specific bh-family combinations
            ("ÉèíHõ∞Î", "భక్తు"),
            ("ÉèíHõÎ", "భakti"), # wait, bhakthi
            ("ÉèíHõÎ", "భక్తి"),
            ("Éèí", "భ"),
            
            # Words and specific mappings discovered in reverse engineering
            ("వేˆర", "వేరే"),
            ("గురుˆరÌవో", "గురుర్దేవో"),
            ("ã¨ﬁ~°‚", "స్వర్ణ"),
            ("శార˚్గము", "శార్ఙ్గము"),
            ("<å~¸", "నాకూ"),
            ("=¸", "మూ"),
            ("Ñ¶¨", "ఫ"),
            ("Ñ¶", "ఫ"),
            ("Ñ¶¨∞", "ఘ"),
            ("Ñ¶", "ఘ"),
            ("àı§", "ళ్ళే"),
            ("o§", "ళ్ళి"),
            ("H\u02dc\u00ce", "క్తి"),
            ("KåHõe", "చాకలి"),
            ("ã¨OÑ¶¨∞hu", "సంఘనీతి"),
            ("áêÑ¨cèu", "పాపభీతి"),
            
            # Multi-byte overrides for u-matra and oo-matra merging
            ("õ¨Ω", "ూ"),
            ("õ¨∞", "ూ"),
            ("õ¨Ú", "ూ"),
            ("õ¨Ù", "ూ"),
            ("õ¨ï", "ూ"),
            ("õΩ", "ూ"),
            ("õ∞", "ూ"),
            ("õÚ", "ూ"),
            ("õÙ", "ూ"),
            ("õï", "ూ"),
            
            # Additional mappings for remaining symbols
            ("ˆ", "¿"),
            ("˚", "్ఙ"),
            ("Ù", "ు"),
            ("f", "తీ"),
            ("¥", "శి"),
            ("§", "ు"),
            ("ª", "్ట"),
            ("®", "ా"),
            ("±", "్"),
            ("Á", "ొ"),
            ("Ä", ""),
            ("ç", "ి"),
            ("é", "ద్ధి"),
            ("]", "కి"),
            ("ı", "ే"),
            ("ó", "ః"),
            ("ü", "్"),
            ("ƒ", "్భ"),
            ("˜", "ి"),
            ("Ω", "ు"),
            ("π", "్"),
            ("–", "-"),
            ("—", "-"),
            ("‘", "ీ"),
            ("“", "ౌ"),
            ("‰", "క"),
            ("‹", "ె"),
            ("™", "స"),
            ("√", "ు"),
            ("¥", "ూ"),
            ("∫", "ౌ"),
            ("≈", "్శ"),
            ("Ì", "్ద"),
            ("Í", "ా"),
            ("Ó", "ూ"),
            ("Ô", "Ã"), # Reordered e-matra
            ("Û", "్చ"),
            ("à", "ళ"),
            ("ä", "థ"),
            ("X", "ఒ"),
            ("[", "జ"),
            ("b", "్లీ"),
            ("w\x9f", "ష"),
            ("w¾", "షి"),
            ("wÓ", "షీ"),
            ("w", "రా"),
            ("ë", "ష"),
            ("ì", "్ట"),
            ("À", "ో"),
            ("È", "ో"),
            ("*", "జ"),
            ("˝", "్ఞ"),
            ("e", "ల"),
            ("l", "ి"),
            ("C", "్పు"),
            ("ï", "ు"),
            ("Ú", "ు"),
            ("˘", "ొ"),
            ("@", "ట"),
            ("ﬁ", "్వ"),
            ("P", "ఆ"),
            ("¤", "ిన"),
            ("£", "్"),
            ("Ü«∂", "యా"),
            ("õ", ""),
            ("÷", "్థ"),
            ("ú", "్ధ"),
            ("ù", ""),
            ("Ÿ", "ో"),
            ("ò", "్"),
            ("«", ""),
            
            # Base glyphs & syllables
            ("_è»∞", "ఢు"),
            ("_è»", "ఢ"),
            ("\"Õ∞", "మే"),
            ("\"≥∞ÿ", "మై"),
            ("\"∞", "మ"),
            ("^è", "ధ"),
            ("ది్", "ధి"),
            ("హాృ", "హృ"),
            
            ("ã¨Oz", "సంచి"),
            ("ã¨∂", "సూ"),
            ("ã¨O", "సం"),
            ("ã¨", "స"),
            ("™ê", "సా"),
            ("~Ú", "యి"),
            ("ÉÏ", "బా"),
            ("Å", "ల"),
            ("q", "వి"),
            ("HÍ", "కా"),
            ("ãπ", "స్"),
            ("Ñ¨Ù", "పు"),
            ("\\˜", "టి"),
            ("Hõ", "క"),
            ("N", "శ్రీ"),
            ("QÆ", "గ"),
            ("}", "ణ"),
            ("Ë", "ే"),
            ("â◊", "శ"),
            ("J", "అ"),
            ("F", "ఓ"),
            ("h", "నీ"),
            ("‰õÄ", "కూ"),
            ("‰õΩ", "కు"),
            ("<Õ", "నే"),
            ("KÕ", "చే"),
            ("Ü«Ú", "యు"),
            ("Ñ¨x", "పని"),
            ("`«∞", "తు"),
            ("O", "ం"),
            ("_»", "డ"),
            ("=∞", "మ"),
            ("Ç¨", "హ"),
            ("\uf8ff", "ా"),
            ("Ü«∞", "య"),
            ("u", "తి"),
            ("i", "రి"),
            ("y", "గి"),
            ("#", "న"),
            ("`˘", "తొ"),
            ("W", "ఇ"),
            ("`«", "త"),
            ("=", "వ"),
            ("º", "్య"),
            ("`", "త"),
            
            # Rebuilding glyph components
            ("ﬂ", "్న"),
            ("¯", "్క"),
            ("K«", "చ"),
            ("K«∞", "చు"),
            ("KÕ", "చే"),
            ("^Õ", "దే"),
            ("`«\"", "తా"),
            ("\"", "వ"),
            ("^", "ద"),
            ("Õ", "ే"),
            ("å", "ా"),
            ("~°∞", "రు"),
            ("~°", "ర"),
            ("∞", "ు"),
            ("Éè", "భ"),
            ("É", "బ"),
            ("è", "్"), 
            ("Ï", "ా"),
            ("∂", "ూ"),
            ("°", ""),
            ("~", "ర"),
            ("◊", ""),
            ("â", "శ"),
            
            # New components discovered in Page 2 & 3
            ("L", "ఉ"),
            ("≤", "ి"),
            ("k", "ది"),
            ("Œ", ""),      # ignored joiner
            ("·", "ౖ"),     # right side of ai matra
            ("+$", "ృష"),   # combined r-vattu + sha
            ("+", "ష"),
            ("$", "ృ"),
            ("‚", "్ణ"),    # na vattu
            ("μ", "ు"),     # u matra (subjoined)
            ("ˇ", "ె"),     # e vowel sign
            ("¡", "్ల"),    # la vattu
            ("á", "ప"),     # pa variant
            ("⁄", "ొ"),     # o matra (subjoined)
            ("Î", "్త"),    # ta vattu
            ("Y", "్ఖ"),    # kha vattu (in సఖ్యం)
            ("ê", "ా"),
            ("Δ", "్ష"),    # sha vattu (in క్ల)
            ("|", "బ"),
            ("•", "ా"),
            ("U", "ఏ"),
            ("Ê", "్ప"),
            ("<", "న"),
            ("ß", "ా"),
            ("í", "క్"),
            ("æ", "్గ"),    # ga vattu
            ("‡", "్మ"),    # ma vattu
            ("©", "ీ"),
            ("û", "్స"),    # sa vattu
            ("≥", "ె"),
            
            # Consonant "ల" (La) family mappings
            ("Ö’", "లో"),
            ("Öే", "లే"),
            ("Ö", "ల"),
            ("’", "ో"),
            ("ˇ", "ె"),
            ("¡", "్ల"),
            
            # Spacing & Punctuation modifiers
            ("`«", "త"),
            ("`«\"", "తా"),
            ("`˘", "తొ"),
            ("`", ""),
            ("¨", ""),      # ignored tick mark
            
            # Singular base consonants (fallbacks)
            ("Ñ¨", "ప"),
            ("Ñ", "ప"),
            ("ã", "స"),
            ("H", "క"),
            ("Q", "గ"),
            ("}", "ణ"),
            ("â", "శ"),
            ("Ç", "హ"),
            ("Ü", "య"),
            ("K", "చ"),
            ("_", "డ"),
            ("á", "ప"),
            ("=", "వ"),
            ("u", "తి"),
            ("i", "రి"),
            ("y", "గి"),
            ("z", "చి"),
            ("x", "ని"),
            ("q", "వి"),
            ("~", "ర"),
            ("#", "న"),
            ("É", "బ"),
            ("J", "అ"),
            ("W", "ఇ"),
            ("D", "ఈ"),
            ("L", "ఉ"),
            ("T", "ఊ"),
            ("Z", "ఎ"),
            ("U", "ఏ"),
            ("F", "ఓ"),
            ("S", "ఐ"),
            ("B", "ఔ"),
            ("t", "శి"),
        ]
        
        # Filter duplicate rules and sort by length of raw sequence descending
        seen = set()
        unique_rules = []
        for raw, tel in self.rules:
            if raw not in seen:
                seen.add(raw)
                unique_rules.append((raw, tel))
        
        self.rules = sorted(unique_rules, key=lambda x: len(x[0]), reverse=True)

    def decode(self, text):
        if not text:
            return ""
            
        decoded = text
        
        # Step 1: Replace matching raw character sequences using sorted rules
        for raw, tel in self.rules:
            decoded = decoded.replace(raw, tel)
            
        # Step 2: Vowel signs pre-consonant reordering
        # ee-matra: "¿" -> "ే"
        decoded = re.sub(r"¿([క-హౘ-ౚౠ-ౡ](?:్[క-హౘ-ౚౠ-ౡ])*[ా-ౄె-ౌౕౖఁ-ః]*)", r"\1ే", decoded)
        # ai-matra: "Ã" -> "ె" (will combine with post-consonant "·" -> "ౖ" which becomes "ై")
        decoded = re.sub(r"Ã([క-హౘ-ౚౠ-ౡ](?:్[క-హౘ-ౚౠ-ౡ])*[ా-ౄె-ౌౕౖఁ-ః]*)", r"\1ె", decoded)
        
        # Step 3: ra-vattu pre-consonant reordering
        # ra-vattu: "„" -> "్ర"
        decoded = re.sub(r"„([క-హౘ-ౚౠ-ౡ](?:్[క-హౘ-ౚౠ-ౡ])*[ా-ౄె-ౌౕౖఁ-ః]*)", r"\1్ర", decoded)
        
        # Step 4: Linguistic Normalization for Unicode Conjuncts
        # Move vowel signs (like ి, ు, ె, etc.) after the subjoined vattu (్ + consonant)
        # Pattern: base consonant + vowel sign + halant + subjoined consonant
        # Replace: base consonant + halant + subjoined consonant + vowel sign
        decoded = re.sub(r"([క-హౘ-ౚ])([ా-ౄె-ౌౕౖ])్([క-హౘ-ౚ])", r"\1్\3\2", decoded)
        
        return decoded

if __name__ == "__main__":
    decoder = PriyaankaDecoder()
    sample = "„¿Ñ=∞"  # raw "ప్రేమ"
    print(f"Sample: {sample}")
    print(f"Decoded: {decoder.decode(sample)}")
