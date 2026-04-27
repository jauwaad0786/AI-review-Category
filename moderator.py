import re
import json
import time
import requests
import os
from collections import Counter  # FIX B — moved from inside layer1_hard_rules
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
)

# ─────────────────────────────────────────────
# PERSISTENT SESSION — reuse TCP connections
# ─────────────────────────────────────────────
_session = requests.Session()
_session.headers.update({"Content-Type": "application/json"})

# ─────────────────────────────────────────────
# RISK C — Gemini degradation tracker
# ─────────────────────────────────────────────
_gemini_fail_count = 0

# ─────────────────────────────────────────────
# SPAM PATTERNS — phone, email, links
# ─────────────────────────────────────────────
SPAM_PATTERNS = [
    # normal phone
    r"\b\d{10,}\b",

    # spaced numbers
    r"(?:\d[\s\-]*){10,}",

    # email
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",

    # links — direct
    r"https?://\S+",
    r"www\.\S+",

    # domain — direct (more TLDs)
    r"\b[a-zA-Z0-9-]+\.(com|in|net|org|io|co|info|biz|xyz|site|online)\b(?!\w)",

    # domain — spaced dot trick: "housing . com"
    r"\b[a-zA-Z0-9-]+\s*\.\s*(com|in|net|org|io|co|info|biz|xyz)\b",

    # domain — written out: "housing dot com"
    r"\b\w+\s+dot\s+(com|in|net|org|io|co|info)\b",

    # social spam
    r"\bwhatsapp\b",
    r"\btelegram\b",
    r"\binstagram\b",
    r"\bdm me\b",
    r"\binbox me\b",
    r"\bcontact me\b",
]

STOP_WORDS = {
    "the", "and", "but", "is", "are", "was", "were",
    "this", "that", "for", "with", "have", "has",
    "had", "not", "very", "it", "of", "to", "in", "on"
}

SPAM_INTENT_WORDS = [
    "spam", "fake review", "paid review",
    "rating girane", "rating down",
    "paid promotion",
]

COMPETITOR_NAMES = [
    "magicbricks", "99acres", "housing.com", "nobroker",
    "makaan", "commonfloor", "squareyards",
    "amazon", "flipkart", "meesho", "myntra",
    "snapdeal", "indiamart", "tradeindia"
]

MILD_NEGATIVE = [
    "slow", "delay", "late", "issue", "problem",
    "not great", "could be better",
    "failed", "failure", "not working", "not activated",
    "deducted", "debited", "not credited", "not received",
    "not refunded", "refund failed",
    "transaction failed", "payment failed",
    "recharge failed", "recharge not done",
    "no response", "not responding", "no support"
]

HARD_NEGATIVE = [
    "complete fraud", "total scam", "money theft",
    "robbery", "chor company", "run away",
    "useless useless", "waste waste",
    "horrible horrible", "worst worst",
    "fake fake", "scam scam"
]

NEGATIVE_SINGLE_WORDS = {
    "fraud", "scam", "fake", "worst",
    "slow", "delay", "problem", "issue",
    "failed", "error"
}

NUM_WORD_MAP = {
    "zero": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9"
}

# FIX A — removed "i","v","vi" — too common as English words/pronouns
# Kept only unambiguous multi-char roman numerals
ROMAN_MAP = {
    "ii": "2", "iii": "3", "iv": "4",
    "vii": "7", "viii": "8", "ix": "9"
}


def normalize_text_for_numbers(text: str) -> str:
    words = text.lower().split()
    normalized = []
    for w in words:
        if w in NUM_WORD_MAP:
            normalized.append(NUM_WORD_MAP[w])
        elif w in ROMAN_MAP:
            normalized.append(ROMAN_MAP[w])
        else:
            normalized.append(w)
    return " ".join(normalized)


