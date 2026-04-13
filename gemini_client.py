import json
import os
import re
import time
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# ─────────────────────────────────────────────
# PERSISTENT SESSIONS — reuse TCP connections
# One session per API endpoint (different base URLs)
# ─────────────────────────────────────────────
_gemini_session = requests.Session()
_gemini_session.headers.update({"Content-Type": "application/json"})

_openai_session = requests.Session()
_openai_session.headers.update({
    "Content-Type":  "application/json",
    "Authorization": f"Bearer {OPENAI_API_KEY}" if OPENAI_API_KEY else "",
})

# ─────────────────────────────────────────────
# SBERT + Clustering — lazy load (heavy import)
# ─────────────────────────────────────────────
_sbert_model      = None
_sentiment_model  = None


def _get_sbert():
    global _sbert_model
    if _sbert_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _sbert_model = SentenceTransformer('all-MiniLM-L6-v2')
        except Exception as e:
            print(f"  [SBERT] Load failed: {e}")
    return _sbert_model


def _get_bert_sentiment():
    global _sentiment_model
    if _sentiment_model is None:
        try:
            from transformers import pipeline
            _sentiment_model = pipeline(
                "sentiment-analysis",
                model="distilbert-base-uncased-finetuned-sst-2-english"
            )
        except Exception as e:
            print(f"  [BERT] Load failed: {e}")
    return _sentiment_model


# ─────────────────────────────────────────────
# PROMPT — universal domain, dynamic categories
# ─────────────────────────────────────────────
PROMPT_TEMPLATE = """
You are an AI review analyst for a multi-domain review platform
(could be real estate, workplace, product, fintech, consulting, etc.).

Review: "{review_text}"
Overall Rating given by user: {star_rating}/5

YOUR TASK:
1. Read the review carefully
2. Find ALL distinct topics mentioned
3. For EACH topic assign a star (1-5) based on the EXACT sentiment written for that topic

CRITICAL STAR RULES:
- "helpful", "responsive", "smooth", "great", "professional" → 4 or 5 stars
- "delayed", "slow", "high price", "slightly high", "not responsive" → 2 or 3 stars
- "worst", "terrible", "very bad" → 1 star
- "okay", "decent", "average" → 3 stars
- Weighted average of all category stars MUST be close to {star_rating}
- DO NOT give same star to all categories — reflect actual sentiment per topic

DOMAIN EXAMPLES (adapt to what the review is about):
- Workplace review → "Work Culture", "Management", "Work-Life Balance", "Office & Facilities", "Professionalism"
- Product review → "Product Quality", "Delivery & Shipping", "Customer Support", "Value for Money"
- Fintech review → "App / Platform UX", "Transaction Speed", "Security & Trust"
- Real estate → "Agent Communication", "Deal Speed", "Pricing & Value", "Documentation"
- Consulting → "Consulting Quality", "Project Delivery", "Professionalism"

SPECIAL RULES:
- Short review like "good", "great", "nice" → 1 category: "Overall Experience" with {star_rating} stars
- "but", "however", "although" = contrast → topics before and after get DIFFERENT stars
- A comma-separated list like "Responsiveness, Quality, Professionalism" →
  treat each as a separate positive category with {star_rating} stars

Return ONLY a JSON array, nothing else:
[
  {{"category": "Work Culture", "category_star": 5}},
  {{"category": "Professionalism", "category_star": 4}},
  {{"category": "Work-Life Balance", "category_star": 2}}
]
"""


# ─────────────────────────────────────────────
# API CALLS — with retry on rate-limit
# ─────────────────────────────────────────────
def _call_openai(prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise Exception("No OpenAI key in .env")
    for attempt in range(3):
        res = _openai_session.post(
            OPENAI_URL,
            json={
                "model":       "gpt-3.5-turbo",
                "messages":    [{"role": "user", "content": prompt}],
                "temperature": 0.2
            },
            timeout=15
        )
        if res.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        if res.status_code != 200:
            raise Exception(f"OpenAI HTTP {res.status_code}: {res.text[:150]}")
        return res.json()["choices"][0]["message"]["content"]
    raise Exception("OpenAI: max retries exceeded")


def _call_gemini(prompt: str) -> str:
    for attempt in range(3):
        res = _gemini_session.post(
            GEMINI_URL,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15
        )
        if res.status_code == 429 or res.status_code == 503:
            time.sleep(2 ** attempt)
            continue
        if res.status_code != 200:
            raise Exception(f"Gemini HTTP {res.status_code}: {res.text[:150]}")
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise Exception("Gemini: max retries exceeded")


# ─────────────────────────────────────────────
# JSON PARSER — normalize all possible formats
# ─────────────────────────────────────────────
def _parse_json(raw: str, star_rating: int) -> list[dict]:
    raw = re.sub(r"```json|```", "", raw).strip()

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, list):
            fixed = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                cat  = item.get("category") or item.get("name") or item.get("topic")
                star = (item.get("category_star") or item.get("stars")
                        or item.get("star") or item.get("avg_star"))
                if not cat:
                    continue
                try:
                    star = int(float(star)) if star is not None else star_rating
                except Exception:
                    star = star_rating
                fixed.append({
                    "category":      str(cat).strip(),
                    "category_star": max(1, min(5, star))
                })
            if fixed:
                return fixed[:5]

    raise Exception("No valid JSON array found")


