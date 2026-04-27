import re
import json
import time
import hashlib
import requests
import os
from collections import Counter
from dotenv import load_dotenv
from transformers import pipeline

# ─────────────────────────────────────────────
# LOCAL LLM — Singleton + Result Cache
# ─────────────────────────────────────────────
_llm = None
_llm_cache: dict = {}   # keyed by MD5(review data) — same tbl_seller_review → same result always


def _get_local_llm():
    global _llm
    if _llm is None:
        print("  [Local LLM] Loading model...")
        _llm = pipeline(
            "text-generation",
            model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            device=-1,
        )
        print("  [Local LLM] Loaded")
    return _llm

# ─────────────────────────────────────────────
# FLAN-T5 — Seq2Seq paraphraser (anti-hallucination)
# Input is always the pre-built skeleton, so no facts can be invented
# ─────────────────────────────────────────────
_flan_model = None


def _get_flan_t5():
    global _flan_model
    if _flan_model is None:
        print("  [Flan-T5] Loading model...")
        _flan_model = pipeline(
            "text2text-generation",
            model="google/flan-t5-base",
            device=-1,
        )
        print("  [Flan-T5] Loaded")
    return _flan_model


load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_gemini_session = requests.Session()
_gemini_session.headers.update({"Content-Type": "application/json"})


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

