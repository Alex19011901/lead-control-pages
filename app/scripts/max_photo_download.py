from __future__ import annotations

import argparse
import json
import mimetypes
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


MAX_API_BASE_URL = "https://platform-api2.max.ru"
MAX_MEDIA_HOST_SUFFIXES = (".max.ru", ".oneme.ru", ".okcdn.ru")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download one MAX image attachment without exposing secrets.")
    parser.add_argument("--chat-id", required=True, type=int)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--photo-id", required=True)
    parser.add_argument("--from-ms", required=True, type=int)
    parser.add_argument("--to-ms", required=True, type=int)
    parser.add_argument("--output-dir", default="max-photo-download")
    parser.add_argument("--ca-file", default="certs/max_ca_bundle.pem")
    parser.add_argument("--count", default=100, type=int)
    args = parser.parse_args()

    token = os.environ.get("MAX_BOT_TOKEN")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "api_ok": True,
        "message_id_requested": args.message_id,
        "photo_id_requested": args.photo_id,
        "message_found": False,
        "photo_found": False,
        "downloaded": False,
        "file_name": None,
        "content_type": None,
        "source_message_id": None,
        "errors": [],
    }

    if not token:
        metadata["api_ok"] = False
        metadata["errors"].append("MAX_BOT_TOKEN is missing")
        _write_metadata(output_dir, metadata)
        return 1

    max_context = ssl.create_default_context(cafile=args.ca_file)
    default_context = ssl.create_default_context()

    try:
        message = _fetch_message_by_id(token, args.message_id, max_context)
        attachment = _find_photo_attachment(message, args.photo_id) if message else None
        if message:
            metadata["message_found"] = True
            metadata["source_message_id"] = _message_id(message)

        if attachment is None:
            message, attachment = _find_photo_in_history(
                token=token,
                chat_id=args.chat_id,
                photo_id=args.photo_id,
                from_ms=args.from_ms,
                to_ms=args.to_ms,
                count=args.count,
                ssl_context=max_context,
            )
            if message:
                metadata["message_found"] = True
                metadata["source_message_id"] = _message_id(message)

        if attachment is None:
            metadata["errors"].append("Photo attachment was not found")
            _write_metadata(output_dir, metadata)
            return 1

        metadata["photo_found"] = True
        url_candidates = _find_urls(attachment)
        if not url_candidates:
            metadata["errors"].append("Photo attachment does not contain downloadable URL")
            _write_metadata(output_dir, metadata)
            return 1

        downloaded = _download_first_image(
            urls=url_candidates,
            output_dir=output_dir,
            photo_id=args.photo_id,
            token=token,
            default_context=default_context,
            max_context=max_context,
        )
        if downloaded is None:
            metadata["errors"].append("Download failed for all URL candidates")
            _write_metadata(output_dir, metadata)
            return 1

        metadata.update(downloaded)
        metadata["downloaded"] = True
        _write_metadata(output_dir, metadata)
        return 0
    except Exception as exc:
        metadata["api_ok"] = False
        metadata["errors"].append(str(exc))
        _write_metadata(output_dir, metadata)
        return 1


def _fetch_message_by_id(token: str, message_id: str, ssl_context: ssl.SSLContext) -> dict[str, Any] | None:
    params = {"message_ids": message_id}
    body = _request_json(token, "/messages", params, ssl_context)
    messages = _extract_messages(body)
    if isinstance(messages, list) and messages:
        return messages[0] if isinstance(messages[0], dict) else None
    if isinstance(body, dict) and _message_id(body) == message_id:
        return body
    return None


