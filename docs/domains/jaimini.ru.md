# Джаймини Core v1 — эксплуатационный контракт

Естественный запрос направляется в read-only MCP-инструмент `jaimini`. Нужны приватный профиль
или полные данные человека, `jaimini_core_v1`, дата отсчёта и пол для Chara Dasha. В обычном
ответе скрыты fact paths, rule IDs, hashes, traces и artifact tokens.

## Матрица точности

| Время рождения | Поведение |
|---|---|
| exact | Один подписанный расчёт. |
| approximate | Явный диапазон с шагом 5 минут, максимум 120 минут/25 точек; нестабильные факты отмечаются. |
| unknown | Не поддерживается: сначала нужен ограниченный диапазон. |

Включены 7/8 карак, rāśi dṛṣṭi, A1–A12/AL/UL, геометрия argalā, svāṁśa/karakāṁśa,
BL/HL/GL, связи по обеим схемам и одна замороженная Chara Dasha. Другие rāśi-daśā и
prediction prose исключены.

## Текущее состояние, Limits и Errors

Доступны вычисленные и подписанные факты, timing и checker. Доктринальная интерпретация
**unavailable**: нет допущенного source pack, qualified human review и adjudicated cases.
Это воспроизводимый расчёт, а не доказательство доктринальной истинности или пользы. Payload
меньше 512 KiB; максимум 12 mahā и 144 antar. Точная ничья требует adjudication; для
approximate возможен rescue `provide_birth_range`.

## Privacy и Inspection

ResearchRun, API/Pi-запись и persistence не создаются. Технический Inspection включается только
явно через `include_trace=true`. Влияние на migration/backup отсутствует: вертикаль stateless.
