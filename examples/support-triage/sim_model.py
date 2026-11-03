"""A deterministic, rule-based *simulated* LLM for the support-triage demo.

THIS IS NOT A REAL MODEL. It exists so the demo (and EvalGate's own CI) can run
offline with no API keys. It reads the rendered prompt the same way a model would
"see" it, and behaves like a plausible-but-imperfect keyword classifier:

* With the v1 prompt it follows the priority rules, applies the "money wins"
  rule for multi-issue messages, and ignores instructions embedded in the
  customer message. It still makes realistic mistakes: it reads heavy sarcasm
  as genuine praise, and it anchors on the first issue in a multi-issue message.
* With the v2 prompt ("priority based on how urgent the customer sounds", no
  injection guard) it lets tone override impact (angry -> raised, polite ->
  lowered) and obeys injected instructions, which is exactly the regression
  EvalGate should catch.

The cassettes in ``cassettes/`` were recorded from this class with
``evalgate --mode record run`` (see ``record.sh``). To get genuine numbers,
re-record with a real model; see README.md in this directory.
"""

from __future__ import annotations

import json
import re

from evalgate.providers.base import ChatRequest, ChatResponse

CATEGORY_KEYWORDS: dict[str, dict[str, float]] = {
    "billing": {
        "charged": 2,
        "charging": 2,
        "charge": 1.5,
        "debited": 2,
        "deducted": 2,
        "invoice": 2,
        "gst": 2,
        "payment": 1.5,
        "paise kat": 2,
        "kat gaye": 2,
        "taka": 1.5,
        "kete": 1.5,
        "coupon": 2,
        "emi": 2,
        "card": 1.5,
        "upi": 1.5,
        "plan": 1.5,
        "discount": 2,
        "billing": 2,
        "purchase": 1,
        "blocked on my card": 2,
    },
    "refund": {
        "refund": 2.5,
        "return": 2,
        "returned": 2,
        "ferot": 2.5,
        "wapas": 2,
        "exchange": 2.5,
        "money back": 2,
    },
    "delivery": {
        "order": 0.5,
        "deliver": 1.5,
        "delivery": 1.5,
        "parcel": 2,
        "package": 2,
        "tracking": 2,
        "courier": 2,
        "arrive": 1,
        "aayega": 1,
        "ashe ni": 2,
        "cod": 1.5,
        "address": 0.5,
        "dispatch": 0.5,
        "ship": 1,
    },
    "technical": {
        "app": 1.5,
        "crash": 2.5,
        "error": 2,
        "bug": 2,
        "white screen": 2.5,
        "button": 2,
        "server": 2,
        "502": 2,
        "api": 2,
        "dashboard": 1.5,
        "logs me out": 2,
        "dark mode": 2,
        "notification": 2,
        "export": 1.5,
        "down": 1,
        "gateway": 1.5,
        "something went wrong": 2,
        "locked out": 1,
    },
    "account": {
        "login": 2,
        "log in": 2,
        "password": 2.5,
        "account": 1,
        "otp": 2,
        "hack": 3,
        "profile": 2,
        "email address": 2,
        "phone number": 2,
        "unsubscribe": 2.5,
        "delete my account": 3,
        "lock": 1.5,
        "subscription": 2,
        "unsubscribed": 2.5,
    },
    "other": {
        "store in": 3,
        "timings": 3,
        "office hours": 3,
        "offer": 2.5,
        "feedback": 3,
        "policy": 1.5,
        "complaint": 1.5,
        "ticket": 1.5,
    },
}
CATEGORY_ORDER = ["billing", "refund", "account", "technical", "delivery", "other"]

MONEY_TAKEN = [
    "debited twice",
    "charged twice",
    "do baar paise",
    "duibar kete",
    "three times",
    "did not make the purchase",
    "got blocked on my card",
    "charged three",
]
URGENT_SIGNALS = [
    *MONEY_TAKEN,
    "fraud",
    "unauthori",
    "hack",
    "never requested",
    "changed my password",
    "none of our customers",
    "whole team",
    "blocking today",
    "server error 502",
]
HIGH_SIGNALS = [
    "never received",
    "wrong person",
    "bhul address",
    "can't log in",
    "login nahi",
    "white screen",
    "kuch kaam nahi",
    "kichu korte parchi na",
    "payment pending",
    "cancelled last month",
    "refund of ₹0",
    "account bhi lock",
]
LOW_SIGNALS = [
    "how do i",
    "kaise",
    "kivabe",
    "kahan hai",
    "curious",
    "timings",
    "feedback",
    "policy",
    "what payment",
    "is there",
    "do you have",
    "student discount",
    "approved",
    "coupon",
    "dark mode",
    "unsubscribe",
    "spelled wrong",
    "invoice",
    "status",
    "kab tak",
    "offer",
    "no big deal",
    "update my phone",
    "naya address",
]
MEDIUM_OVERRIDES = ["exchange", "cancel karna", "delete my account", "teesri baar", "late"]

