#!/usr/bin/env python3
"""
Script de test pour le système de priorité
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

from core.priority_config import PriorityConfig, TokenPriority
from token.priority_manager import TokenPriorityManager
from token.priority_calculator import TokenPriorityCalculator

def test_priority_calculation():
    """Test du calcul de priorité"""
    print("🧪 Test du calcul de priorité")
    
    config = PriorityConfig.from_env()
    calculator = TokenPriorityCalculator(config)
    
    # Token de test - HOT
    hot_token = {
        'address': 'test_hot_token',
        'volume_24h': 500000,  # 500k$
        'price_change_24h': 150,  # +150%
        'market_cap': 10000000,  # 10M$
        'created_at': '2024-08-18 10:00:00',  # Récent
        'is_dead': 0,
        'is_rugged': 0
    }
    
    score = calculator.calculate_token_score(hot_token)
    priority = calculator.determine_priority_level(score, hot_token)
    
    print(f"Token HOT - Score: {score:.1f}, Priorité: {priority.name}")
    assert priority == TokenPriority.HOT or priority == TokenPriority.CRITICAL
    
    # Token de test - DEAD
    dead_token = {
        'address': 'test_dead_token',
        'volume_24h': 10,  # 10$
        'price_change_24h': -99,  # -99%
        'market_cap': 500,  # 500$
        'created_at': '2024-01-01 10:00:00',  # Ancien
        'is_dead': 1,
        'is_rugged': 0
    }
    
    score = calculator.calculate_token_score(dead_token)
    priority = calculator.determine_priority_level(score, dead_token)
    
    print(f"Token DEAD - Score: {score:.1f}, Priorité: {priority.name}")
    assert priority == TokenPriority.DEAD
    
    print("✅ Tests de calcul réussis")

def test_priority_manager():
    """Test du gestionnaire de priorité"""
    print("🧪 Test du gestionnaire de priorité")
    
    config = PriorityConfig.from_env()
    manager = TokenPriorityManager(config)
    
    # Test de récupération des distributions
    distribution = manager.get_priority_distribution()
    print(f"Distribution actuelle: {distribution}")
    
    # Test de récupération des tokens par priorité
    hot_tokens = manager.get_tokens_by_priority(TokenPriority.HOT, 5)
    print(f"Tokens HOT (5 premiers): {len(hot_tokens)}")
    
    print("✅ Tests du gestionnaire réussis")

def main():
    """Exécute tous les tests"""
    print("🚀 Tests du système de priorité")
    print("=" * 50)
    
    try:
        test_priority_calculation()
        print()
        test_priority_manager()
        print()
        print("✅ Tous les tests réussis!")
        return 0
        
    except Exception as e:
        print(f"❌ Erreur pendant les tests: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())