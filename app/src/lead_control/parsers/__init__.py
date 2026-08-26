from __future__ import annotations

from typing import Any

from .mail import parse_mail_message
from .marquiz import parse_marquiz_message
from .tilda import parse_tilda_message


def parse_message(message: dict[str, Any]) -> dict[str, Any] | None:
    return parse_mail_message(message) or parse_marquiz_message(message) or parse_tilda_message(message)
