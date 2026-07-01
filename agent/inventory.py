"""
Collect Docker inventory from the local host for sync to the control server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger("agent.inventory")

_CONTAINER_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")
_IMAGE_REF_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/@: -]*$")
_NETWORK_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


async def _run_docker(args: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace").strip() or "docker command failed")
    return stdout.decode("utf-8", errors="replace")


async def _inspect_project_paths(container_ids: list[str]) -> dict[str, str]:
    """Map container ID -> compose project working dir from labels."""
    paths: dict[str, str] = {}
    for cid in container_ids:
        if not _CONTAINER_ID_RE.match(cid):
            continue
        try:
            raw = await _run_docker(["inspect", cid, "--format", "{{json .Config.Labels}}"])
            labels = json.loads(raw.strip() or "{}")
            path = (
                labels.get("com.docker.compose.project.working_dir")
                or labels.get("com.docker.compose.project.config_files")
                or ""
            )
            if path:
                paths[cid] = path
        except Exception:
            logger.debug("could not inspect container %s", cid, exc_info=True)
    return paths


async def collect_inventory() -> dict[str, list[dict[str, Any]]]:
    """Return containers, images, and networks from local Docker."""
    containers_raw = await _run_docker(
        [
            "ps",
            "-a",
            "--format",
            "{{json .}}",
        ]
    )
    containers: list[dict[str, Any]] = []
    container_ids: list[str] = []

    for line in containers_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        cid = row.get("ID", "")
        if not cid:
            continue
        container_ids.append(cid)
        containers.append(
            {
                "container_id": cid,
                "name": row.get("Names", "").lstrip("/"),
                "image": row.get("Image"),
                "status": row.get("Status"),
                "state": row.get("State"),
                "ports": row.get("Ports"),
                "project_path": None,
                "labels": {},
            }
        )

    paths = await _inspect_project_paths(container_ids)
    for c in containers:
        c["project_path"] = paths.get(c["container_id"])

    images_raw = await _run_docker(
        [
            "images",
            "--format",
            "{{json .}}",
        ]
    )
    images: list[dict[str, Any]] = []
    for line in images_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        repo = row.get("Repository", "")
        tag = row.get("Tag", "")
        images.append(
            {
                "image_id": row.get("ID", ""),
                "repository": repo,
                "tag": tag,
                "size_bytes": _parse_size(row.get("Size", "")),
                "created_at": row.get("CreatedAt"),
            }
        )

    networks_raw = await _run_docker(
        [
            "network",
            "ls",
            "--format",
            "{{json .}}",
        ]
    )
    networks: list[dict[str, Any]] = []
    for line in networks_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        networks.append(
            {
                "network_id": row.get("ID", ""),
                "name": row.get("Name"),
                "driver": row.get("Driver"),
                "scope": row.get("Scope"),
            }
        )

    return {"containers": containers, "images": images, "networks": networks}


def _parse_size(size_str: str) -> int | None:
    """Best-effort parse of docker human-readable size."""
    size_str = size_str.strip()
    if not size_str:
        return None
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    parts = size_str.split()
    if len(parts) != 2:
        return None
    try:
        value = float(parts[0])
    except ValueError:
        return None
    unit = parts[1].upper()
    if unit not in units:
        return None
    return int(value * units[unit])