_groq_session = requests.Session()
_groq_session.headers.update({
    "Content-Type": "application/json",
    "Authorization": f"Bearer {GROQ_API_KEY}" if GROQ_API_KEY else "",
})

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
# PROMPT — for OpenAI / Gemini
# ─────────────────────────────────────────────
def _build_prompt(tbl_seller_review_text: str, count: int) -> str:
    return f"""You are a business intelligence AI for a multi-domain review platform.

Below are {count} customer tbl_seller_review for ONE entity
(could be a company, product, organization, fintech, consulting, real estate, etc.).

YOUR TASK:
1. Read all tbl_seller_review carefully
2. Write a 2-3 line human-like summary of what customers overall feel.
   - Mention positives AND negatives if both present
   - Do NOT use labels like "positive" or "negative"
   - Adapt to the domain: workplace culture/growth, product quality/delivery,
     fintech UX/security, real estate agent/pricing — whatever fits the tbl_seller_review
3. Identify dynamic categories from the tbl_seller_review
   - Min 1, Max 10 categories
   - Short tbl_seller_review like "great" or "good" use "Overall Experience"
   - Each category gets avg_star (1.0-5.0) based on per-topic sentiment

Reviews:
{tbl_seller_review_text}

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
def _call_groq(prompt: str) -> str:
    for attempt in range(3):
        res = _groq_session.post(
            GROQ_URL,
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            },
            timeout=20
        )

        if res.status_code == 429:
            time.sleep(2 ** attempt)
            continue

        if res.status_code != 200:
            raise Exception(f"Groq HTTP {res.status_code}: {res.text[:150]}")

        return res.json()["choices"][0]["message"]["content"]

    raise Exception("Groq: max retries exceeded")


def _call_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise Exception("No Gemini key")
    for attempt in range(3):
        res = _gemini_session.post(
            GEMINI_URL,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20
        )
        if res.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        if res.status_code != 200:
            raise Exception(f"Gemini HTTP {res.status_code}: {res.text[:150]}")
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise Exception("Gemini: max retries exceeded")


def _parse_response(raw: str, star_rating_avg: float) -> dict:
    raw   = re.sub(r"```json|```", "", raw).strip()
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
# TOPIC MAP
# ─────────────────────────────────────────────
TOPIC_MAP = {
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
    "Transaction Speed":    ["transaction", "transfer", "payment", "instant",
                             "slow transfer", "upi", "neft", "imps", "processing"],
    "App Experience":       ["app", "website", "platform", "portal", "ui", "ux",
                             "interface", "navigation", "filter", "search",
                             "bug", "crash", "glitch", "easy to use", "smooth app"],
    "Security & Trust":     ["secure", "security", "fraud", "scam", "trust",
                             "kyc", "verification", "otp", "protected", "safe"],
    "Loan & Credit":        ["loan", "credit", "emi", "mortgage", "interest",
                             "bank", "finance", "approve", "sanction"],
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
    "Consulting Quality":   ["consulting", "consultant", "advisory", "advice",
                             "recommendation", "solution", "it consulting",
                             "business consulting", "insight", "it company"],
    "Project Delivery":     ["project", "deadline", "deliverable", "on time",
                             "milestone", "sprint", "delayed project", "completed"],
    "Overall Experience":   ["good", "great", "amazing", "awesome", "wow",
                             "nice", "excellent", "satisfied", "happy",
                             "recommend", "wonderful", "fantastic", "best",
                             "love", "overall", "impressive", "outstanding",
                             "superb", "positive", "brilliant"],
}
FINTECH_TAG_MAP = {
    "Transaction Speed": ["fast payment", "instant transfer", "upi payment"],
    "App Experience": ["ease of use", "smooth app", "easy interface"],
    "Customer Support": ["customer support", "help support"],
    "Security & Trust": ["secure payment", "trust", "fraud safety"],
    "Pricing": ["charges", "fees", "cashback"],
    "Loan & Credit": ["loan", "credit", "emi"],
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
# HALLUCINATION GUARD
# ─────────────────────────────────────────────
_HALLUCINATION_SIGNALS = [
    "student", "essay", "example", "assistant", "here is", "i ",
    "the following", "professor", "university", "chapter", "exercise",
    "homework", "textbook", "answer:", "question:", "note:", "tip:", "instruction"
]

# ─────────────────────────────────────────────
# HUMAN PHRASE MAPS — raw keyword → natural phrase
# Prevents skeleton from saying "good, amazing, fast"
# ─────────────────────────────────────────────
_POS_PHRASE_MAP = {
    "good":          "solid quality",
    "great":         "great overall experience",
    "amazing":       "impressive performance",
    "awesome":       "exceptional experience",
    "fast":          "quick turnaround",
    "smooth":        "smooth process",
    "helpful":       "helpful support",
    "excellent":     "excellent service",
    "happy":         "high customer satisfaction",
    "satisfied":     "strong customer satisfaction",
    "professional":  "professional handling",
    "quick":         "quick service",
    "nice":          "pleasant experience",
    "outstanding":   "outstanding results",
    "superb":        "superb quality",
    "transparent":   "transparent communication",
    "friendly":      "friendly service",
    "knowledgeable": "knowledgeable staff",
    "dedicated":     "a dedicated team",
    "supportive":    "supportive service",
    "fair":          "fair pricing",
    "affordable":    "affordable pricing",
    "impressive":    "impressive quality",
    "brilliant":     "brilliant service",
    "wonderful":     "a wonderful experience",
    "fantastic":     "fantastic experience",
    "positive":      "positive interactions",
    "collaborative": "a collaborative environment",
    "perfect":       "a seamless experience",
    "reasonable":    "reasonable pricing",
}

_NEG_PHRASE_MAP = {
    "slow":           "slow response times",
    "delay":          "delivery delays",
    "delayed":        "delayed service",
    "late":           "late deliveries",
    "worst":          "a poor overall experience",
    "bad":            "below-average quality",
    "poor":           "poor service quality",
    "issue":          "recurring service issues",
    "problem":        "ongoing problems",
    "expensive":      "high pricing",
    "high":           "above-expected costs",
    "not responsive": "lack of responsiveness",
    "not helpful":    "unhelpful support",
    "disappointing":  "disappointing outcomes",
    "rude":           "unprofessional behaviour",
    "error":          "technical errors",
    "misleading":     "misleading information",
    "difficult":      "difficult processes",
    "confusing":      "a confusing experience",
    "incomplete":     "incomplete service",
    "unprofessional": "unprofessional conduct",
    "toxic":          "a toxic environment",
    "burnout":        "work-life balance concerns",
    "underpaid":      "compensation concerns",
    "overworked":     "excessive workload",
}

# Topic name → human-readable phrase for sentence embedding
_TOPIC_PHRASE = {
    "Product Quality":      "product quality",
    "Customer Support":     "customer support",
    "Delivery & Shipping":  "delivery and shipping",
    "Agent Communication":  "communication with the team",
    "Work Culture":         "workplace culture",
    "Management":           "management and leadership",
    "Work-Life Balance":    "work-life balance",
    "Learning & Growth":    "growth and learning opportunities",
    "Compensation":         "compensation and benefits",
    "Office & Facilities":  "office facilities",
    "Professionalism":      "professionalism",
    "Value for Money":      "value for money",
    "App Experience":       "app experience",
    "Transaction Speed":    "transaction speed",
    "Security & Trust":     "security and trust",
    "Deal Speed":           "deal processing speed",
    "Pricing":              "pricing",
    "Property Quality":     "property quality",
    "Consulting Quality":   "consulting quality",
    "Project Delivery":     "project delivery",
    "Overall Experience":   "overall experience",
}

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
    "product":     "product",
    "fintech":     "platform",
    "real_estate": "seller",
    "consulting":  "firm",
    "general":     "business",
}
def _generate_tags(tbl_seller_review: list, context: str) -> list:
    if context != "fintech":
        return []

    text = " ".join(r["comment"].lower() for r in tbl_seller_review)

    tag_counts = {}

    for topic, tags in FINTECH_TAG_MAP.items():
        for tag in tags:
            if tag in text:
                tag_counts[tag] = tag_counts.get(tag, 0) + text.count(tag)

    # fallback keywords
    keywords = [
        "bill payment", "recharge", "wallet",
        "fast payment", "cashback", "upi", "easy"
    ]

    for kw in keywords:
        if kw in text:
            tag_counts[kw] = tag_counts.get(kw, 0) + text.count(kw)

    # sort by frequency
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)

    return [t[0] for t in sorted_tags[:8]]


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
# STEP 1 — Deterministic fact extraction
# ─────────────────────────────────────────────

def _extract_review_facts(tbl_seller_review: list) -> dict:
    

    # ✅ ADD HERE (VERY TOP)
    if not tbl_seller_review:
        return {
            "avg_rating": 0,
            "total": 0,
            "pos_count": 0,
            "neg_count": 0,
            "pos_topics": [],
            "neg_topics": [],
            "pos_keywords": [],
            "neg_keywords": [],
            "has_both": False,
            "context": "general",
        }

    
    pos_tbl_seller_review = [r for r in tbl_seller_review if r.get("rating", 0) >= 4]
    neg_tbl_seller_review = [r for r in tbl_seller_review if r.get("rating", 0) < 4]
    avg_rating   = sum(r.get("rating", 0) for r in tbl_seller_review) / len(tbl_seller_review)
    all_text     = " ".join(r["comment"].lower() for r in tbl_seller_review)
    pos_text     = " ".join(r["comment"].lower() for r in pos_tbl_seller_review)
    neg_text     = " ".join(r["comment"].lower() for r in neg_tbl_seller_review)

    pos_topics, neg_topics = [], []
    pos_text_lower = pos_text.lower()
    neg_text_lower = neg_text.lower()

    for topic, keywords in TOPIC_MAP.items():
        if topic == "Overall Experience":
            continue

        if any(kw in pos_text_lower for kw in keywords):
            pos_topics.append(topic)

        if any(kw in neg_text_lower for kw in keywords):
            neg_topics.append(topic)

    found_pos_kws = sorted(
        {w for w in POSITIVE_WORDS if re.search(r'\b' + re.escape(w) + r'\b', all_text)},
        key=lambda w: all_text.count(w), reverse=True
    )[:3]

    found_neg_kws = sorted(
        {w for w in NEGATIVE_WORDS if re.search(r'\b' + re.escape(w) + r'\b', all_text)},
        key=lambda w: all_text.count(w), reverse=True
    )[:2]

    
    context = _detect_context(all_text)

# FILTER topics for fintech
    if context == "fintech":
        allowed = {
            "Transaction Speed",
            "App Experience",
            "Customer Support",
            "Security & Trust",
            "Pricing",
            "Loan & Credit",
            "Overall Experience"
        }

        pos_topics = [t for t in pos_topics if t in allowed]
        neg_topics = [t for t in neg_topics if t in allowed]

    return {
        "avg_rating": round(avg_rating, 1),
        "total": len(tbl_seller_review),
        "pos_count": len(pos_tbl_seller_review),
        "neg_count": len(neg_tbl_seller_review),
        "pos_topics": pos_topics[:3],
        "neg_topics": neg_topics[:2],
        "pos_keywords": found_pos_kws,
        "neg_keywords": found_neg_kws,
        "has_both": bool(pos_tbl_seller_review and neg_tbl_seller_review),
        "context": context,
    }


# ─────────────────────────────────────────────
# HELPER — raw keywords → natural phrase
# ─────────────────────────────────────────────
def _kws_to_phrase(kw_list: list, phrase_map: dict, fallback: str) -> str:
    if not kw_list:
        return fallback
    phrases = list(dict.fromkeys(
        phrase_map.get(kw, kw.replace("_", " ")) for kw in kw_list[:2]
    ))
    return phrases[0] if len(phrases) == 1 else f"{phrases[0]} and {phrases[1]}"


# ─────────────────────────────────────────────
# STEP 2 — Natural skeleton + minimal LLM prompt
# ─────────────────────────────────────────────
def _build_llm_prompt(facts: dict) -> tuple[str, str]:
    """
    Builds a fully human-readable skeleton sentence using phrase maps,
    then asks the LLM only to lightly rephrase it.
    The LLM cannot invent new content — all facts are pre-locked.
    """
    pos_topic_raw = facts["pos_topics"][0] if facts["pos_topics"] else "Overall Experience"
    neg_topic_raw = facts["neg_topics"][0]  if facts["neg_topics"]  else None

    pos_topic = _TOPIC_PHRASE.get(pos_topic_raw, pos_topic_raw.lower())
    neg_topic = _TOPIC_PHRASE.get(neg_topic_raw, neg_topic_raw.lower()) if neg_topic_raw else None

    pos_phrase = _kws_to_phrase(
        facts["pos_keywords"], _POS_PHRASE_MAP, f"solid {pos_topic}"
    )
    neg_phrase = _kws_to_phrase(
        facts["neg_keywords"], _NEG_PHRASE_MAP,
        f"issues with {neg_topic or 'responsiveness'}"
    )

    entity = ENTITY_LABEL.get(facts["context"], "business")
    avg    = facts["avg_rating"]
    total  = facts["total"]

    # Multiple varied templates — selected deterministically via hash
    if facts["has_both"]:
        templates = [
            (
                f"Most customers are genuinely impressed with the {pos_topic} here, "
                f"frequently praising {pos_phrase}. "
                f"However, a portion of reviewers also flag {neg_phrase} as an area that needs improvement."
            ),
            (
                f"The {pos_topic} clearly stands out as a strength for this {entity}, "
                f"with {pos_phrase} being a common highlight. "
                f"At the same time, {neg_phrase} remains a recurring concern among some buyers."
            ),
            (
                f"Reviewers widely appreciate {pos_phrase} and consider {pos_topic} a major plus. "
                f"That said, {neg_phrase} is something the {entity} would benefit from addressing."
            ),
        ]
    elif avg >= 4.0:
        templates = [
            (
                f"Customers have responded overwhelmingly well to this {entity}, "
                f"with {pos_phrase} and strong {pos_topic} earning consistent praise "
                f"across {total} tbl_seller_review."
            ),
            (
                f"The overall sentiment is very positive — reviewers repeatedly highlight "
                f"{pos_phrase}, and {pos_topic} emerges as the top-rated aspect of this {entity}."
            ),
            (
                f"This {entity} has clearly made a strong impression, "
                f"with customers most often crediting {pos_phrase} "
                f"and the quality of {pos_topic} for their satisfaction."
            ),
        ]
    else:
        templates = [
            (
                f"Sentiment towards this {entity} is mixed, averaging {avg}/5 across {total} tbl_seller_review. "
                f"Customers acknowledge {pos_phrase}, but {neg_phrase} "
                f"continues to surface as a concern worth addressing."
            ),
            (
                f"Reviews are divided — while {pos_phrase} earns genuine appreciation, "
                f"{neg_phrase} is a recurring theme that pulls the overall rating down to {avg}/5."
            ),
        ]

    # Deterministic template selection — same data always picks same template
    skeleton = templates[hash(str(sorted(facts.items()))) % len(templates)]

    prompt = (
        f"Rewrite this customer review summary to sound more natural and conversational. "
        f"Do NOT change any facts, topics, or meaning — only improve the wording.\n\n"
        f'Summary: "{skeleton}"\n\n'
        f"Rewritten (2 sentences max, no bullet points):"
    )

    return prompt, skeleton


# ─────────────────────────────────────────────
# LOCAL LLM SUMMARY — anti-hallucination + cached
# ─────────────────────────────────────────────
def _local_llm_summary(tbl_seller_review: list) -> str | None:
    if not tbl_seller_review:
        return None

    # Cache check — same tbl_seller_review → instant return
    cache_payload = json.dumps(
        [{"r": r.get("rating", 0), "c": r["comment"][:60]} for r in tbl_seller_review[:15]],
        sort_keys=True
    ).encode()
    cache_key = hashlib.md5(cache_payload).hexdigest() + str(time.time())

    #if cache_key in _llm_cache:
     #   print("  [Local LLM] Cache hit")
      #  return _llm_cache[cache_key]

    try:
        facts             = _extract_review_facts(tbl_seller_review)
        prompt, skeleton  = _build_llm_prompt(facts)

        try:
            import torch
            torch.manual_seed(42)
        except ImportError:
            pass

        llm    = _get_local_llm()
        output = llm(
            prompt,
            max_new_tokens=50,
            do_sample=False,
            repetition_penalty=1.3,
            pad_token_id=2,
        )

        raw    = output[0]["generated_text"]
        result = raw[len(prompt):].strip()
        result = result.split("\n")[0].strip()
        result = re.split(r'(?<=[.!?])\s', result)[0].strip()

        # Hallucination guard — reject if LLM invented content
        result_lower = result.lower()
        all_valid_kws = (
            facts["pos_keywords"] + facts["neg_keywords"] +
            [t.lower() for t in facts["pos_topics"]] +
            [t.lower() for t in facts["neg_topics"]]
        )
        is_hallucinated = (
            len(result.split()) < 6
            or any(sig in result_lower for sig in _HALLUCINATION_SIGNALS)
            or (all_valid_kws and not any(kw in result_lower for kw in all_valid_kws))
        )

        if is_hallucinated:
            print("  [Local LLM] Hallucination detected → trying Flan-T5")
            flan_result = _flan_t5_summary(skeleton)
            if flan_result:
                result = flan_result
                source = "Flan-T5"
            else:
                print("  [Local LLM] Flan-T5 unavailable → using skeleton")
                result = skeleton
                source = "skeleton"
        else:
            if not result.endswith((".", "!", "?")):
                result += "."
            result = result[0].upper() + result[1:]
            source = "LLM"

        print(f"  [Local LLM] OK — source: {source}")
        return result

    except Exception as e:
        print(f"  [Local LLM] Error: {e}")
        try:
            facts    = _extract_review_facts(tbl_seller_review)
            _, skeleton = _build_llm_prompt(facts)
            _llm_cache[cache_key] = skeleton
            return skeleton
        except Exception:
            return None

def _flan_t5_summary(skeleton: str) -> str | None:
    """
    Takes the pre-built skeleton (facts already locked in) and
    asks Flan-T5 to paraphrase it naturally.
    Seq2Seq architecture means it cannot invent content beyond the input.
    """
    try:
        flan   = _get_flan_t5()
        prompt = f"paraphrase: {skeleton}"
        output = flan(
            prompt,
            max_new_tokens=80,
            num_beams=4,
            early_stopping=True,
        )
        result = output[0]["generated_text"].strip()
        if len(result.split()) < 8:
            return None
        if not result.endswith((".", "!", "?")):
            result += "."
        return result[0].upper() + result[1:]
    except Exception as e:
        print(f"  [Flan-T5] Error: {e}")
        return None






# ─────────────────────────────────────────────
# TOPIC MATCHING
# ─────────────────────────────────────────────
def _topic_match(text: str, keywords: list) -> bool:
    for kw in keywords:
        if re.search(r'\b' + re.escape(kw) + r'\b', text, re.IGNORECASE):
            return True
    return False


def _sentiment_star(sentence: str, overall_star: int) -> int:
    t         = sentence.lower()
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
# SBERT CATEGORIES
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

        embeddings              = sbert.encode(all_sentences, convert_to_numpy=True)
        n                       = len(all_sentences)
        best_score, best_labels = -1, None

        for k in range(2, min(8, n) + 1):
            try:
                km     = KMeans(n_clusters=k, random_state=42, n_init=10)
                labels = km.fit_predict(embeddings)
                score  = silhouette_score(embeddings, labels)
                if score > best_score:
                    best_score, best_labels = score, labels
            except Exception:
                pass

        if best_labels is None:
            return []

        clusters: dict = {}
        for sent, label in zip(all_sentences, best_labels):
            clusters.setdefault(int(label), []).append(sent)

        results, seen_topics = [], set()

        for cluster_sents in clusters.values():
            combined            = " ".join(cluster_sents)
            best_topic, best_c  = "Overall Experience", 0
            for topic, keywords in TOPIC_MAP.items():
                if topic == "Overall Experience":
                    continue
                c = sum(1 for kw in keywords
                        if re.search(r'\b' + re.escape(kw) + r'\b', combined, re.IGNORECASE))
                if c > best_c:
                    best_c, best_topic = c, topic

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
# SBERT SUMMARY
# ─────────────────────────────────────────────
def _sbert_summary(tbl_seller_review: list, context: str, avg_rating: float) -> str | None:
    sbert = _get_sbert()
    if sbert is None or len(tbl_seller_review) < 2:
        return None

    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score

        texts      = [r["comment"] for r in tbl_seller_review]
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
            except Exception:
                pass

        if best_labels is None:
            return None

        clusters: dict = {}
        for rev, label in zip(tbl_seller_review, best_labels):
            clusters.setdefault(int(label), []).append(rev)

        entity, pos_themes, neg_themes = ENTITY_LABEL.get(context, "business"), [], []

        for cluster_revs in clusters.values():
            combined  = " ".join(r["comment"] for r in cluster_revs).lower()
            avg_star  = sum(r.get("rating", 0) for r in cluster_revs) / len(cluster_revs)

            best_topic, best_c = "Overall Experience", 0
            for topic, keywords in TOPIC_MAP.items():
                if topic == "Overall Experience":
                    continue
                c = sum(1 for kw in keywords
                        if re.search(r'\b' + re.escape(kw) + r'\b', combined, re.IGNORECASE))
                if c > best_c:
                    best_c, best_topic = c, topic

            pos_kws = [w for w in POSITIVE_WORDS
                       if re.search(r'\b' + re.escape(w) + r'\b', combined)][:2]
            neg_kws = [w for w in NEGATIVE_WORDS
                       if re.search(r'\b' + re.escape(w) + r'\b', combined)][:2]

            info = {"topic": best_topic, "pos_kws": pos_kws,
                    "neg_kws": neg_kws, "avg_star": avg_star,
                    "count": len(cluster_revs)}

            (pos_themes if avg_star >= 3.5 else neg_themes).append(info)

        parts = []
        total = len(tbl_seller_review)

        if pos_themes:
            topics = ", ".join(dict.fromkeys(
                _TOPIC_PHRASE.get(t["topic"], t["topic"].lower())
                for t in pos_themes if t["topic"] != "Overall Experience"
            ))
            kws    = list(dict.fromkeys(
                _POS_PHRASE_MAP.get(kw, kw) for t in pos_themes for kw in t["pos_kws"]
            ))[:2]
            kw_str = " and ".join(kws) if kws else "quality and service"
            if topics:
                parts.append(
                    f"Customers consistently highlight {topics} as key strengths, "
                    f"with frequent appreciation for {kw_str}."
                )
            else:
                parts.append(
                    f"The majority of reviewers share a positive experience, "
                    f"frequently praising {kw_str}."
                )

        if neg_themes:
            topics = ", ".join(dict.fromkeys(
                _TOPIC_PHRASE.get(t["topic"], t["topic"].lower())
                for t in neg_themes if t["topic"] != "Overall Experience"
            ))
            kws    = list(dict.fromkeys(
                _NEG_PHRASE_MAP.get(kw, kw) for t in neg_themes for kw in t["neg_kws"]
            ))[:2]
            note   = f" — particularly around {' and '.join(kws)}" if kws else ""
            if topics:
                parts.append(f"Some reviewers raise concerns about {topics}{note}.")

        if not parts:
            mood = "strong" if avg_rating >= 4.0 else "moderate"
            parts.append(
                f"This {entity} has received {total} tbl_seller_review averaging "
                f"{round(avg_rating, 1)}/5, reflecting {mood} overall satisfaction."
            )

        return " ".join(parts)

    except Exception as e:
        print(f"  [SBERT summary] Error: {e}")
        return None


# ─────────────────────────────────────────────
# KEYWORD CATEGORIES
# ─────────────────────────────────────────────
def _keyword_categories(tbl_seller_review: list) -> list[dict]:
    topic_data: dict = {}

    for r in tbl_seller_review:
        text  = r["comment"].lower()
        stars = r.get("rating", 0)

        raw_sents = re.split(r'[.!?]', text)
        sentences = []
        for s in raw_sents:
            if re.search(r'\b(but|however|although|though)\b', s):
                parts = re.split(r'\b(?:but|however|although|though)\b', s)
                sentences.extend(p.strip() for p in parts if p.strip() and len(p.strip()) > 2)
            elif s.strip():
                sentences.append(s.strip())

        comma_parts = re.split(r'[,;]', text)
        if len(comma_parts) >= 2:
            sentences.extend(p.strip() for p in comma_parts if p.strip())

        sentences = list(dict.fromkeys(s for s in sentences if s))
        matched_any = False

        # ✅ NEW: collect unique topics first
        matched_topics = set()

        for topic, keywords in TOPIC_MAP.items():
            for sent in sentences:
                if _topic_match(sent, keywords):
                    matched_topics.add(topic)
                    break  # topic mil gaya → next topic

        # ✅ NEW: process each topic only once
        for topic in matched_topics:
            topic_data.setdefault(topic, {"stars": [], "count": 0})

            neg  = any(re.search(r'\b' + re.escape(w) + r'\b', text)
                       for w in NEGATIVE_WORDS)
            pos  = any(re.search(r'\b' + re.escape(w) + r'\b', text)
                       for w in POSITIVE_WORDS)

            star = (max(1, stars - 2) if neg and not pos else
                    min(5, stars)     if pos and not neg else
                    max(2, stars - 1) if neg and pos else stars)

            topic_data[topic]["stars"].append(star)
            topic_data[topic]["count"] += 1

            matched_any = True

        if not matched_any:
            topic_data.setdefault("Overall Experience", {"stars": [], "count": 0})
            topic_data["Overall Experience"]["stars"].append(stars)
            topic_data["Overall Experience"]["count"] += 1

    categories = [
        {"name": cat,
         "avg_star":     round(sum(d["stars"]) / len(d["stars"]), 1),
         "review_count": d["count"]}
        for cat, d in topic_data.items()
    ]

    return sorted(categories, key=lambda x: x["review_count"], reverse=True)[:10]
# ─────────────────────────────────────────────
# NLP FALLBACK
# ─────────────────────────────────────────────
def _nlp_fallback(tbl_seller_review: list) -> dict:
    total      = len(tbl_seller_review)
    avg_rating = sum(r.get("rating", 0) for r in tbl_seller_review) / total if total else 3
    all_text   = " ".join(r["comment"] for r in tbl_seller_review)
    context    = _detect_context(all_text)
    entity     = ENTITY_LABEL.get(context, "business")

    all_sents: list = []
    star_map: dict  = {}
    for r in tbl_seller_review:
        for s in re.split(r'[.!?]', r["comment"].lower()):
            s = s.strip()
            if len(s.split()) >= 2:
                all_sents.append(s)
                star_map[s] = r.get("rating", 0)

    categories = _sbert_categories(all_sents, star_map, avg_rating)
    if not categories:
        print("  [NLP] SBERT categories empty → keyword NLP")
        categories = _keyword_categories(tbl_seller_review)
    if not categories:
        categories = [{"name": "Overall Experience",
                       "avg_star": round(avg_rating, 1),
                       "review_count": total}]

    intent_summary = _sbert_summary(tbl_seller_review, context, avg_rating)

    if not intent_summary:
        # Try OpenAI/Gemini with a compressed prompt
        pos_revs   = [r for r in tbl_seller_review if r.get("rating", 0) >= 4]
        neg_revs   = [r for r in tbl_seller_review if r.get("rating", 0) < 4]
        compressed = (
            [f"[Positive] {r['comment'][:80]}" for r in pos_revs[:4]] +
            [f"[Negative] {r['comment'][:80]}" for r in neg_revs[:3]]
        )
        ai_prompt = (
            f"Business analyst for a multi-domain platform. "
            f"{total} tbl_seller_review, avg {round(avg_rating, 1)}/5, domain: {context}.\n\n"
            f"Sample:\n{chr(10).join(compressed)}\n\n"
            f"Write a 2-3 sentence summary in natural, human language. "
            f"Mention actual themes from these tbl_seller_review. Return ONLY the summary text."
        )
        try:
            intent_summary = _call_groq(ai_prompt).strip()
        except Exception:
            try:
                intent_summary = _call_gemini(ai_prompt).strip()
            except Exception:
                pass

    if not intent_summary:
        # Pure keyword fallback — use phrase maps so it still sounds natural
        facts    = _extract_review_facts(tbl_seller_review)
        _, skeleton = _build_llm_prompt(facts)
        intent_summary = skeleton

    return {
        "intent_summary": intent_summary,
        "categories":     categories,
        "source":         "NLP fallback"
    }
def _finalize_result(result: dict, tbl_seller_review: list) -> dict:
    try:
        facts = _extract_review_facts(tbl_seller_review)
        tags  = _generate_tags(tbl_seller_review, facts["context"])
        result["tags"] = tags
    except Exception as e:
        print("  [Tags] Error:", e)
        result["tags"] = []

    return result
# 🔥 SANITIZE REVIEWS (ADD THIS AT TOP)
# 🔥 SAFE SANITIZE (NO CRASH GUARANTEE)

# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────
def analyze_seller(seller_profile_id: int, tbl_seller_review: list) -> dict:

    # 🔥 STEP 1 — SANITIZE REVIEWS (MOST IMPORTANT)
    # Python 3.14 fix: MySQLRow passes isinstance(r, dict) but breaks .get()
    # Force convert to real Python dict FIRST, then sanitize
    clean_tbl_seller_review = []

    for r in tbl_seller_review:
        try:
            # Force real dict — fixes Python 3.14 MySQLRow bug
            if not isinstance(r, dict):
                try:
                    r = dict(r)
                except Exception:
                    continue

            # Extract by key directly from forced-real dict
            try:
                rating  = r["rating"]
                comment = r["comment"]
            except KeyError:
                # Last resort: rebuild from items()
                r = {str(k): v for k, v in r.items()}
                rating  = r.get("rating",  None)
                comment = r.get("comment", "")

            if rating is None:
                continue

            rating = int(float(rating))
            if rating <= 0:
                continue

            comment = str(comment).strip()
            if not comment:
                continue

            clean_tbl_seller_review.append({
                "rating":  rating,
                "comment": comment
            })

        except Exception as e:
            print("❌ Skipping bad review:", e)
            continue

    tbl_seller_review = clean_tbl_seller_review
    total   = len(tbl_seller_review)

    # 🔥 STEP 2 — EMPTY CHECK
    if total == 0:
        return {
            "seller_profile_id": seller_profile_id,
            "total_tbl_seller_review":     0,
            "intent_summary":    "No valid tbl_seller_review found.",
            "categories":        [],
            "source":            "empty"
        }

    # 🔥 STEP 3 — SAFE AVG
    avg_star = sum(r["rating"] for r in tbl_seller_review) / total

    sampled = tbl_seller_review[:30]

    # 🔥 SAFE TEXT BUILD
    tbl_seller_review_text = "\n".join(
        f"[{i+1}] Stars:{r['rating']} — {r['comment']}"
        for i, r in enumerate(sampled)
    )

    prompt = _build_prompt(tbl_seller_review_text, len(sampled))

    # 1. Local LLM (FIRST PRIORITY)
    try:
        print("[SellerAnalysis] Trying Local LLM...")
        #summary = _local_llm_summary(tbl_seller_review)
        summary = None  # 🔥 disable Local LLM for testing
        if summary:
            print("[SellerAnalysis] Local LLM ok")
            result = {
                "seller_profile_id": seller_profile_id,
                "total_tbl_seller_review": total,
                "intent_summary": summary,
                "categories": _keyword_categories(tbl_seller_review),
                "source": "Local LLM"
            }
            return _finalize_result(result, tbl_seller_review)

    except Exception as e:
        print("[SellerAnalysis] Local LLM failed:", e)


    # 2. Groq
    try:
        print("[SellerAnalysis] Trying Groq...")
        raw = _call_groq(prompt)
        result = _parse_response(raw, avg_star)
        result.update({
            "seller_profile_id": seller_profile_id,
            "total_tbl_seller_review": total,
            "source": "Groq"
        })
        print("[SellerAnalysis] Groq ok")
        return _finalize_result(result, tbl_seller_review)

    except Exception as e:
        print("[SellerAnalysis] Groq failed:", e)


    # 3. Gemini
    try:
        print("[SellerAnalysis] Trying Gemini...")
        raw = _call_gemini(prompt)
        result = _parse_response(raw, avg_star)
        result.update({
            "seller_profile_id": seller_profile_id,
            "total_tbl_seller_review": total,
            "source": "Gemini"
        })
        print("[SellerAnalysis] Gemini ok")
        return _finalize_result(result, tbl_seller_review)

    except Exception as e:
        print("[SellerAnalysis] Gemini failed:", e)


    # 4. NLP fallback
    print("[SellerAnalysis] NLP+SBERT fallback")
    result = _nlp_fallback(tbl_seller_review)
    result.update({
        "seller_profile_id": seller_profile_id,
        "total_tbl_seller_review": total
    })
    return _finalize_result(result, tbl_seller_review)