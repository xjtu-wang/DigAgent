from __future__ import annotations


def run(*, tool_context, manifest, command: str, timeout: int | None = None) -> dict[str, object]:
    return tool_context.run_shell(manifest, command, timeout=timeout)
