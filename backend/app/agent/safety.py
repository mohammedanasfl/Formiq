"""The coach's deterministic safety backstop.

assess_safety() reads the user's message, before the model or any tool, and
names the obvious risk in it, if there is one: pain or injury, a medical
question, dangerous exercise, extreme weight loss or extreme dieting, or
discomfort too unclear to answer safely. The graph then lets the model only
redirect (or, for unclear discomfort, ask), whatever the model would have
classified the request as. The model can still recognize risks these rules do
not, but it cannot downgrade one they found.

unsafe_reply() is the matching check on a redirect's reply: a few phrasings
that are never safe in it, and the internal labels the user must not see.

This is not a medical classifier. The rules look for a small set of clear
signals in the user's own words; anything subtler is left to the model and the
decision policy. They ignore what the user says about the check itself ("ignore
the pain", "my doctor said it's fine", "don't classify this as medical"): only
risk signals count, so such wording can neither add nor remove one. For the same
reason they do not read negation, so "I'm not injured" is still about an injury.

The module is pure: it reads text and returns values. It has no access to the
database, the tools or the model.
"""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class SafetyCategory(StrEnum):
    SAFE = "SAFE"
    # pain beyond ordinary soreness, an injury, or a warning symptom such as
    # chest pain, trouble breathing, dizziness or fainting
    PAIN_OR_INJURY = "PAIN_OR_INJURY"
    # a diagnosis, a medical condition, medication or treatment
    MEDICAL = "MEDICAL"
    # exercising through pain or symptoms, or in a way meant to be dangerous
    DANGEROUS_EXERCISE = "DANGEROUS_EXERCISE"
    # weight loss much faster than is safe, or a crash diet
    EXTREME_WEIGHT_LOSS = "EXTREME_WEIGHT_LOSS"
    # starvation, very low calorie intake, long fasts or purging
    EXTREME_DIETING = "EXTREME_DIETING"
    # the user describes pain or discomfort, but not enough to tell whether it
    # is ordinary soreness or something to have checked
    INSUFFICIENT_SAFETY_CONTEXT = "INSUFFICIENT_SAFETY_CONTEXT"


@dataclass(frozen=True)
class SafetyAssessment:
    """What the backstop found in a message: the category, and the name of the
    rule that found it (None when SAFE). Never the message's text."""

    category: SafetyCategory
    signal: str | None = None

    @property
    def enforced(self) -> bool:
        return self.category is not SafetyCategory.SAFE


SAFE = SafetyAssessment(SafetyCategory.SAFE)

# The thresholds below are conservative Formiq safety guardrails, not universal
# medical rules. What is safe differs from person to person and is for a
# healthcare professional to judge; Formiq does not judge it. Each threshold is
# set at or beyond a line in common public guidance, so that only requests
# clearly outside it are redirected to a professional. A request beyond one is not
# declared unsafe for everyone, and a request within one is not declared safe:
# it goes on to the model and the decision policy like any other. They are
# product decisions, to be revisited with a qualified professional.
#
# Weight loss faster than this average rate is redirected. Common public
# guidance (the NHS and the CDC, for example) suggests about 0.5 to 1 kg a week;
# this is twice the top of that range. Periods under a week count as one week,
# so short-term figures such as "1 kg in 3 days" are not inflated into a weekly
# rate.
MAX_WEEKLY_LOSS_KG = 2.0
# A daily intake below this is redirected: it is the usual definition of a
# very-low-calorie diet, which guidance (NICE, for example) reserves for medical
# supervision.
MIN_DAILY_CALORIES = 800
# A fast this long or longer is redirected: prolonged fasts are commonly advised
# only under medical supervision. Shorter ones, such as intermittent fasting or
# a 24-hour fast, go the normal way.
MAX_FAST_HOURS = 72

_KG_PER_POUND = 0.4536
_DAYS_PER_MONTH = 30.44
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}  # fmt: skip
_NUMBER = r"(\d+(?:\.\d+)?|" + "|".join(_NUMBER_WORDS) + r")"


def _number(text: str) -> float:
    return float(_NUMBER_WORDS[text]) if text in _NUMBER_WORDS else float(text)


def _days(amount: float, unit: str) -> float:
    if unit.startswith("h"):
        return amount / 24
    if unit.startswith("week"):
        return amount * 7
    if unit.startswith("month"):
        return amount * _DAYS_PER_MONTH
    return amount


