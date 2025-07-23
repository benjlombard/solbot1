#!/usr/bin/env python3
"""
Diagnostic des dépendances Solana
File: check_solana_deps.py

Script pour vérifier que toutes les dépendances Solana sont correctement installées.
Compatible avec la nouvelle API Solana/solders.
"""

import sys
import importlib

def check_import(module_name, description=""):
    """Check if a module can be imported"""
    try:
        module = importlib.import_module(module_name)
        version = getattr(module, '__version__', 'unknown')
        print(f"✅ {module_name:<20} {version:<10} {description}")
        return True
    except ImportError as e:
        print(f"❌ {module_name:<20} {'MISSING':<10} {description}")
        print(f"   Error: {e}")
        return False

def check_solana_specific():
    """Check Solana-specific functionality with new API"""
    print("\n🔧 Testing Solana-specific functionality...")
    
    try:
        from solana.rpc.api import Client
        print("✅ Solana RPC API imported successfully")
        
        # Test using NEW API first (solders)
        try:
            from solders.keypair import Keypair
            from solders.pubkey import Pubkey
            from solders.transaction import Transaction
            
            print("✅ Solders API (new) - Using recommended API")
            
            # Test creating a keypair with new API
            try:
                keypair = Keypair()
                print(f"✅ Keypair generation works: {keypair.pubkey()}")
            except Exception as e:
                print(f"❌ Keypair generation failed: {e}")
                return False
            
            # Test PublicKey with new API
            try:
                pubkey = Pubkey.from_string("11111111111111111111111111111112")
                print(f"✅ Pubkey creation works: {pubkey}")
            except Exception as e:
                print(f"❌ Pubkey creation failed: {e}")
                return False
            
            api_type = "solders (recommended)"
            
        except ImportError:
            # Fallback to old API
            try:
                from solana.keypair import Keypair
                from solana.publickey import PublicKey
                from solana.transaction import Transaction
                
                print("⚠️ Legacy API - Consider upgrading to solders")
                
                # Test with old API
                try:
                    keypair = Keypair.generate()
                    print("✅ Keypair generation works (legacy)")
                except Exception as e:
                    print(f"❌ Keypair generation failed: {e}")
                    return False
                
                try:
                    pubkey = PublicKey("11111111111111111111111111111112")
                    print("✅ PublicKey creation works (legacy)")
                except Exception as e:
                    print(f"❌ PublicKey creation failed: {e}")
                    return False
                
                api_type = "legacy"
                
            except ImportError as e:
                print(f"❌ No usable Solana API found: {e}")
                return False
        
        # Test creating a client (without connecting)
        try:
            client = Client("https://api.mainnet-beta.solana.com")
            print("✅ Solana RPC client can be created")
        except Exception as e:
            print(f"⚠️ RPC client creation issue: {e}")
        
        print(f"🔧 Using {api_type} API")
        return True
        
    except ImportError as e:
        print(f"❌ Solana core functionality not available: {e}")
        return False

def check_spl_token():
    """Check SPL Token functionality"""
    print("\n🪙 Testing SPL Token functionality...")
    
    try:
        from spl.token.client import Token
        from spl.token.constants import TOKEN_PROGRAM_ID
        from spl.token.instructions import get_associated_token_address
        
        print("✅ SPL Token imports successful")
        
        # Test with new API if available
        try:
            from solders.pubkey import Pubkey
            owner = Pubkey.from_string("11111111111111111111111111111112")
            mint = Pubkey.from_string("So11111111111111111111111111111111111111112")  # SOL mint
            ata = get_associated_token_address(owner, mint)
            print(f"✅ Associated token address (solders): {ata}")
        except ImportError:
            # Fallback to old API
            try:
                from solana.publickey import PublicKey
                owner = PublicKey("11111111111111111111111111111112")
                mint = PublicKey("So11111111111111111111111111111111111111112")
                ata = get_associated_token_address(owner, mint)
                print(f"✅ Associated token address (legacy): {ata}")
            except Exception as e:
                print(f"⚠️ Token address creation issue: {e}")
        
        return True
        
    except ImportError as e:
        print(f"❌ SPL Token not available: {e}")
        return False

