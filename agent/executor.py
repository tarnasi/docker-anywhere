"""
Safe command execution via subprocess with strict action whitelisting.

Compose projects are auto-detected via `docker compose ls`.
Per-container actions use the native `docker` CLI (no compose file path required).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from agent.compose_discovery import ComposeProject, discover_compose_projects
from agent.config import settings
from agent.models import ActionType, CommandPayload, CommandStatus, ExecutionResult
from agent.security import audit_event

logger = logging.getLogger("agent.executor")

_SERVICE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
_SCRIPT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
_IMAGE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/@: -]+$")
_NETWORK_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")

_CONTAINER_ACTIONS = {
    ActionType.DOCKER_RESTART,
    ActionType.DOCKER_LOGS,
    ActionType.DOCKER_STATUS,
    ActionType.DOCKER_STOP,
    ActionType.DOCKER_START,
}


class CommandRejectedError(Exception):
    """Raised when a command fails validation before execution."""


def _validate_service(service: str | None, action: ActionType) -> str:
    needs_service = _CONTAINER_ACTIONS | {
        ActionType.DOCKER_REBUILD,
    }
    if action in needs_service:
        if not service:
            raise CommandRejectedError(f"{action.value} requires a service/container name")
        if not _SERVICE_RE.match(service):
            raise CommandRejectedError(f"invalid service name: {service!r}")
    return service or ""


def _fallback_compose_project() -> ComposeProject | None:
    """Single project from .env when auto-detection is empty."""
    if settings.docker_compose_file and settings.docker_compose_file.is_file():
        work = settings.docker_work_dir or settings.docker_compose_file.parent
        return ComposeProject(
            name=work.name,
            config_files=str(settings.docker_compose_file),
        )
    return None


def _build_command(cmd: CommandPayload) -> list[str]:
    service = _validate_service(cmd.service, cmd.action)
    action = cmd.action

    # Per-container — no compose file needed
    if action == ActionType.DOCKER_RESTART:
        return ["docker", "restart", service]

    if action == ActionType.DOCKER_STOP:
        return ["docker", "stop", service]

    if action == ActionType.DOCKER_START:
        return ["docker", "start", service]

    if action == ActionType.DOCKER_LOGS:
        tail = str(cmd.params.get("tail", 100))
        if not tail.isdigit() or int(tail) > 10_000:
            raise CommandRejectedError("logs tail must be a number <= 10000")
        return ["docker", "logs", f"--tail={tail}", service]

    if action == ActionType.DOCKER_STATUS:
        return ["docker", "ps", "--filter", f"name={service}"]

    if action == ActionType.DOCKER_REBUILD:
        return ["__compose_rebuild__", service]

    if action == ActionType.DOCKER_COMPOSE_UP:
        return ["__compose_up_all__"]

    if action == ActionType.DOCKER_COMPOSE_DOWN:
        return ["__compose_down_all__"]

    if action == ActionType.CONTAINERS_STOP_ALL:
        return ["__stop_all_containers__"]

    if action == ActionType.CONTAINERS_REMOVE_ALL:
        return ["docker", "container", "prune", "-f"]

    if action == ActionType.IMAGE_PULL:
        image = cmd.params.get("image") or service
        if not image or not isinstance(image, str):
            raise CommandRejectedError("image_pull requires params.image or service")
        if not _IMAGE_RE.match(image):
            raise CommandRejectedError(f"invalid image reference: {image!r}")
        return ["docker", "pull", image]

    if action == ActionType.IMAGE_REMOVE:
        image = cmd.params.get("image") or service
        if not image or not isinstance(image, str):
            raise CommandRejectedError("image_remove requires params.image or service")
        if not _IMAGE_RE.match(image):
            raise CommandRejectedError(f"invalid image reference: {image!r}")
        argv = ["docker", "rmi"]
        if cmd.params.get("force", False):
            argv.append("-f")
        argv.append(image)
        return argv

    if action == ActionType.NETWORK_CREATE:
        name = cmd.params.get("name") or service
        if not name or not isinstance(name, str):
            raise CommandRejectedError("network_create requires params.name or service")
        if not _NETWORK_RE.match(name):
            raise CommandRejectedError(f"invalid network name: {name!r}")
        driver = cmd.params.get("driver", "bridge")
        if driver not in ("bridge", "host", "overlay", "macvlan", "none"):
            raise CommandRejectedError(f"unsupported network driver: {driver!r}")
        return ["docker", "network", "create", "--driver", driver, name]

    if action == ActionType.NETWORK_REMOVE:
        name = cmd.params.get("name") or service
        if not name or not isinstance(name, str):
            raise CommandRejectedError("network_remove requires params.name or service")
        if not _NETWORK_RE.match(name):
            raise CommandRejectedError(f"invalid network name: {name!r}")
        return ["docker", "network", "rm", name]

    if action == ActionType.INVENTORY_SYNC:
        return ["__inventory_sync__"]

    if action == ActionType.SERVER_REBOOT:
        token = cmd.params.get("confirmation_token")
        if token != settings.reboot_confirmation_token:
            raise CommandRejectedError("server_reboot requires valid confirmation_token")
        return ["sudo", "/sbin/reboot"]

    if action == ActionType.RUN_SCRIPT:
        script_name = cmd.params.get("script_name")
        if not script_name or not isinstance(script_name, str):
            raise CommandRejectedError("run_script requires params.script_name")
        if not _SCRIPT_RE.match(script_name):
            raise CommandRejectedError(f"invalid script name: {script_name!r}")

        scripts_dir = settings.allowed_scripts_dir.resolve()
        script_path = (scripts_dir / script_name).resolve()
        if not str(script_path).startswith(str(scripts_dir)):
            raise CommandRejectedError("script path escapes allowed directory")
        if not script_path.is_file():
            raise CommandRejectedError(f"script not found: {script_name}")
        if not script_path.stat().st_mode & 0o111:
            raise CommandRejectedError(f"script is not executable: {script_name}")
        return [str(script_path)]

    raise CommandRejectedError(f"action not in whitelist: {action}")


def _truncate_output(text: str) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= settings.max_output_bytes:
        return text
    truncated = encoded[: settings.max_output_bytes].decode("utf-8", errors="ignore")
    return truncated + "\n... [output truncated]"


async def _run_subprocess(
    argv: list[str],
    *,
    cwd: Path | None = None,
) -> tuple[str, str, int]:
    logger.info("executing command", extra={"argv": argv, "cwd": str(cwd) if cwd else None})

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=settings.command_timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise CommandRejectedError(
            f"command timed out after {settings.command_timeout_seconds}s"
        )

    stdout = _truncate_output(stdout_bytes.decode("utf-8", errors="replace"))
    stderr = _truncate_output(stderr_bytes.decode("utf-8", errors="replace"))
    return stdout, stderr, proc.returncode or 0


async def _get_compose_projects() -> list[ComposeProject]:
    projects = await discover_compose_projects()
    if projects:
        return projects
    fallback = _fallback_compose_project()
    return [fallback] if fallback else []


async def _run_compose_on_projects(
    projects: list[ComposeProject],
    extra_args: list[str],
) -> tuple[str, str, int]:
    if not projects:
        return (
            "no compose projects detected (docker compose ls empty); skipped",
            "",
            0,
        )

    outputs: list[str] = []
    errors: list[str] = []
    worst_rc = 0

    for project in projects:
        argv = project.argv_base() + extra_args
        cwd = project.work_dir
        stdout, stderr, rc = await _run_subprocess(argv, cwd=cwd)
        outputs.append(f"=== {project.name} ===\n{stdout}")
        if stderr:
            errors.append(f"=== {project.name} ===\n{stderr}")
        if rc != 0:
            worst_rc = rc

    return "\n".join(outputs), "\n".join(errors), worst_rc


async def _compose_rebuild(service: str) -> tuple[str, str, int]:
    projects = await _get_compose_projects()
    if not projects:
        return (
            "",
            "no compose projects detected; cannot rebuild service",
            1,
        )

    outputs: list[str] = []
    errors: list[str] = []
    succeeded = False
    worst_rc = 0

    for project in projects:
        argv = project.argv_base() + ["up", "-d", "--build", service]
        stdout, stderr, rc = await _run_subprocess(argv, cwd=project.work_dir)
        outputs.append(f"=== {project.name} ===\n{stdout}")
        if stderr:
            errors.append(f"=== {project.name} ===\n{stderr}")
        if rc == 0:
            succeeded = True
        else:
            worst_rc = rc

    if succeeded:
        return "\n".join(outputs), "\n".join(errors), 0
    return "\n".join(outputs), "\n".join(errors), worst_rc


async def execute_command(cmd: CommandPayload) -> ExecutionResult:
    started_at = datetime.now(UTC)
    audit_event(
        "command_received",
        command_id=str(cmd.command_id),
        action=cmd.action.value,
        service=cmd.service,
    )

    try:
        argv = _build_command(cmd)
    except CommandRejectedError as exc:
        finished_at = datetime.now(UTC)
        audit_event("command_rejected", command_id=str(cmd.command_id), reason=str(exc))
        return ExecutionResult(
            command_id=cmd.command_id,
            agent_id=settings.agent_id,
            action=cmd.action,
            status=CommandStatus.REJECTED,
            stderr=str(exc),
            returncode=None,
            error_message=str(exc),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=int((finished_at - started_at).total_seconds() * 1000),
        )

    try:
        if argv == ["__stop_all_containers__"]:
            ps_stdout, _, _ = await _run_subprocess(["docker", "ps", "-q"])
            ids = [i for i in ps_stdout.strip().split() if i]
            if not ids:
                stdout, stderr, returncode = "no running containers", "", 0
            else:
                stdout, stderr, returncode = await _run_subprocess(["docker", "stop", *ids])

        elif argv == ["__inventory_sync__"]:
            stdout, stderr, returncode = "inventory sync scheduled", "", 0

        elif argv == ["__compose_up_all__"]:
            stdout, stderr, returncode = await _run_compose_on_projects(
                await _get_compose_projects(), ["up", "-d"]
            )

        elif argv == ["__compose_down_all__"]:
            stdout, stderr, returncode = await _run_compose_on_projects(
                await _get_compose_projects(), ["down"]
            )

        elif len(argv) == 2 and argv[0] == "__compose_rebuild__":
            stdout, stderr, returncode = await _compose_rebuild(argv[1])

        else:
            stdout, stderr, returncode = await _run_subprocess(argv)

        status = CommandStatus.SUCCESS if returncode == 0 else CommandStatus.FAILED
        audit_event(
            "command_executed",
            command_id=str(cmd.command_id),
            action=cmd.action.value,
            returncode=returncode,
            status=status.value,
        )

        finished_at = datetime.now(UTC)
        return ExecutionResult(
            command_id=cmd.command_id,
            agent_id=settings.agent_id,
            action=cmd.action,
            status=status,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=int((finished_at - started_at).total_seconds() * 1000),
        )

    except CommandRejectedError as exc:
        finished_at = datetime.now(UTC)
        audit_event("command_failed", command_id=str(cmd.command_id), error=str(exc))
        return ExecutionResult(
            command_id=cmd.command_id,
            agent_id=settings.agent_id,
            action=cmd.action,
            status=CommandStatus.FAILED,
            stderr=str(exc),
            returncode=None,
            error_message=str(exc),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=int((finished_at - started_at).total_seconds() * 1000),
        )

    except Exception as exc:
        finished_at = datetime.now(UTC)
        logger.exception("unexpected execution error")
        audit_event("command_error", command_id=str(cmd.command_id), error=str(exc))
        return ExecutionResult(
            command_id=cmd.command_id,
            agent_id=settings.agent_id,
            action=cmd.action,
            status=CommandStatus.FAILED,
            stderr=str(exc),
            returncode=None,
            error_message=str(exc),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=int((finished_at - started_at).total_seconds() * 1000),
        )
