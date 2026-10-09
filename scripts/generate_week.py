#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Weekly batch generator for "오늘의 영어" (Today's English) content.

Creates a week of daily English-learning content JSON files that the EnglishFlow
Android app publishes as "오늘의 영어". By default it calls the Gemini API
(key from the GEMINI_API_KEY environment variable or scripts/.env). Use --demo
to write built-in sample files so the format can be inspected without a key.

Examples:
  python scripts/generate_week.py                     # next Monday, 7 days
  python scripts/generate_week.py --start 2026-10-12 --days 7
  python scripts/generate_week.py --demo --days 3     # sample output
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONTENT_DIR = SCRIPT_DIR.parent / "content"
ENV_FILE = SCRIPT_DIR / ".env"

DEFAULT_TYPES = ["quote", "story", "knowledge", "business", "essay", "travel", "dialogue"]
DEFAULT_MODEL = "gemini-3.8-flash"

# Fallback models tried when a model name returns HTTP 404 (models are
# occasionally retired). The primary model is always tried first.
MODEL_CANDIDATES = [
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]
API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

FILE_NAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+-(?:quote|story|knowledge|business|essay|travel|dialogue)\.json$"
)

DAY_THEMES = [
    "learning and growth",
    "kindness and small gestures",
    "health and daily habits",
    "work and communication",
    "travel and new experiences",
    "food and culture",
    "reflection and rest",
]

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "of", "in", "on", "at", "to", "for",
    "with", "from", "by", "as", "is", "are", "was", "were", "be", "been", "it",
    "i", "we", "you", "they", "he", "she", "this", "that", "my", "your", "our",
}

BASE_INSTRUCTIONS = """\
You write original, high-quality English learning content for Korean adult learners.

Requirements for ALL output:
- Return ONLY valid JSON. No markdown fences, no extra commentary.
- English: natural, modern, everyday English at an intermediate level (CEFR B1-B2).
- Korean: fluent, natural translation for Korean learners (not literal machine translation).
- Never reproduce famous copyrighted quotes or song lyrics; write original sentences.
- "expressions": 3 to 5 useful phrases drawn from the text. Each entry has:
    "en" (the phrase), "ko" (short Korean gloss), "example" (a NEW English example
    sentence using the phrase). "exampleKo" is optional.
"""

