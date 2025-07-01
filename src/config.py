import os
from dotenv import load_dotenv
from ganabosques_orm.enums.species import Species

load_dotenv()

config = {}

config['DEBUG'] = os.getenv('DEBUG', 'true').lower() == 'true'
config['WORKSPACE'] = os.getenv('WORKSPACE')
config['DATA'] = os.getenv('DATA')
config['MONGO_URI'] = os.getenv('MONGO_URI')
config['MONGO_DB_NAME'] = os.getenv('MONGO_DB_NAME')
config['URL_GEO'] = os.getenv("URL_GEO")
config['WORKSPACE'] = os.getenv('WORKSPACE')
config['GEO_USER'] = os.getenv("GEO_USER")
config['GEO_PWD'] = os.getenv("GEO_PWD")
config['GEO_WORKSPACE'] = os.getenv("GEO_WORKSPACE")
config['GEO_STORE'] = os.getenv("GEO_STORE")

config["columnas_requeridas_sigma"]= [
        'ANIO','MES','DIA','NUMERO_GUIA',
        'TIPO_ORIGEN','TIPO_DESTINO','CODIGO_SIT_ORIGEN','CODIGO_SIT_DESTINO', 'ID_UNIDAD_PRODUCTORA_ORIGEN', 'ID_UNIDAD_PRODUCTORA_DESTINO',
        "ID_DEPARTAMENTO_ORIGEN", "ID_MUNICIPIO_ORIGEN","ID_VEREDA_ORIGEN","ID_DEPARTAMENTO_DESTINO", "ID_MUNICIPIO_DESTINO", "ID_VEREDA_DESTINO", 
        'ESPECIE',
        "HEMBRAS MENOR DE 3 MESES", 
        "HEMBRAS ENTRE 3 A 8 MESES", 
        "HEMBRAS DE 8 A 12 MESES", 
        "HEMBRAS 1 A 2 ANIOS", 
        "HEMBRAS 2 A 3 ANIOS", 
        "HEMBRAS DE 3 A 5 ANIOS", 
        "HEMBRAS MAYORES DE 5 ANIOS", 
        "MACHOS MENOR DE 3 MESES",
        "MACHOS ENTRE 3 A 8 MESES",
        "MACHOS DE 8 A 12 MESES", 
        "MACHOS DE 1 A 2 ANIOS",
        "MACHOS DE 2 A 3 ANIOS", 
        "MACHOS MAYORES A 3 ANIOS", 
        "HEMBRA BUFALINA MENOR DE 3 ME", 
        "HEMBRA BUFALINA DE 3 A 8 MESE",
        "HEMBRA BUFALINA ENTRE 8 Y 12", 
        "HEMBRA BUFALINA DE 1 A 2 ANIO", 
        "HEMBRA BUFALINA DE 2 A 3 ANIO", 
        "HEMBRA BUFALINA DE 3 A 5 ANIO", 
        "HEMBRA BUFALINA MAYOR DE 5 A", 
        "MACHOS BUFALINO MENOR DE 3 ME", 
        "MACHOS BUFALINO DE 3 A 8 MESE", 
        "MACHOS BUFALINO DE 8 A 12 MES", 
        "MACHOS BUFALINO DE 1 A 2 ANIO", 
        "MACHOS BUFALINO DE 2 A 3 ANIO", 
        "MACHOS BUFALINO MAYORES A 3 A", 
        "LACTANTES HASTA 30 DIAS", 
        "PRECEBO 31 A 60 DIAS",  
        "LEVANTE CEBA 61 A 180 DIAS", 
        "HEMBRA REEMPLAZO MENOR DE 8 M", 
        "HEMBRA CRIA MAYOR A 8 MESES", 
        "MACHO REPRODUCTOR MAYOR DE 6"
]

config["MOV"]= {
    'PREDIO': "FARM",
    'CONCENTRACION GANADERA': "COLLECTION_CENTER",
    'PLANTA DE BENEFICIO': "SLAUGHTERHOUSE",
    'FERIA GANADERA': "CATTLE_FAIR",
    'EMPRESA' : "ENTERPRISE",
    'MUNICIPIO' :"MUNICIPALITY"
}

config["origen_destino"]={
        "SIGMA": {
            "type_origin": "TIPO_ORIGEN",
            "type_destination": "TIPO_DESTINO"
        },
        "otro": {
            "type_origin": "origen",
            "type_destination": "destino"
        }
}


config["especie_map"] = {
    "bovina": Species.BOVINOS.value,
    "bufalina": Species.BUFALINOS.value
}

if __name__ == "__main__":
    print(config)