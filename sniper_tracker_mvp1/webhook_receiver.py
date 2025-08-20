# webhook_receiver.py
from fastapi import FastAPI, Request, HTTPException
import sqlite3
import json
import logging
from datetime import datetime
from typing import Dict, Any

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Sniper Tracker Webhook Receiver")

@app.post("/helius/webhook")
async def handle_helius_webhook(request: Request):
    """Endpoint principal pour recevoir les webhooks Helius"""
    try:
        data = await request.json()
        
        # Log pour debugging
        logger.info(f"Webhook reçu: {len(data)} transactions")
        
        # Traitement des transactions
        for transaction in data:
            process_transaction(transaction)
        
        return {"status": "success", "processed": len(data)}
    
    except Exception as e:
        logger.error(f"Erreur webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def process_transaction(tx_data: Dict[Any, Any]):
    """Traite une transaction individuelle"""
    
    # Vérification si c'est une création de pool pump.fun → Raydium
    if is_pool_creation(tx_data):
        handle_pool_creation(tx_data)
    
    # Vérification si c'est un swap
    elif is_swap_transaction(tx_data):
        handle_swap(tx_data)

def is_pool_creation(tx_data: Dict[Any, Any]) -> bool:
    """Détermine si la transaction est une création de pool"""
    # Logique basée sur les programmes impliqués
    instructions = tx_data.get('instructions', [])
    
    for instruction in instructions:
        program_id = instruction.get('programId', '')
        if program_id == "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8":  # Raydium LP V4
            if 'initialize' in instruction.get('data', '').lower():
                return True
    return False

def is_swap_transaction(tx_data: Dict[Any, Any]) -> bool:
    """Détermine si la transaction est un swap"""
    instructions = tx_data.get('instructions', [])
    
    for instruction in instructions:
        program_id = instruction.get('programId', '')
        if program_id == "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8":
            if 'swap' in instruction.get('data', '').lower():
                return True
    return False

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)