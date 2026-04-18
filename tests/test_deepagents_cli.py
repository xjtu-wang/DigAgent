from __future__ import annotations

import subprocess
from pathlib import Path

from tests.live_helpers import build_live_settings, cli_env


def test_deepagents_cli_chat_task_reads_probe_file(tmp_path: Path, repo_root: Path) -> None:
    settings, token = build_live_settings(tmp_path, repo_root)
    result = subprocess.run(
        [
            str(repo_root / ".venv" / "bin" / "python"),
            "-m",
            "digagent.cli",
            "chat",
            "--task",
            "读取工作区根目录的 probe.txt，并且只回复其中的完整 token，不要附加任何其他文字。",
            "--auto-approve",
        ],
        cwd=repo_root,
        env=cli_env(settings),
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert token in result.stdout
