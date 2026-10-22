# Разработка и запуск

## Docker Compose

Требуются Docker Engine и Docker Compose v2.

```bash
# Веб, Redis, PostgreSQL и worker
docker compose up --build web

# Проверка конфигурации без запуска
docker compose config --quiet

# Логи расчёта
docker compose logs -f worker

# Остановка; данные Redis и PostgreSQL остаются в именованных томах
docker compose down --remove-orphans
```

Интерфейс: [localhost:8096](http://localhost:8096).
API: [localhost:8096/docs](http://localhost:8096/docs).
Статистика: [localhost:8096/statistics](http://localhost:8096/statistics).
Redis и PostgreSQL доступны внутри сети Compose; публикация их портов на хост не настроена. В Compose используются
демонстрационные реквизиты PostgreSQL `planner/planner`, БД `planner`.
Для внешней БД задайте `DATABASE_URL`.

### Прокси при сборке

Если сборка не может скачать зависимости из PyPI, укажите доступный из Docker
прокси в локальном `.env`. Например, для Docker Desktop:

```dotenv
BUILD_HTTP_PROXY=http://http.docker.internal:3128
BUILD_HTTPS_PROXY=http://http.docker.internal:3128
```

Без этих переменных сборка подключается напрямую. `.env` исключён из Git
и контекста сборки; прокси передаётся только на этапе сборки.

## Локальный запуск без Docker

Нужны Python 3.12, PostgreSQL с заранее созданной БД и работающий Redis с поддержкой Streams и `XAUTOCLAIM`
(в Compose используется Redis 7.4).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export REDIS_URL=redis://localhost:6379/0
export DATABASE_URL=postgresql://planner:planner@localhost:5432/planner
```

В отдельных терминалах с тем же окружением запустите:

```bash
python -m planner.worker
```

```bash
python -m planner.web
```

## Тесты

Compose использует отдельную Redis DB `/1`, тесты создают уникальные префиксы
ключей и удаляют свои данные после завершения.

```bash
# Все проверки
docker compose --profile test run --build --rm tests

# Изолированные расчёты бригад и переносы между сменами
docker compose --profile test run --rm tests \
  python -m unittest discover -s tests -p 'test_department_planning.py' -v

# API, очередь, Redis Pub/Sub и SSE
docker compose --profile test run --rm tests \
  python -m unittest discover -s tests -p 'test_web_queue.py' -v
```

Локально Redis-тесты включаются при наличии `REDIS_URL`, архивные тесты — при наличии
также `DATABASE_URL`. В Compose создана отдельная БД PostgreSQL `planner_test`. Используйте отдельную
тестовую БД:

```bash
REDIS_URL=redis://localhost:6379/1 \
DATABASE_URL=postgresql://planner:planner@localhost:5432/planner_test \
python -m unittest discover -s tests -v
```

Без `REDIS_URL` интеграционные тесты веб-сервиса с Redis пропускаются.

## Консольный пример

```bash
docker compose up --build planner
```

Одноразовый сервис создаёт тестовые данные, распределяет операции общим
сценарием между бригадами и печатает результат. В отличие от веб-сравнения,
он по умолчанию использует горизонт одного дня и не рассчитывает отдельный
заказ для каждого department. Успешный вывод содержит секции `TEST DATA`,
`TECH PROCESS`, `PRODUCTION PLAN`, `ASSIGNMENTS BY DEPARTMENT`.

Проверить OR-Tools:

```bash
docker compose run --rm planner \
  python -c "import ortools; print(ortools.__version__)"
```

Версия зафиксирована в [requirements.txt](../requirements.txt).

## Сохранённый пример результата

[department-comparison.json](examples/department-comparison.json) — сокращённая
выгрузка реального завершённого задания из Redis. Она содержит параметры
расчёта и итоговые времена четырёх бригад, но не полный список операций.
Таблица и диаграмма Ганта в README основаны на этой выгрузке. Полосы диаграммы
показывают календарный интервал, включая перерывы; `workSec` — только работу.
Это пример найденных допустимых планов, а не эталон точного результата теста.

## Импорт существующей истории

После запуска сервисов перенесите рассчитанные задания из Redis в PostgreSQL:

```bash
docker compose exec web python -m planner.migrate_history
```

Команда сохраняет полные снимки и результаты, пропускает уже архивированные
UUID и не выдумывает отсутствующие измерения памяти. Она не удаляет Redis-данные.

## Параллельность бригад

По умолчанию worker запускает до четырёх расчётов departments одновременно:

```bash
DEPARTMENT_PROCESSES=4 docker compose up -d web
```

Лимит — от 1 до 16 процессов на один worker. При масштабировании worker
общая нагрузка увеличивается вместе с количеством worker-процессов.
Для локального `python -m planner.worker` задайте ту же переменную окружения.
На статистике новые записи показывают сумму RSS worker и дочерних процессов;
это не уникальная физическая память, общие страницы могут считаться повторно.
