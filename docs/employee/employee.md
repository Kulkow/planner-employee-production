````
Employee
  id - int PK
  fullName - string
  position - string
  departmnentId : int
  
Department
  id - int PK
  name - string
  
EmployeeEquipment
  id - int PK
  employee_id - int
  equipment_type - int (TechOperationEquipmentType.id)
  
Employee -> hasMany EmployeeEquipment


EmployeeEfficiency
  id - int PK
  employee_id - int
  percent - int
  equipment_type - int (TechOperationEquipmentType.id)
  day - Datetime 
  
EmployeeEfficiency->getPercent(int employee_id, int equipment_type): int  
````

## EmployeeWorkload — дневная загрузка

Неизменяемая запись с ключом `(employeeId, date)`:

| Поле API | Поле Python | Значение |
| --- | --- | --- |
| `employeeId` | `employee_id` | Сотрудник |
| `date` | `date` | Дата загрузки |
| `plannedSeconds` | `planned_seconds` | Фонд рабочего времени на дату |
| `allocatedSeconds` | `allocated_seconds` | Время, уже занятое другими работами |
| `availableSeconds` | `available_seconds` | Остаток для новых назначений |

Все секунды — целые неотрицательные значения.
`availableSeconds = plannedSeconds - allocatedSeconds`; занятое время
не превышает фонд, фонд не превышает смену по графику. На нерабочую дату фонд
равен нулю. На одного сотрудника и дату допустима одна запись.

В `PlanningRequest.employee_workloads` хранится снимок исходной загрузки.
При сравнении он фильтруется по сотрудникам соответствующего department.
Решатель ограничивает суммарную длительность новых операций за день
доступным остатком. Точных интервалов существующей занятости запись не задаёт:
это дневной бюджет, а не календарь уже назначенных операций.

`test_data` создаёт запись на дату планирования каждому сотруднику: фонд
по смене и случайное занятое время от 0 до 180 минут включительно, независимо
для сотрудников разных departments. На выходном все значения нулевые.
Генерация воспроизводится по seed и не изменяет случайные значения норм
и эффективности. Для дат без записи используется полная смена без
дополнительного ограничения загрузки. Снимок не изменяется после расчёта:
сценарии не бронируют ресурсы между заданиями.

На Ганте исходная загрузка отображается под каждой бригадой отдельными серыми
полосами со штриховкой по сотрудникам и датам. Шкала полосы — фонд смены
(`plannedSeconds`), заполнение — доля `allocatedSeconds`. Это не временные
интервалы: полосы не совмещаются с часовой шкалой операций и не означают,
что существующая работа начинается в начале смены. Нулевая загрузка имеет
пустую полосу. Рядом указаны занятое, доступное время и фонд.
