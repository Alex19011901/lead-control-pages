from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    max_bot_token: str
    amocrm_token: str
    amocrm_domain: str
    telegram_chat_id: int
    max_chat_id: int
    use_data_branch: bool
    data_worktree: Path
    data_dir: Path
    fast_refresh: bool


def load_config() -> Config:
    telegram_token = _required_env("TELEGRAM_BOT_TOKEN")
    max_bot_token = _required_env("MAX_BOT_TOKEN")
    amocrm_token = _required_env("AMOCRM_TOKEN")

    return Config(
        telegram_bot_token=telegram_token,
        max_bot_token=max_bot_token,
        amocrm_token=amocrm_token,
        amocrm_domain=os.environ.get("AMOCRM_DOMAIN", "https://alex1901yaru.amocrm.ru"),
        telegram_chat_id=int(os.environ.get("TELEGRAM_CHAT_ID", "-1001645768111")),
        max_chat_id=int(os.environ.get("MAX_CHAT_ID", "-71704692523093")),
        use_data_branch=os.environ.get("LEAD_CONTROL_USE_DATA_BRANCH") == "1",
        data_worktree=Path(os.environ.get("LEAD_CONTROL_DATA_WORKTREE", "../lead-control-data")),
        data_dir=Path(os.environ.get("LEAD_CONTROL_DATA_DIR", "data")),
        fast_refresh=os.environ.get("LEAD_CONTROL_FAST_REFRESH") == "1",
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