def _sentences(text: str) -> list[str]:
    return re.split(r"[.?!;\n]", text)


def _extreme_weight_loss_rate(text: str) -> bool:
    """A weight-loss target faster than MAX_WEEKLY_LOSS_KG a week, such as
    "lose 15 kg in two weeks"."""
    pattern = re.compile(
        rf"\b(?:lose|losing|lost|drop|dropping|shed|shedding|cut|cutting)\s+(?:\w+\s+)?"
        rf"{_NUMBER}\s*(kg|kgs|kilos?|kilograms?|lbs?|pounds?)\b[^.?!]{{0,25}}?"
        rf"\b(?:in|within|over|by)\s+(?:the\s+next\s+|just\s+|only\s+)?{_NUMBER}\s+"
        rf"(days?|weeks?|months?)\b"
    )
    for amount, unit, period, period_unit in pattern.findall(text):
        kg = _number(amount) * (_KG_PER_POUND if unit.startswith(("lb", "pound")) else 1)
        weeks = max(_days(_number(period), period_unit) / 7, 1)
        if kg / weeks > MAX_WEEKLY_LOSS_KG:
            return True
    return False


def _very_low_calorie_intake(text: str) -> bool:
    """A daily intake under MIN_DAILY_CALORIES, such as "eat 500 calories a day";
    not a deficit, a surplus or calories burned."""
    calories = re.compile(
        r"\b(\d{2,4})\s*(?:k?cals?|calories?|kcals?)\b"
        r"(?!\s*(?:deficit|surplus|less|fewer|more|below|above|under|over))"
    )
    intake = re.compile(r"\b(eat|eating|eats|consume|consuming|intake|diet|on|only|limit)\b")
    daily = re.compile(r"\b(a|per|each|every)\s+day\b|/\s*day\b|\bdaily\b")
    # calories burned, or in one meal, are not the day's intake
    other = re.compile(r"\b(burn\w*|breakfast|lunch|dinner|snack\w*|meal\w*)\b")
    for sentence in _sentences(text):
        if other.search(sentence) or not (intake.search(sentence) and daily.search(sentence)):
            continue
        if any(int(value) < MIN_DAILY_CALORIES for value in calories.findall(sentence)):
            return True
    return False


def _prolonged_fast(text: str) -> bool:
    """A fast of MAX_FAST_HOURS or longer, such as "a 5-day fast" or "fast for a
    week"."""
    patterns = (
        rf"\b{_NUMBER}[- ]?(hours?|hrs?|h|days?|weeks?)[- ](?:water\s+|juice\s+)?fast",
        (
            rf"\bfast(?:ing)?\s+for\s+(?:about\s+|over\s+|more\s+than\s+)?{_NUMBER}\s+"
            r"(hours?|hrs?|days?|weeks?)\b"
        ),
    )
    for pattern in patterns:
        for amount, unit in re.findall(pattern, text):
            if _days(_number(amount), unit) * 24 >= MAX_FAST_HOURS:
                return True
    return False


@dataclass(frozen=True)
class _Rule:
    name: str
    category: SafetyCategory
    matches: Callable[[str], bool]


def _pattern(pattern: str) -> Callable[[str], bool]:
    return re.compile(pattern).search


_BODY_PART = (
    r"(back|knee|knees|ankle|shoulder|wrist|neck|hip|elbow|hamstring|groin|calf|quad|"
    r"foot|achilles|rotator cuff)"
)

