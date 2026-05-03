from __future__ import annotations


def run(*, tool_context, manifest, code: str, timeout: int | None = None) -> dict[str, object]:
    return tool_context.run_python(manifest, code, timeout=timeout)