def _find_photo_in_history(
    *,
    token: str,
    chat_id: int,
    photo_id: str,
    from_ms: int,
    to_ms: int,
    count: int,
    ssl_context: ssl.SSLContext,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    current_from = from_ms
    seen_mids: set[str] = set()
    while current_from >= to_ms:
        params = {"chat_id": chat_id, "from": current_from, "to": to_ms, "count": count}
        body = _request_json(token, "/messages", params, ssl_context)
        batch = _extract_messages(body)
        if not isinstance(batch, list) or not batch:
            break

        oldest_timestamp: int | None = None
        new_unique = 0
        for raw in batch:
            if not isinstance(raw, dict):
                continue
            body_obj = _dict(raw.get("body"))
            mid = body_obj.get("mid")
            timestamp = raw.get("timestamp") or body_obj.get("timestamp")
            if timestamp is not None:
                oldest_timestamp = min(int(timestamp), oldest_timestamp) if oldest_timestamp is not None else int(timestamp)
            if mid and mid in seen_mids:
                continue
            if mid:
                seen_mids.add(str(mid))
                new_unique += 1
            attachment = _find_photo_attachment(raw, photo_id)
            if attachment is not None:
                return raw, attachment

        if oldest_timestamp is None or len(batch) < count:
            break
        next_from = oldest_timestamp - 1
        if next_from >= current_from or new_unique == 0:
            break
        current_from = next_from

    return None, None


def _request_json(
    token: str,
    path: str,
    params: dict[str, str | int],
    ssl_context: ssl.SSLContext,
) -> Any:
    query = "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        MAX_API_BASE_URL + path + query,
        headers={"Accept": "application/json", "Authorization": token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30, context=ssl_context) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"MAX {path} failed: HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MAX {path} failed: {exc.reason}") from None
    except json.JSONDecodeError:
        raise RuntimeError(f"MAX {path} failed: invalid JSON response") from None


def _extract_messages(body: Any) -> Any:
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return None
    for key in ("messages", "items", "result"):
        value = body.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_messages(value)
            if isinstance(nested, list):
                return nested
    message = body.get("message")
    if isinstance(message, dict):
        return [message]
    return None


def _find_photo_attachment(message: dict[str, Any] | None, photo_id: str) -> dict[str, Any] | None:
    if not message:
        return None
    attachments = _attachments(message)
    for attachment in attachments:
        if _contains_value(attachment, photo_id):
            return attachment
    return None


def _attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    body = _dict(message.get("body"))
    attachments = message.get("attachments") or body.get("attachments") or []
    if not isinstance(attachments, list):
        return []
    return [item for item in attachments if isinstance(item, dict)]


def _contains_value(value: Any, expected: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_value(item, expected) for item in value)
    return str(value) == expected


def _find_urls(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            result.extend(_find_urls(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_find_urls(item))
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        result.append(value)
    return _dedupe(result)


def _download_first_image(
    *,
    urls: list[str],
    output_dir: Path,
    photo_id: str,
    token: str,
    default_context: ssl.SSLContext,
    max_context: ssl.SSLContext,
) -> dict[str, Any] | None:
    for url in urls:
        for context in (default_context, max_context):
            for use_auth in (False, _is_max_media_host(url)):
                response = _download_url(url, token if use_auth else None, context)
                if response is None:
                    continue
                body, content_type = response
                if not _looks_like_image(body, content_type):
                    continue
                extension = _image_extension(content_type, body)
                file_name = f"max-photo-{photo_id}{extension}"
                (output_dir / file_name).write_bytes(body)
                return {"file_name": file_name, "content_type": content_type}
    return None


def _download_url(url: str, token: str | None, ssl_context: ssl.SSLContext) -> tuple[bytes, str] | None:
    headers = {"Accept": "image/*,*/*;q=0.8"}
    if token:
        headers["Authorization"] = token
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60, context=ssl_context) as response:
            body = response.read(60 * 1024 * 1024)
            content_type = response.headers.get("Content-Type", "").split(";", maxsplit=1)[0].strip().lower()
            return body, content_type
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ssl.SSLError):
        return None


def _looks_like_image(body: bytes, content_type: str) -> bool:
    if content_type.startswith("image/"):
        return True
    signatures = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*")
    return any(body.startswith(signature) for signature in signatures)


def _image_extension(content_type: str, body: bytes) -> str:
    guessed = mimetypes.guess_extension(content_type) if content_type else None
    if guessed:
        return ".jpg" if guessed == ".jpe" else guessed
    if body.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    return ".img"


def _is_max_media_host(url: str) -> bool:
    hostname = urllib.parse.urlparse(url).hostname or ""
    return any(hostname == suffix.lstrip(".") or hostname.endswith(suffix) for suffix in MAX_MEDIA_HOST_SUFFIXES)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _message_id(message: dict[str, Any]) -> Any:
    body = _dict(message.get("body"))
    return body.get("mid") or message.get("message_id")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _write_metadata(output_dir: Path, metadata: dict[str, Any]) -> None:
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
