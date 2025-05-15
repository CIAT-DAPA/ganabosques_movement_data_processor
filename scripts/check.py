import pandas as pd

# Cargar la primera tabla normalmente (asume que los encabezados están en la primera fila)
df1 = pd.read_excel(r'D:\OneDrive - CGIAR\Desktop\ganabosques\movilizacion\data\brutos\sagari\sagari_ciclo1_2024.xlsx')

# Cargar la segunda tabla especificando que los encabezados están en la fila 9 (índice 8)
df2 = pd.read_excel(r'D:\OneDrive - CGIAR\Desktop\ganabosques\movilizacion\data\brutos\sagari\sagari_ciclo2_2024.xlsx', header=8,usecols="A:HM")

# Verificar que ambos DataFrames tienen los encabezados correctos
print("Columnas df1:", df1.columns.tolist())
print("Columnas df2:", df2.columns.tolist())
