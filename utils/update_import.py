#!/usr/bin/env python3
"""
Script pour remplacer solana_client.py par la version corrigée
"""

import shutil
import os

def main():
    print("🔄 Updating solana_client.py with fixed version...")
    
    try:
        # Sauvegarder l'ancienne version
        if os.path.exists('solana_client.py'):
            shutil.copy('solana_client.py', 'solana_client_backup.py')
            print("💾 Backup created: solana_client_backup.py")
        
        # Copier la nouvelle version
        if os.path.exists('solana_client_fixed.py'):
            shutil.copy('solana_client_fixed.py', 'solana_client.py')
            print("✅ Updated solana_client.py with fixed version")
        else:
            print("❌ solana_client_fixed.py not found")
            return False
        
        print("\n🧪 Test the import now:")
        print("   python utils/quick_test.py")
        print("   python main.py --test-solana")
        
        return True
        
    except Exception as e:
        print(f"❌ Update failed: {e}")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)