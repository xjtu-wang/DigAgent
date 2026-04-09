from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False)


def normalize_domain(url_or_domain: str) -> str:
    cleaned = url_or_domain.strip()
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = cleaned.split("/", 1)[0]
    return cleaned.lower()


def action_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def expand_env_text(text: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.environ.get(key, match.group(0))

    return re.sub(r"\$\{([A-Z0-9_]+)\}", replacer, text)

