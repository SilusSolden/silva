"""Speech patterns for Silva news briefing commands."""

from __future__ import annotations

import re

NEWS_PHRASES: tuple[str, ...] = (
    "news briefing",
    "daily news",
    "daily briefing",
    "latest news",
    "latest briefing",
    "whats the latest",
    "what's the latest",
    "what is the latest",
    "local news",
    "my local news",
    "the local news",
    "whats my local news",
    "what's my local news",
    "what is my local news",
    "my news",
    "my latest news",
    "the news",
    "todays news",
    "today's news",
    "today news",
    "current news",
    "recent news",
    "news update",
    "news updates",
    "whats the news",
    "what's the news",
    "what is the news",
    "whats my news",
    "what's my news",
    "what is my news",
    "whats my latest news",
    "what's my latest news",
    "what is my latest news",
    "whats the latest news",
    "what's the latest news",
    "what is the latest news",
    "whats in the news",
    "what's in the news",
    "tell me the news",
    "tell me my news",
    "tell me the latest news",
    "tell me today's news",
    "give me the news",
    "give me my news",
    "give me the latest news",
    "show me the news",
    "show the news",
    "show my news",
    "show news",
    "open the news",
    "open news",
    "open the briefing",
    "read the news",
    "read me the news",
    "pull up the news",
    "pull up news",
    "bring up the news",
    "check the news",
    "check my news",
    "get the news",
    "get my news",
    "any news",
    "got any news",
    "news for today",
    "headlines",
    "today's headlines",
    "the headlines",
)

_SHOW_NEWS_RE = re.compile(
    r"\b("
    r"(show|open|bring up|pull up|read|get|check|tell me|give me|what(?:'s|s| is)) "
    r"(me )?(the |my |today(?:'s|s)? |daily |latest |current |recent )?"
    r"(news|headlines|briefing|news briefing|daily news|daily briefing)|"
    r"(my |the |today(?:'s|s)? |daily |latest |current |recent )?(news briefing|daily news|latest news|headlines)|"
    r"news briefing|"
    r"daily news briefing|"
    r"today(?:'s|s)? news briefing|"
    r"latest news|"
    r"local news|"
    r"my local news|"
    r"the local news|"
    r"whats? my local news|"
    r"what is my local news|"
    r"whats? the latest|"
    r"what is the latest|"
    r"my latest news|"
    r"whats? my latest news|"
    r"what is my latest news|"
    r"any news|"
    r"got any news"
    r")\b",
    re.I,
)

_REFRESH_NEWS_RE = re.compile(
    r"\b("
    r"refresh (the |my )?(news|news briefing|briefing|headlines)|"
    r"update (the |my )?(news|news briefing|briefing|headlines)|"
    r"fetch (the |my )?(news|news briefing|briefing|headlines)|"
    r"new news|"
    r"news again"
    r")\b",
    re.I,
)

_NEWS_YES_RE = re.compile(
    r"\b("
    r"yes|yeah|yep|yup|yea|yah|ya|sure|ok|okay|please|"
    r"show it|open it|go ahead|i do|do it|bring it up"
    r")\b",
    re.I,
)

_NEWS_NO_RE = re.compile(
    r"\b("
    r"no|nope|nah|negative|cancel|skip|later|"
    r"not now|not right now|no thanks|don't|do not|"
    r"save (it|for later)|maybe later"
    r")\b",
    re.I,
)


def _normalize(text: str) -> str:
    text = (text or "").strip().lower().replace("'", "")
    text = re.sub(r"\s+", " ", text)
    return text


def is_news_command(text: str) -> bool:
    if not text or not text.strip():
        return False
    from silva.commands.help_phrases import should_yield_to_feature_help

    if should_yield_to_feature_help(text):
        return False
    normalized = _normalize(text)
    if any(phrase.replace("'", "") in normalized for phrase in NEWS_PHRASES):
        return True
    return bool(_SHOW_NEWS_RE.search(text) or _REFRESH_NEWS_RE.search(text))


_OPEN_NEWS_FILE_RE = re.compile(
    r"\b("
    r"(show|open|bring up|pull up) (me )?(the |my )?(news|briefing|news briefing|headlines|file|text file|txt)|"
    r"open (the )?(news |briefing )?(file|text file|txt)|"
    r"show (me )?(the )?(news |briefing )?(file|text file)"
    r")\b",
    re.I,
)


def is_news_refresh_command(text: str) -> bool:
    return bool(_REFRESH_NEWS_RE.search(text or ""))


def is_news_open_file(text: str) -> bool:
    return bool(_OPEN_NEWS_FILE_RE.search(text or ""))


def is_news_yes(text: str) -> bool:
    return bool(_NEWS_YES_RE.search(text or ""))


def is_news_no(text: str) -> bool:
    if is_news_yes(text) and not re.search(r"\b(no|nope|nah|not now|no thanks)\b", text or "", re.I):
        return False
    return bool(_NEWS_NO_RE.search(text or ""))