PROMPTS = {
    "quote": BASE_INSTRUCTIONS + """
Task: write ONE original, concise quote about "{theme}".
JSON schema:
{{
  "en": "the quote, 1 to 3 sentences, under 60 words",
  "ko": "natural Korean translation of the quote",
  "subject": "quote",
  "expressions": [{{"en": "...", "ko": "...", "example": "...", "exampleKo": ""}}]
}}
""",
    "story": BASE_INSTRUCTIONS + """
Task: write a short everyday story (90 to 150 words) on the theme "{theme}".
It should feel like a page from a diary: a small moment with a light lesson.
JSON schema:
{{
  "en": "the story, 90 to 150 words",
  "ko": "natural Korean translation of the story",
  "subject": "story",
  "expressions": [{{"en": "...", "ko": "...", "example": "...", "exampleKo": ""}}]
}}
""",
    "knowledge": BASE_INSTRUCTIONS + """
Task: write a short, interesting fact (60 to 110 words) on the theme "{theme}".
The fact should be true, easy to understand, and fun for learners.
JSON schema:
{{
  "en": "the fact, 60 to 110 words",
  "ko": "natural Korean translation",
  "subject": "knowledge",
  "expressions": [{{"en": "...", "ko": "...", "example": "...", "exampleKo": ""}}]
}}
""",
    "business": BASE_INSTRUCTIONS + """
Task: write a short workplace/business scenario (80 to 130 words) on the theme "{theme}".
Include natural office English: meetings, email, small talk, or negotiation.
JSON schema:
{{
  "en": "the scenario, 80 to 130 words",
  "ko": "natural Korean translation",
  "subject": "business",
  "expressions": [{{"en": "...", "ko": "...", "example": "...", "exampleKo": ""}}]
}}
""",
    "essay": BASE_INSTRUCTIONS + """
Task: write a short reflective essay (90 to 150 words) on the theme "{theme}".
Write in a warm, personal voice, as if sharing a thought at the end of the day.
JSON schema:
{{
  "en": "the essay, 90 to 150 words",
  "ko": "natural Korean translation",
  "subject": "essay",
  "expressions": [{{"en": "...", "ko": "...", "example": "...", "exampleKo": ""}}]
}}
""",
    "travel": BASE_INSTRUCTIONS + """
Task: write a short travel piece (70 to 120 words) on the theme "{theme}".
Describe a place, a trip, or a travel tip that a learner could actually use.
JSON schema:
{{
  "en": "the piece, 70 to 120 words",
  "ko": "natural Korean translation",
  "subject": "travel",
  "expressions": [{{"en": "...", "ko": "...", "example": "...", "exampleKo": ""}}]
}}
""",
    "dialogue": BASE_INSTRUCTIONS + """
Task: write a natural 6 to 8 line dialogue between two speakers (A and B) on the
theme "{theme}". Alternate speakers. Each line is short, everyday speech.
JSON schema:
{{
  "subject": "dialogue",
  "lines": [
    {{"speaker": "A", "en": "...", "ko": "..."}},
    {{"speaker": "B", "en": "...", "ko": "..."}}
  ],
  "expressions": [{{"en": "...", "ko": "...", "example": "...", "exampleKo": ""}}]
}}
""",
}
DEMO_CONTENT = {
    "quote": {
        "en": "Progress is not a straight line. It is made of small steps, quiet detours, and the courage to try again tomorrow.",
        "ko": "발전은 직선이 아닙니다. 작은 발걸음과 조용한 우회로, 그리고 내일 다시 시도하는 용기로 이루어집니다.",
        "subject": "quote",
        "expressions": [
            {"en": "a straight line", "ko": "직선, 곧은 길", "example": "Learning is not a straight line from beginner to fluent."},
            {"en": "small steps", "ko": "작은 발걸음들", "example": "You can finish a big project by taking small steps."},
            {"en": "try again", "ko": "다시 시도하다", "example": "If the first draft is bad, try again tomorrow."},
        ],
    },
    "story": {
        "en": "This morning I almost skipped my walk because the sky looked gray. Before I left, I talked myself into it anyway and put on a jacket. The air was cold, but the streets were quiet and the walk felt good. Halfway around the park, the clouds parted and the sun came through. I stopped to watch a group of children trying to fly a kite, and one of them finally got it up high. That small moment reminded me that a gray start does not mean a gray day.",
        "ko": "오늘 아침 나는 하늘이 잿빛이라 산책을 건너뛸 뻔했습니다. 나가기 전에 그래도 해보자고 스스로를 설득해서 자켓을 입었습니다. 공기는 차가웠지만 거리는 조용했고 걷는 느낌이 좋았습니다. 공원을 한 바퀴 도는 중간에 구름이 갈라지고 햇살이 비쳐 들어왔습니다. 연을 날리려는 아이들 무리를 멈춰 서서 바라봤는데, 그중 한 명이 마침내 연을 높이 띄웠습니다. 그 작은 순간이 잿빛 시작이 잿빛 하루를 뜻하지는 않는다는 걸 상기시켜 주었습니다.",
        "subject": "story",
        "expressions": [
            {"en": "skip", "ko": "건너뛰다, 빠뜨리다", "example": "I decided to skip lunch because I was busy."},
            {"en": "the clouds parted", "ko": "구름이 갈라졌다", "example": "The clouds parted just in time for the sunset."},
            {"en": "a gray start", "ko": "잿빛(우울한) 시작", "example": "Don't let a gray start ruin your whole day."},
        ],
    },
    "knowledge": {
        "en": "Octopuses have three hearts and blue blood. Two of the hearts pump blood to the gills, while the third pumps it to the rest of the body. When an octopus swims, the heart that serves the body stops beating, which is one reason octopuses prefer to crawl instead of swim. Their blood is blue because it uses copper instead of iron to carry oxygen.",
        "ko": "문어는 심장이 세 개이고 피가 파랗습니다. 두 개의 심장은 아가미로 피를 보내고, 나머지 하나는 몸 전체로 피를 보냅니다. 문어가 헤엄칠 때 몸에 피를 보내는 심장은 멈추는데, 그래서 문어는 헤엄치기보다 기어 다니는 것을 선호합니다. 피가 파란 이유는 산소를 운반할 때 철 대신 구리를 사용하기 때문입니다.",
        "subject": "knowledge",
        "expressions": [
            {"en": "pump blood", "ko": "피를 보내다, 순환시키다", "example": "Your heart pumps blood to every part of your body."},
            {"en": "prefer to", "ko": "~하는 것을 더 좋아하다", "example": "Some people prefer to study in the morning."},
            {"en": "instead of", "ko": "~ 대신에", "example": "I had tea instead of coffee this morning."},
        ],
    },
    "business": {
        "en": "During the team meeting, Mina proposed moving the deadline to Friday. Her manager asked her to explain the reason, so she showed a simple schedule that listed every task still waiting. Because she had prepared the list in advance, the team agreed quickly. Her manager thanked her and said that good preparation makes a short meeting. Later, Mina wrote a short follow-up email to confirm the new date and to thank everyone for their flexibility. She was glad she had asked a clear question before assuming the old deadline was still possible.",
        "ko": "팀 회의에서 미나는 마감일을 금요일로 옮기자고 제안했습니다. 매니저가 이유를 설명해 달라고 하자, 그녀는 아직 남아 있는 모든 업무를 나열한 간단한 일정표를 보여 주었습니다. 미리 목록을 준비해 둔 덕분에 팀은 빠르게 동의했습니다. 매니저는 고마워하며 좋은 준비가 회의를 짧게 만든다고 말했습니다. 이후 미나는 새 날짜를 확인하고 모두의 유연함에 감사하는 짧은 후속 이메일을 보냈습니다. 기존 마감일이 여전히 가능하다고 가정하기 전에 명확한 질문을 한 것이 잘했다고 생각했습니다.",
        "subject": "business",
        "expressions": [
            {"en": "propose", "ko": "제안하다", "example": "She proposed a new schedule at the meeting."},
            {"en": "in advance", "ko": "미리, 사전에", "example": "Please book the room in advance."},
            {"en": "follow-up email", "ko": "후속 이메일", "example": "I sent a follow-up email to confirm the time."},
        ],
    },
    "essay": {
        "en": "I used to think that rest was a reward I had to earn. If I had not been productive, I did not allow myself to relax. Lately I have been trying a different rule: rest is part of the work. A short pause helps me notice what I am feeling and keeps my mind clear. When I sit quietly for five minutes, I often remember what mattered most that day. That small habit has changed how I end my evenings and how I start the next morning. I am learning that doing less can sometimes mean moving forward more.",
        "ko": "나는 예전에 휴식이 벌어야 하는 보상이라고 생각했습니다. 생산적이지 않았다면 스스로 쉬는 것을 허락하지 않았습니다. 최근에는 다른 규칙을 시도하고 있습니다. 휴식은 일의 일부라는 것입니다. 짧은 멈춤은 내가 지금 무엇을 느끼는지 알아차리게 해 주고 마음을 맑게 유지시켜 줍니다. 5분간 조용히 앉아 있으면 그날 가장 중요했던 일이 무엇인지 자주 떠오릅니다. 그 작은 습관이 저녁을 마무리하는 방식과 다음 날 아침을 시작하는 방식을 바꾸어 놓았습니다. 덜 하는 것이 때로는 더 나아가는 것일 수 있다는 것을 배우고 있습니다.",
        "subject": "essay",
        "expressions": [
            {"en": "used to think", "ko": "예전에는 생각했다", "example": "I used to think that talking less made me seem weak."},
            {"en": "part of the work", "ko": "일의 일부", "example": "Planning is part of the work, not extra work."},
            {"en": "move forward", "ko": "앞으로 나아가다", "example": "Taking a break can help you move forward faster."},
        ],
    },
    "travel": {
        "en": "Many travelers plan their day around famous sights, but if you visit a city for just one day, try the early morning market instead. It is usually quiet, and the stall owners have time to chat. You can taste local food, practice simple phrases, and avoid the crowds that arrive later. Start with a small question like \"What do you recommend?\" — it is the fastest way to turn a sightseeing trip into a real conversation with a local.",
        "ko": "많은 여행자가 유명한 관광지를 중심으로 하루를 계획하지만, 도시를 단 하루만 방문한다면 대신 이른 아침 시장에 가 보세요. 보통 조용하고 상인들이 이야기할 시간이 있습니다. 현지 음식을 맛보고 간단한 표현을 연습하며, 나중에 몰려드는 인파를 피할 수 있습니다. \"무엇을 추천하세요?\" 같은 작은 질문으로 시작해 보세요. 관광 여행을 현지인과의 진짜 대화로 바꾸는 가장 빠른 방법입니다.",
        "subject": "travel",
        "expressions": [
            {"en": "stall owners", "ko": "가게 주인들, 노점 주인들", "example": "The stall owners greeted every visitor with a smile."},
            {"en": "avoid the crowds", "ko": "인파를 피하다", "example": "We left early to avoid the crowds at the museum."},
            {"en": "What do you recommend?", "ko": "무엇을 추천하시나요?", "example": "At a new restaurant, I always ask what they recommend."},
        ],
    },
    "dialogue": {
        "subject": "dialogue",
        "lines": [
            {"speaker": "A", "en": "I'm thinking of joining the weekend hiking club.", "ko": "주말 등산 동호회에 가입할까 생각 중이야."},
            {"speaker": "B", "en": "That sounds fun. Have you hiked much before?", "ko": "재밌겠다. 예전에 많이 등산해 봤어?"},
            {"speaker": "A", "en": "Not really. I want to start somewhere easy.", "ko": "별로. 쉬운 데부터 시작하고 싶어."},
            {"speaker": "B", "en": "Good idea. I can lend you my spare shoes if you need.", "ko": "좋은 생각이야. 필요하면 여분 신발 빌려줄게."},
            {"speaker": "A", "en": "That would be a big help. Should I sign up online?", "ko": "정말 큰 도움이 될 거야. 온라인으로 신청하면 돼?"},
            {"speaker": "B", "en": "Yes, just fill out the form and pay a small fee.", "ko": "응, 양식만 작성하고 적은 회비를 내면 돼."},
            {"speaker": "A", "en": "Perfect. Let's go together next weekend.", "ko": "좋아. 다음 주말에 같이 가자."},
        ],
        "expressions": [
            {"en": "thinking of doing", "ko": "~할까 생각 중이다", "example": "I'm thinking of learning how to cook."},
            {"en": "lend", "ko": "빌려주다", "example": "Can you lend me your charger for a minute?"},
            {"en": "sign up", "ko": "가입하다, 신청하다", "example": "You can sign up for the class on the website."},
        ],
    },
}


