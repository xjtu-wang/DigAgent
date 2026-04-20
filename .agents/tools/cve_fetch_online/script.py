from __future__ import annotations


async def run(
    *,
    tool_context,
    query: str = "",
    cve_id: str = "",
    cwe: str = "",
    product: str = "",
    kev_only: bool = False,
    limit: int = 10,
    modified_within_days: int | None = None,
    published_within_days: int | None = None,
    include_history: bool = False,
) -> dict[str, object]:
    return await tool_context.cve_service.fetch_online(
        query=query,
        cve_id=cve_id or None,
        cwe=cwe or None,
        product=product or None,
        kev_only=kev_only,
        limit=limit,
        modified_within_days=modified_within_days,
        published_within_days=published_within_days,
        include_history=include_history,
    )
