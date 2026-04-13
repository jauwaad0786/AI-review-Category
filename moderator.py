import re
import json
import time
import requests
import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
)

# ─────────────────────────────────────────────
# PERSISTENT SESSION — reuse TCP connections
# Eliminates DNS + TLS handshake on every call
# ─────────────────────────────────────────────
_session = requests.Session()
_session.headers.update({"Content-Type": "application/json"})

# ─────────────────────────────────────────────
# SPAM PATTERNS — phone, email, links
# ─────────────────────────────────────────────
SPAM_PATTERNS = [
    r"\b\d{10}\b",
    r"\b\d{5}\s\d{5}\b",
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    r"https?://\S+",
    r"www\.\S+",
    r"\bwhatsapp\b",
    r"\btelegram\b",
    r"\binstagram\b",
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
    "not great", "could be better"
]
HARD_NEGATIVE = [
    "complete fraud", "total scam", "money theft",
    "robbery", "chor company", "run away",
    "useless useless", "waste waste",
    "horrible horrible", "worst worst",
    "fake fake", "scam scam"
]


# ─────────────────────────────────────────────
# LAYER 1 — HARD RULES (instant, no API call)
# ─────────────────────────────────────────────
def layer1_hard_rules(review_text: str, star_rating: int):
    text       = review_text.lower().strip()
    word_count = len(text.split())

    if word_count < 2:
        return True, "review_too_short"

    for pattern in SPAM_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True, "spam_contact_info"

    for comp in COMPETITOR_NAMES:
        if comp in text:
            return True, "competitor_mention"

    for word in SPAM_INTENT_WORDS:
        if word in text:
            return True, f"spam_intent_detected:{word}"

    words = [w for w in text.split() if len(w) > 2 and w not in STOP_WORDS]
    from collections import Counter
    word_freq = Counter(words)
    for word, count in word_freq.items():
        if count >= 3 and word not in STOP_WORDS:
            return True, f"repeated_spam_word:{word}"

    hard_neg_count = sum(1 for w in HARD_NEGATIVE if w in text)
    if hard_neg_count >= 2:
        return True, "excessive_malicious_language"

    alpha_chars = [c for c in review_text if c.isalpha()]
    if len(alpha_chars) > 15:
        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        if upper_ratio > 0.80:
            return True, "aggressive_all_caps"

    return False, "passed"


# ─────────────────────────────────────────────
# LAYER 2 — GEMINI INTENT CHECK
# Retries on 429 / 503 (rate limit / overload)
# ─────────────────────────────────────────────
INTENT_PROMPT = """
You are a content moderator for easeMyDeal, a real estate platform.

Analyze this customer review and determine if it is:
- "genuine": real customer experience, even if negative
- "malicious": intentionally trying to damage the brand with no real experience
- "spam": promotional, random, or irrelevant content

Review: "{review_text}"
Star Rating: {star_rating}/5

Rules:
- Negative genuine reviews ARE allowed (slow response, high price, etc.)
- Malicious = no specific complaint, just attacks with extreme language
- Spam = contact info, ads, gibberish, repeated words

Return ONLY this JSON, nothing else:
{{
  "intent": "genuine",
  "confidence": 0.85,
  "reason": "one line reason"
}}
"""

def layer2_gemini_intent(review_text: str, star_rating: int):
    prompt = INTENT_PROMPT.format(
        review_text=review_text,
        star_rating=star_rating
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for attempt in range(3):                        # retry up to 3x
        try:
            res = _session.post(GEMINI_URL, json=payload, timeout=10)

            if res.status_code == 429 or res.status_code == 503:
                wait = 2 ** attempt                 # 1s, 2s, 4s
                print(f"  [Moderator] Gemini {res.status_code} → retry in {wait}s")
                time.sleep(wait)
                continue

            if res.status_code != 200:
                print(f"  [Moderator] Gemini HTTP {res.status_code} → skipping")
                return False, "gemini_unavailable"

            raw = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            raw = re.sub(r"```json|```", "", raw).strip()
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
                return False, "error_skipped"
            time.sleep(1)

    return False, "error_skipped"


# ─────────────────────────────────────────────
# LAYER 3 — PATTERN SCORE
# ─────────────────────────────────────────────
def layer3_pattern_score(review_text: str, star_rating: int):
    text  = review_text.lower()
    score = 100

    hard_neg_count = sum(1 for w in HARD_NEGATIVE if w in text)
    if hard_neg_count >= 2:
        score -= 25 * hard_neg_count

    mild_neg_count = sum(1 for w in MILD_NEGATIVE if w in text)
    if star_rating == 1 and mild_neg_count == 0 and hard_neg_count == 0:
        score -= 35

    word_count = len(text.split())
    if word_count < 8 and star_rating <= 2:
        score -= 20

    score = max(0, score)

    if star_rating >= 2 and word_count > 8:
        return False, score, "likely_genuine"

    if score < 20:
        return True, score, f"low_pattern_score:{score}"

    return False, score, "passed"


# ─────────────────────────────────────────────
# MAIN MODERATOR
# ─────────────────────────────────────────────
def moderate_review(review_text: str, star_rating: int):
    print(f"  [Moderator] Checking review (stars={star_rating}, words={len(review_text.split())})")

    reject, reason = layer1_hard_rules(review_text, star_rating)
    if reject:
        print(f"  [Moderator] ✗ REJECTED — Layer1: {reason}")
        return "rejected", reason

    reject, reason = layer2_gemini_intent(review_text, star_rating)
    if reject:
        print(f"  [Moderator] ✗ REJECTED — Layer2: {reason}")
        return "rejected", reason

    reject, score, reason = layer3_pattern_score(review_text, star_rating)
    if reject:
        print(f"  [Moderator] ✗ REJECTED — Layer3: {reason}")
        return "rejected", reason

    print(f"  [Moderator] ✓ APPROVED (score={score})")
    return "approved", "clean"