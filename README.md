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

5. **💾 save_movement:** This module saves livestock movement records and related farm and enterprise data into MongoDB. It performs the following tasks:

    - 🗂️ Loads movement files and entity references (farms and enterprises).
    - ✅ Updates or creates Farm and Enterprise entries as needed.
    - 🔗 Matches origin and destination using external identifiers.
    - 🐮 Creates Movement records with species and classification data.
    - ❌ Logs failed rows and generates error reports in CSV format for later review.

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
## 🛠️ Environment Configuration

The pipeline requires a set of environment variables to be configured before execution:

```bash
# URL of the GeoServer instance
URL_GEO

# Local path where the results are to be temporarily stored
WORKSPACE

# Replace GEO_USER with your actual GeoServer username
GEO_USER

# Replace GEO_PWD with your actual GeoServer password
GEO_PWD

# Name of the GeoServer workspace, which must be created before running the code
GEO_WORKSPACE_ADMIN

# Name of the GeoServer data store created for publishing features
GEO_STORE

# MongoDB connection URI
MONGO_URI

# Name of the MongoDB database where the information is stored
MONGO_DB_NAME

# Local path where the raw input movement data is stored
DATA
```



You can set these variables in one of two ways:

### 📄 Option 1: Using a `.env` file

A `.env.example` file is provided as a reference. To configure:

1. Duplicate the file and rename it to `.env`  
2. Replace the placeholder values with your actual configuration

Example values:

```env
URL_GEO=http://localhost:8600/geoserver
WORKSPACE=/path/to/ganabosques/data/
GEO_USER=admin
GEO_PWD=geoserver
GEO_WORKSPACE_ADMIN=administrative
GEO_STORE=admin_3
MONGO_URI=mongodb://usuario:contraseña@localhost:27017
MONGO_DB_NAME=ganabosques
DATA=/path/to/ganabosques/data/data/movements
```



### ⚙️ Option 2: Setting Environment Variables

#### 🪟 Windows (CMD/PowerShell)

```bash
set URL_GEO=http://localhost:8600/geoserver
set WORKSPACE=/path/to/ganabosques/data/
set GEO_USER=admin
set GEO_PWD=geoserver
set GEO_WORKSPACE_ADMIN=administrative
set GEO_STORE=admin_3
set MONGO_URI=mongodb://usuario:contraseña@localhost:27017
set MONGO_DB_NAME=ganabosques
set DATA=/path/to/ganabosques/data/data/movements
```

#### 🐧 Linux / macOS (Terminal)

```bash
export URL_GEO=http://localhost:8600/geoserver
export WORKSPACE=/path/to/ganabosques/data/
export GEO_USER=admin
export GEO_PWD=geoserver
export GEO_WORKSPACE_ADMIN=administrative
export GEO_STORE=admin_3
export MONGO_URI=mongodb://localhost:27017
export MONGO_DB_NAME=ganabosques
export DATA=/path/to/ganabosques/data/data/movements
```



## 🧱 Project Structure

The project uses a modular design, where each directory under `src/` corresponds to a step in the livestock movement data pipeline.

```bash
├── src/
│   ├── get_data_sigma/             # Step 1: Load and parse SIGMA source data
│   ├── quality_control_movement/   # Step 2: Validate movement coordinate quality
│   ├── calculate_movement/         # Step 3: Calculate movement patterns
│   ├── check_farms_enterprise/     # Step 4: Verify new farms or enterprises
│   ├── save_movement/              # Step 5: Save movements and enterprise data to MongoDB
│   ├── tools/                      # Utility functions (e.g., logging)
│   ├── main.py                     # Main pipeline script
│   ├── config.py                   # Loads environment variables and global constants
│   └── .env                        # Configuration for database and paths
├── requirements.txt                # Python dependencies
└── README.md                       # Documentation
```

## 🚀 How to Run the Pipeline

You can execute the full pipeline or select specific steps using command-line arguments.

### 🧭 Available Steps

| Step | Description                              |
|------|------------------------------------------|
| 1    | Get data from SIGMA                      |
| 2    | Quality control of coordinates           |
| 3    | Calculate movement routes                |
| 4    | Check new farms or enterprises           |
| 5    | Save movements and metadata to MongoDB   |

### 🧾 Arguments

- `--source` (`-s`) – Required: Code or identifier for the movement data source  
- `--process` (`-p`) – Optional: Specific steps to execute (e.g., `1 3`)  
- `--from_step` (`-f`) – Optional: Start execution from a specific step onward

> ❌ Note: You **cannot** use `--process` and `--from_step` at the same time.


### 📌 Run all steps:

```bash
python main.py -s SIGMA
```

### 🛠 Run specific steps:

```bash
python main.py -s SIGMA -p 1 3 5
```

### 🔁 Run from a specific step:

```bash
python main.py -s SIGMA -f 2
```

### 📖 Help

```bash
python main.py -h
```
## 📂 Outputs

Output files and logs are stored in the folder defined by the `WORKSPACE` variable, organized in subfolders for each processing step:

| Folder Name                  | Description                                                     |
|------------------------------|-----------------------------------------------------------------|
| `1_tmp_get_sigma`            | Raw and parsed movement data from SIGMA                         |
| `2_tmp_mov_quality_control`  | Validated coordinates and filtered data for quality control     |
| `3_tmp_calc_mov`             | Calculated movement records based on source logic               |
| `4_new_farms`                | New farms or enterprises detected and prepared for validation   |
| `5_save_movement`            | Final data intended for MongoDB storage and error tracking logs |



### 🗂️ `5_save_movement/`

If errors occur while saving records to the database, the system generates detailed CSV logs with the following format:

```text
<original_filename>_errores_<YYYYMMDD>_<HHMMSS>.csv
```

Each error CSV contains:

- The **original row** of the input file that failed  
- The **row number** in the source CSV  
- A **description of the error**, such as:
  - Connectivity issues with MongoDB
  - Foreign key/reference mismatches
  - Type validation errors or missing required fields

> 📝 These files are useful for debugging and retrying failed operations after manual correction.

### 📃 Logging

All logs are stored in:

```
<WORKSPACE>/movilizacion/main_pipeline.log
```

## 👥 Contributors

This project is developed by the CIAT-DAPA team, with contributions from:

- [stevensotelo](https://github.com/stevensotelo)
- [bmora-0110](https://github.com/bmora-0110)
- [victor-993](https://github.com/victor-993)
