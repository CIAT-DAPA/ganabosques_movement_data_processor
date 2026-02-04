from pymongo import MongoClient
from datetime import datetime

# Datos de conexión
MONGO_URI = "mongodb://localhost:27017"
MONGO_DB = "ganabosques"
COLLECTION_NAME = "enterprise"

# Conexión a MongoDB
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
collection = db[COLLECTION_NAME]

# Fecha y hora actual
current_time = datetime.utcnow()

# Registros a insertar
new_records = [
    {
        "adm2_id": "6847012a7bbf516b66a9cea2",
        "name": "COLACTEOS",
        "ext_id": [
            {
                "label": "PRODUCTIONUNIT_ID",
                "ext_code": "NULL"
            }
        ],
        "type_enterprise": "ENTERPRISE",
        "latitude": 0.9573434,
        "longitud": -77.7333581,
        "log": {
            "enable": True,
            "created": current_time,
            "updated": current_time
        }
    },
    {
        "adm2_id": "6847013a7bbf516b66a9e8ce",
        "name": "CARNATURAL",
        "ext_id": [
            {
                "label": "PRODUCTIONUNIT_ID",
                "ext_code": "NULL"
            }
        ],
        "type_enterprise": "ENTERPRISE",
        "latitude": 4.13238,
        "longitud": -73.62564,
        "log": {
            "enable": True,
            "created": current_time,
            "updated": current_time
        }
    }
]

# Inserción en MongoDB
result = collection.insert_many(new_records)

# Confirmación
print("✅ Registros insertados correctamente:")
for _id in result.inserted_ids:
    print(_id)
