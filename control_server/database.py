"""SQLite persistence for the control server."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from agent.models import ActionType, CommandStatus, ExecutionResult
from control_server.config import settings

_iso = lambda: datetime.now(UTC).isoformat()


class Database:
    """Thread-safe SQLite wrapper."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_heartbeat (
                    agent_id TEXT PRIMARY KEY,
                    last_seen_at TEXT NOT NULL,
                    last_inventory_at TEXT,
                    status TEXT NOT NULL DEFAULT 'unknown'
                );

                CREATE TABLE IF NOT EXISTS command_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL,
                    service TEXT,
                    params_json TEXT NOT NULL DEFAULT '{}',
                    description TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'docker',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execute_orders (
                    command_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    template_id INTEGER,
                    action TEXT NOT NULL,
                    service TEXT,
                    params_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    stdout TEXT NOT NULL DEFAULT '',
                    stderr TEXT NOT NULL DEFAULT '',
                    returncode INTEGER,
                    error_message TEXT,
                    FOREIGN KEY (template_id) REFERENCES command_templates(id)
                );

                CREATE INDEX IF NOT EXISTS idx_orders_agent_status
                    ON execute_orders(agent_id, status);

                CREATE TABLE IF NOT EXISTS containers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    container_id TEXT NOT NULL,
                    name TEXT,
                    image TEXT,
                    status TEXT,
                    state TEXT,
                    ports TEXT,
                    project_path TEXT,
                    labels_json TEXT NOT NULL DEFAULT '{}',
                    synced_at TEXT NOT NULL,
                    UNIQUE(agent_id, container_id)
                );

                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    image_id TEXT NOT NULL,
                    repository TEXT,
                    tag TEXT,
                    size_bytes INTEGER,
                    created_at_image TEXT,
                    synced_at TEXT NOT NULL,
                    UNIQUE(agent_id, repository, tag)
                );

                CREATE TABLE IF NOT EXISTS networks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    network_id TEXT NOT NULL,
                    name TEXT,
                    driver TEXT,
                    scope TEXT,
                    synced_at TEXT NOT NULL,
                    UNIQUE(agent_id, network_id)
                );

                CREATE TABLE IF NOT EXISTS api_call_log (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_agent_poll_at TEXT,
                    last_inventory_sync_at TEXT,
                    last_order_executed_at TEXT
                );

                INSERT OR IGNORE INTO api_call_log (id) VALUES (1);
                """
            )
            self._migrate_images_unique(conn)
            self._seed_templates(conn)

    def _migrate_images_unique(self, conn: sqlite3.Connection) -> None:
        """Docker lists one row per repo:tag; the same image_id can repeat."""
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='images'"
        ).fetchone()
        if not row or not row[0]:
            return
        ddl = row[0]
        if "UNIQUE(agent_id, repository, tag)" in ddl:
            return
        if "UNIQUE(agent_id, image_id)" not in ddl:
            return
        conn.executescript(
            """
            CREATE TABLE images_migrated (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                image_id TEXT NOT NULL,
                repository TEXT,
                tag TEXT,
                size_bytes INTEGER,
                created_at_image TEXT,
                synced_at TEXT NOT NULL,
                UNIQUE(agent_id, repository, tag)
            );
            INSERT OR IGNORE INTO images_migrated
                (id, agent_id, image_id, repository, tag, size_bytes, created_at_image, synced_at)
            SELECT id, agent_id, image_id, repository, tag, size_bytes, created_at_image, synced_at
            FROM images;
            DROP TABLE images;
            ALTER TABLE images_migrated RENAME TO images;
            """
        )

    @staticmethod
    def _dedupe_images(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for img in images:
            key = (img.get("repository") or "", img.get("tag") or "")
            unique[key] = img
        return list(unique.values())

    def _seed_templates(self, conn: sqlite3.Connection) -> None:
        now = _iso()
        defaults = [
            ("Compose Up", ActionType.DOCKER_COMPOSE_UP.value, None, "{}", "Start all compose services", "compose"),
            ("Compose Down", ActionType.DOCKER_COMPOSE_DOWN.value, None, "{}", "Stop and remove compose stack", "compose"),
            ("Compose Restart", ActionType.DOCKER_COMPOSE_RESTART.value, None, "{}", "Restart all compose services", "compose"),
            ("Stop All Containers", ActionType.CONTAINERS_STOP_ALL.value, None, "{}", "Stop every running container", "containers"),
            ("Remove All Containers", ActionType.CONTAINERS_REMOVE_ALL.value, None, "{}", "Remove all stopped containers", "containers"),
            ("Sync Inventory", ActionType.INVENTORY_SYNC.value, None, "{}", "Refresh containers, images, networks", "system"),
            (
                "Purge WITSML server",
                ActionType.PURGE_WITSML_SERVER.value,
                None,
                '{"project_path":"/home/app/witsml-server"}',
                "Hard compose down + delete /home/app/witsml-server (best-effort)",
                "danger",
            ),
        ]
        existing = {
            row[0]
            for row in conn.execute("SELECT action FROM command_templates").fetchall()
        }
        for name, action, service, params, desc, cat in defaults:
            if action in existing:
                continue
            conn.execute(
                """
                INSERT INTO command_templates
                    (name, action, service, params_json, description, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, action, service, params, desc, cat, now, now),
            )

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def touch_agent_poll(self, agent_id: str) -> None:
        now = _iso()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_heartbeat (agent_id, last_seen_at, status)
                VALUES (?, ?, 'online')
                ON CONFLICT(agent_id) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    status = 'online'
                """,
                (agent_id, now),
            )
            conn.execute(
                "UPDATE api_call_log SET last_agent_poll_at = ? WHERE id = 1",
                (now,),
            )

    def touch_inventory_sync(self, agent_id: str) -> None:
        now = _iso()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_heartbeat (agent_id, last_seen_at, last_inventory_at, status)
                VALUES (?, ?, ?, 'online')
                ON CONFLICT(agent_id) DO UPDATE SET
                    last_inventory_at = excluded.last_inventory_at,
                    last_seen_at = excluded.last_seen_at,
                    status = 'online'
                """,
                (agent_id, now, now),
            )
            conn.execute(
                "UPDATE api_call_log SET last_inventory_sync_at = ? WHERE id = 1",
                (now,),
            )

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_heartbeat ORDER BY last_seen_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_api_log(self) -> dict[str, Any]:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM api_call_log WHERE id = 1").fetchone()
        return dict(row) if row else {}

    # ── Command templates ─────────────────────────────────────────────────────

    def list_templates(self) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM command_templates ORDER BY category, name"
            ).fetchall()
        return [self._template_row(r) for r in rows]

    def get_template(self, template_id: int) -> dict[str, Any] | None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM command_templates WHERE id = ?", (template_id,)
            ).fetchone()
        return self._template_row(row) if row else None

    def create_template(
        self,
        name: str,
        action: str,
        service: str | None,
        params: dict[str, Any],
        description: str,
        category: str,
    ) -> dict[str, Any]:
        now = _iso()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO command_templates
                    (name, action, service, params_json, description, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, action, service, json.dumps(params), description, category, now, now),
            )
            row = conn.execute(
                "SELECT * FROM command_templates WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return self._template_row(row)

    def update_template(
        self,
        template_id: int,
        *,
        name: str | None = None,
        action: str | None = None,
        service: str | None = None,
        params: dict[str, Any] | None = None,
        description: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_template(template_id)
        if not existing:
            return None
        now = _iso()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                UPDATE command_templates SET
                    name = ?, action = ?, service = ?, params_json = ?,
                    description = ?, category = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    name if name is not None else existing["name"],
                    action if action is not None else existing["action"],
                    service if service is not None else existing["service"],
                    json.dumps(params if params is not None else existing["params"]),
                    description if description is not None else existing["description"],
                    category if category is not None else existing["category"],
                    now,
                    template_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM command_templates WHERE id = ?", (template_id,)
            ).fetchone()
        return self._template_row(row)

    def delete_template(self, template_id: int) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM command_templates WHERE id = ?", (template_id,)
            )
        return cur.rowcount > 0

    @staticmethod
    def _template_row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["params"] = json.loads(d.pop("params_json"))
        return d

    # ── Execute orders ────────────────────────────────────────────────────────

    def has_active_order(self, agent_id: str) -> bool:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM execute_orders
                WHERE agent_id = ? AND status IN ('pending', 'running')
                LIMIT 1
                """,
                (agent_id,),
            ).fetchone()
        return row is not None

    def create_order(
        self,
        agent_id: str,
        action: str,
        service: str | None,
        params: dict[str, Any],
        template_id: int | None = None,
    ) -> dict[str, Any]:
        if self.has_active_order(agent_id):
            raise ValueError("An order is already pending or running for this agent")
        command_id = str(uuid4())
        now = _iso()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO execute_orders
                    (command_id, agent_id, template_id, action, service, params_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (command_id, agent_id, template_id, action, service, json.dumps(params), now),
            )
            row = conn.execute(
                "SELECT * FROM execute_orders WHERE command_id = ?", (command_id,)
            ).fetchone()
        return self._order_row(row)

    def create_order_from_template(self, agent_id: str, template_id: int) -> dict[str, Any]:
        tpl = self.get_template(template_id)
        if not tpl:
            raise ValueError("template not found")
        return self.create_order(
            agent_id=agent_id,
            action=tpl["action"],
            service=tpl.get("service"),
            params=tpl["params"],
            template_id=template_id,
        )

    def poll_next_order(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM execute_orders
                WHERE agent_id = ? AND status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (agent_id,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE execute_orders SET status = 'running' WHERE command_id = ?",
                (row["command_id"],),
            )
            row = conn.execute(
                "SELECT * FROM execute_orders WHERE command_id = ?", (row["command_id"],)
            ).fetchone()
        return self._order_row(row)

    def save_result(self, result: ExecutionResult) -> bool:
        now = _iso()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE execute_orders SET
                    status = ?,
                    finished_at = ?,
                    stdout = ?,
                    stderr = ?,
                    returncode = ?,
                    error_message = ?
                WHERE command_id = ?
                """,
                (
                    result.status.value,
                    result.finished_at.isoformat(),
                    result.stdout,
                    result.stderr,
                    result.returncode,
                    result.error_message,
                    str(result.command_id),
                ),
            )
            if cur.rowcount:
                conn.execute(
                    "UPDATE api_call_log SET last_order_executed_at = ? WHERE id = 1",
                    (now,),
                )
        return cur.rowcount > 0

    def list_orders(self, agent_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = min(max(limit, 1), 500)
        with self._lock, self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    """
                    SELECT * FROM execute_orders WHERE agent_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM execute_orders ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._order_row(r) for r in rows]

    def get_active_order(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM execute_orders
                WHERE agent_id = ? AND status IN ('pending', 'running')
                ORDER BY created_at ASC LIMIT 1
                """,
                (agent_id,),
            ).fetchone()
        return self._order_row(row) if row else None

    def cancel_active_orders(self, agent_id: str, reason: str = "cancelled by operator") -> int:
        """Mark all pending/running orders for an agent as failed so new work can queue."""
        now = _iso()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE execute_orders SET
                    status = 'failed',
                    finished_at = ?,
                    error_message = ?
                WHERE agent_id = ? AND status IN ('pending', 'running')
                """,
                (now, reason, agent_id),
            )
        return cur.rowcount

    def append_order_progress(self, command_id: str, message: str) -> bool:
        """Append a live progress line to stdout while the order is running."""
        line = message.rstrip() + "\n"
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE execute_orders SET
                    stdout = COALESCE(stdout, '') || ?
                WHERE command_id = ? AND status = 'running'
                """,
                (line, command_id),
            )
        return cur.rowcount > 0

    def fail_order(self, command_id: str, error_message: str) -> bool:
        """Force-fail a stuck pending/running order (e.g. agent cannot parse action)."""
        now = _iso()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE execute_orders SET
                    status = 'failed',
                    finished_at = ?,
                    error_message = ?
                WHERE command_id = ? AND status IN ('pending', 'running')
                """,
                (now, error_message, command_id),
            )
        return cur.rowcount > 0

    @staticmethod
    def _order_row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["params"] = json.loads(d.pop("params_json"))
        return d

    # ── Inventory ─────────────────────────────────────────────────────────────

    def replace_inventory(
        self,
        agent_id: str,
        containers: list[dict[str, Any]],
        images: list[dict[str, Any]],
        networks: list[dict[str, Any]],
    ) -> None:
        now = _iso()
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM containers WHERE agent_id = ?", (agent_id,))
            conn.execute("DELETE FROM images WHERE agent_id = ?", (agent_id,))
            conn.execute("DELETE FROM networks WHERE agent_id = ?", (agent_id,))

            for c in containers:
                conn.execute(
                    """
                    INSERT INTO containers
                        (agent_id, container_id, name, image, status, state, ports,
                         project_path, labels_json, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        c["container_id"],
                        c.get("name"),
                        c.get("image"),
                        c.get("status"),
                        c.get("state"),
                        c.get("ports"),
                        c.get("project_path"),
                        json.dumps(c.get("labels", {})),
                        now,
                    ),
                )

            for img in self._dedupe_images(images):
                conn.execute(
                    """
                    INSERT INTO images
                        (agent_id, image_id, repository, tag, size_bytes, created_at_image, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        img["image_id"],
                        img.get("repository"),
                        img.get("tag"),
                        img.get("size_bytes"),
                        img.get("created_at"),
                        now,
                    ),
                )

            for net in networks:
                conn.execute(
                    """
                    INSERT INTO networks
                        (agent_id, network_id, name, driver, scope, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        net["network_id"],
                        net.get("name"),
                        net.get("driver"),
                        net.get("scope"),
                        now,
                    ),
                )

        self.touch_inventory_sync(agent_id)

    def list_containers(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM containers WHERE agent_id = ? ORDER BY name",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM containers ORDER BY agent_id, name"
                ).fetchall()
        return [self._inv_row(r) for r in rows]

    def list_images(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM images WHERE agent_id = ? ORDER BY repository, tag",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM images ORDER BY agent_id, repository, tag"
                ).fetchall()
        return [self._inv_row(r) for r in rows]

    def list_networks(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM networks WHERE agent_id = ? ORDER BY name",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM networks ORDER BY agent_id, name"
                ).fetchall()
        return [self._inv_row(r) for r in rows]

    @staticmethod
    def _inv_row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        if "labels_json" in d:
            d["labels"] = json.loads(d.pop("labels_json"))
        return d


db = Database(settings.database_path)
