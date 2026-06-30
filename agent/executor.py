"""
Safe command execution via subprocess with strict action whitelisting.

Every action maps to a pre-defined command builder. User-supplied input is
validated before interpolation — no shell=True, no arbitrary command strings.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from agent.config import settings
from agent.models import ActionType, CommandPayload, CommandStatus, ExecutionResult
from agent.security import audit_event

logger = logging.getLogger("agent.executor")

# Docker service names: letters, digits, hyphens, underscores only.
_SERVICE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
# Script names: basename only, no path components.
_SCRIPT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


class CommandRejectedError(Exception):
    """Raised when a command fails validation before execution."""


def _validate_service(service: str | None, action: ActionType) -> str:
    """Ensure Docker actions receive a valid service name."""
    docker_actions = {
        ActionType.DOCKER_RESTART,
        ActionType.DOCKER_REBUILD,
        ActionType.DOCKER_LOGS,
        ActionType.DOCKER_STATUS,
        ActionType.DOCKER_STOP,
        ActionType.DOCKER_START,
    }
    if action in docker_actions:
        if not service:
            raise CommandRejectedError(f"{action.value} requires a service name")
        if not _SERVICE_RE.match(service):
            raise CommandRejectedError(f"invalid service name: {service!r}")
    return service or ""


def _compose_base() -> list[str]:
    """Base docker compose invocation using configured paths."""
    return [
        "docker",
        "compose",
        "-f",
        str(settings.docker_compose_file),
    ]


def _build_command(cmd: CommandPayload) -> list[str]:
    """
    Map a whitelisted action to a concrete argv list.

    Returns a list suitable for subprocess exec (no shell interpretation).
  Raises CommandRejectedError for invalid or unauthorized requests.
    """
    service = _validate_service(cmd.service, cmd.action)
    action = cmd.action

    if action == ActionType.DOCKER_RESTART:
        return _compose_base() + ["restart", service]

    if action == ActionType.DOCKER_REBUILD:
        return _compose_base() + ["up", "-d", "--build", service]

    if action == ActionType.DOCKER_LOGS:
        tail = str(cmd.params.get("tail", 100))
        if not tail.isdigit() or int(tail) > 10_000:
            raise CommandRejectedError("logs tail must be a number <= 10000")
        return _compose_base() + ["logs", f"--tail={tail}", service]

    if action == ActionType.DOCKER_STATUS:
        return _compose_base() + ["ps", service]

    if action == ActionType.DOCKER_STOP:
        return _compose_base() + ["stop", service]

    if action == ActionType.DOCKER_START:
        return _compose_base() + ["start", service]

    if action == ActionType.SERVER_REBOOT:
        token = cmd.params.get("confirmation_token")
        if token != settings.reboot_confirmation_token:
            raise CommandRejectedError("server_reboot requires valid confirmation_token")
        # Use systemd reboot — requires passwordless sudo for the agent user.
        return ["sudo", "/sbin/reboot"]

    if action == ActionType.RUN_SCRIPT:
        script_name = cmd.params.get("script_name")
        if not script_name or not isinstance(script_name, str):
            raise CommandRejectedError("run_script requires params.script_name")
        if not _SCRIPT_RE.match(script_name):
            raise CommandRejectedError(f"invalid script name: {script_name!r}")

        scripts_dir = settings.allowed_scripts_dir.resolve()
        script_path = (scripts_dir / script_name).resolve()

        # Prevent path traversal: resolved path must stay inside scripts_dir.
        if not str(script_path).startswith(str(scripts_dir)):
            raise CommandRejectedError("script path escapes allowed directory")
        if not script_path.is_file():
            raise CommandRejectedError(f"script not found: {script_name}")
        if not script_path.stat().st_mode & 0o111:
            raise CommandRejectedError(f"script is not executable: {script_name}")

        return [str(script_path)]

    raise CommandRejectedError(f"action not in whitelist: {action}")


def _truncate_output(text: str) -> str:
    """Truncate output to configured max bytes, preserving UTF-8 boundaries."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= settings.max_output_bytes:
        return text
    truncated = encoded[: settings.max_output_bytes].decode("utf-8", errors="ignore")
    return truncated + "\n... [output truncated]"


async def _run_subprocess(argv: list[str]) -> tuple[str, str, int]:
    """
    Execute argv asynchronously with timeout and output capture.

    Uses asyncio.create_subprocess_exec — never invokes a shell.
    """
    logger.info("executing command", extra={"argv": argv})

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(settings.docker_work_dir),
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


async def execute_command(cmd: CommandPayload) -> ExecutionResult:
    """
    Validate, execute, and return a structured result for a single command.

    This is the sole entry point for running remote commands on the agent.
    """
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
        audit_event(
            "command_rejected",
            command_id=str(cmd.command_id),
            reason=str(exc),
        )
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
        audit_event(
            "command_failed",
            command_id=str(cmd.command_id),
            error=str(exc),
        )
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
        audit_event(
            "command_error",
            command_id=str(cmd.command_id),
            error=str(exc),
        )
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