# In order of precedence: the first that matches names the category. A request
# to exercise through a risk is dangerous exercise, whatever the risk is.
_RULES = (
    _Rule(
        "through_pain",
        SafetyCategory.DANGEROUS_EXERCISE,
        _pattern(
            r"\bthrough\s+(\w+\s+){0,3}?(pain|pains|injur\w*|symptoms?)\b"
            r"|\b(ignor\w*|disregard\w*|despite|regardless\s+of|in\s+spite\s+of|"
            r"forget\s+about)\s+(\w+\s+){0,3}?(pain|pains|injur\w*|symptoms?|warning\s+signs?|"
            r"doctor'?s?\s+(advice|orders))\b"
        ),
    ),
    _Rule(
        "deliberately_dangerous",
        SafetyCategory.DANGEROUS_EXERCISE,
        _pattern(
            r"\buntil\s+(i|you|they|we)\s+(pass\s+out|faint|collapse|throw\s+up|puke|vomit|"
            r"black\s+out)\b"
            r"|\b(even\s+if|i\s+don't\s+care\s+if|doesn't\s+matter\s+if|no\s+matter\s+if)\s+"
            r"(it's|it\s+is)\s+(\w+\s+)?(dangerous|unsafe|risky|harmful|bad\s+for\s+me)\b"
        ),
    ),
    _Rule(
        "severe_pain",
        SafetyCategory.PAIN_OR_INJURY,
        _pattern(
            r"\b(sharp|severe|stabbing|shooting|intense|excruciating|unbearable|extreme|"
            r"serious|burning|sudden)\s+(\w+\s+){0,2}?(pain|pains)\b"
            r"|\bpain\b[^.?!]{0,20}\b(is|gets|got|feels|became)\s+(very\s+|really\s+)?"
            r"(sharp|severe|unbearable|worse)\b"
        ),
    ),
    _Rule(
        "named_injury",
        SafetyCategory.PAIN_OR_INJURY,
        _pattern(
            r"\b(injury|injuries|injured|sprain\w*|fractur\w*|dislocat\w*|torn|ruptur\w*|"
            r"concussion)\b"
            r"|\b(muscle|ligament|tendon|acl|mcl|meniscus|labrum|rotator cuff)\s+tear\b"
            r"|\bbroken\s+(bone|arm|leg|ankle|wrist|foot|hand|toe|finger|rib)s?\b"
            r"|\bi('ve|\s+have)?\s+(just\s+)?(hurt|pulled|tweaked|strained|twisted|rolled|"
            r"jammed|tore)\s+(a|my)\b"
            rf"|\b(pulled|tweaked|strained|twisted|rolled|jammed|tore)\s+(a|my)\s+(\w+\s+)?"
            rf"({_BODY_PART}|muscle)\b"
        ),
    ),
    _Rule(
        "warning_symptom",
        SafetyCategory.PAIN_OR_INJURY,
        _pattern(
            r"\bchest\s+(pain|pains|tightness|pressure)\b|\b(pain|tightness|pressure)\s+in\s+"
            r"(my|the)\s+chest\b|\bpalpitations\b|\birregular\s+heart\s*beat\b"
            r"|\b(difficulty|trouble|struggling|hard|can't|cannot|unable\s+to)\s+(to\s+)?"
            r"breath(e|ing)\b|\bshort(ness)?\s+of\s+breath\b"
            r"|\bdizz(y|iness)\b|\blight-?headed\w*\b|\bfaint(ed|ing)?\b"
            r"|\b(pass|passed|passing)\s+out\b|\b(black|blacked|blacking)\s+out\b"
            r"|\bnumb(ness)?\b|\btingl(e|es|ing)\b|\bswell(ing|ed)\b|\bswollen\b|\bfever\b"
        ),
    ),
    _Rule(
        "medical_condition",
        SafetyCategory.MEDICAL,
        _pattern(
            r"\b(diagnos\w*|medical\s+condition\w*|health\s+condition\w*|"
            r"heart\s+(condition|disease|problem)s?|disease\w*|disorder\w*|illness\w*|"
            r"chronic\s+\w+|surger(y|ies)|post-?op\w*|"
            r"diabet\w*|asthma\w*|hypertension|high\s+blood\s+pressure|arthritis|"
            r"pregnan\w*|hernia\w*|osteoporosis|epilep\w*|cancer)\b"
        ),
    ),
    _Rule(
        "medication_or_treatment",
        SafetyCategory.MEDICAL,
        _pattern(
            r"\b(medication\w*|medicine\w*|meds|pills?|painkill\w*|pain\s*relievers?|"
            r"ibuprofen|paracetamol|acetaminophen|aspirin|insulin|steroids?|treatment\w*|"
            r"cure|rehab\w*)\b"
            # not "prescribe" alone: a workout plan prescribes sets and reps
            r"|\bprescri\w*\s+(drugs?|medication\w*|medicine\w*|meds|pills?)\b"
            r"|\bhow\s+(do|can|should)\s+i\s+treat\b|\btreat\s+my\b"
        ),
    ),
    _Rule(
        "symptom_cause",
        SafetyCategory.MEDICAL,
        _pattern(
            r"\bwhat('s|\s+is)?\s+(causing|caused|causes|the\s+cause\s+of)\s+(my|this|the\s+pain)\b"
            r"|\bwhat('s|\s+is)\s+wrong\s+with\s+my\b"
            r"|\bwhy\s+(does|do|is|did)\s+(my|i)\b[^.?!]{0,40}\b"
            r"(hurt\w*|pain\w*|swollen|swell\w*|numb|tingl\w*)"
        ),
    ),
    _Rule(
        "starvation_or_purging",
        SafetyCategory.EXTREME_DIETING,
        _pattern(
            r"\bstarvation\b|\bstarv(e|ing)\s+(myself|yourself|me)\b"
            r"|\b(no\s+food|eat(ing)?\s+nothing|not\s+eat(ing)?(\s+anything)?|stop\s+eating|"
            r"without\s+(eating|food))\b[^.?!]{0,20}\bfor\s+(\w+\s+)?(days?|weeks?|months?)\b"
            r"|\b(zero|0)\s+calories\b|\bdry\s+fast\w*\b"
            r"|\b(laxatives?|diuretics?|purg(e|ing))\b"
            r"|\bmake\s+(myself|me)\s+(throw\s+up|vomit|sick)\b"
        ),
    ),
    _Rule("very_low_calorie", SafetyCategory.EXTREME_DIETING, _very_low_calorie_intake),
    _Rule("prolonged_fast", SafetyCategory.EXTREME_DIETING, _prolonged_fast),
    _Rule(
        "crash_diet",
        SafetyCategory.EXTREME_WEIGHT_LOSS,
        _pattern(
            r"\bcrash[- ]?diet\w*\b"
            r"|\b(rapid|extreme|drastic)(ly)?\s+(weight|fat)\s+loss\b"
            r"|\blos(e|ing)\s+(weight|fat)\s+(\w+\s+)?(rapidly|drastically|extremely)\b"
            r"|\bdehydrat\w*\s+(myself|me)\b"
        ),
    ),
    _Rule("extreme_loss_rate", SafetyCategory.EXTREME_WEIGHT_LOSS, _extreme_weight_loss_rate),
    _Rule(
        "unclear_discomfort",
        SafetyCategory.INSUFFICIENT_SAFETY_CONTEXT,
        _pattern(
            r"\bmy\b[^.?!]{0,30}\b(hurts?|hurting|pain|pains|painful|discomfort)\b"
            r"|\bi\s+(have|feel|get|got|am\s+having|'m\s+having|'ve\s+got|'ve\s+been\s+having|"
            r"keep\s+getting|felt|had)\b[^.?!]{0,30}\b(pain|pains|discomfort|twinges?|hurt\w*)\b"
            r"|\b(it|this|that)\s+hurts\b|\bhurts?\s+(when|if|after|during|while)\b"
            r"|\bpain\s+(in|on)\s+my\b"
        ),
    ),
)

