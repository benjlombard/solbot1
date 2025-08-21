#!/usr/bin/env python3
"""
Creator Service Manager - Script de gestion du service d'analyse des créateurs
Permet de démarrer, arrêter, redémarrer et surveiller le service
"""

import sys
import os
import time
import subprocess
import signal
import json
import argparse
from pathlib import Path
from datetime import datetime
import psutil

class CreatorServiceManager:
    """Gestionnaire pour le service d'analyse des créateurs"""
    
    def __init__(self):
        self.service_script = "creator_analysis_service.py"
        self.pid_file = "creator_service.pid"
        self.log_file = "creator_service.log"
        self.status_file = "creator_service_status.json"
        
        # Vérifier que le script de service existe
        if not Path(self.service_script).exists():
            print(f"❌ Service script not found: {self.service_script}")
            sys.exit(1)
    
    def start(self, background=True):
        """Démarre le service"""
        if self.is_running():
            print("⚠️ Service is already running")
            return False
        
        print("🚀 Starting Creator Analysis Service...")
        
        try:
            if background:
                # Démarrer en arrière-plan
                process = subprocess.Popen(
                    [sys.executable, self.service_script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                
                # Sauvegarder le PID
                with open(self.pid_file, 'w') as f:
                    f.write(str(process.pid))
                
                # Attendre un peu pour vérifier que ça démarre
                time.sleep(3)
                
                if self.is_running():
                    print(f"✅ Service started successfully (PID: {process.pid})")
                    print(f"📝 Logs: {self.log_file}")
                    return True
                else:
                    print("❌ Service failed to start")
                    return False
            else:
                # Démarrer en premier plan
                subprocess.run([sys.executable, self.service_script])
                return True
                
        except Exception as e:
            print(f"❌ Error starting service: {e}")
            return False
    
    def stop(self):
        """Arrête le service"""
        if not self.is_running():
            print("⚠️ Service is not running")
            return True
        
        print("🛑 Stopping Creator Analysis Service...")
        
        try:
            pid = self.get_pid()
            if pid:
                # Envoyer signal SIGTERM pour arrêt propre
                os.kill(pid, signal.SIGTERM)
                
                # Attendre l'arrêt propre (max 30 secondes)
                for i in range(30):
                    if not self.is_running():
                        print("✅ Service stopped gracefully")
                        self._cleanup_pid_file()
                        return True
                    time.sleep(1)
                
                # Si toujours en cours, forcer l'arrêt
                print("⚠️ Forcing service stop...")
                os.kill(pid, signal.SIGKILL)
                time.sleep(2)
                
                if not self.is_running():
                    print("✅ Service force stopped")
                    self._cleanup_pid_file()
                    return True
                else:
                    print("❌ Failed to stop service")
                    return False
            
        except ProcessLookupError:
            print("✅ Service was already stopped")
            self._cleanup_pid_file()
            return True
        except Exception as e:
            print(f"❌ Error stopping service: {e}")
            return False
    
    def restart(self):
        """Redémarre le service"""
        print("🔄 Restarting Creator Analysis Service...")
        
        if self.is_running():
            if not self.stop():
                return False
            time.sleep(2)
        
        return self.start()
    
    def status(self, detailed=False):
        """Affiche le statut du service"""
        if self.is_running():
            pid = self.get_pid()
            process = psutil.Process(pid) if pid else None
            
            print("✅ Creator Analysis Service is RUNNING")
            
            if process:
                create_time = datetime.fromtimestamp(process.create_time())
                uptime = datetime.now() - create_time
                memory_mb = process.memory_info().rss / 1024 / 1024
                cpu_percent = process.cpu_percent()
                
                print(f"   📊 PID: {pid}")
                print(f"   ⏰ Uptime: {uptime}")
                print(f"   💾 Memory: {memory_mb:.1f} MB")
                print(f"   🖥️ CPU: {cpu_percent:.1f}%")
                
                if detailed:
                    self._show_detailed_status()
            
        else:
            print("❌ Creator Analysis Service is STOPPED")
            
            # Vérifier si le fichier PID existe encore
            if Path(self.pid_file).exists():
                print("⚠️ Stale PID file found, cleaning up...")
                self._cleanup_pid_file()
    
    def logs(self, lines=50, follow=False):
        """Affiche les logs du service"""
        if not Path(self.log_file).exists():
            print(f"❌ Log file not found: {self.log_file}")
            return
        
        try:
            if follow:
                # Suivre les logs en temps réel
                print(f"📝 Following logs (Ctrl+C to stop): {self.log_file}")
                subprocess.run(["tail", "-f", self.log_file])
            else:
                # Afficher les dernières lignes
                result = subprocess.run(
                    ["tail", "-n", str(lines), self.log_file],
                    capture_output=True,
                    text=True
                )
                print(f"📝 Last {lines} lines from {self.log_file}:")
                print("-" * 50)
                print(result.stdout)
                
        except FileNotFoundError:
            # Fallback si 'tail' n'est pas disponible
            with open(self.log_file, 'r') as f:
                lines_list = f.readlines()
                for line in lines_list[-lines:]:
                    print(line.rstrip())
        except Exception as e:
            print(f"❌ Error reading logs: {e}")
    
    def is_running(self):
        """Vérifie si le service tourne"""
        pid = self.get_pid()
        if not pid:
            return False
        
        try:
            # Vérifier si le processus existe
            process = psutil.Process(pid)
            
            # Vérifier si c'est bien notre script
            cmdline = ' '.join(process.cmdline())
            return self.service_script in cmdline
            
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    def get_pid(self):
        """Récupère le PID du service"""
        try:
            if Path(self.pid_file).exists():
                with open(self.pid_file, 'r') as f:
                    return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            pass
        return None
    
    def _cleanup_pid_file(self):
        """Supprime le fichier PID"""
        try:
            if Path(self.pid_file).exists():
                os.remove(self.pid_file)
        except Exception as e:
            print(f"⚠️ Could not remove PID file: {e}")
    
    def _show_detailed_status(self):
        """Affiche un statut détaillé"""
        try:
            # Lire les dernières lignes du log pour les stats
            if Path(self.log_file).exists():
                with open(self.log_file, 'r') as f:
                    lines = f.readlines()
                
                # Chercher la dernière ligne avec "Health Report"
                for line in reversed(lines[-100:]):  # Dernières 100 lignes
                    if "Service Health Report" in line:
                        print("   📊 Latest Health Report:")
                        # Afficher les lignes suivantes
                        idx = lines.index(line)
                        for i in range(1, 8):  # 7 lignes après
                            if idx + i < len(lines):
                                health_line = lines[idx + i].strip()
                                if "•" in health_line:
                                    print(f"      {health_line}")
                        break
                
        except Exception as e:
            print(f"⚠️ Could not read detailed status: {e}")
    
    def monitor(self, interval=30):
        """Surveille le service en continu"""
        print(f"👁️ Monitoring Creator Analysis Service (refresh every {interval}s)")
        print("Press Ctrl+C to stop monitoring")
        
        try:
            while True:
                os.system('clear' if os.name == 'posix' else 'cls')
                print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print("=" * 60)
                
                self.status(detailed=True)
                
                print("=" * 60)
                print(f"Next refresh in {interval} seconds...")
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n👋 Monitoring stopped")

def main():
    """Point d'entrée principal"""
    parser = argparse.ArgumentParser(description="Creator Analysis Service Manager")
    parser.add_argument("command", choices=[
        "start", "stop", "restart", "status", "logs", "monitor"
    ], help="Command to execute")
    
    parser.add_argument("--foreground", "-f", action="store_true",
                       help="Start service in foreground (only for start command)")
    parser.add_argument("--detailed", "-d", action="store_true",
                       help="Show detailed status")
    parser.add_argument("--lines", "-n", type=int, default=50,
                       help="Number of log lines to show (default: 50)")
    parser.add_argument("--follow", action="store_true",
                       help="Follow logs in real-time")
    parser.add_argument("--interval", "-i", type=int, default=30,
                       help="Monitor refresh interval in seconds (default: 30)")
    
    args = parser.parse_args()
    
    # Changer vers le répertoire du script
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    manager = CreatorServiceManager()
    
    try:
        if args.command == "start":
            success = manager.start(background=not args.foreground)
            sys.exit(0 if success else 1)
            
        elif args.command == "stop":
            success = manager.stop()
            sys.exit(0 if success else 1)
            
        elif args.command == "restart":
            success = manager.restart()
            sys.exit(0 if success else 1)
            
        elif args.command == "status":
            manager.status(detailed=args.detailed)
            
        elif args.command == "logs":
            manager.logs(lines=args.lines, follow=args.follow)
            
        elif args.command == "monitor":
            manager.monitor(interval=args.interval)
            
    except KeyboardInterrupt:
        print("\n👋 Operation cancelled")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()