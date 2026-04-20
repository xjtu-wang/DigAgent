from __future__ import annotations


def run(
    *,
    tool_context,
    query: str = "",
    cve_id: str = "",
    cwe: str = "",
    product: str = "",
    limit: int = 10,
) -> list[dict[str, object]]:
    matches = tool_context.knowledge_base.search(
        query=query,
        cve_id=cve_id or None,
        cwe=cwe or None,
        product=product or None,
        limit=limit,
    )
    return [item.model_dump(mode="json") for item in matches]