def detect_hidden_phone(text: str) -> bool:
    text_lower = text.lower()
    normalized = normalize_text_for_numbers(text_lower)

    # Rule 1 — 5+ digits after normalization
    # catches: "nine 7 6 two three four VII" → "9 7 6 2 3 4 7" = 7 digits
    digits = re.findall(r"\d", normalized)
    if len(digits) >= 5:
        return True

    # Rule 2 — 3+ consecutive spaced/separated digits
    # catches: "6 7 5" → 3 consecutive single digits
    if re.search(r"(?:\d[\s\-–_]*){3,}", normalized):
        return True

    # Rule 3 — 5+ roman numeral tokens
    # catches: "IX VIII VII VI V IV III II" = 8 roman tokens
    roman_tokens = [w for w in text_lower.split() if w in ROMAN_MAP]
    if len(roman_tokens) >= 5:
        return True

    # Rule 4 — mixed format: 2+ different number types AND total tokens >= 4
    # catches: "nine 7 VIII 6" → word + digit + roman = 3 types, 4 tokens
    word_num_tokens = [w for w in text_lower.split() if w in NUM_WORD_MAP]
    digit_tokens    = [w for w in text_lower.split() if re.fullmatch(r"\d+", w)]
    types_used = sum([
        len(word_num_tokens) > 0,
        len(digit_tokens) > 0,
        len(roman_tokens) > 0,
    ])
    total_num_tokens = len(word_num_tokens) + len(digit_tokens) + len(roman_tokens)
    if types_used >= 2 and total_num_tokens >= 4:
        return True

    return False


# ─────────────────────────────────────────────
# LAYER 1 — HARD RULES (instant, no API call)
# ─────────────────────────────────────────────
def layer1_hard_rules(comment: str, star_rating: int):
    text = comment.lower().strip()

    # FIX LOGIC — word_count check moved to top (fastest reject, no point running anything else)
    word_count = len(text.split())
    if word_count < 2:
        return True, "review_too_short"

    if detect_hidden_phone(text):
        return True, "hidden_phone_number"

    # too many numbers (OTP / spam pattern)
    digit_ratio = sum(c.isdigit() for c in text) / max(len(text), 1)
    if digit_ratio > 0.4:
        return True, "too_many_numbers"

    # mixed number words sequence
    if re.search(r"(?:\b(zero|one|two|three|four|five|six|seven|eight|nine)\b[\s]*){4,}", text):
        return True, "word_number_sequence"

    for pattern in SPAM_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True, f"spam_pattern_detected:{pattern}"

    for comp in COMPETITOR_NAMES:
        if comp in text:
            return True, "competitor_mention"

    for word in SPAM_INTENT_WORDS:
        if word in text:
            return True, f"spam_intent_detected:{word}"

    # FIX B — Counter now imported at top of file, not here
    words     = [w for w in text.split() if len(w) > 2 and w not in STOP_WORDS]
    word_freq = Counter(words)
    pos_words = {"good", "great", "easy", "fast", "smooth", "best", "excellent"}
    pos_count = sum(1 for w in words if w in pos_words)
    neg_count = sum(1 for w in words if w in NEGATIVE_SINGLE_WORDS)

    for word, count in word_freq.items():
        if pos_count > neg_count:
            continue
        if word in NEGATIVE_SINGLE_WORDS and count >= 3:
            return True, f"negative_repetition:{word}"
        if count >= 12:
            return True, f"extreme_repetition:{word}"

    hard_neg_count = sum(1 for w in HARD_NEGATIVE if w in text)
    if hard_neg_count >= 2:
        return True, "excessive_malicious_language"

    alpha_chars = [c for c in comment if c.isalpha()]
    if len(alpha_chars) > 15:
        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        if upper_ratio > 0.80:
            return True, "aggressive_all_caps"

    return False, "passed"


# ─────────────────────────────────────────────
# LAYER 2 — GEMINI INTENT CHECK
# ─────────────────────────────────────────────
INTENT_PROMPT = """
You are a content moderator for easeMyDeal, a real estate platform.

Analyze this customer review and determine if it is:
- "genuine": real customer experience, even if negative
- "malicious": intentionally trying to damage the brand with no real experience
- "spam": promotional, random, or irrelevant content

Review: "{comment}"
Star Rating: {star_rating}/5

Rules:
- Negative genuine tbl_seller_review ARE allowed (slow response, high price, etc.)
- Malicious = no specific complaint, just attacks with extreme language
- Spam = contact info, ads, gibberish, repeated words

Return ONLY this JSON, nothing else:
{{
  "intent": "genuine",
  "confidence": 0.85,
  "reason": "one line reason"
}}
"""

