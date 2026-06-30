from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
import json
from datetime import datetime, timedelta
from pathlib import Path

from pos_inventory_system.config import BASE_DIR, DATABASE_PATH


BACKUP_DIR = BASE_DIR / "backups"
BACKUP_SETTINGS_PATH = BACKUP_DIR / "backup_settings.json"


@dataclass(frozen=True)
class BackupFile:
    name: str
    path: Path
    size_bytes: int
    modified_at: datetime
    integrity: str = "unchecked"


@dataclass(frozen=True)
class BackupSettings:
    enabled: bool = False
    schedule: str = "daily"
    retention_count: int = 10
    last_run_at: str = ""


class BackupService:
    def create_backup(self, prefix: str = "pos_inventory_backup", enforce_retention: bool = True) -> BackupFile:
        if not DATABASE_PATH.exists():
            raise FileNotFoundError("Database file does not exist yet.")

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_prefix = "".join(character for character in prefix if character.isalnum() or character in {"_", "-"})
        backup_path = BACKUP_DIR / f"{safe_prefix or 'pos_inventory_backup'}_{timestamp}.sqlite3"
        shutil.copy2(DATABASE_PATH, backup_path)
        if enforce_retention:
            self.apply_retention()
        return self._file_info(backup_path)

    def list_backups(self) -> list[BackupFile]:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backups = [self._file_info(path) for path in BACKUP_DIR.glob("*.sqlite3")]
        return sorted(backups, key=lambda backup: backup.modified_at, reverse=True)

    def verify_backup(self, backup_name: str) -> str:
        backup_path = self._backup_path(backup_name)
        if not backup_path.exists():
            raise FileNotFoundError("Backup file not found.")
        return self._sqlite_integrity(backup_path)

    def restore_backup(self, backup_name: str, confirmation: str) -> BackupFile:
        if confirmation.strip().upper() != "RESTORE":
            raise ValueError("Type RESTORE to confirm the database restore.")
        backup_path = self._backup_path(backup_name)
        if not backup_path.exists():
            raise FileNotFoundError("Backup file not found.")
        integrity = self._sqlite_integrity(backup_path)
        if integrity != "ok":
            raise ValueError(f"Backup is not safe to restore: {integrity}")
        pre_restore = self.create_backup("pos_inventory_before_restore", enforce_retention=False)
        shutil.copy2(backup_path, DATABASE_PATH)
        self.apply_retention()
        return pre_restore

    def get_settings(self) -> BackupSettings:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        if not BACKUP_SETTINGS_PATH.exists():
            return BackupSettings()
        try:
            data = json.loads(BACKUP_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return BackupSettings()
        return BackupSettings(
            enabled=bool(data.get("enabled", False)),
            schedule=str(data.get("schedule", "daily") or "daily"),
            retention_count=max(int(data.get("retention_count", 10) or 10), 1),
            last_run_at=str(data.get("last_run_at", "") or ""),
        )

    def update_settings(self, enabled: bool, schedule: str, retention_count: int) -> BackupSettings:
        if schedule not in {"daily", "weekly"}:
            raise ValueError("Backup schedule must be daily or weekly.")
        settings = BackupSettings(
            enabled=enabled,
            schedule=schedule,
            retention_count=max(retention_count, 1),
            last_run_at=self.get_settings().last_run_at,
        )
        self._write_settings(settings)
        self.apply_retention(settings)
        return settings

    def maybe_run_scheduled_backup(self) -> BackupFile | None:
        settings = self.get_settings()
        if not settings.enabled:
            return None
        if not self._is_due(settings):
            return None
        backup = self.create_backup("pos_inventory_scheduled")
        self._write_settings(
            BackupSettings(
                enabled=settings.enabled,
                schedule=settings.schedule,
                retention_count=settings.retention_count,
                last_run_at=datetime.now().isoformat(timespec="seconds"),
            )
        )
        self.apply_retention()
        return backup

    def apply_retention(self, settings: BackupSettings | None = None) -> None:
        settings = settings or self.get_settings()
        backups = sorted(self.list_backups(), key=lambda backup: backup.modified_at, reverse=True)
        for backup in backups[max(settings.retention_count, 1) :]:
            try:
                backup.path.unlink()
            except OSError:
                continue

    def _backup_path(self, backup_name: str) -> Path:
        backup_path = (BACKUP_DIR / backup_name).resolve()
        backup_root = BACKUP_DIR.resolve()
        if backup_path.parent != backup_root or backup_path.suffix != ".sqlite3":
            raise ValueError("Invalid backup file name.")
        return backup_path

    def _write_settings(self, settings: BackupSettings) -> None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_SETTINGS_PATH.write_text(
            json.dumps(
                {
                    "enabled": settings.enabled,
                    "schedule": settings.schedule,
                    "retention_count": settings.retention_count,
                    "last_run_at": settings.last_run_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _is_due(settings: BackupSettings) -> bool:
        if not settings.last_run_at:
            return True
        try:
            last_run = datetime.fromisoformat(settings.last_run_at)
        except ValueError:
            return True
        interval = timedelta(days=7 if settings.schedule == "weekly" else 1)
        return datetime.now() - last_run >= interval

    @staticmethod
    def _file_info(path: Path) -> BackupFile:
        stat = path.stat()
        return BackupFile(
            name=path.name,
            path=path,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            integrity=BackupService._sqlite_integrity(path),
        )

    @staticmethod
    def _sqlite_integrity(path: Path) -> str:
        try:
            connection = sqlite3.connect(path)
            try:
                result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                if result == "ok" and not foreign_keys:
                    return "ok"
                if foreign_keys:
                    return f"foreign key issues: {len(foreign_keys)}"
                return result
            finally:
                connection.close()
        except sqlite3.DatabaseError as error:
            return f"invalid: {error}"