def check_api_compatibility():
    """Check which API version is available and recommend best choice"""
    print("\n🔄 API Compatibility Check...")
    
    solders_available = False
    legacy_available = False
    
    try:
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from solders.transaction import Transaction
        solders_available = True
        print("✅ Solders API available (recommended)")
    except ImportError:
        print("❌ Solders API not available")
    
    try:
        from solana.keypair import Keypair
        from solana.publickey import PublicKey
        from solana.transaction import Transaction
        legacy_available = True
        print("✅ Legacy API available")
    except ImportError:
        print("❌ Legacy API not available")
    
    if solders_available:
        print("🎯 Recommendation: Use solders API (already available)")
        return "solders"
    elif legacy_available:
        print("⚠️ Recommendation: Upgrade to solders API")
        print("   Run: pip install --upgrade solana solders")
        return "legacy"
    else:
        print("❌ No Solana API available")
        return "none"

def main():
    """Main diagnostic function"""
    print("🔍 Solana Dependencies Diagnostic (New API Compatible)")
    print("=" * 70)
    
    # Core dependencies
    print("📦 Core Dependencies:")
    core_deps = [
        ("requests", "HTTP client"),
        ("aiohttp", "Async HTTP client"),
        ("base58", "Base58 encoding"),
        ("construct", "Binary data parsing")
    ]
    
    core_success = 0
    for module, desc in core_deps:
        if check_import(module, desc):
            core_success += 1
    
    # Solana dependencies
    print("\n🔗 Solana Dependencies:")
    solana_deps = [
        ("solana", "Main Solana library"),
        ("solders", "Solana Rust bindings (recommended)"),
        ("spl.token", "SPL Token support")
    ]
    
    solana_success = 0
    for module, desc in solana_deps:
        if check_import(module, desc):
            solana_success += 1
    
    # Optional dependencies
    print("\n🔧 Optional Dependencies:")
    optional_deps = [
        ("anchorpy", "Anchor framework support"),
        ("bip_utils", "BIP utilities")
    ]
    
    optional_success = 0
    for module, desc in optional_deps:
        if check_import(module, desc):
            optional_success += 1
    
    # API compatibility check
    api_type = check_api_compatibility()
    
    # Detailed tests
    solana_functional = check_solana_specific()
    spl_functional = check_spl_token()
    
    # Summary
    print("\n" + "=" * 70)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 70)
    
    print(f"Core dependencies:     {core_success}/{len(core_deps)}")
    print(f"Solana dependencies:   {solana_success}/{len(solana_deps)}")
    print(f"Optional dependencies: {optional_success}/{len(optional_deps)}")
    print(f"Solana functionality:  {'✅' if solana_functional else '❌'}")
    print(f"SPL Token support:     {'✅' if spl_functional else '❌'}")
    print(f"API type:              {api_type}")
    
    # Determine overall status
    essential_ok = (core_success == len(core_deps) and 
                   solana_success >= 2 and  # At least solana + one of solders/legacy
                   solana_functional)
    
    if essential_ok:
        print("\n🎉 All essential dependencies are working!")
        print("✅ Solana client should function correctly")
        
        if api_type == "legacy":
            print("\n⚠️ API Upgrade Recommendation:")
            print("   Your setup uses the legacy API. For better performance:")
            print("   pip install --upgrade solana solders")
        elif api_type == "solders":
            print("\n🚀 You're using the latest recommended API!")
        
        if optional_success < len(optional_deps):
            print("⚠️ Some optional features may be limited")
        
        print("\nNext steps:")
        print("1. Configure your wallet in .env:")
        print("   SOLANA_PRIVATE_KEY=your_private_key")
        print("2. Test the client:")
        print("   python main.py --test-solana")
        print("3. Run quick test:")
        print("   python utils/quick_test.py")
        
    else:
        print("\n❌ Some essential dependencies are missing")
        print("\nTo fix, run:")
        print("   python utils/install_solana_deps.py")
        print("Or manually install:")
        if api_type == "none":
            print("   pip install solana solders spl-token base58 requests aiohttp")
        else:
            print("   pip install --upgrade solana solders")
    
    print("\n📚 API Migration Guide:")
    print("=" * 70)
    print("Old Import                    →  New Import")
    print("-" * 70)
    print("from solana.publickey import  →  from solders.pubkey import")
    print("from solana.keypair import    →  from solders.keypair import")
    print("from solana.transaction import →  from solders.transaction import")
    print("PublicKey('string')           →  Pubkey.from_string('string')")
    print("Keypair.generate()            →  Keypair()")
    print("keypair.public_key            →  keypair.pubkey()")
    print("=" * 70)
    
    return essential_ok

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)