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

  # ── 10 Complete learning path (Persian, step-by-step) ───────────────────
  pdf.add_page()
  pdf.h2("۱۰. مسیر کامل: از عضو جدید تا توسعه‌دهنده حرفه‌ای")
  pdf.write_rtl(
    "این بخش را عنوان به عنوان نخوانید. مراحل شماره‌دار را به ترتیب انجام دهید. "
    "بعد از هر مرحله یک جمله بنویسید که «الان چه می‌دانم». "
    "هدف: شناخت کامل ساختار، خواندن، کاوش، و توسعه امن این پروژه در ۳ تا ۵ هفته."
  )

  pdf.h3("مرحله ۰ — ساختار کامل مخزن (قبل از هر کدی)")
  pdf.write_ltr_block(
    "docker-anywhere/\n"
    "  pyproject.toml, .python-version, uv.lock\n"
    "  agent/  -> main, config, models, security, executor, poller, .env.example, agent.service\n"
    "  control_server/ -> main, config, models, security, cli, .env.example\n"
    "  docs/ -> documentation-fa.html, generate_pdf.py, fonts/"
  )
  pdf.write_rtl("دو پروسه جدا: Control Server (پورت 8000، اپراتور + عامل) و Agent (پورت 8080 محلی، فقط /health).")

  pdf.h3("مرحله ۱ — راه‌اندازی و اولین اجرا (روز ۱–۲)")
  stage1 = [
    "گام ۱.۱: نصب Python 3.12+ و UV. اجرای uv sync در ریشه پروژه.",
    "گام ۱.۲: کپی control_server/.env.example به .env و agent/.env.example به .env. "
    "API_KEY عامل = AGENT_API_KEY سرور. HMAC_SECRET = AGENT_HMAC_SECRET. AGENT_ID=prod-server-01.",
    "گام ۱.۳: ترمینال ۱ — uv run uvicorn control_server.main:app --host 0.0.0.0 --port 8000. "
    "باز کردن /health و /docs. باید ۵ endpoint ببینید.",
    "گام ۱.۴: ترمینال ۲ — uv run uvicorn agent.main:app --host 127.0.0.1 --port 8080. "
    "ظرف ۱۵ ثانیه poll در لاگ دیده شود. /health باید poller_running=true نشان دهد.",
    "گام ۱.۵: ترمینال ۳ — push دستور docker_status با CLI. "
    "command_id بگیرید. در لاگ عامل اجرا را ببینید. commands_executed افزایش یابد.",
    "گام ۱.۶: رسم دیاگرام از حافظه: اپراتور - POST commands - صف - poll - executor - results - history.",
  ]
  for s in stage1:
    pdf.write_rtl(s)

  pdf.add_page()
  pdf.h3("مرحله ۲ — خواندن هر فایل به ترتیب وابستگی (روز ۳–۷)")
  stage2 = [
    "گام ۲.۱: pyproject.toml و .python-version — FastAPI، httpx، pydantic-settings، UV.",
    "گام ۲.۲: agent/models.py — ActionType (۸ action)، CommandStatus، CommandPayload، "
    "ExecutionResult، HealthResponse. تمرین: توکن reboot در params است.",
    "گام ۲.۳: control_server/models.py — PushCommandRequest، QueuedCommand، HistoryEntry. "
    "ببینید ActionType از agent.models import می‌شود.",
    "گام ۲.۴: agent/.env.example + agent/config.py و control_server/.env.example + config.py — "
    "جدول تطابق env بین دو سرویس بنویسید.",
    "گام ۲.۵: agent/security.py (signed_headers) سپس control_server/security.py (verify_signed_request) — "
    "رشته کاننیکال، nonce، timestamp، compare_digest.",
    "گام ۲.۶: control_server/main.py — _queues و _history در حافظه. "
    "هر route: POST commands، GET poll، POST results، GET history. نقش Operator vs Agent.",
    "گام ۲.۷: control_server/cli.py — تابع _sign و push_command و argparse.",
    "گام ۲.۸: agent/executor.py — _build_command برای هر action، _run_subprocess بدون shell، "
    "run_script با path traversal check، server_reboot با confirmation_token، execute_command.",
    "گام ۲.۹: agent/poller.py — حلقه poll، httpx، backoff، به‌روزرسانی state برای health.",
    "گام ۲.۱۰: agent/main.py — lifespan شروع/توقف poller، فقط /health و /.",
    "گام ۲.۱۱: agent/agent.service — ExecStart و hardening systemd.",
  ]
  for s in stage2:
    pdf.write_rtl(s)

  pdf.h3("مرحله ۳ — کاوش عملی هر مسیر (هفته ۲)")
  stage3 = [
    "گام ۳.۱: هر action Docker را با CLI تست کنید: status، logs، restart، stop، start، rebuild. "
    "لاگ عامل و history را بخوانید.",
    "گام ۳.۲: تست رد امنیتی — کلید اشتباه (۴۰۱)، reboot بدون token (rejected)، نام سرویس نامعتبر (validation).",
    "گام ۳.۳: breakpoint در main.py (push)، poller.py (دریافت دستور)، executor.py (execute_command). "
    "یک دستور را قدم‌به‌قدم debug کنید.",
    "گام ۳.۴: git log --oneline -20 — ببینید تیم اخیراً روی چه چیزی کار کرده.",
  ]
  for s in stage3:
    pdf.write_rtl(s)

  pdf.add_page()
  pdf.h3("مرحله ۴ — اولین کارهای توسعه (هفته ۳)")
  stage4 = [
    "گام ۴.۱: افزودن action جدید (مثلاً docker_pull) — ActionType در models.py، "
    "شاخه در _build_command() با argv ثابت، تست با CLI، به‌روزرسانی مستندات.",
    "گام ۴.۲: تغییر POLL_INTERVAL_SECONDS در agent/.env — مشاهده poll سریع‌تر در /health.",
    "گام ۴.۳: افزودن لاگ ساختاریافته در executor با audit_event موجود.",
    "گام ۴.۴: چک‌لیست PR — بدون shell=True، بدون دستور خام از شبکه، "
    "secret فقط در .env.example، auth جدا برای operator و agent، اعتبارسنجی Pydantic.",
  ]
  for s in stage4:
    pdf.write_rtl(s)

  pdf.h3("مرحله ۵ — تولید و عملیات (هفته ۴)")
  stage5 = [
    "گام ۵.۱: Control Server پشت HTTPS (Nginx + TLS). کلید با openssl rand -hex 32. "
    "برنامه جایگزینی صف in-memory با PostgreSQL/Redis.",
    "گام ۵.۲: نصب agent روی لینوکس — uv sync، agent/.env با chmod 600، "
    "کاربر در گروه docker، systemd enable secure-agent، curl 127.0.0.1:8080/health.",
    "گام ۵.۳: عیب‌یابی — عامل poll نمی‌کند (لاگ، شبکه، کلید)، "
    "دستور pending ماند (agent_id یا agent خاموش)، failed (stderr در history).",
  ]
  for s in stage5:
    pdf.write_rtl(s)

  pdf.h3("مرحله ۶ — تسلط حرفه‌ای (هفته ۵ به بعد)")
  stage6 = [
    "گام ۶.۱: بدون نگاه به کد توضیح دهید: تفاوت auth اپراتور و عامل، "
    "صف چند دستور، چرا outbound polling، خطر restart سرور کنترل.",
    "گام ۶.۲: بتوانید اضافه کنید: action، API اپراتور، config، persistence، تست.",
  ]
  for s in stage6:
    pdf.write_rtl(s)

  pdf.h3("چک‌لیست تسلط (همه باید برقرار باشد)")
  mastery = [
    "رسم معماری و نقش هر فایل بدون یادداشت",
    "خواندن خط‌به‌خط همه فایل‌های Python در agent و control_server",
    "اجرای هر ۸ ActionType (یا دلیل عدم اجرا)",
    "trace در debugger در سه لایه",
    "حداقل یک تغییر end-to-end (action، لاگ، یا config)",
    "توضیح HMAC و ضد replay به همکار",
    "استقرار agent با systemd و control server با HTTPS",
    "شناخت شکاف تولید (in-memory، نبود تست) و پیشنهاد راه‌حل",
  ]
  for m in mastery:
    pdf.write_rtl("- " + m)

  pdf.box(
    "توسعه‌دهنده حرفه‌ای روی این پروژه کسی است که بدون نقشه فایل درست را باز کند، "
    "باگ را از history تا executor در چند دقیقه trace کند، و هر PR که shell خام از شبکه "
    "می‌پذیرد را رد کند. نسخه انگلیسی کامل با جزئیات بیشتر در documentation-fa.html بخش ۱۰."
  )

  pdf.output(str(PDF_FILE))
  print(f"PDF created: {PDF_FILE}")


if __name__ == "__main__":
  build_pdf()