# ─────────────────────────────────────────────
# UNIVERSAL TOPIC KEYWORDS
# ─────────────────────────────────────────────
TOPIC_KEYWORDS = {
    "Work Culture":         ["culture", "work culture", "environment", "atmosphere",
                             "vibe", "colleagues", "coworkers", "collaborative",
                             "toxic", "inclusive", "nice culture", "great culture"],
    "Management":           ["management", "manager", "leadership", "ceo", "boss",
                             "hierarchy", "micromanage", "vision", "directive"],
    "Work-Life Balance":    ["work life", "work-life", "balance", "overtime", "hours",
                             "flexible", "remote", "hybrid", "wfh", "burnout",
                             "late nights", "weekends", "stress"],
    "Learning & Growth":    ["learning", "growth", "career", "promotion", "training",
                             "skill", "development", "mentorship", "opportunity",
                             "upskill", "exposure", "challenging work"],
    "Office & Facilities":  ["office", "floor", "view", "building", "facility",
                             "cafeteria", "gym", "parking", "workspace", "desk",
                             "amenity", "infrastructure", "good office"],
    "Compensation":         ["salary", "pay", "hike", "increment", "bonus",
                             "compensation", "package", "ctc", "stipend", "benefits",
                             "underpaid", "overpaid"],
    "Professionalism":      ["professional", "professionalism", "expert", "skilled",
                             "knowledgeable", "competent", "industry standard",
                             "positive professionalism"],
    "Product Quality":      ["quality", "build quality", "material", "durable",
                             "sturdy", "defective", "broke", "poor quality"],
    "Delivery & Shipping":  ["delivery", "shipping", "dispatch", "arrived",
                             "late delivery", "fast delivery", "courier", "packaging"],
    "Customer Support":     ["support", "customer service", "helpline", "chat",
                             "resolved", "not responsive", "helpful staff",
                             "responsiveness"],
    "Value for Money":      ["value", "worth", "money", "overpriced", "affordable",
                             "value for money"],
    "Return & Refund":      ["return", "refund", "exchange", "replace",
                             "money back", "cancelled", "cancellation"],
    "Transaction Speed":    ["transaction", "transfer", "payment", "instant",
                             "slow transfer", "upi", "neft", "imps", "processing"],
    "App / Platform UX":    ["app", "website", "platform", "portal", "ui", "ux",
                             "interface", "navigation", "filter", "search",
                             "bug", "crash", "glitch", "easy to use"],
    "Security & Trust":     ["secure", "security", "fraud", "scam", "trust",
                             "kyc", "verification", "otp", "protected", "safe"],
    "Loan & Credit":        ["loan", "credit", "emi", "mortgage", "interest",
                             "bank", "finance", "approve", "sanction"],
    "Agent Communication":  ["agent", "broker", "dealer", "follow up", "contact",
                             "communication", "replied", "representative"],
    "Deal Speed":           ["delay", "delayed", "slow process", "fast deal",
                             "process time", "took time", "waited", "lengthy"],
    "Pricing & Value":      ["price", "pricing", "cost", "expensive", "high price",
                             "commission", "fee", "charge", "affordable"],
    "Documentation":        ["document", "documentation", "paper", "legal",
                             "registry", "lawyer", "paperwork", "stamp duty"],
    "Property Quality":     ["property", "flat", "apartment", "house", "plot",
                             "construction", "possession", "floor plan"],
    "Consulting Quality":   ["consulting", "consultant", "advisory", "advice",
                             "recommendation", "solution", "it consulting",
                             "business consulting", "expertise"],
    "Project Delivery":     ["project", "deadline", "deliverable", "on time",
                             "milestone", "sprint", "delayed project"],
    "Overall Experience":   ["good", "great", "amazing", "awesome", "wow",
                             "nice", "excellent", "satisfied", "happy",
                             "recommend", "wonderful", "fantastic", "best",
                             "love", "overall", "impressive", "outstanding",
                             "superb", "positive", "nice organization",
                             "great organization", "awesome organization"],
}

