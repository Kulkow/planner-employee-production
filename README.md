# Планировщик производства

Пример распределения операций технологического процесса между сотрудниками.
План строится на Python с помощью Google OR-Tools CP-SAT.

## Требования

- Docker Engine;
- Docker Compose v2 (`docker compose`).

Проверить установленное окружение:

```bash
docker --version
docker compose version
```

## Веб-интерфейс (диаграмма Ганта)

Запустить веб-версию на порту `8096`:

```bash
docker compose up --build web
```

Открыть [http://localhost:8096](http://localhost:8096). В форме можно выбрать
дату планирования, количество изделий (до 30) и отфильтровать диаграмму по
подразделению. Наведение на блок операции показывает исполнителя, оборудование,
эффективность, фактическую длительность и время выполнения.

## Консольный запуск

Собрать образ и запустить планировщик:

```bash
docker compose up --build planner
```

Сервис является одноразовой задачей: он создаёт тестовые данные, рассчитывает
производственный план, выводит назначения в консоль и завершается.

В успешном выводе должны присутствовать секции:

```text
TEST DATA
TECH PROCESS
PRODUCTION PLAN
ASSIGNMENTS BY DEPARTMENT
```

Статус плана должен быть `OPTIMAL` или `FEASIBLE`. Для каждой операции выводятся
время начала и окончания, этап, сотрудник, подразделение, эффективность и
фактическая длительность.

Повторный запуск без пересборки образа:

```bash
docker compose run --rm planner
```

## Проверка OR-Tools

Проверить импорт библиотеки и установленную версию:

```bash
docker compose run --rm planner \
  python -c "import ortools; print(ortools.__version__)"
```

Ожидаемая версия:

```text
9.15.6755
```

## Тесты

Запустить все доменные и интеграционные тесты:

```bash
docker compose --profile test run --build --rm tests
```

В конце успешного запуска будет выведено:

```text
OK
```

Запустить только тесты генератора и доменной модели:

```bash
docker compose --profile test run --rm tests \
  python -m unittest discover -s tests \
  -p 'test_domain_and_test_data.py' -v
```

Запустить только интеграционные тесты CP-SAT:

```bash
docker compose --profile test run --rm tests \
  python -m unittest discover -s tests \
  -p 'test_cp_sat_planner.py' -v
```

## Проверка Docker Compose

Проверить итоговую конфигурацию без запуска контейнеров:

```bash
docker compose config --quiet
```

Команда завершается без вывода и с кодом `0`, если конфигурация корректна.

## Остановка и очистка

Удалить созданные контейнеры и сеть проекта:

```bash
docker compose down --remove-orphans
```

Удалить также локальный образ планировщика:

```bash
docker compose down --remove-orphans --rmi local
```

## Структура

```text
planner/
├── domain/          # Доменные сущности и бизнес-правила
├── application/     # Сценарий планирования и порт оптимизатора
├── infrastructure/  # CP-SAT и генератор тестовых данных
└── main.py          # Точка входа
tests/               # Доменные и интеграционные тесты
```

Описание правил планирования находится в
[`docs/planner/readme.md`](docs/planner/readme.md).
