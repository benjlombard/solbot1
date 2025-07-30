#!/usr/bin/env python3
"""
🔍 Script de vérification des holders - Base de données vs APIs externes
Compare le nombre de holders stockés avec les données réelles de Helius, Solscan et DexScreener
"""

import sqlite3
import asyncio
import aiohttp
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import argparse
import sys
from dataclasses import dataclass

@dataclass
class HoldersComparison:
    """Structure pour stocker les résultats de comparaison"""
    symbol: str
    address: str
    db_holders: int
    helius_holders: Optional[int] = None
    solscan_holders: Optional[int] = None
    dexscreener_holders: Optional[int] = None
    helius_diff: Optional[float] = None
    solscan_diff: Optional[float] = None
    dexscreener_diff: Optional[float] = None
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []

class HoldersVerifier:
    """Classe principale pour vérifier les holders"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.helius_api_key = ""
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Rate limiting
        self.helius_delay = 1.0  # 1 seconde entre les calls Helius
        self.solscan_delay = 2.0  # 2 secondes entre les calls Solscan
        self.dexscreener_delay = 1.5  # 1.5 secondes entre les calls DexScreener
        
    async def __aenter__(self):
        """Context manager pour la session aiohttp"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            connector=aiohttp.TCPConnector(limit=10)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Fermer la session"""
        if self.session:
            await self.session.close()
    
    def get_tokens_to_verify(self, limit: int = 20, filter_recent_dex: bool = True) -> List[Tuple[str, str, int]]:
        """
        Récupère les tokens à vérifier depuis la base de données
        Priorise les tokens avec données DexScreener récentes
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            base_query = """
                SELECT address, symbol, holders, dexscreener_price_usd, updated_at, 
                       dexscreener_volume_24h, volume_24h
                FROM tokens 
                WHERE symbol IS NOT NULL 
                AND symbol != 'UNKNOWN' 
                AND symbol != ''
                AND holders IS NOT NULL 
                AND holders > 0
            """
            
            if filter_recent_dex:
                # Prioriser les tokens avec données DexScreener récentes et activité
                query = base_query + """
                    AND dexscreener_price_usd > 0 
                    AND updated_at > datetime('now', '-6 hours', 'localtime')
                    AND (dexscreener_volume_24h > 10000 OR volume_24h > 10000)
                    ORDER BY 
                        CASE WHEN dexscreener_volume_24h > 100000 THEN 1 ELSE 2 END,
                        updated_at DESC,
                        dexscreener_volume_24h DESC NULLS LAST
                    LIMIT ?
                """
            else:
                # Prendre un échantillon plus large
                query = base_query + """
                    ORDER BY 
                        CASE WHEN dexscreener_price_usd > 0 THEN 1 ELSE 2 END,
                        CASE WHEN updated_at > datetime('now', '-24 hours', 'localtime') THEN 1 ELSE 2 END,
                        holders DESC
                    LIMIT ?
                """
            
            cursor.execute(query, (limit,))
            tokens = cursor.fetchall()
            
            print(f"📊 Sélection de {len(tokens)} tokens pour vérification:")
            print(f"   - Filtre DexScreener récent: {'✅' if filter_recent_dex else '❌'}")
            
            # Afficher quelques stats sur la sélection
            if tokens:
                avg_holders = sum(t[2] for t in tokens) / len(tokens)
                max_holders = max(t[2] for t in tokens)
                min_holders = min(t[2] for t in tokens)
                
                with_dex_data = sum(1 for t in tokens if len(t) > 3 and t[3] and t[3] > 0)
                
                print(f"   - Holders moyen: {avg_holders:.0f}")
                print(f"   - Holders min/max: {min_holders}/{max_holders}")
                print(f"   - Avec données DexScreener: {with_dex_data}/{len(tokens)}")
            
            return [(t[0], t[1], t[2]) for t in tokens]
            
        except Exception as e:
            print(f"❌ Erreur lors de la récupération des tokens: {e}")
            return []
        finally:
            conn.close()
    
    async def verify_holders_helius(self, address: str) -> Optional[int]:
        """Vérifier le nombre de holders via l'API Helius"""
        try:
            url = f"https://rpc.helius.xyz/?api-key={self.helius_api_key}"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [address]
            }
            
            async with self.session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if "result" in data and "value" in data["result"]:
                        accounts = data["result"]["value"]
                        # Compter seulement les comptes avec un solde > 0
                        active_holders = len([acc for acc in accounts if acc.get("uiAmount", 0) > 0])
                        return active_holders
                    else:
                        return None
                else:
                    print(f"   ⚠️ Helius HTTP {response.status} pour {address[:8]}...")
                    return None
                    
        except Exception as e:
            print(f"   ❌ Erreur Helius pour {address[:8]}...: {e}")
            return None
    
    async def verify_holders_solscan(self, address: str) -> Optional[int]:
        """Vérifier le nombre de holders via l'API Solscan"""
        try:
            url = f"https://public-api.solscan.io/token/holders?tokenAddress={address}&limit=1"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("total", 0)
                elif response.status == 429:
                    print(f"   ⚠️ Solscan rate limit pour {address[:8]}...")
                    return None
                else:
                    print(f"   ⚠️ Solscan HTTP {response.status} pour {address[:8]}...")
                    return None
                    
        except Exception as e:
            print(f"   ❌ Erreur Solscan pour {address[:8]}...: {e}")
            return None
    
    async def verify_holders_dexscreener(self, address: str) -> Optional[int]:
        """
        ❌ DexScreener ne fournit PAS le nombre de holders
        Cette fonction est conservée pour compatibilité mais retourne toujours None
        """
        # DexScreener API ne contient pas les données de holders
        # Les données disponibles sont: price, volume, liquidity, transactions, etc.
        # Mais pas le nombre de holders
        return None
    
    async def verify_single_token(self, address: str, symbol: str, db_holders: int) -> HoldersComparison:
        """Vérifier un token contre toutes les APIs"""
        print(f"🔍 Vérification {symbol} ({address[:8]}...) - DB: {db_holders} holders")
        
        comparison = HoldersComparison(
            symbol=symbol,
            address=address,
            db_holders=db_holders
        )
        
        # Vérification Helius
        try:
            comparison.helius_holders = await self.verify_holders_helius(address)
            await asyncio.sleep(self.helius_delay)
            
            if comparison.helius_holders is not None:
                comparison.helius_diff = self.calculate_percentage_diff(
                    db_holders, comparison.helius_holders
                )
        except Exception as e:
            comparison.errors.append(f"Helius: {e}")
        
        # Vérification Solscan
        try:
            comparison.solscan_holders = await self.verify_holders_solscan(address)
            await asyncio.sleep(self.solscan_delay)
            
            if comparison.solscan_holders is not None:
                comparison.solscan_diff = self.calculate_percentage_diff(
                    db_holders, comparison.solscan_holders
                )
        except Exception as e:
            comparison.errors.append(f"Solscan: {e}")
        
        # ❌ DexScreener ne fournit pas les holders - Skip cette vérification
        # try:
        #     comparison.dexscreener_holders = await self.verify_holders_dexscreener(address)
        #     await asyncio.sleep(self.dexscreener_delay)
        #     
        #     if comparison.dexscreener_holders is not None:
        #         comparison.dexscreener_diff = self.calculate_percentage_diff(
        #             db_holders, comparison.dexscreener_holders
        #         )
        # except Exception as e:
        #     comparison.errors.append(f"DexScreener: {e}")
        
        # DexScreener ne fournit pas les holders, on skip cette vérification
        comparison.dexscreener_holders = None
        comparison.dexscreener_diff = None
        
        return comparison
    
    @staticmethod
    def calculate_percentage_diff(value1: int, value2: int) -> float:
        """Calculer la différence en pourcentage"""
        if value1 == 0 and value2 == 0:
            return 0.0
        if value1 == 0:
            return 100.0
        return abs(value1 - value2) / value1 * 100
    
    async def verify_batch(self, tokens: List[Tuple[str, str, int]]) -> List[HoldersComparison]:
        """Vérifier un batch de tokens"""
        results = []
        
        for i, (address, symbol, db_holders) in enumerate(tokens, 1):
            print(f"\n--- Token {i}/{len(tokens)} ---")
            
            comparison = await self.verify_single_token(address, symbol, db_holders)
            results.append(comparison)
            
            # Affichage des résultats immédiats
            self.print_comparison_result(comparison)
        
        return results
    
    def print_comparison_result(self, comparison: HoldersComparison):
        """Afficher le résultat d'une comparaison"""
        print(f"📊 Résultats pour {comparison.symbol}:")
        print(f"   🗄️  Base de données: {comparison.db_holders}")
        
        if comparison.helius_holders is not None:
            emoji = "✅" if comparison.helius_diff < 10 else "⚠️" if comparison.helius_diff < 25 else "❌"
            print(f"   🔵 Helius: {comparison.helius_holders} ({comparison.helius_diff:.1f}% écart) {emoji}")
        else:
            print(f"   🔵 Helius: ❌ Non disponible")
        
        if comparison.solscan_holders is not None:
            emoji = "✅" if comparison.solscan_diff < 10 else "⚠️" if comparison.solscan_diff < 25 else "❌"
            print(f"   🟡 Solscan: {comparison.solscan_holders} ({comparison.solscan_diff:.1f}% écart) {emoji}")
        else:
            print(f"   🟡 Solscan: ❌ Non disponible")
        
        # ❌ DexScreener ne fournit pas les holders
        print(f"   🟢 DexScreener: ❌ Ne fournit pas les holders")
        
        if comparison.errors:
            print(f"   ⚠️ Erreurs: {', '.join(comparison.errors)}")
    
    def generate_report(self, results: List[HoldersComparison]) -> Dict:
        """Générer un rapport de synthèse"""
        if not results:
            return {"error": "Aucun résultat à analyser"}
        
        report = {
            "total_verified": len(results),
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "helius": {"available": 0, "accurate": 0, "warnings": 0, "errors": 0},
                "solscan": {"available": 0, "accurate": 0, "warnings": 0, "errors": 0},
                "dexscreener": {"available": 0, "accurate": 0, "warnings": 0, "errors": 0}
            },
            "accuracy_stats": {},
            "problematic_tokens": [],
            "best_source": None
        }
        
        # Analyser chaque source
        for source in ["helius", "solscan", "dexscreener"]:
            source_data = report["summary"][source]
            diffs = []
            
            for result in results:
                holders_attr = f"{source}_holders"
                diff_attr = f"{source}_diff"
                
                holders = getattr(result, holders_attr)
                diff = getattr(result, diff_attr)
                
                if holders is not None:
                    source_data["available"] += 1
                    diffs.append(diff)
                    
                    if diff < 10:
                        source_data["accurate"] += 1
                    elif diff < 25:
                        source_data["warnings"] += 1
                    else:
                        source_data["errors"] += 1
                        
                        # Ajouter aux tokens problématiques
                        report["problematic_tokens"].append({
                            "symbol": result.symbol,
                            "address": result.address,
                            "source": source,
                            "db_holders": result.db_holders,
                            "api_holders": holders,
                            "diff_percentage": diff
                        })
            
            # Calculer les stats de précision pour cette source
            if diffs:
                report["accuracy_stats"][source] = {
                    "avg_diff": sum(diffs) / len(diffs),
                    "max_diff": max(diffs),
                    "min_diff": min(diffs),
                    "accuracy_rate": source_data["accurate"] / source_data["available"] * 100
                }
        
        # Déterminer la meilleure source
        best_accuracy = 0
        for source, stats in report["accuracy_stats"].items():
            if stats["accuracy_rate"] > best_accuracy:
                best_accuracy = stats["accuracy_rate"]
                report["best_source"] = source
        
        return report
    
    def print_final_report(self, report: Dict):
        """Afficher le rapport final"""
        print("\n" + "="*60)
        print("📋 RAPPORT FINAL - VÉRIFICATION HOLDERS")
        print("="*60)
        
        if "error" in report:
            print(f"❌ {report['error']}")
            return
        
        print(f"📊 Tokens vérifiés: {report['total_verified']}")
        print(f"⏰ Timestamp: {report['timestamp']}")
        
        print(f"\n📈 PRÉCISION PAR SOURCE:")
        for source, summary in report["summary"].items():
            if summary["available"] > 0:
                accuracy_rate = summary["accurate"] / summary["available"] * 100
                print(f"   {source.upper()}:")
                print(f"      Disponible: {summary['available']}/{report['total_verified']} tokens")
                print(f"      Précis (<10% écart): {summary['accurate']} ({accuracy_rate:.1f}%)")
                print(f"      Avertissements (10-25%): {summary['warnings']}")
                print(f"      Erreurs (>25%): {summary['errors']}")
                
                if source in report["accuracy_stats"]:
                    stats = report["accuracy_stats"][source]
                    print(f"      Écart moyen: {stats['avg_diff']:.1f}%")
            else:
                print(f"   {source.upper()}: ❌ Aucune donnée disponible")
        
        if report["best_source"]:
            print(f"\n🏆 MEILLEURE SOURCE: {report['best_source'].upper()}")
        
        # Tokens problématiques
        problematic = report["problematic_tokens"]
        if problematic:
            print(f"\n⚠️ TOKENS PROBLÉMATIQUES ({len(problematic)}):")
            for token in problematic[:10]:  # Limiter à 10
                print(f"   {token['symbol']}: DB={token['db_holders']}, "
                      f"{token['source']}={token['api_holders']} "
                      f"({token['diff_percentage']:.1f}% écart)")
            
            if len(problematic) > 10:
                print(f"   ... et {len(problematic) - 10} autres")
        
        print("\n🔗 LIENS DE VÉRIFICATION MANUELLE:")
        for token in problematic[:3]:
            print(f"   {token['symbol']}: https://solscan.io/token/{token['address']}")