CANONICAL_CATEGORIES = set(TOPIC_KEYWORDS.keys())

POS_WORDS = {
    "helpful", "responsive", "professional", "smooth", "fast", "quick",
    "great", "good", "excellent", "amazing", "easy", "satisfied",
    "happy", "nice", "perfect", "outstanding", "superb", "reasonable",
    "affordable", "fair", "transparent", "well", "properly", "clearly",
    "friendly", "knowledgeable", "supportive", "impressive", "dedicated",
    "collaborative", "innovative", "inclusive", "skilled", "fantastic",
    "wonderful", "awesome", "positive", "brilliant"
}

NEG_WORDS = {
    "slow", "delay", "delayed", "late", "not responsive", "ignored",
    "expensive", "high", "slightly high", "misleading", "hidden",
    "problem", "issue", "bad", "poor", "terrible", "worst",
    "incomplete", "wrong", "error", "confusing", "difficult",
    "not helpful", "not very helpful", "not very responsive",
    "toxic", "burnout", "bias", "underpaid", "overworked"
}


def _nlp_sentiment_star(sentence: str, overall_star: int) -> int:
    t       = sentence.lower()
    negated = bool(re.search(r"\bnot\s+\w+", t))

    pos_count = sum(1 for w in POS_WORDS if w in t)
    neg_count = sum(1 for w in NEG_WORDS if w in t)

    if negated and pos_count > 0:
        pos_count = 0
        neg_count += 1

    if "slightly" in t or "a bit" in t or "little" in t:
        if neg_count > 0:
            return max(2, overall_star - 1)

    if neg_count > pos_count:
        return max(1, overall_star - 2)
    elif pos_count > neg_count:
        return min(5, overall_star + 1)
    elif "okay" in t or "decent" in t or "average" in t or "fine" in t:
        return 3
    else:
        return overall_star


def _expand_comma_list(review_text: str, star_rating: int) -> list[dict] | None:
    text = review_text.strip()
    if "," not in text:
        return None
    cleaned = re.sub(r"^(positive|good|great|excellent|amazing|nice)\s*[,:]?\s*",
                     "", text, flags=re.IGNORECASE).strip()
    parts = [p.strip() for p in re.split(r"[,;]", cleaned) if p.strip()]

    if len(parts) < 2:
        return None
    if not all(len(p.split()) <= 3 for p in parts):
        return None

    results = []
    seen    = set()
    for part in parts:
        cat = _match_topic(part)
        if cat not in seen:
            seen.add(cat)
            results.append({"category": cat, "category_star": star_rating})
    return results[:5] if results else None


def _match_topic(text: str) -> str:
    t = text.lower().strip()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return topic
    words = [w for w in re.findall(r"[a-z]{4,}", t)
             if w not in {"this", "that", "with", "have", "been", "from",
                          "they", "their", "about", "would", "could", "should"}]
    for word in words:
        for topic in CANONICAL_CATEGORIES:
            if word in topic.lower():
                return topic
    return "Overall Experience"


def _smart_nlp_fallback(review_text: str, star_rating: int) -> list[dict]:
    text = review_text.lower().strip()

    expanded = _expand_comma_list(review_text, star_rating)
    if expanded:
        return expanded

    raw_sentences = re.split(r"[.!?]", text)
    sentences     = []
    for s in raw_sentences:
        if re.search(r"\bbut\b|\bhowever\b|\balthough\b|\bthough\b", s):
            parts = re.split(r"\bbut\b|\bhowever\b|\balthough\b|\bthough\b", s)
            sentences.extend([p.strip() for p in parts if p.strip()])
        else:
            if s.strip():
                sentences.append(s.strip())

    results          = []
    seen_categories  = set()

    for sentence in sentences:
        if len(sentence.split()) < 2:
            continue
        matched_topic = None
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(kw in sentence for kw in keywords):
                matched_topic = topic
                break
        if not matched_topic or matched_topic in seen_categories:
            continue
        seen_categories.add(matched_topic)
        star = _nlp_sentiment_star(sentence, star_rating)
        results.append({"category": matched_topic, "category_star": star})

    if not results:
        results.append({"category": "Overall Experience", "category_star": star_rating})

    return results[:5]