# Wording about preventing an injury is not an injury.
_PREVENTION = re.compile(
    r"\b(prevent\w*|avoid\w*|reduc\w*|minimi[sz]\w*|lower\w*)\s+(the\s+)?(risk\s+of\s+)?"
    r"(an?\s+)?(\w+\s+)?injur(y|ies)\b"
    r"|\b(risk|chance)\s+of\s+(an?\s+)?(\w+\s+)?injur(y|ies)\b"
    r"|\binjury[- ](free|prevention)\b"
)
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))
_QUOTES = {ord("\u2018"): "'", ord("\u2019"): "'"}


def _normalize(message: str) -> str:
    text = unicodedata.normalize("NFKC", message).translate(_ZERO_WIDTH).translate(_QUOTES)
    text = re.sub(r"\s+", " ", text.casefold())
    return _PREVENTION.sub(" ", text)


def assess_safety(message: str) -> SafetyAssessment:
    """The first obvious risk in the user's message, or SAFE."""
    text = _normalize(message)
    for rule in _RULES:
        if rule.matches(text):
            return SafetyAssessment(rule.category, rule.name)
    return SAFE


# What a redirect's reply must never say. Training through pain or ignoring
# symptoms is allowed only as what not to do ("I can't recommend training
# through pain"): the negation must come right before it, with nothing between
# but a few words that keep its sense, so "never stop pushing through it" or
# "it's not a big deal to push through it" are still caught.
_UNSAFE_ACTION = re.compile(
    r"\b(push|train|work|keep\s+going|power|lift|run|play|grind)\w*\s+(on\s+)?through\s+"
    r"(\w+\s+){0,2}?(pain|it|injur\w*|discomfort|symptoms?)\b"
    r"|\bignor\w*\s+(\w+\s+){0,2}?(pain|symptoms?|warning\s+signs?)\b",
    re.IGNORECASE,
)
_NEGATED = re.compile(
    r"\b(not|never|cannot|can't|don't|do\s+not|won't|shouldn't|avoid\w*|against|"
    r"instead\s+of|rather\s+than)\s+"
    r"((to|recommend|advise|suggest|encourage|safely|help|with|provide|give|guidance|"
    r"advice|on|about|you|try|be|keep|continue|any)\s+){0,5}$",
    re.IGNORECASE,
)
# ...and, in any form: that no professional is needed, a hedged diagnosis, or a
# dose. A safe reply that happens to use such wording is replaced by the fixed
# reply below, which is safe too.
_UNSAFE_CLAIM = re.compile(
    r"\bno\s+pain,?\s+no\s+gain\b"
    r"|\b(don't|do\s+not)\s+need\s+(to\s+see\s+)?(a\s+)?(doctor|physio\w*|medical)"
    r"|\b(sounds\s+like|it's\s+probably|it\s+is\s+probably|it's\s+likely|it\s+is\s+likely|"
    r"you\s+(probably|likely|most\s+likely)\s+have)\b"
    r"|\b\d+\s*(mg|milligrams?)\b",
    re.IGNORECASE,
)


