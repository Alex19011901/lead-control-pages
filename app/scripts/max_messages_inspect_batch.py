from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from pathlib import Path
from typing import Any

from max_message_inspect import _fetch_messages, _sanitize_message


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect selected MAX messages without exposing secrets.")
    parser.add_argument("--chat-id", required=True, type=int)
    parser.add_argument("--message-id", action="append", default=[])
    parser.add_argument("--message-id-file")
    parser.add_argument("--from-ms", required=True, type=int)
    parser.add_argument("--to-ms", required=True, type=int)
    parser.add_argument("--output", default="max-messages-inspect-batch.json")
    parser.add_argument("--ca-file", default="certs/max_ca_bundle.pem")
    parser.add_argument("--count", default=100, type=int)
    args = parser.parse_args()

    token = os.environ.get("MAX_BOT_TOKEN")
    target_ids = _target_ids(args.message_id, args.message_id_file)
    result: dict[str, Any] = {
        "api_ok": True,
        "chat_id": args.chat_id,
        "target_count": len(target_ids),
        "found_count": 0,
        "missing_message_ids": [],
        "messages": [],
        "errors": [],
    }
    if not token:
        result["api_ok"] = False
        result["errors"].append("MAX_BOT_TOKEN is missing")
        _write_result(Path(args.output), result)
        return 1

    remaining = set(target_ids)
    seen_mids: set[str] = set()
    current_from = args.from_ms
    ssl_context = ssl.create_default_context(cafile=args.ca_file)

    try:
        while current_from >= args.to_ms and remaining:
            batch = _fetch_messages(
                token=token,
                chat_id=args.chat_id,
                from_ms=current_from,
                to_ms=args.to_ms,
                count=args.count,
                ssl_context=ssl_context,
            )
            if not batch:
                break

            oldest_timestamp: int | None = None
            new_unique = 0
            for raw in batch:
                body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
                mid = body.get("mid")
                timestamp = raw.get("timestamp") or body.get("timestamp")
                if timestamp is not None:
                    oldest_timestamp = min(int(timestamp), oldest_timestamp) if oldest_timestamp is not None else int(timestamp)
                if not mid or mid in seen_mids:
                    continue
                seen_mids.add(str(mid))
                new_unique += 1
                if str(mid) in remaining:
                    result["messages"].append(_sanitize_message(raw, fallback_chat_id=args.chat_id))
                    remaining.remove(str(mid))

            if oldest_timestamp is None or len(batch) < args.count:
                break
            next_from = oldest_timestamp - 1
            if next_from >= current_from or new_unique == 0:
                break
            current_from = next_from
    except Exception as exc:
        result["api_ok"] = False
        result["errors"].append(str(exc))

    result["messages"].sort(key=lambda item: target_ids.index(str(item.get("message_id"))))
    result["found_count"] = len(result["messages"])
    result["missing_message_ids"] = [mid for mid in target_ids if mid in remaining]
    _write_result(Path(args.output), result)
    return 0 if result["api_ok"] and not remaining else 1


def _target_ids(args_ids: list[str], message_id_file: str | None) -> list[str]:
    values = list(args_ids)
    if message_id_file:
        values.extend(Path(message_id_file).read_text().splitlines())
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in value.replace(",", "\n").splitlines():
            message_id = item.strip()
            if not message_id or message_id in seen:
                continue
            seen.add(message_id)
            result.append(message_id)
    return result


def _write_result(path: Path, result: dict[str, Any]) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
