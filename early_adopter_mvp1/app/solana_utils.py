import struct
from solders.pubkey import Pubkey
from solders.rpc.async_client import AsyncClient
from typing import Dict, Optional

# Constants
PUMP_FUN_PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

def get_bonding_curve_address(token_mint_address: str) -> str:
    """
    Calculates the PDA for the bonding curve account.
    This is a standard PDA calculation based on seeds.
    """
    mint_pubkey = Pubkey.from_string(token_mint_address)
    seeds = [b'bonding-curve', bytes(mint_pubkey)]
    bonding_curve_pubkey, _ = Pubkey.find_program_address(seeds, PUMP_FUN_PROGRAM_ID)
    return str(bonding_curve_pubkey)

def get_associated_bonding_curve_address(bonding_curve_address: str, token_mint_address: str) -> str:
    """
    Calculates the associated token account for the bonding curve.
    """
    # This is a standard Associated Token Account (ATA) address calculation.
    # It's the ATA for the bonding curve's ownership of the new token.
    # However, the user's sample data suggests this might be a different PDA.
    # The value is already in the database, so we will rely on that primarily.
    # This function is here as a fallback if needed.
    bonding_curve_pubkey = Pubkey.from_string(bonding_curve_address)
    token_mint_pubkey = Pubkey.from_string(token_mint_address)
    
    # Standard ATA derivation
    associated_token_address, _ = Pubkey.find_program_address(
        [bytes(bonding_curve_pubkey), bytes(TOKEN_PROGRAM_ID), bytes(token_mint_pubkey)],
        Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
    )
    return str(associated_token_address)


async def get_pump_progress_correct(
    token_address: str, 
    db_bonding_curve: Optional[str],
    db_associated_bonding_curve: Optional[str]
) -> Optional[Dict]:
    """
    Solution corrigée utilisant la vraie bonding curve pour calculer le progrès.
    Utilise les valeurs de la DB si disponibles, sinon les calcule.
    """
    print(f"🔍 Getting progress for: {token_address}")
    
    try:
        bonding_curve_address = db_bonding_curve or get_bonding_curve_address(token_address)
        
        # NOTE: The associated curve address is not a standard ATA, so we must rely on the DB value.
        # If it's missing, we cannot proceed. The user's initial data scraping must capture this.
        if not db_associated_bonding_curve:
            print(f"❌ Missing associated_bonding_curve in database for {token_address}. Cannot calculate progress.")
            return None
        
        associated_bonding_curve = db_associated_bonding_curve
        
        print(f"📍 Bonding curve address: {bonding_curve_address}")
        print(f"🏦 Associated bonding curve token account: {associated_bonding_curve}")
        
        client = AsyncClient("https://rpc.helius.xyz/?api-key=b51a900a-0585-48c1-b8f5-b46f4d76d790")
        
        bonding_curve_pubkey = Pubkey.from_string(bonding_curve_address)
        account_info = await client.get_account_info(bonding_curve_pubkey)
        
        if account_info.value and account_info.value.data:
            print(f"✅ Bonding curve account found. Data length: {len(account_info.value.data)} bytes")
            data = account_info.value.data
            
            try:
                # Bonding curve data structure from https://gist.github.com/rubpy/6c57e9d12acd4b6ed84e9f205372631d
                virtual_token_reserves = struct.unpack('<Q', data[8:16])[0]
                virtual_sol_reserves = struct.unpack('<Q', data[16:24])[0]
                
                # Calcul du progrès selon la formule fournie par l'utilisateur
                initial_virtual_tokens = 1_073_000_000  # Total virtual tokens at the start
                tokens_to_sell = 793_100_000      # Total sellable virtual tokens
                
                tokens_sold_virtual = (initial_virtual_tokens * 10**6 - virtual_token_reserves) / (10**6)
                
                if tokens_to_sell > 0:
                    progress = (tokens_sold_virtual / tokens_to_sell) * 100
                else:
                    progress = 100.0
                    
                progress = max(0, min(progress, 100)) # Clamp between 0 and 100
                
                print(f"🎯 Progress (user formula): {progress:.2f}%")
                
                await client.close()
                
                return {
                    'bonding_curve_progress': round(progress, 2),
                    'success': True
                }
                
            except Exception as e:
                print(f"❌ Error decoding bonding curve data for {token_address}: {e}")
        
        await client.close()
        
    except Exception as e:
        print(f"❌ Bonding curve method failed for {token_address}: {e}")
    
    return None
