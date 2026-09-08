from pathlib import Path

snapshot_path = Path("app/scripts/build_dashboard_snapshot.py")
snapshot = snapshot_path.read_text(encoding="utf-8")

old_daily = '''            "event_types": Counter(),
            "channel": Counter(),
'''
new_daily = '''            "event_types": Counter(),
            "event_type_excluded": 0,
            "channel": Counter(),
'''
if snapshot.count(old_daily) != 1:
    raise SystemExit(f"snapshot daily insertion point count={snapshot.count(old_daily)}")
snapshot = snapshot.replace(old_daily, new_daily, 1)

old_count = '''        d["guest_ranges"][guest_key] += 1
        d["event_types"][event_type] += 1
        d["channel"][channel] += 1
'''
new_count = '''        d["guest_ranges"][guest_key] += 1
        # Tilda Veranda does not collect an event type by design. Keep these
        # leads in totals/source/channel/guest statistics, but do not treat a
        # missing type from this source as an unknown event type.
        if source == "Тильда Веранда" and event_type == "unknown":
            d["event_type_excluded"] += 1
        else:
            d["event_types"][event_type] += 1
        d["channel"][channel] += 1
'''
if snapshot.count(old_count) != 1:
    raise SystemExit(f"snapshot counting insertion point count={snapshot.count(old_count)}")
snapshot = snapshot.replace(old_count, new_count, 1)

old_serialize = '''                "guest_ranges": dict(values["guest_ranges"]),
                "event_types": dict(values["event_types"]),
                "channel": dict(values["channel"]),
'''
new_serialize = '''                "guest_ranges": dict(values["guest_ranges"]),
                "event_types": dict(values["event_types"]),
                "event_type_excluded": int(values["event_type_excluded"]),
                "channel": dict(values["channel"]),
'''
if snapshot.count(old_serialize) != 1:
    raise SystemExit(f"snapshot serialization insertion point count={snapshot.count(old_serialize)}")
snapshot = snapshot.replace(old_serialize, new_serialize, 1)
snapshot_path.write_text(snapshot, encoding="utf-8")

view_path = Path("app/scripts/build_dashboard_view.py")
view = view_path.read_text(encoding="utf-8")
old_view = '''        undefined_event_count = max(0, n - defined_event_count)
        if undefined_event_count:
            event["Не определено"] += undefined_event_count
'''
new_view = '''        excluded_event_count = int(item.get("event_type_excluded") or 0)
        undefined_event_count = max(0, n - defined_event_count - excluded_event_count)
        if undefined_event_count:
            event["Не определено"] += undefined_event_count
'''
if view.count(old_view) != 1:
    raise SystemExit(f"view insertion point count={view.count(old_view)}")
view = view.replace(old_view, new_view, 1)
view_path.write_text(view, encoding="utf-8")

view_test_path = Path("app/tests/test_dashboard_view_event_types.py")
view_test = view_test_path.read_text(encoding="utf-8")
view_marker = '''    def test_explicit_unknown_is_counted_as_undefined(self) -> None:
'''
view_addition = '''    def test_excluded_event_type_does_not_become_undefined(self) -> None:
        daily = {
            "2026-08-22": {
                "total": 5,
                "source": {"Тильда Веранда": 2, "Заявки хост": 3},
                "event_types": {"Свадьба": 1, "unknown": 2},
                "event_type_excluded": 2,
            }
        }

        result = module.merge_range(daily, date(2026, 8, 22), date(2026, 8, 22))

        self.assertEqual(result["total"], 5)
        self.assertEqual(result["source"]["Тильда Веранда"], 2)
        self.assertEqual(result["event"], {"Свадьба": 1, "Не определено": 2})

'''
if view_test.count(view_marker) != 1:
    raise SystemExit(f"view test insertion point count={view_test.count(view_marker)}")
view_test = view_test.replace(view_marker, view_addition + view_marker, 1)
view_test_path.write_text(view_test, encoding="utf-8")

snapshot_test_path = Path("app/tests/test_dashboard_snapshot.py")
snapshot_test = snapshot_test_path.read_text(encoding="utf-8")
snapshot_marker = '''    def test_dashboard_rows_use_exact_guest_value_from_text(self) -> None:
'''
snapshot_addition = '''    def test_tilda_veranda_unknown_event_is_excluded_only_from_event_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "leads.json"
            daily_path = root / "dashboard_daily.json"
            view_path = root / "dashboard_view.json"
            input_path.write_text(
                json.dumps(
                    {
                        "leads": [
                            {
                                "received_at": "2026-08-20T12:00:00+03:00",
                                "source": "Тильда Веранда",
                                "category": "TILDA_VERANDA",
                                "status": "OK",
                                "channel": "MAX",
                                "guests": 20,
                            },
                            {
                                "received_at": "2026-08-20T11:00:00+03:00",
                                "source": "Заявки хост",
                                "status": "OK",
                                "channel": "MAX",
                                "guests": 30,
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            build(input_path, daily_path)
            build_view(daily_path, view_path)

            daily = json.loads(daily_path.read_text(encoding="utf-8"))
            view = json.loads(view_path.read_text(encoding="utf-8"))
            day = daily["daily"]["2026-08-20"]
            self.assertEqual(day["total"], 2)
            self.assertEqual(day["source"]["Тильда Веранда"], 1)
            self.assertEqual(day["event_type_excluded"], 1)
            self.assertEqual(day["event_types"], {"unknown": 1})
            self.assertEqual(view["ranges"]["all"]["total"], 2)
            self.assertEqual(view["ranges"]["all"]["source"]["Тильда Веранда"], 1)
            self.assertEqual(view["ranges"]["all"]["event"], {"Не определено": 1})

'''
if snapshot_test.count(snapshot_marker) != 1:
    raise SystemExit(f"snapshot test insertion point count={snapshot_test.count(snapshot_marker)}")
snapshot_test = snapshot_test.replace(snapshot_marker, snapshot_addition + snapshot_marker, 1)
snapshot_test_path.write_text(snapshot_test, encoding="utf-8")
