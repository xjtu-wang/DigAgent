from __future__ import annotations


def run(
    *,
    tool_context,
    query: str = "",
    cve_id: str = "",
    cwe: str = "",
    product: str = "",
    kev_only: bool = False,
    limit: int = 10,
) -> list[dict[str, object]]:
    matches = tool_context.cve_service.search_local(
        query=query,
        cve_id=cve_id or None,
        cwe=cwe or None,
        product=product or None,
        kev_only=kev_only,
        limit=limit,
    )
    return [item.model_dump(mode="json") for item in matches]