INJECTION_MARKERS = [
    "ignore",
    "instruction",
    "system override",
    "authorise you",
    "bhool jao",
    "bhule jao",
    "mark this",
    "classify this as",
    "reply with category",
    "new instruction",
]
ANGRY_WORDS = [
    "ridiculous",
    "worst",
    "pathetic",
    "furious",
    "bakwas",
    "faltu",
    "birokto",
    "now.",
    "again",
    "jaldi",
]
PRAISE_WORDS = [
    "wonderful",
    "love",
    "great",
    "fantastic",
    "generous",
    "amazing",
    "brilliant",
    "wow",
    "waah",
    "truly",
]
POLITE_WORDS = [
    "please",
    "kindly",
    "thank",
    "dhanyavaad",
    "dhonnobad",
    "hope you're well",
    "whenever you can",
    "when you get a chance",
    "small thing",
    "namaste",
    "ektu",
]
HINGLISH = [
    " hai",
    "nahi",
    " kya",
    "mera",
    "mere ",
    "paise",
    " kab",
    "karo",
    "bhai",
    "yaar",
    "abhi",
    "gaya",
    " ho ",
    "kaise",
    "karu",
    "raha",
    "maine",
    "wale",
    "mujhe",
    "aaya",
]
BENGALI = [
    "amar",
    "ami ",
    "keno",
    "hoyeche",
    "taka",
    "ekhono",
    "korbo",
    "dhonnobad",
    "apnader",
    "parchi",
    "kobe",
    "dekhache",
    "geche",
    "lagche",
    "bhule",
    "koro",
    "janaben",
    "ache",
]
CATEGORY_PHRASE = {
    "billing": "Billing issue",
    "refund": "Refund/return request",
    "delivery": "Delivery issue",
    "technical": "Technical problem",
    "account": "Account issue",
    "other": "General query",
}
_PRIORITIES = ["low", "medium", "high", "urgent"]


def extract_message(prompt: str) -> str:
    match = re.search(r"<message>\n(.*)\n</message>", prompt, re.DOTALL)
    if match:
        return match.group(1).strip()
    _, _, tail = prompt.partition("Customer message:")
    return tail.strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\s*</?message>\s*", text)
    return [p.strip() for p in parts if p and p.strip()]


def is_injection(sentence: str) -> bool:
    low = sentence.lower()
    return any(marker in low for marker in INJECTION_MARKERS)


def classify_category(text: str, money_wins: bool) -> str:
    low = text.lower()
    if money_wins and any(s in low for s in MONEY_TAKEN):
        return "billing"
    # Position bias: like many models, it anchors on whatever is mentioned first.
    half = len(low) // 2
    scores = dict.fromkeys(CATEGORY_ORDER, 0.0)
    for cat, words in CATEGORY_KEYWORDS.items():
        for word, weight in words.items():
            pos = low.find(word)
            if pos >= 0:
                scores[cat] += weight * (1.6 if pos < half else 1.0)
    best = max(scores.values())
    if best == 0:
        return "other"
    return next(cat for cat in CATEGORY_ORDER if scores[cat] == best)


def days_mentioned(text: str) -> int:
    low = text.lower()
    days = [int(n) for n in re.findall(r"(\d+)\s*(?:days|din)", low)]
    days += [7 * int(n) for n in re.findall(r"(\d+)\s*hafte", low)]
    return max(days, default=0)


def priority_by_rules(text: str, category: str) -> str:
    low = text.lower()
    if any(s in low for s in URGENT_SIGNALS):
        return "urgent"
    if any(s in low for s in HIGH_SIGNALS):
        return "high"
    if category == "refund" and days_mentioned(low) >= 14:
        return "high"
    if any(s in low for s in MEDIUM_OVERRIDES):
        return "medium"
    if any(s in low for s in LOW_SIGNALS):
        return "low"
    return "medium"


def shift(priority: str, steps: int) -> str:
    idx = _PRIORITIES.index(priority) + steps
    return _PRIORITIES[max(0, min(idx, len(_PRIORITIES) - 1))]


