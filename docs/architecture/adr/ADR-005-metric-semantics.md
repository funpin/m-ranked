# ADR-005: Единая семантика метрик и наблюдений

- Status: **Proposed**
- Date: 2026-09-02
- Owners: data / analytics / product
- Related: [target ERD](../erd/target-postgresql.puml),
  [formula engine](../c4/09-code-formula-engine.puml)

## Context

Telegram, VK, MAX и Rutube публикуют разные наборы счетчиков с различной
точностью и надежностью. Текущий код местами хранит рассчитанные delta рядом с
raw counter, допускает synthetic baseline, использует текущий subscriber count
без истории и имеет отдельно реализованные правила Telegram/generic platforms.

Без общего определения `0`, `NULL`, времени наблюдения, baseline, cohort и
completeness два визуально одинаковых графика могут иметь разный смысл. Формула
рейтинга не воспроизводима, если ее input semantics изменились без версии.

## Decision

### Наблюдение, а не событие

`publication_metric_snapshot` фиксирует опубликованное платформой состояние
накопительного счетчика в `observed_at`. Оно не утверждает, когда и кем были
созданы отдельные просмотры или реакции.

Основные времена:

- `published_at` — время публикации по источнику;
- `observed_at` — момент, к которому относится считанное состояние;
- `collected_at` — техническое время получения payload, хранится в lineage/run;
- `as_of` — отсечка воспроизводимого расчета.

Все моменты — UTC `timestamptz`.

### NULL и zero

- `0` — источник успешно измерил нулевое значение.
- `NULL` — метрика отсутствует, не поддерживается, не прочитана или признана
  непригодной.
- UI показывает `NULL` как «нет данных/не поддерживается», а не `0`.
- Нельзя включать `NULL` в сумму, среднее или медиану как zero без явно
  versioned missing-value policy.
- Переход ранее положительного монотонного счетчика в `0` не исправляется молча:
  значение становится `NULL` с quality flag `suspected_reset`, raw provenance
  сохраняется на срок raw retention.
- Настоящее снижение счетчика хранится, если платформа допускает удаление
  реакций/просмотров; delta будет отрицательной и получит semantic flag.

### Canonical metric keys

| Key | Смысл | Unit | Примечание |
|---|---|---|---|
| `views` | Опубликованный счетчик просмотров/показов платформы | count | Межплатформенная эквивалентность не предполагается |
| `reactions` | Общий доступный reaction/like counter | count | Reaction breakdown хранится отдельно |
| `comments` | Доступный счетчик комментариев | count | `NULL`, если источник не предоставляет |
| `shares` | Доступный счетчик repost/share | count | Не подменять количеством ссылок |
| `subscribers` | Опубликованный размер аудитории аккаунта | count | Exact и rounded имеют разное quality |
| `interactions` | Производная сумма поддерживаемых reactions+comments+shares | count | Состав и platform capability входят в definition version |

Названия платформы остаются в presentation layer; формула использует canonical
key вместе с platform, capability и semantic version.

### Delta и rate

Delta вычисляется при чтении/агрегации из двух сохраненных snapshots:

```text
delta = current.value - previous.value
rate_per_hour = delta / elapsed_seconds * 3600
```

Она валидна только если:

- это одна публикация и одна canonical metric;
- обе точки не `NULL` и проходят minimum quality;
- порядок `observed_at` определен;
- интервал не пересекает semantic/capability change;
- формула явно принимает отрицательные delta или исключает их с warning.

Предрассчитанная delta может храниться только как rebuildable projection, а не
как первичный факт.

### Baseline и completeness

- Baseline `0` в момент публикации допускается только когда первая реальная
  точка получена внутри `complete_history_max_first_age` и source semantics
  позволяют считать счетчик начинающимся с нуля.
- Synthetic baseline всегда помечается и не выдается за измерение.
- Поздно найденная публикация имеет incomplete history; для нее разрешен только
  прирост между реально наблюдавшимися точками.
- График partial history прекращается на последней точке и не переносит значение
  в будущее.

### Albums, joint posts и reposts

- Telegram album — одна logical publication с несколькими platform message IDs.
- Если members album дают несовместимые reaction states, выбирается только
  documented platform policy и ставится ambiguity flag.
- VK joint post хранит стабильную canonical identity, source external ID и роли
  accounts; одна публикация не должна удваивать totals одного вуза.
- `is_repost` является измеренным классификационным признаком, а не отдельной
  метрикой; включение reposts определяется версией cohort/filter.

### Aggregates and cohorts

- Каждая aggregate row содержит window, `as_of`, dataset revision, sample size,
  coverage и minimum quality.
- Median curve для сравнения горизонтов использует fixed cohort, покрывающий
  выбранные start/end points; меняющийся состав cohort явно отмечается.
- Среднее и медиана не взаимозаменяемы и кодируются разными aggregation keys.
- Cross-platform totals допустимы только в формуле, явно определяющей
  нормализацию несовпадающих platform semantics.

### Versioning and lineage

Semantic registry, formula definition и API contract имеют версии. Rating run
сохраняет:

- formula version и source hash;
- dataset revision и `as_of`;
- window/cohort/filter;
- component inputs, quality и warnings;
- rounding/tie/missing policies.

Изменение любого правила создает новую версию; исторический результат не
перезаписывается.

## Consequences

Положительные:

- графики и рейтинги интерпретируются одинаково;
- отсутствие данных не повышает и не снижает показатель скрытым образом;
- расчеты можно воспроизвести и объяснить;
- platform-specific особенности не теряются при общей модели.

Отрицательные:

- API DTO должны передавать quality/coverage, а не только число;
- часть старых данных останется `unknown` или incomplete;
- миграция не может надежно восстановить отсутствующую историю subscribers;
- запросы и UI становятся содержательнее и требуют больше тестов.

## Alternatives considered

### Привести все отсутствующие значения к нулю

Отклонено: смешивает «нет функции», «ошибка API» и измеренный ноль, искажая
межплатформенные сравнения.

### Хранить только delta

Отклонено: теряется исходное наблюдение и возможность пересчитать новые окна.

### Считать все платформенные views одинаковыми

Отклонено: платформы не гарантируют одинаковую методику счетчика. Допустима
только явно описанная нормализация в конкретной formula version.

## Fitness functions

- Contract tests для каждого platform fixture проверяют NULL/zero/capability.
- Golden dataset проверяет delta, negative/reset, baseline и fixed cohort.
- Одинаковые input+version дают byte-equivalent normalized result.
- API всегда передает quality, sample size и coverage для aggregate/rating.
- Ни один formula component не читает метрику без semantic registry.

## Revisit when

- платформа документированно меняет значение счетчика;
- появляется новый источник или canonical metric;
- официальная методика требует иной baseline/missing policy;
- исследование доказывает более корректную cross-platform normalization.