def layer2_gemini_intent(comment: str, star_rating: int):
    global _gemini_fail_count

    prompt  = INTENT_PROMPT.format(comment=comment, star_rating=star_rating)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for attempt in range(3):
        try:
            res = _session.post(GEMINI_URL, json=payload, timeout=10)

            if res.status_code in (429, 503):
                wait = 2 ** attempt
                print(f"  [Moderator] Gemini {res.status_code} → retry in {wait}s")
                time.sleep(wait)
                continue

            if res.status_code != 200:
                print(f"  [Moderator] Gemini HTTP {res.status_code} → skipping")
                # FIX C — track consecutive failures
                _gemini_fail_count += 1
                if _gemini_fail_count >= 5:
                    print(f"  [Moderator] ⚠ WARNING: Gemini failed {_gemini_fail_count} times — L2 degraded")
                return False, "gemini_unavailable"

            _gemini_fail_count = 0  # reset on success

            raw   = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            raw   = re.sub(r"```json|```", "", raw).strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return False, "parse_failed"

            parsed     = json.loads(match.group(0))
            intent     = parsed.get("intent", "genuine").lower()
            confidence = float(parsed.get("confidence", 0.5))
            reason     = parsed.get("reason", "")

            print(f"  [Moderator] Intent={intent} | Confidence={confidence:.2f} | {reason}")

            if intent == "malicious" and confidence >= 0.75:
                return True, f"malicious_intent:{reason}"

            if intent == "spam" and confidence >= 0.70:
                return True, f"spam_detected:{reason}"

            return False, "passed"

        except Exception as e:
            print(f"  [Moderator] Intent check error (attempt {attempt+1}): {e}")
            if attempt == 2:
                _gemini_fail_count += 1
                return False, "error_skipped"
            time.sleep(1)

    return False, "error_skipped"


# ─────────────────────────────────────────────
# LAYER 3 — PATTERN SCORE
# ─────────────────────────────────────────────
def layer3_pattern_score(comment: str, star_rating: int):
    text  = comment.lower()
    score = 100

    hard_neg_count = sum(1 for w in HARD_NEGATIVE if w in text)
    if hard_neg_count >= 2:
        score -= 25 * hard_neg_count

    mild_neg_count = sum(1 for w in MILD_NEGATIVE if w in text)

    complaint_phrases = [
        "money deducted", "not refunded",
        "transaction failed", "recharge failed",
        "amount debited", "payment not received"
    ]

    if star_rating == 1:
        if any(p in text for p in complaint_phrases):
            return False, score, "genuine_complaint"
        if mild_neg_count > 0 or hard_neg_count > 0:
            return False, score, "genuine_negative"
        score -= 15

    word_count = len(text.split())

    if word_count < 8 and star_rating <= 2:
        score -= 20

    # FIX D — replaced early return with score bonus
    # long detailed tbl_seller_review get rewarded but still go through scoring
    if word_count > 30:
        score = min(100, score + 15)

    score = max(0, score)

    if star_rating >= 2 and word_count > 8:
        return False, score, "likely_genuine"

    if score < 20:
        return True, score, f"low_pattern_score:{score}"

    return False, score, "passed"


# ─────────────────────────────────────────────
# MAIN MODERATOR
# ─────────────────────────────────────────────
def moderate_review(comment: str, star_rating: int):
    print(f"  [Moderator] Checking review (stars={star_rating}, words={len(comment.split())})")

    reject, reason = layer1_hard_rules(comment, star_rating)
    if reject:
        print(f"  [Moderator] ✗ REJECTED — Layer1: {reason}")
        return "rejected", reason

    #reject, reason = layer2_gemini_intent(comment, star_rating) because groq is used 
    # 🔥 Gemini disabled for testing
    reject, reason = False, "gemini_skipped"
    if reject:
        print(f"  [Moderator] ✗ REJECTED — Layer2: {reason}")
        return "rejected", reason

    reject, score, reason = layer3_pattern_score(comment, star_rating)

    # FIX E — removed fallback_safe block
    # layer3 decides cleanly; no word-count bypass
    if reject:
        print(f"  [Moderator] ✗ REJECTED — Layer3: {reason}")
        return "rejected", reason

    print(f"  [Moderator] ✓ APPROVED (score={score}, reason={reason})")
    return "approved", reason