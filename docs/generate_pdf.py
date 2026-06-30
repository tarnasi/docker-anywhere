#!/usr/bin/env python3
"""
Generate Persian RTL PDF documentation for docker-anywhere.

Uses fpdf2 + Vazirmatn font + python-bidi for correct RTL rendering.
"""

from __future__ import annotations

import re
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from fpdf import FPDF

DOCS_DIR = Path(__file__).resolve().parent
FONTS_DIR = DOCS_DIR / "fonts"
PDF_FILE = DOCS_DIR / "docker-anywhere-documentation-fa.pdf"


def rtl(text: str) -> str:
    """Reshape and reorder Persian/Arabic text for PDF RTL display."""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


class PersianPDF(FPDF):
  def __init__(self) -> None:
    super().__init__(orientation="P", unit="mm", format="A4")
    self.set_auto_page_break(auto=True, margin=18)
    self.add_font("Vazir", "", str(FONTS_DIR / "Vazirmatn-Regular.ttf"))
    self.add_font("Vazir", "B", str(FONTS_DIR / "Vazirmatn-Bold.ttf"))

  def header(self) -> None:
    self.set_font("Vazir", "B", 9)
    self.set_text_color(100, 100, 100)
    self.cell(0, 8, rtl("مستندات docker-anywhere"), align="R")
    self.ln(4)

  def footer(self) -> None:
    self.set_y(-12)
    self.set_font("Vazir", "", 9)
    self.set_text_color(120, 120, 120)
    self.cell(0, 8, rtl(f"صفحه {self.page_no()}"), align="C")

  def write_rtl(self, text: str, size: int = 11, bold: bool = False) -> None:
    self.set_font("Vazir", "B" if bold else "", size)
    self.set_text_color(26, 26, 26)
    self.multi_cell(0, 7, rtl(text), align="R")
    self.ln(2)

  def write_ltr_block(self, text: str, size: int = 9) -> None:
    """Code / ASCII blocks — left-aligned LTR."""
    self.set_font("Vazir", "", size)
    self.set_fill_color(244, 246, 248)
    self.set_text_color(11, 61, 74)
    self.multi_cell(0, 5, text, align="L", fill=True)
    self.ln(3)

  def h1(self, text: str) -> None:
    self.ln(4)
    self.set_font("Vazir", "B", 18)
    self.set_text_color(15, 61, 94)
    self.multi_cell(0, 10, rtl(text), align="R")
    self.set_draw_color(15, 61, 94)
    self.line(10, self.get_y(), 200, self.get_y())
    self.ln(6)

  def h2(self, text: str) -> None:
    self.ln(3)
    self.set_font("Vazir", "B", 14)
    self.set_text_color(21, 82, 122)
    self.multi_cell(0, 8, rtl(text), align="R")
    self.ln(3)

  def h3(self, text: str) -> None:
    self.ln(2)
    self.set_font("Vazir", "B", 12)
    self.set_text_color(31, 111, 139)
    self.multi_cell(0, 7, rtl(text), align="R")
    self.ln(2)

  def box(self, text: str) -> None:
    self.set_fill_color(240, 247, 251)
    self.set_draw_color(184, 212, 232)
    y = self.get_y()
    self.set_font("Vazir", "", 10)
    self.set_text_color(26, 26, 26)
    self.multi_cell(0, 6, rtl(text), align="R", fill=True, border=1)
    self.ln(4)


