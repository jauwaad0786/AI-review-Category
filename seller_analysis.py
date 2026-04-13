import re
import json
import requests
import os
from collections import Counter
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
# LAZY SBERT LOAD
# ─────────────────────────────────────────────
_sbert_model = None

def _get_sbert():
    global _sbert_model
    if _sbert_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _sbert_model = SentenceTransformer('all-MiniLM-L6-v2')
            print("  [SBERT] Loaded ok")
        except Exception as e:
            print(f"  [SBERT] Load failed: {e}")
    return _sbert_model


# ─────────────────────────────────────────────
# PROMPT — universal domain
# ─────────────────────────────────────────────
def _build_prompt(reviews_text: str, count: int) -> str:
    return f"""You are a business intelligence AI for a multi-domain review platform.

Below are {count} customer reviews for ONE entity
(could be a company, product, organization, fintech, consulting, real estate, etc.).

YOUR TASK:
1. Read all reviews carefully
2. Write a 2-3 line human-like summary of what customers overall feel.
   - Mention positives AND negatives if both present
   - Do NOT use labels like "positive" or "negative"
   - Adapt to the domain: workplace culture/growth, product quality/delivery,
     fintech UX/security, real estate agent/pricing — whatever fits the reviews
3. Identify dynamic categories from the reviews
   - Min 1, Max 10 categories
   - Short reviews like "great" or "good" use "Overall Experience"
   - Each category gets avg_star (1.0-5.0) based on per-topic sentiment

Reviews:
{reviews_text}

Return ONLY this JSON, nothing else:
{{
  "intent_summary": "2-3 line human summary here",
  "categories": [
    {{"name": "Work Culture", "avg_star": 4.5, "review_count": 3}},
    {{"name": "Professionalism", "avg_star": 4.8, "review_count": 2}}
  ]
}}"""


