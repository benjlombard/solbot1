import sqlite3
import pandas as pd

# Connexion à la base de données SQLite
conn = sqlite3.connect('../tokens.db')  # Remplacez par le chemin de votre fichier SQLite

# Lire la table 'tokens_hist' dans un DataFrame
query = "SELECT * FROM tokens_hist"
df = pd.read_sql_query(query, conn)

# Exporter le DataFrame en CSV
df.to_csv('tokens_hist.csv', index=False, encoding='utf-8')

# Fermer la connexion à la base de données
conn.close()

print("Exportation en CSV terminée avec succès.")