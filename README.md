# 🐄 Movement Data Processor

![GitHub release (latest by date)](https://img.shields.io/github/v/release/CIAT-DAPA/ganabosques_movenment_data_processor) ![](https://img.shields.io/github/v/tag/CIAT-DAPA/ganabosques_movenment_data_processor)

## Descripcion: 
The Movement Data Processor container works as an ETL (Extract, Transform, and Load) process designed to query and process mobilization data. Its main function is to access mobilization guides to classify them by movement type and subsequently standardize the information to ensure compatibility with subsequent analysis systems. The resulting information is stored in the GANABOSQUES Database container.

The **Movenment Data Processor** contains 5 modules, which are described below:

1. **📥 get_data_sigma**: This module processes .txt files from the SIGMA system. It performs the following tasks:

   - 📂 Bulk loading of .txt files encoded in Latin-1 and separated by |.\
   - ✅ Column validation according to SIGMA's official structure.\
   - 🗓️ Generación de columna de fecha unificada a partir de ANIO, MES y DIA.\
   - 💾 Exportación de archivos procesados a formato .csv limpio.\
    
2. **🧹quality_control_movement:** This module performs quality control on .csv files containing livestock movement records. Its goal is to validate, clean, and standardize origin and destination data. It performs the following tasks:

    - 📥 Load and read files.
    - ✅ Verify required columns
    - 🔤 Standardize key values.
    - 🚫 Filter out invalid records.
    - 💾 Save cleaned files.

3. **🧮 calculate_movement** This module classifies livestock movements based on the combination of origin and destination types, filtering for relevant species. It performs:

    - 📂 File loading.
    - 📄 Read CSV files.
    - 🐃 Filter by species (bovine and buffalo).
    - 🏷️ Generate TIPO_MOVIMIENTO column.\
    - 💾 Save processed results.

4. **🧭 Check_farms:** This module verifies whether SIT codes from farms in movement records match those in the SAGARI database. If no match is found, it creates new entries. It performs the following:

   - 🗃️ Load farm data from MongoDB.
   - 📄 Check movement files.
   - 🔍 Identify unmatched records.
   - 🆕 Create new farms with SIT code, department, municipality, and locality information.
   - 💾 Save in MongoDB the new farms

5. **💾 save_movement:** 

## ⚙️ Features
- 🧩 Modular structure oriented to data frame processing.
- Developed with MongoEngine for efficient document-oriented mapping on MongoDB. 
- 🗄 Compatible with Python > 3.10
- 🐍 Compatible with Python > 3.10
- 🏗 Designed for integration into GANABOSQUES infrastructure

## Requirements
- Python > 3.10
- MongoDB (for managing deforestation records)
- Full integration with the GeoServer REST API for publishing, updating, and managing raster mosaics.
- GeoServer runs inside a Docker container, which facilitates portability and deployment across different environments.

## 🚀 Installation
1.  Clone repository 
 ```bash
 git clone https://github.com/CIAT-DAPA/ganabosques_movement_data_processor.git
 ```
2. Create  a virtual environment
```bash
 python -m venv env_mov
 ```

3. Ativate a virtual environment
```bash
 env_mov\Scripts\activate
```

4. Install the dependencies
 ```bash
pip install -r requirements.txt
```
## Environment Configuration
1. Creating a .env file in your project
2. Setting environment variables directly in your system

#### Option 1: Using .env file

Create a file named .env with these configurations:

 ```bash
WORKSPACE=D:/OneDrive - CGIAR/Proyectos/ganabosques/data
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=ganabosques
DATA=D:/OneDrive - CGIAR/Proyectos/ganabosques/data/prueba_mov
```
#### Option 2: Setting Environment Variables
- Windows (CMD/PowerShell)
 ```bash
set WORKSPACE=D:/OneDrive - CGIAR/Proyectos/ganabosques/data
set MONGO_URI=mongodb://localhost:27017
set MONGO_DB_NAME=ganabosques
set DATA=D:/OneDrive - CGIAR/Proyectos/ganabosques/data/prueba_mov
```
- Linux/Ubuntu (Terminal)
export 

 ```bash
export WORKSPACE="D:/OneDrive - CGIAR/Proyectos/ganabosques/data"
export MONGO_URI="mongodb://localhost:27017"
export MONGO_DB_NAME="ganabosques"
export DATA="D:/OneDrive - CGIAR/Proyectos/ganabosques/data/prueba_mov"
```

#### 💡 Notes 
 - Replace GEO_USER, GEO_PWD with your actual credentials.
 - URL_GEO refers to the URL of the GeoServer instance enabled through Docker.
 - WORKSPACE refers to the local path where the results are to be temporarily stored.
 - GEO_WORKSPACE refers to the name of the GeoServer workspace, which must be created before running the code.
 - MONGO_URI refers to the MongoDB URL enabled through Docker.
 - MONGO_DB_NAME refers to the database where the information is stored within MongoDB.

## ▶️ Running the modules
```bash
Windows CMD o PowerShell
py deforestation\src\main.py

Linux, macOS o Git Bash
python3 deforestation/src/main.py
```


