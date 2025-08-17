#!/usr/bin/env python3
"""
Script de comptage de lignes pour les fichiers Python
Compte les lignes de code dans le dossier scanner_wallet en excluant old1
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import argparse

class PythonLineCounter:
    """Compteur de lignes pour fichiers Python"""
    
    def __init__(self, base_path: str = "scanner_wallet", excluded_dirs: List[str] = None):
        self.base_path = Path(base_path)
        self.excluded_dirs = excluded_dirs or ["old1", "__pycache__", ".git", ".pytest_cache"]
        self.stats = {
            'total_files': 0,
            'total_lines': 0,
            'code_lines': 0,
            'comment_lines': 0,
            'blank_lines': 0,
            'docstring_lines': 0
        }
        self.file_stats = []
    
    def is_excluded_dir(self, path: Path) -> bool:
        """Vérifie si un répertoire est exclu"""
        for excluded in self.excluded_dirs:
            if excluded in path.parts:
                return True
        return False
    
    def count_lines_in_file(self, file_path: Path) -> Dict[str, int]:
        """Compte les différents types de lignes dans un fichier Python"""
        stats = {
            'total': 0,
            'code': 0,
            'comments': 0,
            'blank': 0,
            'docstring': 0
        }
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            in_multiline_string = False
            multiline_char = None
            in_docstring = False
            
            for i, line in enumerate(lines):
                stats['total'] += 1
                stripped = line.strip()
                
                # Ligne vide
                if not stripped:
                    stats['blank'] += 1
                    continue
                
                # Gestion des chaînes multilignes et docstrings
                if not in_multiline_string:
                    # Début d'une chaîne multiligne
                    if '"""' in stripped or "'''" in stripped:
                        if '"""' in stripped:
                            multiline_char = '"""'
                        else:
                            multiline_char = "'''"
                        
                        # Vérifier si c'est un docstring (début de fonction/classe)
                        if i > 0:
                            prev_lines = [lines[j].strip() for j in range(max(0, i-3), i)]
                            if any(line.startswith(('def ', 'class ', 'async def ')) for line in prev_lines):
                                in_docstring = True
                        
                        in_multiline_string = True
                        
                        # Vérifier si ça se ferme sur la même ligne
                        if stripped.count(multiline_char) >= 2:
                            in_multiline_string = False
                            if in_docstring:
                                stats['docstring'] += 1
                                in_docstring = False
                            else:
                                stats['code'] += 1
                        else:
                            if in_docstring:
                                stats['docstring'] += 1
                            else:
                                stats['code'] += 1
                        continue
                
                # Dans une chaîne multiligne
                if in_multiline_string:
                    if multiline_char in stripped:
                        in_multiline_string = False
                        if in_docstring:
                            in_docstring = False
                        
                    if in_docstring:
                        stats['docstring'] += 1
                    else:
                        stats['code'] += 1
                    continue
                
                # Commentaire simple
                if stripped.startswith('#'):
                    stats['comments'] += 1
                    continue
                
                # Code normal
                stats['code'] += 1
            
        except Exception as e:
            print(f"⚠️ Erreur lecture {file_path}: {e}")
            return stats
        
        return stats
    
    def scan_directory(self) -> None:
        """Scan le répertoire et compte les lignes"""
        if not self.base_path.exists():
            print(f"❌ Le répertoire {self.base_path} n'existe pas")
            return
        
        print(f"🔍 Scan du répertoire: {self.base_path.absolute()}")
        print(f"📁 Répertoires exclus: {', '.join(self.excluded_dirs)}")
        print("-" * 60)
        
        for py_file in self.base_path.rglob("*.py"):
            # Vérifier si le fichier est dans un répertoire exclu
            if self.is_excluded_dir(py_file):
                continue
            
            file_stats = self.count_lines_in_file(py_file)
            
            # Calculer le chemin relatif
            relative_path = py_file.relative_to(self.base_path)
            
            self.file_stats.append({
                'path': str(relative_path),
                'full_path': str(py_file),
                **file_stats
            })
            
            # Mettre à jour les statistiques globales
            self.stats['total_files'] += 1
            self.stats['total_lines'] += file_stats['total']
            self.stats['code_lines'] += file_stats['code']
            self.stats['comment_lines'] += file_stats['comments']
            self.stats['blank_lines'] += file_stats['blank']
            self.stats['docstring_lines'] += file_stats['docstring']
    
    def print_detailed_results(self) -> None:
        """Affiche les résultats détaillés"""
        print("\n📊 RÉSULTATS DÉTAILLÉS PAR FICHIER")
        print("=" * 80)
        
        # Trier par nombre de lignes (décroissant)
        sorted_files = sorted(self.file_stats, key=lambda x: x['total'], reverse=True)
        
        print(f"{'Fichier':<50} {'Total':<8} {'Code':<8} {'Com.':<6} {'Doc.':<6} {'Vide':<6}")
        print("-" * 80)
        
        for file_stat in sorted_files:
            print(f"{file_stat['path']:<50} "
                  f"{file_stat['total']:<8} "
                  f"{file_stat['code']:<8} "
                  f"{file_stat['comments']:<6} "
                  f"{file_stat['docstring']:<6} "
                  f"{file_stat['blank']:<6}")
    
    def print_summary(self) -> None:
        """Affiche le résumé"""
        print("\n📈 RÉSUMÉ GLOBAL")
        print("=" * 50)
        print(f"📁 Nombre de fichiers Python    : {self.stats['total_files']:,}")
        print(f"📝 Total des lignes            : {self.stats['total_lines']:,}")
        print(f"💻 Lignes de code              : {self.stats['code_lines']:,}")
        print(f"💬 Lignes de commentaires      : {self.stats['comment_lines']:,}")
        print(f"📖 Lignes de docstring         : {self.stats['docstring_lines']:,}")
        print(f"⭕ Lignes vides               : {self.stats['blank_lines']:,}")
        
        # Pourcentages
        if self.stats['total_lines'] > 0:
            code_pct = (self.stats['code_lines'] / self.stats['total_lines']) * 100
            comment_pct = (self.stats['comment_lines'] / self.stats['total_lines']) * 100
            doc_pct = (self.stats['docstring_lines'] / self.stats['total_lines']) * 100
            blank_pct = (self.stats['blank_lines'] / self.stats['total_lines']) * 100
            
            print("\n📊 RÉPARTITION (%)")
            print("-" * 30)
            print(f"Code         : {code_pct:5.1f}%")
            print(f"Commentaires : {comment_pct:5.1f}%")
            print(f"Docstrings   : {doc_pct:5.1f}%")
            print(f"Lignes vides : {blank_pct:5.1f}%")
    
    def print_final_totals(self) -> None:
        """Affiche les totaux finaux de manière claire"""
        print("\n" + "="*60)
        print("🎯 TOTAUX FINAUX")
        print("="*60)
        print(f"📊 TOTAL GÉNÉRAL      : {self.stats['total_lines']:,} lignes")
        print(f"💻 TOTAL CODE         : {self.stats['code_lines']:,} lignes de code")
        print("="*60)
    
    def print_top_files(self, n: int = 10) -> None:
        """Affiche les N plus gros fichiers"""
        print(f"\n🏆 TOP {n} DES PLUS GROS FICHIERS")
        print("=" * 60)
        
        sorted_files = sorted(self.file_stats, key=lambda x: x['total'], reverse=True)[:n]
        
        for i, file_stat in enumerate(sorted_files, 1):
            print(f"{i:2d}. {file_stat['path']:<40} {file_stat['total']:>6} lignes")
    
    def print_directory_stats(self) -> None:
        """Affiche les statistiques par répertoire"""
        print("\n📂 STATISTIQUES PAR RÉPERTOIRE")
        print("=" * 60)
        
        dir_stats = {}
        
        for file_stat in self.file_stats:
            path_parts = Path(file_stat['path']).parts
            if len(path_parts) > 1:
                directory = path_parts[0]
            else:
                directory = "racine"
            
            if directory not in dir_stats:
                dir_stats[directory] = {
                    'files': 0,
                    'total': 0,
                    'code': 0
                }
            
            dir_stats[directory]['files'] += 1
            dir_stats[directory]['total'] += file_stat['total']
            dir_stats[directory]['code'] += file_stat['code']
        
        print(f"{'Répertoire':<20} {'Fichiers':<10} {'Total':<10} {'Code':<10}")
        print("-" * 60)
        
        for directory, stats in sorted(dir_stats.items(), key=lambda x: x[1]['total'], reverse=True):
            print(f"{directory:<20} {stats['files']:<10} {stats['total']:<10} {stats['code']:<10}")
    
    def export_to_csv(self, filename: str = "python_lines_stats.csv") -> None:
        """Exporte les résultats en CSV"""
        try:
            import csv
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['path', 'total', 'code', 'comments', 'docstring', 'blank']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for file_stat in self.file_stats:
                    writer.writerow({
                        'path': file_stat['path'],
                        'total': file_stat['total'],
                        'code': file_stat['code'],
                        'comments': file_stat['comments'],
                        'docstring': file_stat['docstring'],
                        'blank': file_stat['blank']
                    })
            
            print(f"\n💾 Résultats exportés vers: {filename}")
            
        except Exception as e:
            print(f"❌ Erreur export CSV: {e}")

