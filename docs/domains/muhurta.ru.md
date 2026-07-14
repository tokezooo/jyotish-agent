# Мухурта focused-work v1 — эксплуатационный контракт

Read-only `muhurta` принимает `general` или `focused_work_session_v1`, региональную IANA-зону,
точные aware start/exclusive end, длительность 15–480 минут, hard constraints и preferences.
Без end используются семь локальных гражданских дней. Записи в календарь нет.

## Матрица точности

| Ввод | Поведение |
|---|---|
| exact диапазон | Подписанный boundary-driven search. |
| approximate пожелание | Только preferences; точный anchor поиска не меняется. |
| unknown end | Детерминированные 7 civil days; максимум 31 день. |

Включены sunrise/sunset, tithi, nakshatra, yoga, karana, lagna и дневные boundary facts,
half-open intervals, явные daylight/time/weekday exclusions, calendar-ready candidates и near misses.
Marriage/medical/contract, planetary-change requests, doctrine eligibility/ranking, tāra-bala и
candra-bala исключены.

## Текущее состояние, Limits и Errors

Boundary facts и фильтрация явных ограничений доступны. Ranking и interpretation **unavailable**
до source pack, qualified review и adjudications. Defaults 5/5, maxima 20/20, 31 days, 5000
candidates, 512 KiB. No-window — успешный пустой результат; oversized range нужно сузить;
cancellation/deadline даёт incomplete; high-stakes activity unsupported.

## Privacy и Inspection

Метрики не получают profile, coordinates, times, place labels или traces. ResearchRun/persistence,
REST/Pi и side effects отсутствуют. Inspection только `include_trace=true`. Migration/backup: none.
