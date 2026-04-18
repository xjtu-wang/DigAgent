from __future__ import annotations

from typing import Any

from digagent.config import AppSettings, resolve_profile

DEFAULT_SESSION_TITLE = "新会话"
MAX_SESSION_TITLE_CHARS = 20
MIN_SESSION_TITLE_CHARS = 2
TITLE_PROMPT = """你负责为 Web 会话生成中文短标题。

请根据用户的第一条消息生成一个简洁、自然、准确的中文标题。

输出要求：
- 只输出标题本身
- 使用中文
- 不要引号、句号、冒号、换行或 emoji
- 长度控制在 4 到 16 个字符
- 不要原样照抄整句，提炼核心主题

用户第一条消息：
{message}
"""


def is_seed_title(value: str | None) -> bool:
    return not value or value.strip() == DEFAULT_SESSION_TITLE


async def generate_session_title(*, settings: AppSettings, profile_name: str, message: str) -> str:
    from langchain_openai import ChatOpenAI

    profile = resolve_profile(profile_name, settings)
    model = ChatOpenAI(
        model=profile.model or settings.model,
        api_key=settings.openai_api_key,
        base_url=settings.base_url,
        temperature=0,
    )
    response = await model.ainvoke(TITLE_PROMPT.format(message=message))
    return _validate_title(_extract_message_text(response))


def _extract_message_text(response: Any) -> str:
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return str(content).strip()
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(part for part in parts if part).strip()


def _validate_title(title: str) -> str:
    normalized = " ".join(title.split())
    if not normalized:
        raise ValueError("Title model returned empty content.")
    if "\n" in normalized or "\r" in normalized:
        raise ValueError("Title model returned a multiline title.")
    if len(normalized) < MIN_SESSION_TITLE_CHARS or len(normalized) > MAX_SESSION_TITLE_CHARS:
        raise ValueError(f"Title model returned an invalid title length: {len(normalized)}")
    if any(char in normalized for char in {'"', "'", "`", "“", "”", "‘", "’", "。", "！", "？", ":", "："}):
        raise ValueError("Title model returned unsupported punctuation.")
    return normalized