def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="Compteur de lignes Python pour scanner_wallet")
    parser.add_argument("--path", "-p", default="scanner_wallet", 
                       help="Chemin du répertoire à analyser (défaut: scanner_wallet)")
    parser.add_argument("--exclude", "-e", nargs="+", default=["old1"], 
                       help="Répertoires à exclure (défaut: old1)")
    parser.add_argument("--detailed", "-d", action="store_true", 
                       help="Afficher les résultats détaillés par fichier")
    parser.add_argument("--top", "-t", type=int, default=10, 
                       help="Nombre de fichiers à afficher dans le top (défaut: 10)")
    parser.add_argument("--csv", "-c", action="store_true", 
                       help="Exporter les résultats en CSV")
    parser.add_argument("--csv-file", default="python_lines_stats.csv", 
                       help="Nom du fichier CSV (défaut: python_lines_stats.csv)")
    
    args = parser.parse_args()
    
    # Créer le compteur
    counter = PythonLineCounter(args.path, args.exclude)
    
    # Scanner le répertoire
    counter.scan_directory()
    
    if counter.stats['total_files'] == 0:
        print("❌ Aucun fichier Python trouvé")
        return
    
    # Afficher les résultats
    counter.print_summary()
    counter.print_top_files(args.top)
    counter.print_directory_stats()
    
    if args.detailed:
        counter.print_detailed_results()
    
    if args.csv:
        counter.export_to_csv(args.csv_file)
    
    # Afficher les totaux finaux en grand à la fin
    counter.print_final_totals()
    
    print(f"\n✅ Analyse terminée - {counter.stats['total_files']} fichiers analysés")

if __name__ == "__main__":
    main()