#!/usr/bin/env python3
import base64
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PC = ROOT / "price-control"
HISTORY = PC / "history"
PARTS = PC / "history-parts"

def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def load_gzip_b64(paths):
    text = "".join(Path(p).read_text(encoding="utf-8").strip() for p in paths)
    raw = gzip.decompress(base64.b64decode(text))
    return json.loads(raw.decode("utf-8"))

def normalize_hist(src, *, key, label, start, end, price_date):
    rows_data = src["rowsData"]
    out = {
        "key": key,
        "label": label,
        "supplier": "Парадис Экзотика",
        "start": start,
        "end": end,
        "docs": int(src["docs"]),
        "rows": len(rows_data),
        "above": int(src["above"]),
        "below": int(src["below"]),
        "equal": int(src.get("equal", 0)),
        "unmatched": int(src["unmatched"]),
        "overpay": float(src["overpay"]),
        "priceDocumentDate": price_date,
        "indexGroup": "paradis",
        "rowsData": rows_data,
    }
    assert out["rows"] == out["above"] + out["below"] + out["equal"] + out["unmatched"]
    return out

p2606 = load_gzip_b64([
    PARTS / "hist_2606_0207.v2.b64.00",
    PARTS / "hist_2606_0207.v2.b64.01",
    PARTS / "hist_2606_0207.v2.b64.02",
    PARTS / "hist_2606_0207.v2.b64.03",
])
p2407 = load_gzip_b64([PARTS / "hist_2407_2907.json.gz.b64"])
p3007 = load_gzip_b64([PARTS / "hist_3007_0508.json.gz.b64"])
interfood = load_json(HISTORY / "interfood_20260520.json")
current_payload = load_json(PC / "current.json")
current = current_payload["week"]

p2606 = normalize_hist(
    p2606, key="2026-06-26", label="Прайс 26.06 → 02.07",
    start="26.06.2026", end="02.07.2026", price_date="25.06.2026",
)
p2407 = normalize_hist(
    p2407, key="2026-07-24", label="Прайс 24.07 → 29.07",
    start="24.07.2026", end="29.07.2026", price_date="22.07.2026",
)
p3007 = normalize_hist(
    p3007, key="2026-07-30", label="Прайс 30.07 → 05.08",
    start="30.07.2026", end="05.08.2026", price_date="30.07.2026",
)

expected = {
    "2026-06-26": (13, 216, 149, 38, 0, 29, 8531.74),
    "2026-07-24": (7, 199, 161, 31, 0, 7, 17953.72),
    "2026-07-30": (7, 189, 172, 11, 0, 6, 12514.78),
    "2026-05-20": (13, 305, 20, 0, 269, 16, 1676.33),
    "2026-08-26": (2, 32, 25, 7, 0, 0, 731.68),
}
periods = [current, p3007, p2407, p2606, interfood]
for p in periods:
    got = (
        int(p["docs"]), int(p["rows"]), int(p["above"]), int(p["below"]),
        int(p.get("equal", 0)), int(p["unmatched"]), round(float(p["overpay"]), 2),
    )
    want = expected[p["key"]]
    assert got == want, (p["key"], got, want)
    assert len(p["rowsData"]) == p["rows"], (p["key"], len(p["rowsData"]), p["rows"])

full = {
    "generatedAt": current_payload["generatedAt"],
    "currentKey": current["key"],
    "periods": periods,
    "indexGroups": {
        "paradis": {
            "supplier": "Парадис Экзотика",
            "baseKey": "2026-06-26",
            "baseLabel": "26.06–02.07",
            "points": [
                {"key": "2026-06-26", "label": "26.06–02.07", "value": 100.0},
                {"key": "2026-07-24", "label": "24.07–29.07", "value": 98.5},
                {"key": "2026-07-30", "label": "30.07–05.08", "value": 101.2},
                {"key": "2026-08-26", "label": "26.08–01.09", "value": 108.9},
            ],
            "current": 108.9,
            "prevChange": 7.6,
            "periodChange": 8.9,
        },
        "interfood": {
            "supplier": "Интерфуд",
            "baseKey": "2026-05-20",
            "baseLabel": "20.05–26.05",
            "points": [
                {"key": "2026-05-20", "label": "20.05–26.05", "value": 100.0}
            ],
            "current": 100.0,
            "prevChange": None,
            "periodChange": 0.0,
        },
    },
}

HISTORY.mkdir(parents=True, exist_ok=True)
for path, data in [
    (HISTORY / "paradis_20260626.json", p2606),
    (HISTORY / "paradis_20260724.json", p2407),
    (HISTORY / "paradis_20260730.json", p3007),
    (PC / "full.json", full),
]:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("FULL_DATA_OK", json.dumps({
    "generatedAt": full["generatedAt"],
    "currentKey": full["currentKey"],
    "periods": [
        {
            "key": p["key"], "docs": p["docs"], "rows": p["rows"],
            "above": p["above"], "below": p["below"],
            "equal": p.get("equal", 0), "unmatched": p["unmatched"],
            "overpay": p["overpay"],
        } for p in periods
    ],
    "paradisIndex": full["indexGroups"]["paradis"],
}, ensure_ascii=False))