async def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="Vérification des holders vs APIs externes")
    parser.add_argument("--tokens", "-t", type=int, default=15, 
                       help="Nombre de tokens à vérifier (défaut: 15)")
    parser.add_argument("--database", "-d", default="tokens.db",
                       help="Chemin vers la base de données (défaut: tokens.db)")
    parser.add_argument("--all", action="store_true",
                       help="Vérifier tous les tokens (sans filtre DexScreener)")
    parser.add_argument("--export", "-e", 
                       help="Exporter les résultats en JSON vers ce fichier")
    
    args = parser.parse_args()
    
    print("🔍 VÉRIFICATION HOLDERS - BASE DE DONNÉES vs APIs EXTERNES")
    print("="*60)
    
    async with HoldersVerifier(args.database) as verifier:
        # Récupérer les tokens à vérifier
        tokens = verifier.get_tokens_to_verify(
            limit=args.tokens, 
            filter_recent_dex=not args.all
        )
        
        if not tokens:
            print("❌ Aucun token trouvé à vérifier")
            return
        
        print(f"\n🚀 Début de la vérification de {len(tokens)} tokens...")
        start_time = time.time()
        
        # Vérifier les tokens
        results = await verifier.verify_batch(tokens)
        
        # Générer et afficher le rapport
        report = verifier.generate_report(results)
        verifier.print_final_report(report)
        
        # Exporter si demandé
        if args.export:
            with open(args.export, 'w', encoding='utf-8') as f:
                json.dump({
                    "report": report,
                    "detailed_results": [
                        {
                            "symbol": r.symbol,
                            "address": r.address,
                            "db_holders": r.db_holders,
                            "helius_holders": r.helius_holders,
                            "solscan_holders": r.solscan_holders,
                            "dexscreener_holders": r.dexscreener_holders,
                            "helius_diff": r.helius_diff,
                            "solscan_diff": r.solscan_diff,
                            "dexscreener_diff": r.dexscreener_diff,
                            "errors": r.errors
                        } for r in results
                    ]
                }, f, indent=2)
            print(f"\n💾 Résultats exportés vers: {args.export}")
        
        duration = time.time() - start_time
        print(f"\n⏱️ Vérification terminée en {duration:.1f} secondes")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Vérification interrompue par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erreur fatale: {e}")
        sys.exit(1)