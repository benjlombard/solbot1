import asyncio
import random
from typing import List, Dict, Any

async def get_security_scores_for_mints(mints: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Mock function to simulate fetching security scores for token mints.
    In a real implementation, this would call an external security analysis API.
    """
    if not mints:
        return {}

    # Simulate a non-blocking API call
    await asyncio.sleep(0.1) 

    results = {}
    for mint in mints:
        # Generate some plausible fake data
        rug_probability = round(random.uniform(0.05, 0.85), 2)
        
        if rug_probability > 0.7:
            risk_level = "High"
        elif rug_probability > 0.4:
            risk_level = "Medium"
        else:
            risk_level = "Low"
            
        results[mint] = {
            "rug_probability": rug_probability,
            "risk_level": risk_level,
            "ownership_renounced": random.choice([True, False]),
            "liquidity_locked_percent": round(random.uniform(70, 100), 1)
        }
        
    return results
