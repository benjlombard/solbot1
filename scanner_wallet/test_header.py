import pandas as pd
csv_file = "export_balance_change_6KNbsP3eLVsFEJY9mJUz8h47B6X1GDh1RnYQPgsiCD1a_1754165179612.csv"
df = pd.read_csv(csv_file)
print("Column names in the CSV:", df.columns.tolist())