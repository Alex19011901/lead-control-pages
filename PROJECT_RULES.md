# Lead Control — fixed working rules

1. Work only through the existing project path first: GitHub -> existing workflow -> existing amoCRM integration.
2. Do not switch to new browser/session/plugin/access paths just because one API request fails, unless the user explicitly asks for that.
3. One technical step -> verify -> short report. Do not launch parallel production runs.
4. A successful workflow is not proof that the feature is fixed. Before saying "исправлено", verify the real generated data for the concrete case.
5. On amoCRM/API errors, do not replace previously valid data with empty values.
6. For closed leads, freeze the verified result after the first successful read and reuse it on future refreshes.
7. For "Закрыто и не реализовано — 5 дней", "Последний комментарий" means the last meaningful record strictly before closed_at.
8. If a read source cannot return the record text, keep that state explicit; do not present a dash as if there was no record.
