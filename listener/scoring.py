"""Rule-based pain/intent scoring. Transparent and free; an LLM pass can be layered on later
via the JSON export (e.g. a newmax skill that re-scores `new` leads)."""
import re

DEFAULT_RULES = {
    "pain": {
        "không có khách": 12, "ít khách": 8, "không có đơn": 12,
        "không ra đơn": 12, "khó tìm khách": 11, "khó chốt đơn": 10,
        "mất khách": 10, "bị bỏ sót": 9, "quá tải tin nhắn": 12,
        "không quản lý nổi": 12, "tốn thời gian": 7, "khó quản lý": 8,
        "web chậm": 8, "website chậm": 8, "không biết làm sao": 6,
        "traffic dropped": 12, "traffic drop": 12, "lost traffic": 12, "organic traffic down": 12,
        "ai overviews": 8, "ai overview": 8, "zero-click": 8, "zero click": 8,
        "doesn't mention": 12, "doesnt mention": 12, "not mentioned": 10, "not showing up": 10,
        "show up in chatgpt": 12, "appear in chatgpt": 12, "recommend us": 8, "ai search": 6,
        "struggling": 8, "frustrated": 6, "can't get": 6, "no customers": 10, "no users": 8,
        "cac": 6, "customer acquisition": 6, "lead gen": 5, "pipeline": 4, "churn": 3,
    },
    "intent": {
        "đang tìm": 9, "cần thuê": 14, "cần người làm": 12,
        "cần dịch vụ": 13, "xin giới thiệu": 11, "ai biết chỗ nào": 10,
        "có bên nào": 10, "báo giá": 11, "có ngân sách": 12,
        "looking for": 10, "any recommendations": 10, "recommend an agency": 15, "agency": 6,
        "consultant": 8, "freelancer": 6, "how do i": 6, "how do you": 5, "what worked": 6,
        "anyone tried": 6, "need help": 10, "hire": 4, "budget": 6, "willing to pay": 12,
    },
    "persona": {
        "saas": ["saas", "b2b", "arr", "mrr", "founder", "startup", "head of growth", "demand gen"],
        "local_business": ["cửa hàng", "quán", "shop", "doanh nghiệp", "kinh doanh", "chủ tiệm"],
        "dtc": ["shopify", "dtc", "d2c", "ecommerce", "e-commerce", "amazon seller", "store", "brand"],
    },
    "negative": {
        "mình cung cấp dịch vụ": -15, "nhận làm": -9,
        "liên hệ mình": -9, "khuyến mãi": -5, "tuyển cộng tác viên": -8,
        "i built": -8, "check out my": -10, "launching my": -6, "giveaway": -15, "crypto": -15,
        "airdrop": -20, "nsfw": -30, "job seeker": -10, "open to work": -15,
        "who is hiring": -30, "who wants to be hired": -30, "seeking work": -20,
    },
}


def _hits(text, table):
    found, total = [], 0
    for phrase, weight in table.items():
        if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", text):
            found.append(phrase)
            total += weight
    return found, total


def score_signal(sig, rules=None):
    """Return (score 0-100, persona, matched_terms)."""
    rules = rules or DEFAULT_RULES
    # community carries subreddit / HN thread title, useful for persona and for filtering hiring threads.
    text = f"{sig.get('title', '')} {sig.get('text', '')} {sig.get('community', '')}".lower()
    pain_f, pain = _hits(text, rules.get("pain", {}))
    intent_f, intent = _hits(text, rules.get("intent", {}))
    neg_f, neg = _hits(text, rules.get("negative", {}))

    persona, best = "other", 0
    for name, words in rules.get("persona", {}).items():
        n = sum(1 for w in words if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text))
        if n > best:
            persona, best = name, n

    base = {"hiring": 30, "funding": 35}.get(sig.get("kind"), 0)
    eng = min(10, (sig.get("engagement") or 0) // 10)
    # Questions are a strong "asking for help" signal on forums.
    question = 5 if "?" in text else 0
    score = base + min(45, pain) + min(30, intent) + min(10, best * 3) + eng + question + neg
    return max(0, min(100, score)), persona, pain_f + intent_f + neg_f