def _sbert_fallback(review_text: str, star_rating: int) -> list[dict]:
    sbert = _get_sbert()
    if sbert is None:
        raise Exception("SBERT not available")

    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    import numpy as np

    raw       = re.split(r"[.!?]", review_text.lower())
    sentences = []
    for s in raw:
        if re.search(r"\bbut\b|\bhowever\b|\balthough\b", s):
            parts = re.split(r"\bbut\b|\bhowever\b|\balthough\b", s)
            sentences.extend([p.strip() for p in parts if p.strip()])
        elif s.strip():
            sentences.append(s.strip())

    sentences = [s for s in sentences if len(s.split()) >= 2]

    if not sentences:
        return _smart_nlp_fallback(review_text, star_rating)

    if len(sentences) == 1:
        cat  = _match_topic(sentences[0])
        star = _nlp_sentiment_star(sentences[0], star_rating)
        return [{"category": cat, "category_star": star}]

    embeddings                  = sbert.encode(sentences, convert_to_numpy=True)
    best_k, best_score, best_labels = 2, -1, None
    for k in range(2, min(4, len(sentences)) + 1):
        try:
            kmeans  = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels  = kmeans.fit_predict(embeddings)
            score   = silhouette_score(embeddings, labels)
            if score > best_score:
                best_score, best_labels = score, labels
        except Exception:
            pass

    if best_labels is None:
        return _smart_nlp_fallback(review_text, star_rating)

    clusters = {}
    for sent, label in zip(sentences, best_labels):
        clusters.setdefault(label, []).append(sent)

    results = []
    seen    = set()
    for cluster_sentences in clusters.values():
        combined = " ".join(cluster_sentences)
        cat      = _match_topic(combined)
        star     = _nlp_sentiment_star(combined, star_rating)
        if cat not in seen:
            seen.add(cat)
            results.append({"category": cat, "category_star": star})

    return results[:5] if results else _smart_nlp_fallback(review_text, star_rating)


def _bert_nlp_fallback(review_text: str, star_rating: int) -> list[dict]:
    model      = _get_bert_sentiment()
    nlp_result = _smart_nlp_fallback(review_text, star_rating)

    if model is None:
        return nlp_result

    try:
        text_short = review_text[:512]
        bert_out   = model(text_short)[0]
        label      = bert_out["label"]
        for item in nlp_result:
            if label == "POSITIVE":
                item["category_star"] = min(5, item["category_star"] + 1)
            else:
                item["category_star"] = max(1, item["category_star"] - 1)
    except Exception as e:
        print(f"  [BERT] Error: {e}")

    return nlp_result


# ─────────────────────────────────────────────
# MAIN FUNCTION — worker calls this
# ─────────────────────────────────────────────
def analyze_review(review_text: str, star_rating: int) -> list[dict]:
    """
    Returns list of dicts: [{category, category_star}]
    Never returns None. Always at least 1 category.
    Fallback chain: OpenAI → Gemini → SBERT → BERT+NLP → NLP
    """
    prompt = PROMPT_TEMPLATE.format(
        review_text=review_text,
        star_rating=star_rating
    )

    try:
        print("  Trying OpenAI...")
        raw    = _call_openai(prompt)
        result = _parse_json(raw, star_rating)
        print(f"  ✓ OpenAI → {[r['category'] for r in result]}")
        return result
    except Exception as e:
        print(f"  OpenAI failed: {e}")

    try:
        print("  Trying Gemini...")
        raw    = _call_gemini(prompt)
        result = _parse_json(raw, star_rating)
        print(f"  ✓ Gemini → {[r['category'] for r in result]}")
        return result
    except Exception as e:
        print(f"  Gemini failed: {e}")

    try:
        print("  Trying SBERT...")
        result = _sbert_fallback(review_text, star_rating)
        if result:
            print(f"  ✓ SBERT → {[r['category'] for r in result]}")
            return result
    except Exception as e:
        print(f"  SBERT failed: {e}")

    try:
        print("  Trying BERT+NLP...")
        result = _bert_nlp_fallback(review_text, star_rating)
        if result:
            print(f"  ✓ BERT+NLP → {[r['category'] for r in result]}")
            return result
    except Exception as e:
        print(f"  BERT+NLP failed: {e}")

    print("  Using NLP fallback...")
    result = _smart_nlp_fallback(review_text, star_rating)
    print(f"  ✓ NLP → {[r['category'] for r in result]}")
    return result