def demo_content(ctype: str) -> dict:
    """Return a built-in sample for a type (used with --demo)."""
    return json.loads(json.dumps(DEMO_CONTENT[ctype]))
def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.is_file():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def get_api_key() -> str | None:
    env = load_env()
    return os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY")


def next_monday(from_date: date) -> date:
    days_ahead = (7 - from_date.weekday()) % 7
    return from_date + timedelta(days=days_ahead if days_ahead else 7)


def _post_gemini(url: str, body: dict, timeout: int, retries: int = 3) -> dict:
    """POST a request to the Gemini API, retrying transient failures.

    Retries with a short backoff on rate limits / server overload (429, 500,
    503) and on network timeouts. Permanent errors (4xx other than 429,
    including auth and unknown-model 404s) fail immediately.
    """
    last_error: Exception | None = None
    for attempt in range(max(retries, 1)):
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if error.code in (429, 500, 503) and attempt < retries - 1:
                delay = 5 * (attempt + 1)
                print(f"  (API busy HTTP {error.code}; retrying in {delay}s ...)")
                time.sleep(delay)
                last_error = RuntimeError(f"Gemini API HTTP {error.code}: {detail[:500]}")
                continue
            raise RuntimeError(f"Gemini API HTTP {error.code}: {detail[:500]}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if attempt < retries - 1:
                delay = 5 * (attempt + 1)
                print(f"  (network/timeout retry in {delay}s ...)")
                time.sleep(delay)
                last_error = error
                continue
            raise RuntimeError(f"Gemini API request failed: {error}") from error
    raise RuntimeError(f"Gemini API request failed after {retries} attempts: {last_error}")


def call_gemini(prompt: str, model: str, api_key: str, timeout: int = 120) -> str:
    """Call the Gemini generateContent endpoint and return the raw text.

    Retries once without responseMimeType for models that do not support JSON
    mode, and falls back to MODEL_CANDIDATES when a model name returns a 404
    (retired model) or a 429 (per-model free-tier quota exhausted).
    """
    candidates = [model] + [m for m in MODEL_CANDIDATES if m != model]
    last_error: Exception | None = None
    for candidate in candidates:
        if last_error is not None:
            print(f"  (model fallback -> {candidate})")
        try:
            return _call_gemini_model(prompt, candidate, api_key, timeout)
        except RuntimeError as error:
            last_error = error
            message = str(error)
            model_related = ("HTTP 404" in message) or ("HTTP 429" in message)
            if not model_related:
                raise
    raise RuntimeError(f"Gemini API call failed: {last_error}")


def _call_gemini_model(prompt: str, model: str, api_key: str, timeout: int) -> str:
    url = API_ENDPOINT.format(model=urllib.parse.quote(model)) + "?key=" + urllib.parse.quote(api_key)
    base = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9, "topP": 0.95, "maxOutputTokens": 4096},
    }
    attempts = [
        {**base, "generationConfig": {**base["generationConfig"], "responseMimeType": "application/json"}},
        base,
    ]
    last_error: Exception | None = None
    for body in attempts:
        try:
            payload = _post_gemini(url, body, timeout)
            return payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as error:
            raise RuntimeError(f"Unexpected Gemini response: {json.dumps(payload)[:500]}") from error
        except RuntimeError as error:
            last_error = error
    raise RuntimeError(f"Gemini API call failed: {last_error}")


