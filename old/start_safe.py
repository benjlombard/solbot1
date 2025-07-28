#!/usr/bin/env python3
"""
Lancement sécurisé du bot avec timeout automatique
"""
import subprocess
import signal
import time
import sys

def run_bot_with_timeout(timeout_minutes=30):
    """Lance le bot avec timeout automatique"""
    
    print(f"🚀 Lancement du bot avec timeout de {timeout_minutes} minutes")
    print("🛑 Appuyez sur Ctrl+C pour arrêter manuellement")
    
    try:
        # Lancer le bot
        process = subprocess.Popen([
            sys.executable, 'main.py', 
            '--log-level', 'INFO'
        ])
        
        # Attendre avec timeout
        try:
            process.wait(timeout=timeout_minutes * 60)
        except subprocess.TimeoutExpired:
            print(f"\n⏰ Timeout de {timeout_minutes} minutes atteint")
            print("🛑 Arrêt automatique du bot...")
            
            # Tuer le processus proprement
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            
            print("✅ Bot arrêté automatiquement")
            
    except KeyboardInterrupt:
        print("\n🛑 Arrêt manuel demandé...")
        if 'process' in locals():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        print("✅ Bot arrêté manuellement")

if __name__ == "__main__":
    run_bot_with_timeout(30)  # 30 minutes max