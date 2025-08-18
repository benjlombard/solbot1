#!/usr/bin/env python3
"""
Script pour recalculer les priorités de tous les tokens existants
Utilise la nouvelle configuration optimisée
"""

import sys
import time
from pathlib import Path

# Ajouter le projet au path
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

import tokenize  # Import du module standard

from core.priority_config import PriorityConfig, TokenPriority
from tokens.priority_manager import TokenPriorityManager
from core.logger import get_logger

def main():
    """Recalcule toutes les priorités avec la nouvelle configuration"""
    
    print("🔄 Recalcul des priorités avec la configuration optimisée")
    print("=" * 60)
    
    try:
        # Charger la nouvelle configuration
        config = PriorityConfig.from_env()
        
        print("🔧 Nouvelle configuration:")
        print(f"   Hot threshold: {config.hot_threshold}")
        print(f"   Warm threshold: {config.warm_threshold}")
        print(f"   Cold threshold: {config.cold_threshold}")
        print(f"   Volume max: ${config.volume_24h_max:,.0f}")
        print(f"   Market cap max: ${config.market_cap_max:,.0f}")
        print(f"   Price change max: {config.price_change_max}%")
        print()
        
        # Créer le gestionnaire
        manager = TokenPriorityManager(config)
        
        # Afficher la distribution avant
        print("📊 Distribution AVANT recalcul:")
        distribution_before = manager.get_priority_distribution()
        total_before = sum(distribution_before.values())
        
        for priority, count in distribution_before.items():
            percentage = (count / total_before * 100) if total_before > 0 else 0
            print(f"   {priority}: {count} tokens ({percentage:.1f}%)")
        
        print(f"\nTotal: {total_before} tokens")
        print()
        
        # Lancer le recalcul
        print("🚀 Début du recalcul...")
        start_time = time.time()
        
        stats = manager.recalculate_all_priorities()
        
        duration = time.time() - start_time
        
        # Afficher les résultats
        print(f"✅ Recalcul terminé en {duration:.2f} secondes")
        print()
        
        print("📈 Statistiques du recalcul:")
        print(f"   Tokens traités: {stats['total_tokens']}")
        print(f"   Changements de priorité: {stats['priority_changes']}")
        print(f"   Erreurs: {stats['errors']}")
        print()
        
        # Afficher la nouvelle distribution
        print("📊 Distribution APRÈS recalcul:")
        distribution_after = manager.get_priority_distribution()
        total_after = sum(distribution_after.values())
        
        for priority, count in distribution_after.items():
            percentage = (count / total_after * 100) if total_after > 0 else 0
            before_count = distribution_before.get(priority, 0)
            change = count - before_count
            change_str = f"({change:+d})" if change != 0 else ""
            print(f"   {priority}: {count} tokens ({percentage:.1f}%) {change_str}")
        
        print(f"\nTotal: {total_after} tokens")
        print()
        
        # Résumé des changements
        if stats['priority_changes'] > 0:
            change_percentage = (stats['priority_changes'] / stats['total_tokens']) * 100
            print(f"📊 {change_percentage:.1f}% des tokens ont changé de priorité")
        else:
            print("📊 Aucun changement de priorité")
        
        # Recommandations
        print("\n💡 Recommandations:")
        
        critical_count = distribution_after.get('CRITICAL', 0)
        hot_count = distribution_after.get('HOT', 0)
        warm_count = distribution_after.get('WARM', 0)
        cold_count = distribution_after.get('COLD', 0)
        dead_count = distribution_after.get('DEAD', 0)
        
        if critical_count > total_after * 0.05:  # Plus de 5%
            print("   ⚠️ Beaucoup de tokens CRITICAL - vérifiez les seuils")
        
        if hot_count > total_after * 0.20:  # Plus de 20%
            print("   ⚠️ Beaucoup de tokens HOT - augmentez le seuil HOT")
        
        if dead_count > total_after * 0.50:  # Plus de 50%
            print("   💀 Beaucoup de tokens DEAD - considérez un nettoyage")
        
        if cold_count < total_after * 0.10:  # Moins de 10%
            print("   🧊 Peu de tokens COLD - baissez le seuil COLD")
        
        print("\n🎉 Recalcul terminé avec succès!")
        
        return 0
        
    except Exception as e:
        print(f"❌ Erreur pendant le recalcul: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())