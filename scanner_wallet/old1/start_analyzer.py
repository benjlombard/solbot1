#!/bin/bash
# start_analyzer_api.sh
# Script de démarrage pour l'API Token Analyzer

echo "🚀 Démarrage de l'API Token Creator Analyzer"
echo "============================================="

# Configuration des variables d'environnement
export QUICKNODE_ENDPOINT="https://misty-alpha-aura.solana-mainnet.quiknode.pro/2a16287e4ba93a9df419f3fa8da45d135d682202/"
export FLASK_HOST="0.0.0.0"
export FLASK_PORT="5001"
export FLASK_DEBUG="False"

# Vérification de Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 n'est pas installé"
    exit 1
fi

# Installation des dépendances si nécessaire
echo "📦 Vérification des dépendances..."
python3 -c "import flask, flask_cors, requests" 2>/dev/null || {
    echo "🔧 Installation des dépendances manquantes..."
    pip3 install flask flask-cors requests
}


python3 analyze_token_creator_backend.py