from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class TelegramClient:
    def __init__(self, token: str) -> None:
        self._token = token

    def get_updates(
        self,
        offset: int | None,
        limit: int = 100,
        timeout: int = 0,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
            "allowed_updates": ["message", "message_reaction"],
        }
        if offset is not None:
            payload["offset"] = int(offset)

        url = f"https://api.telegram.org/bot{self._token}/getUpdates"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Telegram getUpdates failed: HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Telegram getUpdates failed: {exc.reason}") from None
        except json.JSONDecodeError:
            raise RuntimeError("Telegram getUpdates failed: invalid JSON response") from None

        if not body.get("ok"):
            raise RuntimeError("Telegram getUpdates failed: API returned ok=false")

        result = body.get("result")
        if not isinstance(result, list):
            raise RuntimeError("Telegram getUpdates failed: result is not a list")
        return result

