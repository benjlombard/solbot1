#!/usr/bin/env python3
"""
Test Solana Client - Script de test autonome
File: test_solana.py

Script pour tester le client Solana indépendamment du bot principal.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

# Import our modules
from config import get_config
from solana_client import create_solana_client, SolanaClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_basic_functionality():
    """Test basic Solana client functionality"""
    print("🔗 Testing Solana Client Basic Functionality")
    print("=" * 60)
    
    try:
        # Load configuration
        config = get_config()
        
        # Check if we have required keys
        if not config['solana']['wallet_private_key']:
            print("❌ No private key configured in environment")
            print("   Set SOLANA_PRIVATE_KEY in your .env file")
            return False
        
        # Create client
        print("🔧 Creating Solana client...")
        solana_client = create_solana_client(config)
        
        print(f"✅ Client created for wallet: {solana_client.wallet_address}")
        
        # Test 1: Health check
        print("\n🏥 Testing RPC connection...")
        health = await solana_client.health_check()
        
        print(f"   Status: {health['status']}")
        print(f"   RPC Latency: {health.get('rpc_latency_ms', 0):.1f}ms")
        
        if health['status'] != 'healthy':
            print(f"❌ RPC connection failed: {health.get('error', 'Unknown error')}")
            return False
        
        # Test 2: Get balance
        print("\n💰 Testing balance retrieval...")
        sol_balance = await solana_client.get_balance()
        print(f"   SOL Balance: {sol_balance:.6f}")
        
        # Test 3: Get complete balance
        print("\n📊 Testing complete balance...")
        complete_balance = await solana_client.get_balance('ALL')
        print(f"   SOL: {complete_balance.sol_balance:.6f}")
        print(f"   Token accounts: {len(complete_balance.token_balances)}")
        print(f"   Estimated value: ${complete_balance.total_value_usd:.2f}")
        
        # Test 4: Token info
        print("\n🪙 Testing token info retrieval...")
        usdc_info = await solana_client.get_token_info(solana_client.COMMON_TOKENS['USDC'])
        if usdc_info:
            print(f"   USDC decimals: {usdc_info.decimals}")
            print(f"   USDC supply: {usdc_info.supply}")
        
        # Test 5: Price fetching
        print("\n💱 Testing price fetching...")
        usdc_price = await solana_client.get_token_price(solana_client.COMMON_TOKENS['USDC'], 'SOL')
        if usdc_price:
            print(f"   USDC/SOL price: {usdc_price:.6f}")
        
        # Test 6: Performance metrics
        print("\n📈 Performance metrics...")
        metrics = solana_client.get_performance_metrics()
        print(f"   Total transactions: {metrics['total_transactions']}")
        print(f"   Success rate: {metrics['success_rate_percent']:.1f}%")
        
        # Close client
        await solana_client.close()
        
        print("\n✅ All basic tests passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        logger.error(f"Test error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_swap_quote():
    """Test swap quote functionality"""
    print("\n🔄 Testing Swap Quote Functionality")
    print("=" * 60)
    
    try:
        config = get_config()
        
        if not config['solana']['wallet_private_key']:
            print("❌ No private key configured")
            return False
        
        async with create_solana_client(config) as client:
            # Test Jupiter quote
            from solana_client import SwapParams, DEXType
            
            params = SwapParams(
                input_token=client.COMMON_TOKENS['SOL'],
                output_token=client.COMMON_TOKENS['USDC'],
                amount=0.1,  # 0.1 SOL
                slippage=0.01,  # 1%
                dex_preference=DEXType.JUPITER
            )
            
            print(f"🔍 Getting quote: 0.1 SOL → USDC")
            quote = await client.get_swap_quote(params)
            
            if quote:
                output_decimals = 6  # USDC decimals
                output_amount_ui = quote.output_amount / (10 ** output_decimals)
                
                print(f"✅ Quote received:")
                print(f"   Input: {params.amount} SOL")
                print(f"   Output: {output_amount_ui:.6f} USDC")
                print(f"   Price impact: {quote.price_impact_pct:.3%}")
                print(f"   Slippage: {quote.slippage_bps / 100:.2f}%")
                print(f"   Route steps: {len(quote.route_plan)}")
                
                return True
            else:
                print("❌ Failed to get quote")
                return False
                
    except Exception as e:
        print(f"❌ Swap quote test failed: {e}")
        return False

async def test_transaction_simulation():
    """Test transaction simulation (without actual execution)"""
    print("\n🧪 Testing Transaction Simulation")
    print("=" * 60)
    
    try:
        config = get_config()
        
        if not config['solana']['wallet_private_key']:
            print("❌ No private key configured")
            return False
        
        async with create_solana_client(config) as client:
            # Check if we have enough SOL for testing
            sol_balance = await client.get_balance()
            
            if sol_balance < 0.01:
                print(f"❌ Insufficient SOL for testing: {sol_balance:.6f}")
                print("   Need at least 0.01 SOL for simulation tests")
                return False
            
            print(f"💰 Wallet has {sol_balance:.6f} SOL - sufficient for testing")
            
            # Test swap simulation
            from solana_client import SwapParams, DEXType
            
            params = SwapParams(
                input_token=client.COMMON_TOKENS['SOL'],
                output_token=client.COMMON_TOKENS['USDC'],
                amount=0.001,  # Very small amount
                slippage=0.01
            )
            
            quote = await client.get_swap_quote(params)
            if quote:
                print("✅ Swap quote obtained for simulation")
                
                # Simulate without executing
                simulation_ok = await client._simulate_swap(quote)
                print(f"🧪 Simulation result: {'✅ PASS' if simulation_ok else '❌ FAIL'}")
                
                return simulation_ok
            else:
                print("❌ Could not get quote for simulation")
                return False
                
    except Exception as e:
        print(f"❌ Simulation test failed: {e}")
        return False

async def test_token_account_operations():
    """Test token account operations"""
    print("\n🪙 Testing Token Account Operations")
    print("=" * 60)
    
    try:
        config = get_config()
        async with create_solana_client(config) as client:
            
            # Test getting token balance for USDC
            usdc_balance = await client._get_token_balance(client.COMMON_TOKENS['USDC'])
            print(f"💰 USDC balance: {usdc_balance:.6f}")
            
            # Test token info for various tokens
            test_tokens = [
                ('USDC', client.COMMON_TOKENS['USDC']),
                ('USDT', client.COMMON_TOKENS['USDT']),
            ]
            
            for symbol, address in test_tokens:
                info = await client.get_token_info(address)
                if info:
                    print(f"🪙 {symbol}: {info.decimals} decimals, supply: {info.supply}")
                else:
                    print(f"❌ Could not get info for {symbol}")
            
            return True
            
    except Exception as e:
        print(f"❌ Token account test failed: {e}")
        return False

async def comprehensive_test():
    """Run comprehensive test suite"""
    print("🚀 Solana Client Comprehensive Test Suite")
    print("=" * 80)
    print(f"Test started at: {datetime.now()}")
    print()
    
    tests = [
        ("Basic Functionality", test_basic_functionality),
        ("Swap Quotes", test_swap_quote),
        ("Transaction Simulation", test_transaction_simulation),
        ("Token Account Operations", test_token_account_operations),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            print(f"\n{'='*20} {test_name} {'='*20}")
            result = await test_func()
            results.append((test_name, result))
            
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"\n{test_name}: {status}")
            
        except Exception as e:
            print(f"\n❌ {test_name}: EXCEPTION - {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test_name:<30} {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 All tests passed! Solana client is working correctly.")
    else:
        print(f"⚠️ {total - passed} test(s) failed. Check configuration and network.")
    
    return passed == total

def main():
    """Main test function"""
    print("Solana Client Test Suite")
    print("Make sure you have:")
    print("1. SOLANA_PRIVATE_KEY in your .env file")
    print("2. Internet connection")
    print("3. Some SOL in your wallet for testing")
    print()
    
    try:
        # Run comprehensive tests
        success = asyncio.run(comprehensive_test())
        return 0 if success else 1
        
    except KeyboardInterrupt:
        print("\n🛑 Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)