def extract_json(text: str) -> dict:
    """Parse the first JSON object out of a model reply (tolerates fences)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        # Models occasionally add a trailing comma before } or ].
        repaired = re.sub(r",\s*([}\]])", r"\1", text)
        if repaired != text:
            return json.loads(repaired)
        raise error


WORD_LIMITS = {
    "quote": (5, 60),
    "story": (80, 180),
    "knowledge": (60, 120),
    "business": (80, 140),
    "essay": (90, 180),
    "travel": (70, 130),
    "dialogue": None,
}


def validate_expression(expr: dict, index: int, errors: list[str]) -> None:
    if not str(expr.get("en") or "").strip() or not str(expr.get("ko") or "").strip():
        errors.append(f"expressions[{index}]: 'en' and 'ko' must be non-blank.")
    if not str(expr.get("example") or "").strip():
        errors.append(f"expressions[{index}]: missing 'example'.")


def validate_content(ctype: str, data: dict, errors: list[str]) -> None:
    if ctype != "dialogue":
        en = str(data.get("en") or "").strip()
        ko = str(data.get("ko") or "").strip()
        if not en or not ko:
            errors.append("'en' and 'ko' must be non-blank.")
        if en:
            word_count = len(en.split())
            limit = WORD_LIMITS.get(ctype)
            if limit and not (limit[0] <= word_count <= limit[1]):
                errors.append(f"en word count {word_count} outside expected {limit} for '{ctype}'.")
    expressions = data.get("expressions") or []
    if not (3 <= len(expressions) <= 5):
        errors.append(f"expressions should be 3-5, got {len(expressions)}.")
    for i, expr in enumerate(expressions):
        if not isinstance(expr, dict):
            errors.append(f"expressions[{i}] must be an object.")
            continue
        validate_expression(expr, i, errors)
    if ctype == "dialogue":
        lines = data.get("lines") or []
        if len(lines) < 4:
            errors.append(f"dialogue needs at least 4 lines, got {len(lines)}.")
        speakers: set[str] = set()
        for i, line in enumerate(lines):
            if not isinstance(line, dict):
                errors.append(f"lines[{i}] must be an object.")
                continue
            if not str(line.get("en") or "").strip() or not str(line.get("ko") or "").strip():
                errors.append(f"lines[{i}]: 'en' and 'ko' must be non-blank.")
            speaker = str(line.get("speaker") or "").strip()
            if speaker:
                speakers.add(speaker)
        if len(speakers) < 2:
            errors.append("dialogue should have at least two speakers.")


def make_slug(en: str, ctype: str, used: set[str]) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", en.lower()) if w not in STOP_WORDS]
    base = "-".join(words[:6])[:40].rstrip("-")
    if not base:
        base = ctype
    slug, n = base, 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def write_content(content_dir: Path, file_name: str, data: dict) -> Path:
    target = content_dir / file_name
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--start", metavar="YYYY-MM-DD", help="start date (default: next Monday)")
    parser.add_argument("--days", type=int, default=7, help="number of days to generate (default: 7)")
    parser.add_argument(
        "--types", default=",".join(DEFAULT_TYPES),
        help="comma-separated type order (default: quote,story,knowledge,business,essay,travel,dialogue)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model (default: {DEFAULT_MODEL})")
    parser.add_argument("--content-dir", type=Path, default=CONTENT_DIR, help=f"output directory (default: {CONTENT_DIR})")
    parser.add_argument("--demo", action="store_true", help="write built-in samples instead of calling the Gemini API")
    args = parser.parse_args()

    types = [t for t in (x.strip() for x in args.types.split(",")) if t]
    unknown = sorted(set(types) - set(DEFAULT_TYPES))
    if unknown:
        parser.error(f"unknown type(s): {', '.join(unknown)}; allowed: {', '.join(DEFAULT_TYPES)}")

    start = date.fromisoformat(args.start) if args.start else next_monday(date.today())
    api_key = None if args.demo else get_api_key()
    if not args.demo and not api_key:
        print("[ERROR] GEMINI_API_KEY is not set.", file=sys.stderr)
        print("  Set the environment variable, or create scripts/.env with GEMINI_API_KEY=...", file=sys.stderr)
        print("  (Run with --demo to inspect the output format without a key.)", file=sys.stderr)
        return 2

    content_dir = args.content_dir
    content_dir.mkdir(parents=True, exist_ok=True)
    existing_files = {p.name for p in content_dir.glob("*.json") if p.is_file()}
    existing_dates = {name[:10] for name in existing_files if FILE_NAME_RE.match(name)}
    existing_slugs: set[str] = set()
    for name in existing_files:
        m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+?)-(?:quote|story|knowledge|business|essay|travel|dialogue)\.json$", name)
        if m:
            existing_slugs.add(m.group(1))

    print(f"Generating {max(args.days, 1)} day(s) starting {start.isoformat()} -> {content_dir}")
    generated, skipped, failed = [], [], []
    for offset in range(max(args.days, 1)):
        day = start + timedelta(days=offset)
        date_str = day.isoformat()
        if date_str in existing_dates:
            skipped.append(date_str)
            print(f"  [SKIP] {date_str}: content already exists")
            continue
        ctype = types[offset % len(types)]
        theme = DAY_THEMES[day.weekday()]

        if args.demo:
            data = demo_content(ctype)
        else:
            try:
                raw = call_gemini(PROMPTS[ctype].format(theme=theme), args.model, api_key)
                data = extract_json(raw)
            except Exception as error:  # noqa: BLE001
                failed.append((date_str, ctype, str(error)))
                print(f"  [FAIL] {date_str} {ctype}: {error}")
                continue

        errors: list[str] = []
        validate_content(ctype, data, errors)
        if errors:
            failed.append((date_str, ctype, "; ".join(errors)))
            print(f"  [INVALID] {date_str} {ctype}: {'; '.join(errors)}")
            continue

        en = str(data.get("en") or (data.get("lines") or [{}])[0].get("en") or "")
        slug = make_slug(en, ctype, existing_slugs)
        file_name = f"{date_str}-{slug}-{ctype}.json"
        write_content(content_dir, file_name, data)
        existing_dates.add(date_str)
        generated.append(file_name)
        print(f"  [OK] {file_name}")

    print(f"\nSummary: generated={len(generated)} skipped={len(skipped)} failed={len(failed)}")
    if generated:
        print(f"Review files in: {content_dir}")
        print("Then commit & push to deploy (git add content/ && git commit -m ... && git push).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())