# ─────────────────────────────────────────────
# API CALLS
# ─────────────────────────────────────────────
def _call_openai(prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise Exception("No OpenAI key")
    res = requests.post(
        OPENAI_URL,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={"model": "gpt-3.5-turbo",
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.3},
        timeout=20
    )
    if res.status_code != 200:
        raise Exception(f"OpenAI HTTP {res.status_code}: {res.text[:150]}")
    return res.json()["choices"][0]["message"]["content"]


def _call_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise Exception("No Gemini key")
    res = requests.post(
        GEMINI_URL,
        headers={"Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=20
    )
    if res.status_code != 200:
        raise Exception(f"Gemini HTTP {res.status_code}: {res.text[:150]}")
    return res.json()["candidates"][0]["content"]["parts"][0]["text"]


# ─────────────────────────────────────────────
# PARSE AI RESPONSE
# ─────────────────────────────────────────────
def _parse_response(raw: str, star_rating_avg: float) -> dict:
    raw = re.sub(r"```json|```", "", raw).strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise Exception("No JSON found")
    parsed = json.loads(match.group(0))

    summary  = str(parsed.get("intent_summary", "")).strip()
    cats_raw = parsed.get("categories", [])

    categories = []
    for c in cats_raw[:10]:
        name  = str(c.get("name", "")).strip()
        star  = float(c.get("avg_star", star_rating_avg))
        count = int(c.get("review_count", 1))
        if name:
            categories.append({
                "name":         name,
                "avg_star":     round(max(1.0, min(5.0, star)), 1),
                "review_count": count
            })

    if not summary:
        raise Exception("Empty summary")
    if not categories:
        raise Exception("No categories")

    return {"intent_summary": summary, "categories": categories}


# ─────────────────────────────────────────────
# UNIVERSAL TOPIC MAP
# ─────────────────────────────────────────────
TOPIC_MAP = {
    # Workplace
    "Work Culture":         ["culture", "work culture", "colleagues", "coworkers",
                             "team spirit", "workplace", "environment", "atmosphere",
                             "inclusive", "diversity", "collaborative", "toxic",
                             "great place to work", "work environment"],
    "Management":           ["management", "manager", "leadership", "ceo", "boss",
                             "director", "hierarchy", "micromanage", "vision",
                             "guidance", "mentor", "leadership team"],
    "Work-Life Balance":    ["work life", "work-life", "balance", "overtime",
                             "flexible", "remote", "hybrid", "wfh", "burnout",
                             "late nights", "weekends", "stress", "long hours"],
    "Learning & Growth":    ["learning", "growth", "career", "promotion", "training",
                             "skill development", "mentorship", "opportunity",
                             "upskill", "exposure", "challenging"],
    "Office & Facilities":  ["office", "floor", "view", "building", "facility",
                             "cafeteria", "gym", "parking", "workspace", "desk",
                             "amenity", "infrastructure", "work place", "workstation"],
    "Compensation":         ["salary", "pay", "hike", "increment", "bonus",
                             "compensation", "package", "ctc", "stipend",
                             "benefits", "underpaid", "overpaid"],
    "Professionalism":      ["professional", "professionalism", "expert", "skilled",
                             "knowledgeable", "competent", "expertise",
                             "industry standard", "dedicated", "proficient"],

    # Product
    "Product Quality":      ["quality", "build quality", "material", "durable",
                             "sturdy", "defective", "broke", "poor quality",
                             "excellent quality", "well built"],
    "Delivery & Shipping":  ["delivery", "shipping", "dispatch", "arrived",
                             "late delivery", "fast delivery", "courier",
                             "packaging", "damaged"],
    "Customer Support":     ["support", "customer service", "helpline", "chat",
                             "resolved", "responsiveness", "helpful staff",
                             "not responsive", "response time", "after sales"],
    "Value for Money":      ["value", "worth", "money", "overpriced",
                             "affordable", "value for money", "cost effective"],
    "Return & Refund":      ["return", "refund", "exchange", "replace",
                             "money back", "cancelled", "cancellation"],

    # Fintech
    "Transaction Speed":    ["transaction", "transfer", "payment", "instant",
                             "slow transfer", "upi", "neft", "imps", "processing"],
    "App Experience":       ["app", "website", "platform", "portal", "ui", "ux",
                             "interface", "navigation", "filter", "search",
                             "bug", "crash", "glitch", "easy to use", "smooth app"],
    "Security & Trust":     ["secure", "security", "fraud", "scam", "trust",
                             "kyc", "verification", "otp", "protected", "safe"],
    "Loan & Credit":        ["loan", "credit", "emi", "mortgage", "interest",
                             "bank", "finance", "approve", "sanction"],

    # Real Estate
    "Agent Communication":  ["agent", "broker", "dealer", "follow up",
                             "communication", "replied", "representative"],
    "Deal Speed":           ["delay", "delayed", "slow process", "fast deal",
                             "process time", "waited", "lengthy process"],
    "Pricing":              ["price", "pricing", "cost", "expensive", "high price",
                             "commission", "fee", "charge", "affordable"],
    "Documentation":        ["document", "documentation", "legal", "registry",
                             "lawyer", "paperwork", "stamp duty"],
    "Property Quality":     ["property", "flat", "apartment", "house", "plot",
                             "construction", "possession", "floor plan"],

    # Consulting
    "Consulting Quality":   ["consulting", "consultant", "advisory", "advice",
                             "recommendation", "solution", "it consulting",
                             "business consulting", "insight", "it company"],
    "Project Delivery":     ["project", "deadline", "deliverable", "on time",
                             "milestone", "sprint", "delayed project", "completed"],

    # Generic
    "Overall Experience":   ["good", "great", "amazing", "awesome", "wow",
                             "nice", "excellent", "satisfied", "happy",
                             "recommend", "wonderful", "fantastic", "best",
                             "love", "overall", "impressive", "outstanding",
                             "superb", "positive", "brilliant"],
}

POSITIVE_WORDS = {
    "good", "great", "amazing", "awesome", "excellent", "helpful",
    "smooth", "fast", "quick", "professional", "nice", "perfect",
    "outstanding", "superb", "reasonable", "affordable", "fair",
    "transparent", "friendly", "knowledgeable", "supportive",
    "impressive", "dedicated", "collaborative", "fantastic",
    "wonderful", "positive", "brilliant", "satisfied", "happy"
}

NEGATIVE_WORDS = {
    "slow", "delay", "delayed", "late", "expensive", "high",
    "problem", "issue", "bad", "poor", "terrible", "worst",
    "incomplete", "wrong", "error", "confusing", "difficult",
    "toxic", "burnout", "bias", "underpaid", "overworked",
    "rude", "unprofessional", "misleading", "disappointing",
    "not helpful", "not responsive"
}


# ─────────────────────────────────────────────
# WORD-BOUNDARY MATCH  ← KEY FIX
# \b handles start/end of string correctly
# Old space-padding trick failed at sentence boundaries
# ─────────────────────────────────────────────
def _topic_match(text: str, keywords: list) -> bool:
    for kw in keywords:
        if re.search(r'\b' + re.escape(kw) + r'\b', text, re.IGNORECASE):
            return True
    return False


def _sentiment_star(sentence: str, overall_star: int) -> int:
    t = sentence.lower()
    negated   = bool(re.search(r'\bnot\s+\w+', t))
    pos_count = sum(1 for w in POSITIVE_WORDS
                    if re.search(r'\b' + re.escape(w) + r'\b', t))
    neg_count = sum(1 for w in NEGATIVE_WORDS
                    if re.search(r'\b' + re.escape(w) + r'\b', t))

    if negated and pos_count > 0:
        pos_count = 0
        neg_count += 1

    if re.search(r'\b(slightly|a bit|little)\b', t) and neg_count > 0:
        return max(2, overall_star - 1)
    if neg_count > pos_count:
        return max(1, overall_star - 2)
    elif pos_count > neg_count:
        return min(5, overall_star + 1)
    elif re.search(r'\b(okay|decent|average|fine)\b', t):
        return 3
    return overall_star


# ─────────────────────────────────────────────
# CONTEXT DETECTOR
# ─────────────────────────────────────────────
CONTEXT_SIGNALS = {
    "workplace":   ["office", "work culture", "colleagues", "management",
                    "salary", "workplace", "work-life", "career", "promotion",
                    "coworkers", "boss", "employees", "hr", "wfh"],
    "product":     ["delivery", "packaging", "quality", "defective", "return",
                    "refund", "shipped", "ordered", "product", "item"],
    "fintech":     ["payment", "transaction", "upi", "bank", "loan", "emi",
                    "credit", "account", "kyc", "transfer", "interest", "app"],
    "real_estate": ["property", "flat", "agent", "registry", "possession",
                    "rent", "builder", "plot", "apartment", "broker"],
    "consulting":  ["consulting", "advisory", "project", "deliverable",
                    "strategy", "solution", "it consulting", "business consulting"],
}

ENTITY_LABEL = {
    "workplace":   "organization",
    "product":     "product/service",
    "fintech":     "platform",
    "real_estate": "seller",
    "consulting":  "firm",
    "general":     "entity",
}

def _detect_context(all_text: str) -> str:
    t = all_text.lower()
    scores = {
        domain: sum(
            1 for kw in signals
            if re.search(r'\b' + re.escape(kw) + r'\b', t)
        )
        for domain, signals in CONTEXT_SIGNALS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


# ─────────────────────────────────────────────
# SBERT CATEGORY CLUSTERING
# ─────────────────────────────────────────────
def _sbert_categories(all_sentences: list, star_map: dict,
                       overall_avg: float) -> list[dict]:
    sbert = _get_sbert()
    if sbert is None or len(all_sentences) < 2:
        return []

    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score

        embeddings = sbert.encode(all_sentences, convert_to_numpy=True)
        n      = len(all_sentences)
        best_score, best_labels = -1, None

        for k in range(2, min(8, n) + 1):
            try:
                km     = KMeans(n_clusters=k, random_state=42, n_init=10)
                labels = km.fit_predict(embeddings)
                score  = silhouette_score(embeddings, labels)
                if score > best_score:
                    best_score, best_labels = score, labels
            except:
                pass

        if best_labels is None:
            return []

        clusters: dict = {}
        for sent, label in zip(all_sentences, best_labels):
            clusters.setdefault(int(label), []).append(sent)

        results     = []
        seen_topics = set()

        for cluster_sents in clusters.values():
            combined = " ".join(cluster_sents)

            # Best matching topic for this cluster
            best_topic, best_count = "Overall Experience", 0
            for topic, keywords in TOPIC_MAP.items():
                if topic == "Overall Experience":
                    continue
                c = sum(1 for kw in keywords
                        if re.search(r'\b' + re.escape(kw) + r'\b',
                                     combined, re.IGNORECASE))
                if c > best_count:
                    best_count, best_topic = c, topic

            if best_topic in seen_topics:
                continue
            seen_topics.add(best_topic)

            base = sum(star_map.get(s, overall_avg) for s in cluster_sents) / len(cluster_sents)
            neg  = any(re.search(r'\b' + re.escape(w) + r'\b', combined.lower())
                       for w in NEGATIVE_WORDS)
            pos  = any(re.search(r'\b' + re.escape(w) + r'\b', combined.lower())
                       for w in POSITIVE_WORDS)

            star = (max(1.0, base - 1.5) if neg and not pos else
                    min(5.0, base + 0.2) if pos and not neg else base)

            results.append({
                "name":         best_topic,
                "avg_star":     round(max(1.0, min(5.0, star)), 1),
                "review_count": len(cluster_sents)
            })

        return sorted(results, key=lambda x: x["review_count"], reverse=True)[:10]

    except Exception as e:
        print(f"  [SBERT categories] Error: {e}")
        return []


# ─────────────────────────────────────────────
# SBERT INTENT SUMMARY
# ─────────────────────────────────────────────
def _sbert_summary(reviews: list, context: str, avg_rating: float) -> str | None:
    sbert = _get_sbert()
    if sbert is None or len(reviews) < 2:
        return None

    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score

        texts      = [r["review_text"] for r in reviews]
        embeddings = sbert.encode(texts, convert_to_numpy=True)
        n          = len(texts)

        best_score, best_labels = -1, None
        for k in range(2, min(4, n) + 1):
            try:
                km     = KMeans(n_clusters=k, random_state=42, n_init=10)
                labels = km.fit_predict(embeddings)
                score  = silhouette_score(embeddings, labels)
                if score > best_score:
                    best_score, best_labels = score, labels
            except:
                pass

        if best_labels is None:
            return None

        clusters: dict = {}
        for rev, label in zip(reviews, best_labels):
            clusters.setdefault(int(label), []).append(rev)

        entity         = ENTITY_LABEL.get(context, "entity")
        pos_themes     = []
        neg_themes     = []

        for cluster_revs in clusters.values():
            combined  = " ".join(r["review_text"] for r in cluster_revs).lower()
            avg_star  = sum(r["star_rating"] for r in cluster_revs) / len(cluster_revs)

            best_topic, best_c = "Overall Experience", 0
            for topic, keywords in TOPIC_MAP.items():
                if topic == "Overall Experience":
                    continue
                c = sum(1 for kw in keywords
                        if re.search(r'\b' + re.escape(kw) + r'\b',
                                     combined, re.IGNORECASE))
                if c > best_c:
                    best_c, best_topic = c, topic

            pos_kws = [w for w in POSITIVE_WORDS
                       if re.search(r'\b' + re.escape(w) + r'\b', combined)][:2]
            neg_kws = [w for w in NEGATIVE_WORDS
                       if re.search(r'\b' + re.escape(w) + r'\b', combined)][:2]

            info = {"topic": best_topic, "pos_kws": pos_kws,
                    "neg_kws": neg_kws, "avg_star": avg_star,
                    "count": len(cluster_revs)}

            if avg_star >= 3.5:
                pos_themes.append(info)
            else:
                neg_themes.append(info)

        parts = []
        total = len(reviews)

        if pos_themes:
            topics = ", ".join(dict.fromkeys(
                t["topic"] for t in pos_themes
                if t["topic"] != "Overall Experience"
            ))
            kws = list(dict.fromkeys(
                kw for t in pos_themes for kw in t["pos_kws"]
            ))[:3]
            kw_str = ", ".join(kws) if kws else "overall quality"
            if topics:
                parts.append(
                    f"Customers consistently highlight {topics} as key strengths, "
                    f"with frequent mentions of {kw_str}."
                )
            else:
                parts.append(
                    f"The majority of reviewers share a positive experience, "
                    f"frequently describing the {entity} as {kw_str}."
                )

        if neg_themes:
            topics = ", ".join(dict.fromkeys(
                t["topic"] for t in neg_themes
                if t["topic"] != "Overall Experience"
            ))
            kws = list(dict.fromkeys(
                kw for t in neg_themes for kw in t["neg_kws"]
            ))[:2]
            note = f" — particularly around {', '.join(kws)}" if kws else ""
            if topics:
                parts.append(
                    f"Some reviewers flag concerns with {topics}{note}."
                )

        if not parts:
            parts.append(
                f"This {entity} has received {total} reviews averaging "
                f"{round(avg_rating, 1)}/5, reflecting "
                f"{'strong' if avg_rating >= 4.0 else 'moderate'} overall satisfaction."
            )

        return " ".join(parts)

    except Exception as e:
        print(f"  [SBERT summary] Error: {e}")
        return None


# ─────────────────────────────────────────────
# KEYWORD CATEGORIES — regex word-boundary
# ─────────────────────────────────────────────
def _keyword_categories(reviews: list) -> list[dict]:
    topic_data: dict = {}

    for r in reviews:
        used_topics: set = set()
        text  = r["review_text"].lower()
        stars = r["star_rating"]

        # Split sentences + contrast handling
        raw_sents = re.split(r'[.!?]', text)
        sentences = []
        for s in raw_sents:
            if re.search(r'\b(but|however|although|though)\b', s):
                parts = re.split(r'\b(?:but|however|although|though)\b', s)
                sentences.extend(p.strip() for p in parts
                                 if p.strip() and len(p.strip()) > 2)
            elif s.strip():
                sentences.append(s.strip())

        # Also include comma-separated parts as extra sentences
        comma_parts = re.split(r'[,;]', text)
        if len(comma_parts) >= 2:
            sentences.extend(p.strip() for p in comma_parts if p.strip())

        sentences = list(dict.fromkeys(s for s in sentences if s))

        matched_any = False
        for topic, keywords in TOPIC_MAP.items():
            if topic in used_topics:
                continue
            for sent in sentences:
                if _topic_match(sent, keywords):
                    used_topics.add(topic)
                    topic_data.setdefault(topic, {"stars": [], "count": 0})

                    neg = any(re.search(r'\b' + re.escape(w) + r'\b', sent)
                              for w in NEGATIVE_WORDS)
                    pos = any(re.search(r'\b' + re.escape(w) + r'\b', sent)
                              for w in POSITIVE_WORDS)

                    star = (max(1, stars - 2) if neg and not pos else
                            min(5, stars)     if pos and not neg else
                            max(2, stars - 1) if neg and pos else stars)

                    topic_data[topic]["stars"].append(star)
                    topic_data[topic]["count"] += 1
                    matched_any = True
                    break

        if not matched_any:
            topic_data.setdefault("Overall Experience", {"stars": [], "count": 0})
            topic_data["Overall Experience"]["stars"].append(stars)
            topic_data["Overall Experience"]["count"] += 1

    categories = [
        {"name": cat,
         "avg_star": round(sum(d["stars"]) / len(d["stars"]), 1),
         "review_count": d["count"]}
        for cat, d in topic_data.items()
    ]
    return sorted(categories, key=lambda x: x["review_count"], reverse=True)[:10]


# ─────────────────────────────────────────────
# NLP FALLBACK — SBERT + keyword + smart summary
# ─────────────────────────────────────────────
def _nlp_fallback(reviews: list) -> dict:
    total      = len(reviews)
    avg_rating = sum(r["star_rating"] for r in reviews) / total if total else 3
    all_text   = " ".join(r["review_text"] for r in reviews)
    context    = _detect_context(all_text)
    entity     = ENTITY_LABEL.get(context, "entity")

    # ── Categories: SBERT first, keyword fallback ──
    all_sents: list = []
    star_map: dict  = {}
    for r in reviews:
        for s in re.split(r'[.!?]', r["review_text"].lower()):
            s = s.strip()
            if len(s.split()) >= 2:
                all_sents.append(s)
                star_map[s] = r["star_rating"]

    categories = _sbert_categories(all_sents, star_map, avg_rating)

    if not categories:
        print("  [NLP] SBERT categories empty → keyword NLP")
        categories = _keyword_categories(reviews)

    if not categories:
        categories = [{"name": "Overall Experience",
                       "avg_star": round(avg_rating, 1),
                       "review_count": total}]

    # ── Intent summary: SBERT → AI → smart keyword ──
    intent_summary = _sbert_summary(reviews, context, avg_rating)

    if not intent_summary:
        # Try AI with compressed sample
        pos_revs    = [r for r in reviews if r["star_rating"] >= 4]
        neg_revs    = [r for r in reviews if r["star_rating"] < 4]
        compressed  = (
            [f"[Positive] {r['review_text'][:80]}" for r in pos_revs[:4]] +
            [f"[Negative] {r['review_text'][:80]}" for r in neg_revs[:3]]
        )
        ai_prompt = f"""Business analyst for a multi-domain platform.

{total} reviews, avg {round(avg_rating, 1)}/5, domain: {context}.

Sample:
{chr(10).join(compressed)}

Write a 2-3 line summary. Mention actual themes from these reviews.
Do NOT use generic phrases about "service and pricing" unless those exact
topics appear. Adapt to the domain (workplace/product/fintech/consulting etc.).
Return ONLY the summary text."""

        try:
            intent_summary = _call_openai(ai_prompt).strip()
        except Exception:
            try:
                intent_summary = _call_gemini(ai_prompt).strip()
            except Exception:
                pass

    if not intent_summary:
        # Pure keyword summary — zero hardcoded domain text
        all_lower   = all_text.lower()
        pos_kws     = [w for w in POSITIVE_WORDS
                       if re.search(r'\b' + re.escape(w) + r'\b', all_lower)][:3]
        neg_kws     = [w for w in NEGATIVE_WORDS
                       if re.search(r'\b' + re.escape(w) + r'\b', all_lower)][:2]
        top_cat     = categories[0]["name"] if categories else "Overall Experience"
        pos_count   = sum(1 for r in reviews if r["star_rating"] >= 4)
        pos_pct     = round(pos_count / total * 100, 1)

        kw_str      = ", ".join(pos_kws) if pos_kws else "quality and service"
        concern_str = ", ".join(neg_kws) if neg_kws else None

        if pos_pct >= 80 and avg_rating >= 4.0:
            intent_summary = (
                f"Customers consistently rate this {entity} highly, "
                f"with strong appreciation for {top_cat.lower()} "
                f"and recurring mentions of {kw_str}. "
                f"The {round(avg_rating, 1)}/5 average across {total} reviews "
                f"reflects broadly positive sentiment."
            )
        elif concern_str:
            intent_summary = (
                f"Most customers appreciate this {entity} — especially {kw_str} "
                f"and {top_cat.lower()}. "
                f"A portion of reviews highlight concerns around {concern_str}, "
                f"with an overall average of {round(avg_rating, 1)}/5."
            )
        else:
            intent_summary = (
                f"This {entity} has received {total} reviews with an average "
                f"rating of {round(avg_rating, 1)}/5. "
                f"Customers frequently mention {kw_str} and {top_cat.lower()} "
                f"as notable aspects of their experience."
            )

    return {
        "intent_summary": intent_summary,
        "categories":     categories,
        "source":         "NLP fallback"
    }


# ─────────────────────────────────────────────
# MAIN FUNCTION — api.py se call hota hai
# ─────────────────────────────────────────────
def analyze_seller(seller_id: int, reviews: list) -> dict:
    """
    Input:
        seller_id : int
        reviews   : list of {review_text, star_rating, user_id, created_at}
    Output:
        {seller_id, total_reviews, intent_summary, categories, source}
    """
    total = len(reviews)

    if total == 0:
        return {
            "seller_id":      seller_id,
            "total_reviews":  0,
            "intent_summary": "No approved reviews found yet.",
            "categories":     [],
            "source":         "empty"
        }

    avg_star = sum(r["star_rating"] for r in reviews) / total

    sampled      = reviews[:30]
    reviews_text = "\n".join(
        f"[{i+1}] Stars:{r['star_rating']} — {r['review_text']}"
        for i, r in enumerate(sampled)
    )
    prompt = _build_prompt(reviews_text, len(sampled))

    # ── Try OpenAI ──
    try:
        print(f"  [SellerAnalysis] Trying OpenAI...")
        raw    = _call_openai(prompt)
        result = _parse_response(raw, avg_star)
        result.update({"seller_id": seller_id, "total_reviews": total,
                        "source": "OpenAI"})
        print(f"  [SellerAnalysis] OpenAI ok")
        return result
    except Exception as e:
        print(f"  [SellerAnalysis] OpenAI failed: {e}")

    # ── Try Gemini ──
    try:
        print(f"  [SellerAnalysis] Trying Gemini...")
        raw    = _call_gemini(prompt)
        result = _parse_response(raw, avg_star)
        result.update({"seller_id": seller_id, "total_reviews": total,
                        "source": "Gemini"})
        print(f"  [SellerAnalysis] Gemini ok")
        return result
    except Exception as e:
        print(f"  [SellerAnalysis] Gemini failed: {e}")

    # ── NLP + SBERT fallback ──
    print(f"  [SellerAnalysis] NLP+SBERT fallback")
    result = _nlp_fallback(reviews)
    result.update({"seller_id": seller_id, "total_reviews": total})
    return result