from __future__ import annotations


async def run(
    *,
    tool_context,
    max_records: int | None = None,
    start_index: int = 0,
    page_size: int = 2000,
) -> dict[str, object]:
    state = await tool_context.cve_service.sync_sources(
        max_records=max_records,
        start_index=start_index,
        page_size=page_size,
    )
    return state.model_dump(mode="json")
