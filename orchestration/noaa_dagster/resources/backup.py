"""clickhouse-backup wrapper resource for Dagster."""

import logging
import subprocess

from dagster import ConfigurableResource

logger = logging.getLogger(__name__)


class BackupResource(ConfigurableResource):
    container_name: str = "clickhouse-backup"

    def _run(self, *args: str, timeout: int = 3600) -> str:
        cmd = ["docker", "exec", self.container_name, "clickhouse-backup"] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"clickhouse-backup failed: {result.stderr}")
        return result.stdout

    def create_backup(self, name: str) -> str:
        logger.info(f"Creating backup: {name}")
        return self._run("create", name, timeout=7200)

    def list_backups(self) -> str:
        return self._run("list")

    def restore(self, name: str) -> str:
        logger.info(f"Restoring backup: {name}")
        return self._run("restore", name, timeout=7200)
