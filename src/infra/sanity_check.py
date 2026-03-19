import os
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger("SanityCheck")

class StartupSanityCheck:
    """Verifies system integrity before booting agents."""
    
    def __init__(self):
        self.root = Path(__file__).resolve().parents[2]
        self.db_paths = [
            self.root / "logs" / "audit.db",
            self.root / "data" / "sentiment.db"
        ]
        self.model_paths = [
            self.root / "models" / "nexus_regime.json",
            self.root / "models" / "karma_ppo.zip"
        ]

    def run(self) -> bool:
        logger.info("Running pre-flight sanity checks...")
        return all([
            self._check_directories(),
            self._check_databases(),
            self._check_models()
        ])

    def _check_directories(self) -> bool:
        dirs = ["logs", "data", "data/cache", "models"]
        for d in dirs:
            path = self.root / d
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"Cannot create directory {d}: {e}")
                return False
        return True

    def _check_databases(self) -> bool:
        for db in self.db_paths:
            if not db.exists():
                continue
            try:
                conn = sqlite3.connect(str(db))
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check;")
                result = cursor.fetchone()
                conn.close()
                if result and result[0] != "ok":
                    logger.warning(f"Database corruption detected in {db.name}: {result[0]}")
                    self._recover_db(db)
            except sqlite3.DatabaseError as e:
                logger.warning(f"Database error in {db.name}: {e}")
                self._recover_db(db)
            except Exception as e:
                logger.error(f"Failed to check {db.name}: {e}")
        return True

    def _recover_db(self, db_path: Path):
        backup_path = db_path.with_suffix(".db.bak")
        try:
            if backup_path.exists():
                backup_path.unlink()
            db_path.rename(backup_path)
            logger.info(f"Renamed corrupted DB {db_path.name} to {backup_path.name}. A new one will be created.")
        except Exception as e:
            logger.error(f"Failed to recover corrupted DB {db_path.name}: {e}")

    def _check_models(self) -> bool:
        for model in self.model_paths:
            if model.exists():
                # Verify it's not empty
                if model.stat().st_size == 0:
                    logger.warning(f"Model file {model.name} is empty. Might need retraining.")
        return True
