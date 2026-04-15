import pandas as pd
import json

df = pd.read_excel('data/Sewing loading Plan..xlsx', sheet_name='Sewing Loading Plan', skiprows=2)
cols = list(df.columns)
print(json.dumps({"total": len(cols), "columns": cols}, indent=2))