def unsafe_reply(reply: str, internal_labels: frozenset[str]) -> str | None:
    """Why a safety reply cannot reach the user, or None when it can."""
    text = unicodedata.normalize("NFKC", reply).translate(_QUOTES)
    if _UNSAFE_CLAIM.search(text) or any(
        not _NEGATED.search(text[: match.start()]) for match in _UNSAFE_ACTION.finditer(text)
    ):
        return "the reply gives unsafe guidance"
    if any(re.search(rf"\b{re.escape(label)}\b", text) for label in internal_labels):
        return "the reply shows internal labels"
    return None


# The replies Formiq gives itself when the model's reply cannot be used: no
# diagnosis, no treatment, no certainty about the user's condition.
SAFE_REPLIES: dict[SafetyCategory, str] = {
    SafetyCategory.PAIN_OR_INJURY: (
        "I can't safely advise on exercising with pain, an injury or symptoms like these. "
        "Please stop any exercise that brings them on, and have them checked by a doctor "
        "or physiotherapist before you continue training. If you have chest pain, trouble "
        "breathing or feel faint, stop and get medical help right away."
    ),
    SafetyCategory.MEDICAL: (
        "I can't give medical advice, such as diagnosing a condition or recommending "
        "treatment or medication. A doctor or another qualified healthcare professional "
        "can advise on this, including what exercise is safe for you. Once you have "
        "their guidance, I'm happy to help you plan training that fits it."
    ),
    SafetyCategory.DANGEROUS_EXERCISE: (
        "I can't help with exercising in a way that risks hurting you, such as carrying "
        "on despite pain or warning symptoms. If something hurts or feels wrong, stop and "
        "have it checked by a doctor or physiotherapist. I'm happy to help you find a "
        "safe way to work toward your goal instead."
    ),
    SafetyCategory.EXTREME_WEIGHT_LOSS: (
        "I can't help with losing weight that quickly: very fast weight loss can harm "
        "your health. A gradual rate, often around 0.5 to 1 kg a week, is safer and "
        "easier to keep off. A doctor or registered dietitian can help you set a safe "
        "target, and I'm happy to help with training that supports it."
    ),
    SafetyCategory.EXTREME_DIETING: (
        "I can't help with starving yourself, very low-calorie diets or long fasts: they "
        "can harm your health. A doctor or registered dietitian can help you plan a safe "
        "way to eat for your goal, and I'm happy to help with the training side. If "
        "you're struggling with food or eating, please talk to a doctor or someone you "
        "trust."
    ),
    SafetyCategory.INSUFFICIENT_SAFETY_CONTEXT: (
        "Can you tell me more about what you're feeling? Is it general muscle soreness "
        "after training, or is it in a joint, sharp, or not easing after a few days? If "
        "it's sharp, severe or getting worse, please stop the exercise that causes it "
        "and have it checked by a doctor or physiotherapist."
    ),
}
