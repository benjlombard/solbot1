#!/usr/bin/env python3
"""
Test rapide des imports Solana
File: quick_test.py

Test rapide pour voir si les imports Solana fonctionnent avec la nouvelle API.
"""

def test_imports():
    """Test les imports essentiels avec la nouvelle API Solana"""
    print("🔍 Testing Solana imports...")
    
    try:
        print("Testing solana...")
        import solana
        print(f"✅ solana: {getattr(solana, '__version__', 'unknown')}")
    except ImportError as e:
        print(f"❌ solana: {e}")
        return False
    
    try:
        print("Testing solders...")
        import solders
        print(f"✅ solders: {getattr(solders, '__version__', 'unknown')}")
    except ImportError as e:
        print(f"❌ solders: {e}")
        return False
    
    try:
        print("Testing solana.rpc.api...")
        from solana.rpc.api import Client
        print("✅ solana.rpc.api: OK")
    except ImportError as e:
        print(f"❌ solana.rpc.api: {e}")
        return False
    
    # Nouvelle API - utilise solders pour Keypair et Pubkey
    try:
        print("Testing solders.keypair...")
        from solders.keypair import Keypair
        print("✅ solders.keypair: OK")
    except ImportError as e:
        print(f"❌ solders.keypair: {e}")
        return False
    
    try:
        print("Testing solders.pubkey...")
        from solders.pubkey import Pubkey
        print("✅ solders.pubkey: OK")
    except ImportError as e:
        print(f"❌ solders.pubkey: {e}")
        return False
    
    try:
        print("Testing solana.transaction...")
        from solana.transaction import Transaction
        print("✅ solana.transaction: OK")
    except ImportError as e:
        print(f"❌ solana.transaction: {e}")
        return False
    
    try:
        print("Testing spl.token...")
        from spl.token.client import Token
        print("✅ spl.token: OK")
    except ImportError as e:
        print(f"❌ spl.token: {e}")
        return False
    
    print("\n🎉 All essential imports working!")
    return True

def test_solana_functionality():
    """Test la fonctionnalité Solana avec la nouvelle API"""
    print("\n🔧 Testing Solana functionality...")
    
    try:
        from solana.rpc.api import Client
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from solana.transaction import Transaction
        
        # Test basic functionality
        print("✅ Basic Solana classes imported successfully")
        
        # Test creating a client (without connecting)
        try:
            client = Client("https://api.mainnet-beta.solana.com")
            print("✅ Solana RPC client can be created")
        except Exception as e:
            print(f"⚠️ RPC client creation issue: {e}")
        
        # Test creating a keypair
        try:
            keypair = Keypair()
            print(f"✅ Keypair generation works: {keypair.pubkey()}")
        except Exception as e:
            print(f"❌ Keypair generation failed: {e}")
            return False
        
        # Test PublicKey
        try:
            pubkey = Pubkey.from_string("11111111111111111111111111111112")
            print(f"✅ Pubkey creation works: {pubkey}")
        except Exception as e:
            print(f"❌ Pubkey creation failed: {e}")
            return False
        
        return True
        
    except ImportError as e:
        print(f"❌ Solana core functionality not available: {e}")
        return False

def test_spl_token():
    """Test SPL Token functionality"""
    print("\n🪙 Testing SPL Token functionality...")
    
    try:
        from spl.token.client import Token
        from spl.token.constants import TOKEN_PROGRAM_ID
        from spl.token.instructions import get_associated_token_address
        from solders.pubkey import Pubkey
        
        print("✅ SPL Token imports successful")
        
        # Test creating a basic token address
        try:
            owner = Pubkey.from_string("11111111111111111111111111111112")
            mint = Pubkey.from_string("So11111111111111111111111111111111111111112")  # SOL mint
            ata = get_associated_token_address(owner, mint)
            print(f"✅ Associated token address creation works: {ata}")
        except Exception as e:
            print(f"⚠️ Token address creation issue: {e}")
        
        return True
        
    except ImportError as e:
        print(f"❌ SPL Token not available: {e}")
        return False

def test_solana_client_import():
    """Test l'import de notre client Solana"""
    print("\n🔍 Testing our solana_client import...")
    
    try:
        from solana_client import create_solana_client, SolanaClient
        print("✅ solana_client imports successfully!")
        return True
    except ImportError as e:
        print(f"❌ solana_client import failed: {e}")
        print("💡 Hint: You might need to update solana_client.py to use the new API")
        return False
    except Exception as e:
        print(f"❌ solana_client error: {e}")
        return False

def test_main_import():
    """Test l'import dans main.py"""
    print("\n🔍 Testing main.py imports...")
    
    try:
        # Test si on peut importer sans erreur
        import sys
        import os
        
        # Ajouter le répertoire actuel au path
        sys.path.insert(0, os.getcwd())
        
        from config import get_config
        print("✅ config import: OK")
        
        config = get_config()
        print("✅ config loading: OK")
        
        from solana_client import create_solana_client
        print("✅ solana_client import: OK")
        
        print("✅ All main.py imports should work!")
        return True
        
    except Exception as e:
        print(f"❌ main.py import test failed: {e}")
        print("💡 Hint: Check if solana_client.py needs updating for new API")
        return False

def show_api_migration_info():
    """Affiche les informations sur la migration de l'API"""
    print("\n📝 API Migration Info:")
    print("=" * 50)
    print("Old API → New API:")
    print("• solana.publickey.PublicKey → solders.pubkey.Pubkey")
    print("• solana.keypair.Keypair → solders.keypair.Keypair")
    print("• PublicKey('string') → Pubkey.from_string('string')")
    print("• Keypair.generate() → Keypair()")
    print("• keypair.public_key → keypair.pubkey()")
    print("=" * 50)

if __name__ == "__main__":
    print("🚀 Quick Solana Test (Updated for New API)")
    print("=" * 60)
    
    success = True
    
    # Test 1: Basic imports
    if not test_imports():
        success = False
    
    # Test 2: Solana functionality
    if not test_solana_functionality():
        success = False
    
    # Test 3: SPL Token
    if not test_spl_token():
        success = False
    
    # Test 4: Our client
    if not test_solana_client_import():
        success = False
    
    # Test 5: Main imports
    if not test_main_import():
        success = False
    
    print("\n" + "=" * 60)
    if success:
        print("✅ All tests passed! You should be able to run:")
        print("   python main.py --test-solana")
    else:
        print("❌ Some tests failed.")
        print("\n🔧 Common fixes:")
        print("1. Update dependencies:")
        print("   pip install --upgrade solana solders")
        print("2. Update your solana_client.py to use new API")
        print("3. Check that all imports use solders instead of solana for keys")
    
    # Afficher les infos de migration
    show_api_migration_info()
    
    print("=" * 60)