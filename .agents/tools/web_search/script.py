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


async def run(*, tool_context, query: str, limit: int = 5) -> dict[str, object]:
    tool_context.ensure_search_query_allowed(query)
    title, summary, raw, facts, source, _, _ = await tool_context.network.web_search({"query": query, "limit": limit})
    return _network_payload(title, summary, raw, facts, source)
