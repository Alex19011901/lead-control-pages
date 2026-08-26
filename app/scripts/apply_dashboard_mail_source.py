from __future__ import annotations

import argparse
import json
from pathlib import Path

MAIL_SOURCE = "ЗАЯВКА ПОЧТА"
LEGACY = "Заявка почта"


def apply(view_path: Path) -> None:
    view = json.loads(view_path.read_text(encoding="utf-8"))
    for bucket in (view.get("ranges") or {}).values():
        sources = bucket.get("source") or bucket.get("src") or {}
        if LEGACY in sources:
            sources[MAIL_SOURCE] = int(sources.get(MAIL_SOURCE) or 0) + int(sources.pop(LEGACY) or 0)
    for key in ("latest", "not_entered", "feedback"):
        for row in view.get(key) or []:
            if str(row.get("source") or "").casefold() == LEGACY.casefold():
                row["source"] = MAIL_SOURCE
    view_path.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--view", required=True)
    args = parser.parse_args()
    apply(Path(args.view))


if __name__ == "__main__":
    main()
