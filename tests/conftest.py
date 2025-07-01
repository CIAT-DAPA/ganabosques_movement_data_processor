import pytest
import mongomock
from mongoengine import connect, disconnect
from datetime import datetime
from ganabosques_orm.auxiliaries.log import Log
from ganabosques_orm.collections.adm1 import Adm1
from ganabosques_orm.collections.adm2 import Adm2
from ganabosques_orm.collections.adm3 import Adm3

@pytest.fixture(scope="function", autouse=True)
def mongo_mock():
    disconnect()
    connect('testdb', host='mongodb://localhost', mongo_client_class=mongomock.MongoClient)
    yield
    disconnect()

@pytest.fixture(scope="function", autouse=True)
def create_admin_hierarchy(mongo_mock):
    """Fixture que crea una jerarquía administrativa completa (Adm1 → Adm2 → Adm3) para pruebas unitarias.

    Se ejecuta automáticamente antes de cada prueba para garantizar que existan los niveles administrativos
    requeridos en la base de datos mock. Crea:

    - Un Adm1 con código "01"
    - Dos Adm2 ("0101", "0202") asociados a ese Adm1
    - Dos Adm3 ("010101", "020202") asociados a sus respectivos Adm2"""
    now = datetime.now()

    adm1 = Adm1.objects(ext_id="01").first()
    if not adm1:
        adm1 = Adm1(ext_id="01", name="Departamento 01", ugg_size=1.0, log=Log(enable=True, created=now, updated=now))
        adm1.save()

    for adm2_id, adm2_name in [("0101", "Municipio 0101"), ("0202", "Municipio 0202")]:
        if not Adm2.objects(ext_id=adm2_id).first():
            adm2 = Adm2(ext_id=adm2_id, name=adm2_name, adm1_id=adm1, log=Log(enable=True, created=now, updated=now))
            adm2.save()

    for adm3_id, adm3_name, adm2_id in [("010101", "Vereda 010101", "0101"), ("020202", "Vereda 020202", "0202")]:
        adm2 = Adm2.objects(ext_id=adm2_id).first()
        if not Adm3.objects(ext_id=adm3_id).first():
            adm3 = Adm3(ext_id=adm3_id, name=adm3_name, adm2_id=adm2, log=Log(enable=True, created=now, updated=now))
            adm3.save()