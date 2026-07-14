# Прашна work/project v1 — эксплуатационный контракт

Read-only инструмент `prashna` поддерживает один низкорисковый вопрос о статусе/препятствии
рабочего проекта. Передайте explicit RFC3339 момент и региональную IANA-зону либо `capture_now`
с местом и idempotency key. «Сейчас» захватывается один раз. Уточнение переиспользует opaque
token; новый по существу вопрос создаёт новый anchor.

## Матрица точности

| Время | Поведение |
|---|---|
| exact / explicit | Offset, IANA zone и fold должны дать один момент. |
| approximate | Не является режимом Прашны; подтвердите один operational moment. |
| unknown / «сейчас» | `capture_now` запечатывает одно чтение часов и возвращает summary. |

Включены D1 time-chart, panchanga, lagna/Moon/lords, dṛṣṭi, work-router, readability traces,
sealed replay, signed artifact и checker. KP-249/108, Nāḍi, applying/separating judgement,
composite и high-stakes prediction исключены.

## Текущее состояние, Limits и Errors

Факты и anchor lifecycle доступны; доктринальное суждение **unavailable** до source mapping,
reviewer и adjudication. Максимум 100 rules и 512 KiB. `ANCHOR_MISMATCH` требует новый anchor,
`ANCHOR_STALE` — повторный захват; unsupported/composite — один главный вопрос; high-stakes —
обращение к профильному специалисту.

## Privacy и Inspection

Token не раскрывает вопрос, координаты или место. ResearchRun/persistence отсутствуют.
Inspection только по `include_trace=true`. Migration/backup impact: none; cache process-local.
