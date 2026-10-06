````

TechProcess
  id - int PK
  productCardId - int
  stages []TechProcessStage
  
TechProcessStage
  stage - int
  groups []TechProcessStageGroup
  
TechProcessStageGroup
  name - string
  operations []TechOperation
  
TechOperation
  id - int PK
  norm_sec - int
  type TechOperationType 
  equipmentType TechOperationEquipmentType  

TechOperationType
  id - int PK
  name - string
  rank - int
  
TechOperationEquipmentType
  id - int PK
  name - string
  code - string
````
