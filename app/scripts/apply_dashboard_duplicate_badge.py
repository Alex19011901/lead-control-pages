from __future__ import annotations

import argparse
from pathlib import Path


OLD = "function bg(s){return s==='OK'?['ok','Вовремя']:s==='LATE_CRM'?['warn','С опозданием']:s==='ALARM_NO_CRM'?['alarm','Не внесено']:s==='PENDING'?['pending','Ожидает внесения']:['neutral','—']}"
NEW = "function bg(s){return s==='DUPLICATE'?['alarm','ДУБЛЬ']:s==='OK'?['ok','Вовремя']:s==='LATE_CRM'?['warn','С опозданием']:s==='ALARM_NO_CRM'?['alarm','Не внесено']:s==='PENDING'?['pending','Ожидает внесения']:['neutral','—']}"


def apply(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
    if NEW in html:
        return
    if html.count(OLD) != 1:
        raise RuntimeError("dashboard status renderer was not found exactly once")
    path.write_text(html.replace(OLD, NEW, 1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    args = parser.parse_args()
    apply(Path(args.path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
