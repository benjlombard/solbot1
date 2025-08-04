import requests
import time
import json
import logging
from typing import Optional
from datetime import datetime, timedelta
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

class TokenCreatorAnalyzer:
    def __init__(self, quicknode_endpoint: str = None):
        self.base_url = "https://explorer.solana.com/address/{}/history"
        self.tx_base_url = "https://explorer.solana.com/tx/{}"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self.request_count = 0
        self.quicknode_endpoint = quicknode_endpoint
        self.rpc_client = Client(quicknode_endpoint) if quicknode_endpoint else None
        # Configuration Selenium
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument(f"user-agent={self.headers['User-Agent']}")
        self.driver = webdriver.Chrome(options=chrome_options)

    def _fetch_page_selenium(self, url: str) -> Optional[str]:
        """Récupère le contenu HTML d'une page avec Selenium"""
        try:
            self.request_count += 1
            logger.info(f"Récupération de la page avec Selenium: {url[:50]}...")
            self.driver.get(url)
            # Attendre que la table des transactions soit chargée
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CLASS_NAME, "table"))
            )
            html_content = self.driver.page_source
            logger.info(f"Récupération réussie de la page")
            time.sleep(1)
            return html_content
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la page {url[:50]}...: {e}")
            return None

    def _find_initialize_mint_transaction_selenium(self, html_content: str, token_address: str) -> Optional[dict]:
        """Analyse le HTML pour trouver la transaction initializeMint"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            # Trouver la table des transactions
            transaction_table = soup.find("table", class_="table")
            if not transaction_table:
                logger.error("Tableau des transactions non trouvé")
                return None

            # Parcourir toutes les lignes de la table
            rows = transaction_table.find_all("tr")[1:]  # Ignorer l'en-tête
            logger.info(f"Analyse de {len(rows)} transactions")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 2:
                    continue
                signature = cols[0].find("a").text.strip() if cols[0].find("a") else None
                timestamp_str = cols[2].text.strip() if len(cols) > 2 else "N/A"
                if not signature:
                    continue

                # Récupérer les détails de la transaction
                tx_url = self.tx_base_url.format(signature)
                tx_html = self._fetch_page_selenium(tx_url)
                if not tx_html:
                    continue

                tx_soup = BeautifulSoup(tx_html, 'html.parser')
                # Chercher les instructions
                instruction_sections = tx_soup.find_all("div", class_="term")
                for section in instruction_sections:
                    instruction_name = section.find(string=lambda text: text and "initializemint" in text.lower())
                    if instruction_name:
                        # Trouver le signataire
                        signer_section = tx_soup.find("div", string=lambda text: text and "Signature" in text)
                        signer = None
                        if signer_section:
                            signer_link = signer_section.find_next("a")
                            signer = signer_link.text.strip() if signer_link else "N/A"
                        logger.info(f"Transaction initializeMint trouvée: {signature[:8]}...")
                        logger.info(f"Signataire: {signer}")
                        logger.info(f"Timestamp: {timestamp_str}")
                        return {
                            "signature": signature,
                            "signer": signer,
                            "timestamp": timestamp_str,
                            "block_time": self._parse_timestamp(timestamp_str)
                        }
                
                logger.debug(f"Aucune instruction initializeMint dans la transaction {signature[:8]}...")

            logger.info("Aucune transaction initializeMint trouvée dans la page")
            return None
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse des transactions: {e}")
            return None

    def _parse_timestamp(self, timestamp_str: str) -> Optional[int]:
        """Converti le timestamp de Solana Explorer en Unix timestamp"""
        try:
            # Exemple: "Aug 03, 2025 11:27:00 UTC"
            dt = datetime.strptime(timestamp_str, "%b %d, %Y %H:%M:%S %Z")
            return int(dt.timestamp())
        except Exception as e:
            logger.error(f"Erreur lors du parsing du timestamp {timestamp_str}: {e}")
            return None

    def _get_token_age_dexscreener(self, token_address: str) -> Optional[int]:
        """Récupère l'âge du token depuis DEXScreener"""
        try:
            logger.info("Recherche de l'âge du token sur DEXScreener...")
            url = f"https://dexscreener.com/solana/{token_address}"
            response = requests.get(url, headers=self.headers, timeout=10)
            self.request_count += 1
            if response.status_code != 200:
                logger.error(f"Erreur DEXScreener: {response.status_code}")
                return None

            soup = BeautifulSoup(response.text, 'html.parser')
            age_element = soup.find(string=lambda text: text and "Age:" in text)
            if not age_element:
                logger.error("Âge non trouvé sur DEXScreener")
                return None

            age_text = age_element.strip()
            logger.info(f"Âge trouvé: {age_text}")
            age_seconds = 0
            if "h" in age_text:
                hours = int(age_text.split("h")[0].split(":")[1].strip())
                age_seconds += hours * 3600
            if "m" in age_text:
                minutes = int(age_text.split("m")[0].split("h")[-1].strip())
                age_seconds += minutes * 60

            block_time = int(time.time()) - age_seconds
            logger.info(f"Âge estimé: {age_seconds} secondes, blockTime: {block_time}")
            return block_time
        except Exception as e:
            logger.error(f"Erreur scraping DEXScreener: {e}")
            return None

    def _find_initialize_mint_quicknode(self, token_address: str) -> Optional[dict]:
        """Recherche la transaction initializeMint via QuickNode"""
        if not self.rpc_client:
            logger.error("Client QuickNode non configuré")
            return None

        try:
            # Convertir l'adresse en Pubkey
            pubkey = Pubkey.from_string(token_address)
            logger.info("Recherche des transactions via QuickNode...")
            # Récupérer l'âge depuis DEXScreener pour limiter la fenêtre temporelle
            block_time = self._get_token_age_dexscreener(token_address)
            window_seconds = 10 * 60  # ±10 minutes
            time_lower_bound = block_time - window_seconds if block_time else None
            time_upper_bound = block_time + window_seconds if block_time else None

            # Récupérer toutes les signatures disponibles
            signatures_result = self.rpc_client.get_signatures_for_address(pubkey, limit=1000)
            self.request_count += 1
            signatures = signatures_result.get("result", [])
            if not signatures:
                logger.info("Aucune transaction trouvée via QuickNode")
                return None

            # Filtrer par fenêtre temporelle si disponible
            if time_lower_bound and time_upper_bound:
                signatures = [
                    sig for sig in signatures
                    if sig.get("blockTime") and time_lower_bound <= sig["blockTime"] <= time_upper_bound
                ]
                logger.info(f"{len(signatures)} transactions dans la fenêtre temporelle ±10 min")
            else:
                logger.info(f"Analyse de {len(signatures)} transactions (pas de fenêtre temporelle)")

            for sig_info in signatures:
                signature = sig_info["signature"]
                block_time = sig_info["blockTime"]
                logger.info(f"Analyse de la transaction: {signature[:8]}... (blockTime: {block_time})")
                
                tx_details = self.rpc_client.get_transaction(
                    signature, encoding="jsonParsed", max_supported_transaction_version=0
                )
                self.request_count += 1
                if not tx_details or not tx_details.get("result"):
                    logger.debug(f"Transaction {signature[:8]}... ignorée (pas de détails)")
                    continue

                tx = tx_details["result"]
                if tx.get("meta", {}).get("err"):
                    logger.debug(f"Transaction {signature[:8]}... échouée, ignorée")
                    continue

                # Récupérer le signataire
                signers = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                signer = None
                for account in signers:
                    if account.get("signer"):
                        signer = account["pubkey"]
                        break

                # Chercher initializeMint
                instructions = tx.get("transaction", {}).get("message", {}).get("instructions", [])
                for instruction in instructions:
                    if "parsed" in instruction and instruction["parsed"].get("type") == "initializeMint":
                        logger.info(f"Transaction initializeMint trouvée: {signature[:8]}...")
                        logger.info(f"Signataire: {signer}")
                        logger.info(f"Timestamp: {datetime.fromtimestamp(block_time).strftime('%Y-%m-%d %H:%M:%S')}")
                        return {
                            "signature": signature,
                            "signer": signer,
                            "timestamp": datetime.fromtimestamp(block_time).strftime("%b %d, %Y %H:%M:%S UTC"),
                            "block_time": block_time
                        }

                # Chercher dans les inner instructions
                inner_instructions = tx.get("meta", {}).get("innerInstructions", [])
                for inner_group in inner_instructions:
                    for inner_instruction in inner_group.get("instructions", []):
                        if "parsed" in inner_instruction and inner_instruction["parsed"].get("type") == "initializeMint":
                            logger.info(f"Transaction initializeMint trouvée dans inner: {signature[:8]}...")
                            logger.info(f"Signataire: {signer}")
                            logger.info(f"Timestamp: {datetime.fromtimestamp(block_time).strftime('%Y-%m-%d %H:%M:%S')}")
                            return {
                                "signature": signature,
                                "signer": signer,
                                "timestamp": datetime.fromtimestamp(block_time).strftime("%b %d, %Y %H:%M:%S UTC"),
                                "block_time": block_time
                            }

            logger.info("Aucune transaction initializeMint trouvée via QuickNode")
            return None
        except Exception as e:
            logger.error(f"Erreur QuickNode: {e}")
            return None

    def find_token_creator(self, token_address: str) -> Optional[dict]:
        """Trouve le créateur du token via Solana Explorer ou QuickNode"""
        logger.info(f"🔍 Recherche du créateur pour le token: {token_address}")

        # Étape 1 : Tenter le scraping avec Selenium
        logger.info("Tentative de scraping via Solana Explorer...")
        url = self.base_url.format(token_address)
        html_content = self._fetch_page_selenium(url)
        if html_content:
            result = self._find_initialize_mint_transaction_selenium(html_content, token_address)
            if result:
                logger.info(f"✅ Créateur trouvé via Solana Explorer: {result['signer']}")
                if result["block_time"]:
                    age_seconds = int(time.time()) - result["block_time"]
                    logger.info(f"🕒 Âge du token: {datetime.fromtimestamp(result['block_time']).strftime('%Y-%m-%d %H:%M:%S')} ({age_seconds} secondes)")
                return result

        # Étape 2 : Fallback via QuickNode
        logger.info("Scraping échoué, tentative via QuickNode...")
        result = self._find_initialize_mint_quicknode(token_address)
        if result:
            logger.info(f"✅ Créateur trouvé via QuickNode: {result['signer']}")
            if result["block_time"]:
                age_seconds = int(time.time()) - result["block_time"]
                logger.info(f"🕒 Âge du token: {datetime.fromtimestamp(result['block_time']).strftime('%Y-%m-%d %H:%M:%S')} ({age_seconds} secondes)")
            return result

        logger.error("❌ Impossible de trouver le créateur du token")
        return None

    def __del__(self):
        """Ferme le driver Selenium"""
        try:
            self.driver.quit()
        except:
            pass

