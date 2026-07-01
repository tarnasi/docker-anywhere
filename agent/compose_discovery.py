"""
Discover Docker Compose projects from the local daemon (no fixed paths required).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from agent.inventory import _run_docker

logger = logging.getLogger("agent.compose_discovery")


@dataclass(frozen=True)
class ComposeProject:
    name: str
    config_files: str
    status: str = ""

    @property
    def work_dir(self) -> Path | None:
        if not self.config_files:
            return None
        first = self.config_files.split(",")[0].strip()
        if not first:
            return None
        return Path(first).parent

    def argv_base(self) -> list[str]:
        """docker compose -f ... -f ..."""
        argv = ["docker", "compose"]
        for cfg in self.config_files.split(","):
            cfg = cfg.strip()
            if cfg:
                argv.extend(["-f", cfg])
        return argv


async def discover_compose_projects() -> list[ComposeProject]:
    """
    List compose projects via `docker compose ls`.

    Returns an empty list if compose is unavailable or no projects exist.
    """
    try:
        raw = await _run_docker(["compose", "ls", "--format", "json"])
    except Exception:
        logger.debug("docker compose ls failed", exc_info=True)
        return []

    projects: list[ComposeProject] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = row.get("Name") or row.get("name") or ""
        configs = row.get("ConfigFiles") or row.get("ConfigFile") or ""
        if not name:
            continue
        projects.append(
            ComposeProject(
                name=name,
                config_files=configs,
                status=row.get("Status") or row.get("status") or "",
            )
        )
    return projects
