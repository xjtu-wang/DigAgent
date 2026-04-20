from __future__ import annotations


def _network_payload(
    title: str,
    summary: str,
    raw_output: str,
    facts: list[dict[str, object]],
    source: dict[str, object],
) -> dict[str, object]:
    return {
        "title": title,
        "summary": summary,
        "raw_output": raw_output,
        "facts": facts,
        "source": source,
    }


async def run(*, tool_context, url: str, method: str = "GET") -> dict[str, object]:
    tool_context.ensure_url_allowed(url)
    title, summary, raw, facts, source, _, _ = await tool_context.network.web_fetch({"url": url, "method": method})
    return _network_payload(title, summary, raw, facts, source)