def build_pdf() -> None:
  pdf = PersianPDF()
  pdf.add_page()

  # ── Cover / intro ──────────────────────────────────────────────────────
  pdf.h1("مستندات پروژه docker-anywhere")
  pdf.write_rtl(
    "راهنمای کامل فارسی — عامل اجرای دستور از راه دور با ارتباط خروجی‌محور "
    "(Outbound-Only) برای مدیریت Docker و سرور تولید"
  )
  pdf.box(
    "خلاصه: این پروژه دو بخش دارد — Agent روی سرور تولید (فقط درخواست خروجی) "
    "و Control Server مرکزی (صف دستورات و تاریخچه). هیچ پورت ورودی برای اجرای "
    "دستور از اینترنت روی سرور تولید باز نیست."
  )

  # ── 1 Overview ─────────────────────────────────────────────────────────
  pdf.h2("۱. معرفی کلی پروژه")
  pdf.write_rtl(
    "پروژه docker-anywhere با Python، FastAPI و UV ساخته شده است. "
    "هدف: مدیریت امن Docker و سرور از راه دور بدون باز کردن API ورودی روی تولید."
  )
  pdf.write_rtl("مشکل API ورودی: هر مهاجم می‌تواند به POST /execute حمله کند.")
  pdf.write_rtl("راه‌حل: Agent هر ۱۵ ثانیه Control Server را poll می‌کند، "
                "فقط دستورات Whitelist اجرا می‌شود، نتیجه برمی‌گردد.")

  pdf.h3("دو پوشه اصلی")
  pdf.write_rtl("agent/ — روی سرور تولید: poll، اجرا، گزارش نتیجه")
  pdf.write_rtl("control_server/ — سرور مرکزی: صف دستور، احراز هویت، تاریخچه")

  # ── 2 Architecture ─────────────────────────────────────────────────────
  pdf.add_page()
  pdf.h2("۲. معماری و جریان کار")
  pdf.write_ltr_block(
    "Operator --POST /api/v1/commands--> Control Server\n"
    "Agent    <--GET  /api/v1/poll-------- Control Server (every 15s)\n"
    "Agent    --POST /api/v1/results-----> Control Server\n"
    "Agent: only GET /health on 127.0.0.1 (local monitoring)"
  )
  pdf.write_rtl("۱. اپراتور دستور را با کلید Operator به صف می‌فرستد.")
  pdf.write_rtl("۲. Agent در poll بعدی دستور را می‌گیرد.")
  pdf.write_rtl("۳. executor.py دستور را به argv امن تبدیل می‌کند (بدون shell=True).")
  pdf.write_rtl("۴. نتیجه stdout/stderr/returncode به Control Server برمی‌گردد.")

  # ── 3 Agent folder ─────────────────────────────────────────────────────
  pdf.h2("۳. پوشه agent/ — عامل روی سرور تولید")

  files_agent = [
    ("agent/main.py — نقطه ورود FastAPI",
     "startup: تنظیم لاگ و شروع poller. shutdown: توقف poller. "
     "GET /health: وضعیت عامل برای systemd. GET /: پاسخ ساده. "
     "هیچ endpoint اجرای دستور از راه دور وجود ندارد."),
    ("agent/config.py — تنظیمات Pydantic",
     "خواندن agent/.env: AGENT_ID، API_KEY، HMAC_SECRET، CONTROL_SERVER_URL، "
     "POLL_INTERVAL_SECONDS، مسیرهای Docker، ALLOWED_SCRIPTS_DIR، "
     "REBOOT_CONFIRMATION_TOKEN، timeout و LOG_FILE."),
    ("agent/models.py — مدل‌های داده",
     "ActionType (enum دستورات مجاز)، CommandPayload، ExecutionResult، "
     "HealthResponse، CommandStatus."),
    ("agent/security.py — امنیت",
     "setup_logging و audit_event (لاگ JSON). signed_headers و signed_request "
     "با HMAC-SHA256. هدرها: X-API-Key، X-Timestamp، X-Nonce، X-Signature. "
     "RateLimiter برای /health."),
    ("agent/executor.py — اجرای دستور",
     "_build_command: map هر action به argv ثابت. اعتبارسنجی نام سرویس با regex. "
     "run_script: فقط از ALLOWED_SCRIPTS_DIR، ضد path traversal. "
     "server_reboot: نیاز به confirmation_token. _run_subprocess با asyncio و timeout. "
     "execute_command: نقطه ورود اصلی."),
    ("agent/poller.py — حلقه polling",
     "AgentPoller: httpx AsyncClient، GET poll، execute، POST results. "
     "backoff نمایی در خطا. نگهداری last_poll_at و commands_executed برای health."),
    ("agent/.env.example", "نمونه متغیرهای محیط — کپی به .env"),
    ("agent/agent.service", "نمونه systemd با hardening امنیتی"),
    ("agent/__init__.py", "علامت‌گذاری پکیج Python"),
  ]
  for title, body in files_agent:
    pdf.h3(title)
    pdf.write_rtl(body)

  # ── 4 Control server ───────────────────────────────────────────────────
  pdf.add_page()
  pdf.h2("۴. پوشه control_server/ — سرور کنترل")
  pdf.write_rtl(
    "سرور مرکزی. داده‌ها فعلاً in-memory است — برای تولید واقعی PostgreSQL/Redis پیشنهاد می‌شود."
  )

  endpoints = [
    "GET /health — سلامت سرور",
    "POST /api/v1/commands — اپراتور: صف کردن دستور (کلید Operator)",
    "GET /api/v1/poll?agent_id=... — Agent: برداشتن دستور pending",
    "POST /api/v1/results — Agent: ارسال نتیجه اجرا",
    "GET /api/v1/history — اپراتور: مشاهده تاریخچه",
  ]
  pdf.h3("control_server/main.py — API")
  for ep in endpoints:
    pdf.write_rtl(ep)

  files_cs = [
    ("control_server/config.py",
     "AGENT_API_KEY/HMAC (مشترک با Agent)، OPERATOR_API_KEY/HMAC، "
     "MAX_TIMESTAMP_SKEW، rate limit."),
    ("control_server/security.py",
     "verify_signed_request: API key، timestamp، nonce، HMAC. ضد replay و timing attack."),
    ("control_server/models.py",
     "PushCommandRequest، QueuedCommand، HistoryEntry — استفاده مجدد از agent.models."),
    ("control_server/cli.py",
     "CLI اپراتور برای push دستور امضا‌شده بدون نوشتن کد."),
    ("control_server/.env.example", "نمونه تنظیمات سرور کنترل"),
  ]
  for title, body in files_cs:
    pdf.h3(title)
    pdf.write_rtl(body)

  # ── 5 Root ─────────────────────────────────────────────────────────────
  pdf.h2("۵. فایل‌های ریشه")
  pdf.write_rtl("pyproject.toml — تعریف پروژه UV و وابستگی‌ها (fastapi، httpx)")
  pdf.write_rtl("main.py (ریشه) — نسخه قدیمی آزمایشی؛ جایگزین: agent/main.py")
  pdf.write_rtl(".python-version — نسخه Python (۳.۱۲+)")

  # ── 6 Actions ──────────────────────────────────────────────────────────
  pdf.add_page()
  pdf.h2("۶. دستورات مجاز (Whitelist)")
  actions = [
    "docker_restart — ری‌استارت سرویس (نیاز به service)",
    "docker_rebuild — build و up -d",
    "docker_logs — لاگ (params.tail پیش‌فرض ۱۰۰)",
    "docker_status — docker compose ps",
    "docker_stop / docker_start — توقف / شروع",
    "server_reboot — ریبوت (نیاز confirmation_token)",
    "run_script — اسکریپت از پوشه مجاز (params.script_name)",
  ]
  for a in actions:
    pdf.write_rtl("• " + a)

  # ── 7 Security ─────────────────────────────────────────────────────────
  pdf.h2("۷. امنیت")
  security = [
    "فقط ارتباط خروجی از Agent — بدون پورت دستور ورودی",
    "/health فقط 127.0.0.1",
    "API key + HMAC روی هر درخواست",
    "Nonce و timestamp ضد replay",
    "Whitelist — بدون shell — subprocess با argv ثابت",
    "کلیدها: openssl rand -hex 32 — chmod 600 روی .env",
    "HTTPS اجباری برای Control Server در تولید",
  ]
  for s in security:
    pdf.write_rtl("• " + s)

  # ── 8 Run ──────────────────────────────────────────────────────────────
  pdf.h2("۸. نحوه اجرا با UV")
  pdf.write_ltr_block(
    "uv sync\n"
    "cp control_server/.env.example control_server/.env\n"
    "uv run uvicorn control_server.main:app --host 0.0.0.0 --port 8000\n\n"
    "cp agent/.env.example agent/.env\n"
    "uv run uvicorn agent.main:app --host 127.0.0.1 --port 8080"
  )
  pdf.write_ltr_block(
    "export OPERATOR_API_KEY=...\n"
    "export OPERATOR_HMAC_SECRET=...\n"
    "uv run python -m control_server.cli push \\\n"
    "  --agent-id prod-server-01 --action docker_restart --service web"
  )

  # ── 9 New action ───────────────────────────────────────────────────────
  pdf.h2("۹. افزودن دستور جدید")
  pdf.write_rtl("۱. مقدار جدید به ActionType در agent/models.py")
  pdf.write_rtl("۲. شاخه در _build_command() داخل agent/executor.py — فقط argv ثابت")
  pdf.write_rtl("۳. ارسال از CLI یا API — هرگز رشته shell خام قبول نکنید")
  pdf.box("هشدار: هر action جدید باید ورودی validate شود و به دستور از پیش تعریف‌شده map شود.")

  pdf.output(str(PDF_FILE))
  print(f"PDF created: {PDF_FILE}")


if __name__ == "__main__":
  build_pdf()
