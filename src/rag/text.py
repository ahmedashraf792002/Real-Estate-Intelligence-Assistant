"""Arabic/English tokenisation shared by ingestion and search.

Besides plain word tokens, it emits language-neutral "concept" tokens (e.g. فيلا / villas -> c_villa)
so keyword search still works when the question and the page are in different languages.
"""
import re

_DIAC = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[A-Za-z؀-ۿ]+")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٬", "0123456789,")

STOP = set("""في من على الي إلى عن هل ما ماذا كم هو هي هذا هذه ان أن و او مع كل لي لك
the a an of in on is are was were what which how much many for to and or with me tell about do does i you it
this that there their can could give list show any""".split())


def norm_ar(s):
    s = _DIAC.sub("", s).replace("ـ", "")
    s = re.sub("[إأآٱ]", "ا", s)
    return s.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")


# concept -> words (Arabic ones are normalised below)
_CONCEPTS = {
    "villa": ["villa", "فيلا", "فلل", "فيلات"],
    "apartment": ["apartment", "flat", "شقة", "شقق"],
    "land": ["land", "plot", "أرض", "ارض", "أراضي", "اراضي"],
    "floor": ["floor", "دور", "أدوار", "ادوار"],
    "project": ["project", "development", "مشروع", "مشاريع"],
    "price": ["price", "cost", "سعر", "أسعار", "اسعار", "تكلفة"],
    "rent": ["rent", "rental", "إيجار", "ايجار", "للإيجار", "للايجار"],
    "sale": ["sale", "buy", "بيع", "للبيع", "شراء"],
    "riyadh": ["riyadh", "الرياض", "رياض"],
    "jeddah": ["jeddah", "jedda", "جدة", "جده"],
    "makkah": ["makkah", "mecca", "مكة", "مكه"],
    "madinah": ["madinah", "medina", "المدينة", "المدينه"],
    "dammam": ["dammam", "الدمام"],
    "khobar": ["khobar", "الخبر"],
    "bedroom": ["bedroom", "bedrooms", "غرفة", "غرف", "نوم"],
    "developer": ["developer", "مطور", "مطوّر"],
    "dar": ["dar", "دار"],
    "global": ["global", "جلوبال"],
    "alarkan": ["alarkan", "arkan", "الأركان", "الاركان", "اركان"],
    "mouawad": ["mouawad", "معوض"],
    "oman": ["oman", "عمان", "عُمان"],
    "qatar": ["qatar", "قطر"],
    "dubai": ["dubai", "دبي"],
    "trump": ["trump", "ترامب"],
    "construction": ["construction", "إنشاء", "انشاء"],
    "area": ["area", "size", "مساحة", "مساحه"],
    "district": ["district", "neighborhood", "حي", "حى"],
    "location": ["location", "موقع"],
    "unit": ["unit", "units", "وحدة", "وحدات"],
    "golf": ["golf", "جولف"],
    "hotel": ["hotel", "فندق"],
}
WORD2CONCEPT = {}
for _c, _ws in _CONCEPTS.items():
    for _w in _ws:
        WORD2CONCEPT[norm_ar(_w.lower())] = "c_" + _c


def _stem(w):
    if re.match(r"[A-Za-z]+$", w):
        if len(w) > 4 and w.endswith("ies"):
            return w[:-3] + "y"
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            return w[:-1]
        return w
    for p in ("وال", "بال", "كال", "فال", "لل", "ال"):
        if w.startswith(p) and len(w) - len(p) >= 3:
            return w[len(p):]
    return w


def tokens(text):
    text = norm_ar(text.translate(_DIGITS)).lower()
    out = []
    for raw in _TOKEN.findall(text):
        w = raw.replace(",", "") if raw[0].isdigit() else raw
        if w in STOP or len(w) < 2 and not w.isdigit():
            continue
        c = WORD2CONCEPT.get(w) or WORD2CONCEPT.get(_stem(w))
        out.append(_stem(w))
        if c:
            out.append(c)
    return out
