import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime

# Paramètres
csv_file = "export_balance_change_D6JhU5uiVutVUido9N9RPuKs79pvxXsxBv9CTjCR1hhz_1754167130895.csv"
token_address = "7w8vCPw7iYQfN7PJNbKYMMyAoa9mWNZAHxiGSEHm7kg4"
creator_address = "D6JhU5uiVutVUido9N9RPuKs79pvxXsxBv9CTjCR1hhz"  # À remplacer si vous avez l'adresse réelle du créateur
label = 1  # 1 = scam (soft rug pull confirmé)
db_name = "token_analysis.db"

# Charger le fichier CSV
try:
    df = pd.read_csv(csv_file)
except FileNotFoundError:
    print(f"Erreur : Le fichier {csv_file} n'a pas été trouvé.")
    exit()

# Supprimer les espaces dans les noms de colonnes
df.columns = df.columns.str.strip()
print("Colonnes après suppression des espaces :", df.columns.tolist())

# Vérifier les colonnes
expected_columns = {
    'Txhash': ['Txhash', 'tx_hash', 'transaction_hash'],
    'BlockTimeUnix': ['BlockTimeUnix', 'block_time_unix', 'timestamp'],
    'BlockTime': ['BlockTime', 'block_time'],
    'Fee(SOL)': ['Fee(SOL)', 'fee', 'fee_sol'],
    'TokenAccount': ['TokenAccount', 'token_account', 'account'],
    'ChangeType': ['ChangeType', 'change_type', 'type'],
    'ChangeAmount': ['ChangeAmount', 'change_amount', 'amount'],
    'PreBalancer': ['PreBalancer', 'pre_balancer', 'pre_balance'],
    'PostBalancer': ['PostBalancer', 'post_balancer', 'post_balance'],
    'TokenAddress': ['TokenAddress', 'token_address', 'address'],
    'TokenDecimals': ['TokenDecimals', 'token_decimals', 'decimals'],
    'TokenMultiplier': ['TokenMultiplier', 'token_multiplier', 'multiplier']
}

# Trouver les colonnes correspondantes
column_mapping = {}
for expected, aliases in expected_columns.items():
    for alias in aliases:
        if alias in df.columns:
            column_mapping[expected] = alias
            break
    if expected not in column_mapping:
        print(f"Erreur : Colonne '{expected}' non trouvée. Colonnes disponibles : {df.columns.tolist()}")
        exit()

# Renommer les colonnes pour correspondre aux attentes
df = df.rename(columns={v: k for k, v in column_mapping.items()})

# Afficher les colonnes pour débogage
print("Colonnes utilisées :", df.columns.tolist())

# Filtrer les transactions pour le token cible
token_df = df[df['TokenAddress'] == token_address]

# Vérifier si le DataFrame n'est pas vide
if token_df.empty:
    print(f"Aucune transaction trouvée pour le token {token_address}")
    exit()

# Calculer les caractéristiques
def calculate_features(df, token_df):
    features = {}

    # 1. Fréquence des transactions
    time_span = (token_df['BlockTimeUnix'].max() - token_df['BlockTimeUnix'].min()) / 60  # en minutes
    features['tx_per_minute'] = len(token_df) / time_span if time_span > 0 else 0

    # 2. Variabilité des intervalles
    intervals = token_df['BlockTimeUnix'].diff().dropna()
    features['coefficient_variation_intervals'] = intervals.std() / intervals.mean() if intervals.mean() > 0 else 0

    # 3. Patterns d'accumulation
    deposit_amount = token_df[token_df['ChangeType'] == 'inc']['ChangeAmount'].sum()
    withdrawal_amount = token_df[token_df['ChangeType'] == 'dec']['ChangeAmount'].sum()
    features['deposit_ratio'] = deposit_amount / withdrawal_amount if withdrawal_amount > 0 else float('inf')
    features['net_balance'] = deposit_amount - withdrawal_amount

    # 4. Signaux de rug pull
    features['max_withdrawal'] = token_df[token_df['ChangeType'] == 'dec']['ChangeAmount'].max() if not token_df[token_df['ChangeType'] == 'dec'].empty else 0
    burst_threshold = 30  # secondes
    burst_count = len(token_df[token_df['BlockTimeUnix'].diff() < burst_threshold])
    features['burst_ratio'] = burst_count / len(token_df) if len(token_df) > 0 else 0

    # 5. Diversité des adresses
    features['unique_addresses'] = len(token_df['TokenAccount'].unique())

    # 6. Variabilité des montants
    features['amount_variability'] = token_df['ChangeAmount'].std() / token_df['ChangeAmount'].mean() if token_df['ChangeAmount'].mean() > 0 else 0

    # 7. Frais de transaction
    features['avg_fee'] = df['Fee(SOL)'].mean()
    features['fee_variability'] = df['Fee(SOL)'].std() / df['Fee(SOL)'].mean() if df['Fee(SOL)'].mean() > 0 else 0

    # 8. Durée totale
    features['time_span'] = time_span * 60  # en secondes

    return features

# Extraire les caractéristiques
features = calculate_features(df, token_df)

# Ajouter l'adresse du token, du créateur et le label
features['token_address'] = token_address
features['creator_address'] = creator_address
features['label'] = label
features['analysis_date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Créer un DataFrame pour les résultats
results_df = pd.DataFrame([features])

# Stocker dans SQLite3
conn = sqlite3.connect(db_name)
cursor = conn.cursor()

# Créer la table si elle n'existe pas
cursor.execute('''
CREATE TABLE IF NOT EXISTS token_analysis (
    token_address TEXT,
    creator_address TEXT,
    tx_per_minute REAL,
    coefficient_variation_intervals REAL,
    deposit_ratio REAL,
    net_balance REAL,
    max_withdrawal REAL,
    burst_ratio REAL,
    unique_addresses INTEGER,
    amount_variability REAL,
    avg_fee REAL,
    fee_variability REAL,
    time_span REAL,
    label INTEGER,
    analysis_date TEXT
)
''')

# Insérer les données
results_df.to_sql('token_analysis', conn, if_exists='append', index=False)

# Confirmer l'insertion
cursor.execute("SELECT * FROM token_analysis WHERE token_address = ?", (token_address,))
stored_data = cursor.fetchall()
print("Données stockées dans la table 'token_analysis':")
for row in stored_data:
    print(row)

# Fermer la connexion
conn.commit()
conn.close()

# Afficher les caractéristiques calculées
print("\nCaractéristiques calculées :")
for key, value in features.items():
    print(f"{key}: {value}")