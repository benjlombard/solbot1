#!/usr/bin/env python3
"""
Script pour corriger les problèmes de timezone dans la base de données tokens
"""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta

def fix_existing_tokens_timezone(database_path="tokens.db"):
    """
    Corriger les timestamps existants pour qu'ils soient explicitement en UTC
    et ajouter +2h aux tokens existants si nécessaire
    """
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()
    
    try:
        # Vérifier d'abord la structure de la table
        cursor.execute("PRAGMA table_info(tokens)")
        columns = [row[1] for row in cursor.fetchall()]
        
        print(f"Colonnes disponibles: {columns}")
        
        # Récupérer tous les tokens avec leurs timestamps
        cursor.execute('''
            SELECT address, first_discovered_at, updated_at 
            FROM tokens 
            WHERE first_discovered_at IS NOT NULL
        ''')
        
        tokens = cursor.fetchall()
        print(f"Trouvé {len(tokens)} tokens à potentiellement corriger")
        
        for address, first_discovered, updated_at in tokens:
            try:
                # Parser first_discovered_at
                if first_discovered:
                    # Essayer de parser le timestamp
                    if isinstance(first_discovered, str):
                        # Si c'est déjà un string datetime
                        dt = datetime.fromisoformat(first_discovered.replace('Z', '+00:00'))
                    else:
                        # Si c'est un timestamp Unix
                        dt = datetime.fromtimestamp(float(first_discovered), tz=timezone.utc)
                    
                    # Ajouter 2h pour corriger le décalage (si le token a été créé avec un décalage UTC)
                    corrected_dt = dt + timedelta(hours=2)
                    corrected_str = corrected_dt.strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Mettre à jour first_discovered_at
                    cursor.execute('''
                        UPDATE tokens 
                        SET first_discovered_at = ?
                        WHERE address = ?
                    ''', (corrected_str, address))
                    
                    print(f"Corrigé {address}: {first_discovered} -> {corrected_str}")
                
                # Si updated_at existe et a aussi besoin d'être corrigé
                if updated_at:
                    if isinstance(updated_at, str):
                        dt_updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                        corrected_updated = dt_updated + timedelta(hours=2)
                        corrected_updated_str = corrected_updated.strftime('%Y-%m-%d %H:%M:%S')
                        
                        cursor.execute('''
                            UPDATE tokens 
                            SET updated_at = ?
                            WHERE address = ?
                        ''', (corrected_updated_str, address))
                        
            except Exception as e:
                print(f"Erreur pour le token {address}: {e}")
                continue
        
        conn.commit()
        print(f"✅ Correction terminée pour {len(tokens)} tokens")
        
    except Exception as e:
        print(f"❌ Erreur lors de la correction: {e}")
        conn.rollback()
    finally:
        conn.close()