def main():
    """Point d'entrée principal"""
    print("🚀 Token Creator Analyzer via Solana Explorer et QuickNode")
    print("=" * 60)

    # Configuration
    TOKEN_ADDRESS = "DkC9HMQ9hsK1LBkeCb1MBmRkAk4LefTgnDiTeKBGbonk"
    QUICKNODE_ENDPOINT = "https://misty-alpha-aura.solana-mainnet.quiknode.pro/2a16287e4ba93a9df419f3fa8da45d135d682202/"

    if not TOKEN_ADDRESS:
        print("❌ Adresse de token requise")
        return

    # Initialiser l'analyseur
    analyzer = TokenCreatorAnalyzer(QUICKNODE_ENDPOINT)
    
    # Lancer l'analyse
    result = analyzer.find_token_creator(TOKEN_ADDRESS)
    
    if result:
        print("\n✅ Analyse terminée avec succès !")
        print(f"📜 Signature de la transaction: {result['signature']}")
        print(f"👤 Créateur: {result['signer']}")
        print(f"🕒 Timestamp: {result['timestamp']}")
        if result["block_time"]:
            print(f"📅 Âge du token: {datetime.fromtimestamp(result['block_time']).strftime('%Y-%m-%d %H:%M:%S')} ({int(time.time()) - result['block_time']} secondes)")
        print(f"🔢 Requêtes (HTTP + RPC): {analyzer.request_count}")
    else:
        print("\n❌ Échec de l'analyse")
        print("💡 Suggestions :")
        print(f"   - Vérifiez manuellement sur https://explorer.solana.com/address/{TOKEN_ADDRESS}/history")
        print("   - Cherchez la transaction avec 'initializeMint' et notez le signataire")
        print("   - Vérifiez votre endpoint QuickNode")

if __name__ == "__main__":
    main()