from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


_DEFAULT_BLOCK_PATTERNS: Sequence[str] = (
    # generic jailbreak / instruction override
    r"ignore\s+(all|previous|prior)\s+instructions",
    r"ignore.*(all|previous|prior).*instructions",
    r"system\s+prompt",
    r"developer\s+message",
    r"you\s+are\s+chatgpt",
    r"jailbreak",
    r"do\s+anything\s+now",
    # trading-specific malicious phrasing
    r"execute\s+order",
    r"open\s+new\s+positions?\s+now",
    r"disable\s+risk",
    r"bypass\s+risk",
    r"忽略.*風控",
    r"立刻.*下單",
    r"系統指令",
    # tool / code injection
    r"```[\s\S]*```",  # code blocks are too often instruction-carriers
    r"<script[\s\S]*?>[\s\S]*?</script>",
)


@dataclass(frozen=True)
class PromptGuardResult:
    safe: bool
    sanitized_text: str
    reason: str = ""
    matched_patterns: List[str] | None = None


_TAG_STRIP_PATTERNS: Sequence[tuple[str, int]] = (
    # Common bracketed wrappers that often carry meta-instructions.
    (r"(?:(?<=\s)|^)\[[^\]]*(system|系統)\s*(prompt|指令)[^\]]*\](?=\s|$)", re.IGNORECASE),
    (r"\[[^\]]*(developer|開發者)[^\]]*\]", re.IGNORECASE),
    # XML-like wrappers.
    (r"<(system|developer)[^>]*>", re.IGNORECASE),
    (r"</(system|developer)>", re.IGNORECASE),
)


def _strip_instruction_like_wrappers(text: str) -> str:
    out = text
    for pat, flags in _TAG_STRIP_PATTERNS:
        out = re.sub(pat, "", out, flags=flags)
    return out.strip()


def sanitize_external_text(
    raw_text: str,
    *,
    max_chars: int = 10_000,
    block_patterns: Optional[Iterable[str]] = None,
) -> PromptGuardResult:
    """Basic prompt-injection defense for untrusted external text.

    Strategy (P1):
    - strip obvious wrapper tags first (so harmless quoted tags don't hard-block)
    - hard-block common jailbreak / instruction patterns
    - clamp length

    Callers should treat blocked results as "do not call LLM".
    """

    text = (raw_text or "").strip()
    if not text:
        return PromptGuardResult(False, "", "EMPTY_INPUT", [])

    if len(text) > max_chars:
        text = text[:max_chars]

    # Strip wrapper tags BEFORE scanning.
    sanitized = _strip_instruction_like_wrappers(text)
    if not sanitized:
        return PromptGuardResult(False, "", "EMPTY_AFTER_SANITIZE", [])

    patterns = list(block_patterns or _DEFAULT_BLOCK_PATTERNS)
    lowered = sanitized.lower()

    hits: List[str] = []
    for p in patterns:
        if re.search(p, lowered, flags=re.IGNORECASE):
            hits.append(p)

    if hits:
        return PromptGuardResult(False, sanitized, "PROMPT_INJECTION_SUSPECTED", hits)

    return PromptGuardResult(True, sanitized, "OK", [])


def enforce_tool_whitelist(tool_calls: list[dict] | None, *, allowed: Iterable[str]) -> bool:
    """Return True if all tool calls are allowed.

    For P1 we only enforce a name-based allowlist.
    """

    if not tool_calls:
        return True
    allowed_set = {str(a) for a in allowed}
    for tc in tool_calls:
        name = str(tc.get("name") or tc.get("tool") or "")
        if name not in allowed_set:
            return False
    return True
