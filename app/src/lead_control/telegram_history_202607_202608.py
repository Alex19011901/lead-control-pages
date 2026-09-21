from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path


# Full Telegram export "Заявки с САЙТА" supplied on 2026-08-22.
# Contains 122 unambiguous historical leads after applying the standing
# Cebikova/Tatiana Telegram exclusion. Message 5666 is restored separately
# through manual_history.py using the user's earlier persisted TG_LEAD decision.
# Message 5670 remains an explicit one-off skip.


def load_history() -> list[dict]:
    root = Path(__file__).resolve().parent
    encoded = "".join(
        (root / filename).read_text(encoding="ascii")
        for filename in (
            "telegram_history_payload_1.txt",
            "telegram_history_payload_2.txt",
            "telegram_history_payload_3.txt",
            "telegram_history_payload_4a.txt",
            "telegram_history_payload_4b.txt",
        )
    )
    raw = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
    return json.loads(raw)
