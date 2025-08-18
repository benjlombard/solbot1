"""
Database Connection Management
Provides robust SQLite connection handling with retries and optimization.
"""
import sqlite3
import time
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Any
import functools


class DatabaseConnectionError(Exception):
    """Custom exception for database connection issues"""
    pass


class DatabaseConnection:
    """Manages SQLite database connections with optimizations and retry logic"""
    
    def __init__(self, db_path: str, timeout: float = 30.0, logger: Optional[logging.Logger] = None):
        self.db_path = Path(db_path)
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)
        
        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema if database is new or tables are missing
        self.initialize_schema()
    
    def initialize_schema(self):
        """
        Initializes the database schema by executing SQL scripts
        from the schema directory.
        """
        try:
            with self.get_connection_context() as conn:
                cursor = conn.cursor()
                # Check if tables exist
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tokens'")
                if cursor.fetchone():
                    self.logger.debug("Database schema already exists.")
                    return

                self.logger.info("Initializing new database schema...")
                
                # Correctly locate the schema directory
                schema_dir = Path(__file__).parent.parent.parent / "database" / "schema"
                
                if not schema_dir.exists():
                    self.logger.error(f"Schema directory not found at {schema_dir}")
                    raise DatabaseConnectionError(f"Schema directory not found: {schema_dir}")

                sql_files = sorted(list(schema_dir.glob('*.sql')))
                
                for sql_file in sql_files:
                    try:
                        with open(sql_file, 'r', encoding='utf-8') as f:
                            sql_script = f.read()
                            # Execute script, handling multiple statements
                            for statement in sql_script.split(';'):
                                if statement.strip():
                                    cursor.execute(statement)
                            self.logger.debug(f"Executed schema file: {sql_file.name}")
                    except Exception as e:
                        self.logger.error(f"Failed to execute schema file {sql_file.name}: {e}")
                        raise
                
                conn.commit()
                self.logger.info("✅ Database schema initialized successfully.")

        except Exception as e:
            self.logger.error(f"Failed to initialize database schema: {e}", exc_info=True)
            # We don't re-raise here to allow the application to continue
            # if the database is already set up, but we log it as a critical error.

    def get_connection(self, retries: int = 5, delay: float = 0.1) -> sqlite3.Connection:
        """
        Get a database connection with retry logic and optimizations
        
        Args:
            retries: Number of retry attempts
            delay: Initial delay between retries (exponential backoff)
            
        Returns:
            SQLite connection object
            
        Raises:
            DatabaseConnectionError: If all retry attempts fail
        """
        for attempt in range(retries):
            try:
                conn = sqlite3.connect(
                    str(self.db_path),
                    timeout=self.timeout,
                    check_same_thread=False
                )
                
                # Set row factory for dict-like access
                conn.row_factory = sqlite3.Row
                
                # Apply SQLite optimizations
                self._optimize_connection(conn)
                
                # Test connection
                conn.execute("SELECT 1").fetchone()
                
                return conn
                
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < retries - 1:
                    wait_time = delay * (2 ** attempt)
                    self.logger.warning(
                        f"Database locked, retry {attempt + 1}/{retries} in {wait_time:.2f}s"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    error_msg = f"Database connection error after {retries} attempts: {e}"
                    self.logger.error(error_msg)
                    raise DatabaseConnectionError(error_msg)
                    
            except Exception as e:
                error_msg = f"Unexpected database connection error: {e}"
                self.logger.error(error_msg)
                raise DatabaseConnectionError(error_msg)
        
        raise DatabaseConnectionError(f"Failed to connect after {retries} attempts")
    
    def _optimize_connection(self, conn: sqlite3.Connection) -> None:
        """Apply SQLite performance optimizations"""
        optimizations = [
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA cache_size=-65536",  # 64MB cache
            "PRAGMA temp_store=memory",
            f"PRAGMA busy_timeout={int(self.timeout * 1000)}",
            "PRAGMA wal_autocheckpoint=1000"
        ]
        
        for pragma in optimizations:
            try:
                conn.execute(pragma)
            except sqlite3.Error as e:
                self.logger.warning(f"Failed to apply optimization '{pragma}': {e}")
    
    @contextmanager
    def get_connection_context(self, retries: int = 5):
        """
        Context manager for database connections
        Ensures proper cleanup even if errors occur
        """
        conn = None
        try:
            conn = self.get_connection(retries=retries)
            yield conn
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as e:
                    self.logger.warning(f"Error closing database connection: {e}")
    
    def check_health(self) -> bool:
        """
        Check database health and fix common issues
        
        Returns:
            True if database is healthy, False otherwise
        """
        try:
            with self.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Basic connectivity test
                cursor.execute("SELECT 1")
                
                # Check journal mode
                cursor.execute("PRAGMA journal_mode")
                journal_mode = cursor.fetchone()[0]
                if journal_mode != 'wal':
                    self.logger.warning(f"Database not in WAL mode: {journal_mode}")
                    cursor.execute("PRAGMA journal_mode=WAL")
                
                # Check database integrity
                cursor.execute("PRAGMA integrity_check")
                integrity = cursor.fetchone()[0]
                if integrity != 'ok':
                    self.logger.error(f"Database integrity issue: {integrity}")
                    return False
                
                # Optimize database
                cursor.execute("PRAGMA optimize")
                
                self.logger.debug("✅ Database health check passed")
                return True
                
        except Exception as e:
            self.logger.error(f"❌ Database health check failed: {e}")
            return False
    
    def vacuum_database(self) -> bool:
        """
        Vacuum the database to reclaim space and optimize performance
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.logger.info("Starting database vacuum operation...")
            
            with self.get_connection_context() as conn:
                # Switch to DELETE mode temporarily for vacuum
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("VACUUM")
                # Switch back to WAL mode
                conn.execute("PRAGMA journal_mode=WAL")
                conn.commit()
            
            self.logger.info("✅ Database vacuum completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Database vacuum failed: {e}")
            return False


def db_retry(max_retries: int = 3, delay: float = 0.2):
    """
    Decorator to automatically retry database operations
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Base delay between retries (exponential backoff)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            logger = getattr(self, 'logger', logging.getLogger(__name__))
            
            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                    
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt)
                        logger.warning(
                            f"Database locked in {func.__name__}, "
                            f"retry {attempt + 1}/{max_retries} in {wait_time:.2f}s"
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(
                            f"Database error in {func.__name__} after {max_retries} attempts: {e}"
                        )
                        raise
                        
                except Exception as e:
                    logger.error(f"Unexpected error in {func.__name__}: {e}")
                    raise
            
            return None
        return wrapper
    return decorator


# Convenience function for backward compatibility
def get_db_connection(db_path: str, **kwargs) -> sqlite3.Connection:
    """
    Convenience function to get a database connection
    
    Args:
        db_path: Path to the SQLite database file
        **kwargs: Additional arguments for DatabaseConnection
        
    Returns:
        SQLite connection object
    """
    db_conn = DatabaseConnection(db_path, **kwargs)
    return db_conn.get_connection()