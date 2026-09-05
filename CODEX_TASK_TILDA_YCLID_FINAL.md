# CODEX TASK — Tilda YCLID end-to-end fix

Work autonomously to FINAL RESULT. Do not stop after diagnostics. Inspect existing implementation first, identify root cause, implement the minimal safe fix, test it, push it, run/verify diagnostics as possible, and report exact final status.

## Known facts
- Lead Control production repo: Alex19011901/lead-control-pages.
- Counter: 112267492.
- Test lead submitted 2026-09-05 around 14:53:52 MSK, name Test, phone 79265350168, guests 11.
- Production Lead Control run #162 / run id 33964597026 successfully received exactly one new Telegram event and stored the Test lead.
- Existing parser unit test `test_tilda_yclid_is_parsed_from_telegram_message` passes.
- Therefore parser supports YCLID if Telegram message contains it.
- The real Test lead does NOT contain expected marker/YCLID in the stored Lead Control event.
- Previous diagnostics established that historical Metrika `ym:s:startURL` does not expose yclid for this counter/period, so do NOT loop back to historical startURL matching.
- User explicitly wants prospective/current flow working, not historical recovery.

## Hard safety constraints
1. Inspect the whole current chain and existing code before changing anything. Do not guess.
2. Do not change Lead Control dashboard design or unrelated lead-processing logic.
3. Do not change amoCRM entities/data.
4. Do not use Direct API.
5. No offline conversion uploads.
6. Yandex Metrika Logs export may be used read-only/stateful-read only; no analytical/ad entity mutations.
7. Do not add another duplicate site script if an existing mechanism can be corrected.
8. Preserve all existing site/form behavior.
9. Minimal change only after root cause is demonstrated from current code/config/evidence.

## Goal
For NEW Tilda leads from now on, the actual YCLID from the landing URL must travel end-to-end into the Telegram form message (or another already-consumed Lead Control field), be parsed by Lead Control, and become available for subsequent Metrika/Direct attribution. No historical backfill is required.

## Required investigation
- Search repo history/current files/tests/diagnostics for every existing YCLID/Tilda implementation and document what is already present.
- Determine exactly where YCLID is currently captured, persisted, injected into Tilda forms, sent to Telegram, and parsed.
- Check for multiple Tilda forms/popups/pages and whether the current script attaches only to some form, runs too early/late, loses value on popup/dynamic form creation, uses wrong field name, or is overwritten.
- Inspect any browser/site diagnostic evidence already committed. If repository does not contain the Tilda page source/config, state exactly what can and cannot be changed from GitHub, but still finish every repo-side change/test that is justified.
- Specifically explain why the synthetic/parser test passes while the real Test submission lacks YCLID.

## Implementation requirement
Once root cause is proven, implement the smallest robust prospective fix. It must support dynamically rendered Tilda forms/popups if those are in use, preserve YCLID across navigation/form opening as appropriate, and avoid duplicate scripts/listeners/fields. Never fabricate a YCLID.

## Tests
Add/adjust tests that reproduce the real failure mode, not merely a synthetic Telegram message containing YCLID. Tests should cover capture -> persistence -> form payload/message boundary as far as repository code permits, plus parser compatibility. Run all relevant tests.

## Final verification
Verify the complete chain as far as tooling permits. If a real new browser submission is strictly required for the final external proof, do not call the implementation unfinished: report implementation/test status separately and provide ONE exact final user action (the submission) and what observable value must appear afterward. Do not ask for repeated exploratory tests.

## Final report format
ROOT_CAUSE:
EXISTING_SITE_YCLID_IMPLEMENTATION:
WHY_REAL_TEST_FAILED:
CHANGED_FILES:
TESTS:
PUSH:
PRODUCTION_CHANGED:
END_TO_END_STATUS:
ONLY_REMAINING_USER_ACTION: (NONE if fully proven; otherwise exactly one concrete action)

Do not stop at intermediate findings. Continue until final implementation/test result or a genuinely external-only blocker is reached.