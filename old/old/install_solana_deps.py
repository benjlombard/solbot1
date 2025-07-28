#!/usr/bin/env python3
"""
Installation des dépendances Solana
File: install_solana_deps.py

Script pour installer automatiquement toutes les dépendances Solana nécessaires.
"""

import subprocess
import sys
import os

def install_package(package):
    """Install a package using pip"""
    try:
        print(f"📦 Installing {package}...")
        result = subprocess.check_call([
            sys.executable, "-m", "pip", "install", package
        ])
        print(f"✅ {package} installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install {package}: {e}")
        return False

def main():
    """Install all Solana dependencies"""
    print("🚀 Installing Solana Trading Bot Dependencies")
    print("=" * 60)
    
    # Liste des packages nécessaires pour Solana
    packages = [
        "solana>=0.30.2",
        "solders>=0.18.1", 
        "base58>=2.1.1",
        "construct>=2.10.68",
        "requests>=2.31.0",
        "aiohttp>=3.8.5"
    ]
    
    # Packages optionnels mais recommandés
    optional_packages = [
        "anchorpy>=0.20.1",  # Pour l'intégration DEX avancée
        "bip-utils>=2.9.0"   # Pour les utilitaires crypto
    ]
    
    success_count = 0
    total_packages = len(packages) + len(optional_packages)
    
    # Installation des packages essentiels
    print("🔧 Installing essential packages...")
    for package in packages:
        if install_package(package):
            success_count += 1
        else:
            print(f"⚠️ Essential package {package} failed to install")
    
    # Installation des packages optionnels
    print("\n🔧 Installing optional packages...")
    for package in optional_packages:
        if install_package(package):
            success_count += 1
        else:
            print(f"⚠️ Optional package {package} failed to install (non-critical)")
    
    print("\n" + "=" * 60)
    print("INSTALLATION SUMMARY")
    print("=" * 60)
    print(f"Successfully installed: {success_count}/{total_packages} packages")
    
    if success_count >= len(packages):  # Au moins les essentiels
        print("✅ Solana client should work correctly!")
        print("\nNext steps:")
        print("1. Configure your wallet in .env file:")
        print("   SOLANA_PRIVATE_KEY=your_private_key_here")
        print("2. Test the client:")
        print("   python main.py --test-solana")
        return True
    else:
        print("❌ Some essential packages failed to install")
        print("Try running manually:")
        for package in packages:
            print(f"   pip install {package}")
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n🛑 Installation interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Installation failed: {e}")
        sys.exit(1)