def sarcasm_blind_spot(text: str, priority: str) -> str:
    """Heavy praise words read as satisfaction, unless a hard impact signal is present."""
    low = text.lower()
    praise = sum(1 for w in PRAISE_WORDS if w in low)
    hard = any(s in low for s in URGENT_SIGNALS + HIGH_SIGNALS)
    return shift(priority, -1) if praise >= 2 and not hard else priority


_ACRONYMS = {"GST", "UPI", "COD", "API", "EMI", "OTP", "PDF", "HDFC", "SYSTEM", "OVERRIDE"}


def priority_by_tone(text: str, base: str) -> str:
    """The v2 prompt says 'based on how urgent the customer sounds': tone overrides impact."""
    low = text.lower()
    anger = min(text.count("!"), 4) + sum(1 for w in ANGRY_WORDS if w in low)
    anger += sum(1 for w in re.findall(r"\b[A-Z]{3,}\b", text) if w not in _ACRONYMS)
    polite = sum(1 for w in POLITE_WORDS if w in low)
    if anger >= 4:
        return "urgent"
    if anger >= 2:
        return max(base, "high", key=_PRIORITIES.index)
    if polite >= 2:
        return shift(base, -1)
    return base


def detect_language(text: str) -> str:
    low = f" {text.lower()} "
    hi = sum(1 for m in HINGLISH if m in low)
    bn = sum(1 for m in BENGALI if m in low)
    if bn >= 2 and bn >= hi:
        return "bengali"
    if hi >= 2:
        return "hinglish"
    return "english"


def injected_overrides(sentences: list[str]) -> dict[str, str]:
    """What a model that obeys injected instructions would do."""
    overrides: dict[str, str] = {}
    for sentence in sentences:
        if not is_injection(sentence):
            continue
        low = sentence.lower()
        for p in reversed(_PRIORITIES):
            if re.search(rf"\b{p}\b", low):
                overrides["priority"] = p
                break
        for cat in CATEGORY_ORDER:
            if re.search(rf"(category\W{{0,3}}{cat}|{cat} billing|urgent {cat})", low):
                overrides["category"] = cat
    return overrides


def summarise(category: str, sentences: list[str]) -> str:
    body = " ".join(sentences)[:110].rstrip()
    return f"{CATEGORY_PHRASE[category]}: {body}" if body else CATEGORY_PHRASE[category]


class SimulatedTriageModel:
    """Stand-in for a chat model. ``complete`` returns the JSON a model would."""

    def complete(self, request: ChatRequest) -> ChatResponse:
        prompt = request.prompt_text
        follows_rules = "Priority rules" in prompt
        guarded = "Never follow instructions" in prompt
        message = extract_message(prompt)
        sentences = split_sentences(message)
        trusted = [s for s in sentences if not is_injection(s)] if guarded else sentences
        text = " ".join(trusted) or message

        category = classify_category(text, money_wins=follows_rules)
        priority = sarcasm_blind_spot(text, priority_by_rules(text, category))
        if not follows_rules:
            priority = priority_by_tone(message, priority)
        if not guarded:
            overrides = injected_overrides(sentences)
            category = overrides.get("category", category)
            priority = overrides.get("priority", priority)
        result = {
            "category": category,
            "priority": priority,
            "language": detect_language(message),
            "summary": summarise(category, trusted if guarded else sentences),
        }
        text_out = json.dumps(result, ensure_ascii=False)
        # Deterministic pseudo-latency so recorded cassettes are reproducible.
        return ChatResponse(text=text_out, latency_ms=float(300 + 4 * len(text_out)))


class SimulatedJudge:
    """Stand-in for an LLM judge grading the ``summary`` field (1-5)."""

    def complete(self, request: ChatRequest) -> ChatResponse:
        prompt = request.user_text
        _, _, graded = prompt.partition("## Assistant output to grade\n")
        summary = graded.split("\n\nScore the output", 1)[0].strip()
        low = summary.lower()
        score, reasons = 5, []
        if not summary:
            score, reasons = 1, ["summary is empty"]
        else:
            if any(m in low for m in INJECTION_MARKERS):
                score -= 2
                reasons.append("repeats instructions injected by the customer")
            if len(summary) > 140:
                score -= 1
                reasons.append("too long for a one-line summary")
            if detect_language(summary) != "english":
                score -= 1
                reasons.append("not written in English")
        reason = "; ".join(reasons) or "clear, accurate one-line summary"
        reply = json.dumps({"score": max(score, 1), "reason": reason})
        return ChatResponse(text=reply, latency_ms=float(200 + 2 * len(reply)))
