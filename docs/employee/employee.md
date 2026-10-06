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
