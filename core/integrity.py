"""
Project Integrity & Custom Extension Engine for VPS Telegram Bot.

Features:
- SHA-256 verification of core files against git upstream (origin/main or custom branch).
- Cross-platform line-ending normalization (prevents CRLF vs LF false positives).
- Detection and isolation of user custom extensions (custom/modules, custom/web, etc.).
- Safe backup generation before updates to prevent overwriting user modifications.
- Template generation for custom modules and WebUI pages.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("core.integrity")

# Paths & patterns to protect / inspect
CORE_SYSTEM_PATTERNS = [
    "core",
    "modules",
    "bot.py",
    "watchdog.py",
    "manage.py",
    "migrate.py",
    "requirements.txt",
    "aerich.ini",
    "Dockerfile",
    "docker-compose.yml",
    "deploy.sh",
    "deploy_en.sh",
]

# Deployment artifacts that are intentionally cleaned up on VPS hosts (e.g. systemd mode)
# If these files are absent locally, they do NOT trigger a MISSING_LOCAL alert.
OPTIONAL_DEPLOY_PATTERNS = {
    "Dockerfile",
    "docker-compose.yml",
    "deploy.sh",
    "deploy_en.sh",
    "node",
}

# Paths explicitly excluded from integrity verification
IGNORED_PATTERNS = {
    "__pycache__",
    ".git",
    ".env",
    ".backups",
    "custom",
    "modules/custom",
    "core/static/vendor",
    "logs",
    "db.sqlite3",
    "db.sqlite3-journal",
    ".idea",
    ".pytest_cache",
}


def _normalize_content(raw_bytes: bytes, is_binary: bool = False) -> bytes:
    """Normalize CRLF to LF for text files to prevent false diffs across OS."""
    if is_binary:
        return raw_bytes
    try:
        # If decode succeeds, normalize newlines
        text = raw_bytes.decode("utf-8")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        return normalized.encode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes


def compute_sha256(file_path: Path | str, normalize_text: bool = True) -> str:
    """Compute SHA-256 hash of a local file."""
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    raw = p.read_bytes()
    if normalize_text:
        raw = _normalize_content(raw)
    return hashlib.sha256(raw).hexdigest()


def get_git_remote_blob(
    rel_path: str, branch: str = "main", repo_root: Path | str = "."
) -> Optional[bytes]:
    """Retrieve raw file content from git upstream origin/{branch}:{rel_path}."""
    git_path = rel_path.replace("\\", "/")
    cmd = ["git", "show", f"origin/{branch}:{git_path}"]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if res.returncode == 0:
            return res.stdout
    except Exception as e:
        logger.debug(f"Git show failed for {rel_path}: {e}")
    return None


def get_git_tracked_files(
    repo_root: Path | str = ".", branch: str = "main"
) -> List[str]:
    """List tracked files from origin/{branch}."""
    cmd = ["git", "ls-tree", "-r", "--name-only", f"origin/{branch}"]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception as e:
        logger.debug(f"Git ls-tree failed: {e}")
    return []


def is_system_file(rel_path: str) -> bool:
    """Determine whether a file belongs to the core system codebase."""
    normalized = rel_path.replace("\\", "/")
    # Ignore blacklisted dirs
    for ignored in IGNORED_PATTERNS:
        if normalized == ignored or normalized.startswith(f"{ignored}/"):
            return False

    # Check if inside any core patterns
    for pattern in CORE_SYSTEM_PATTERNS:
        if normalized == pattern or normalized.startswith(f"{pattern}/"):
            return True
    return False


@dataclass
class CustomFileEntry:
    category: str  # 'module', 'web_route', 'web_template', 'web_static'
    rel_path: str
    abs_path: str
    sha256: str
    modified_time: str


@dataclass
class ModifiedFileEntry:
    rel_path: str
    local_sha256: str
    remote_sha256: str
    status: str  # 'MODIFIED', 'MISSING_LOCAL', 'UNTRACKED_SYSTEM'


@dataclass
class IntegrityReport:
    branch: str
    timestamp: str
    status: str  # 'OK', 'CUSTOM_ACTIVE', 'MODIFIED', 'ERROR'
    total_checked: int
    matches_count: int
    modified_files: List[ModifiedFileEntry] = field(default_factory=list)
    custom_files: List[CustomFileEntry] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def find_custom_extensions(repo_root: Path | str = ".") -> List[CustomFileEntry]:
    """Find all user-defined custom files in custom/ and modules/custom/."""
    root = Path(repo_root).resolve()
    results: List[CustomFileEntry] = []

    search_dirs = [
        (root / "custom" / "modules", "module"),
        (root / "modules" / "custom", "module"),
        (root / "custom" / "web" / "routes", "web_route"),
        (root / "custom" / "web" / "templates", "web_template"),
        (root / "custom" / "web" / "static", "web_static"),
    ]

    for dir_path, category in search_dirs:
        if not dir_path.is_dir():
            continue
        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.name.startswith("__") or file_path.suffix in (".pyc", ".tmp"):
                continue
            try:
                rel_path = file_path.relative_to(root).as_posix()
                file_hash = compute_sha256(file_path, normalize_text=True)
                mtime = datetime.datetime.fromtimestamp(
                    file_path.stat().st_mtime
                ).isoformat()
                results.append(
                    CustomFileEntry(
                        category=category,
                        rel_path=rel_path,
                        abs_path=str(file_path),
                        sha256=file_hash,
                        modified_time=mtime,
                    )
                )
            except Exception as e:
                logger.debug(f"Failed scanning custom file {file_path}: {e}")

    return results


def discover_custom_modules(repo_root: Path | str = ".") -> Dict[str, Dict[str, Any]]:
    """
    Discover custom modules in custom/modules/ and modules/custom/.
    Returns a dict mapping module import path to orchestrator configuration dict:
    e.g. {"custom.modules.my_plugin": {"tier": ModuleTier.ON_DEMAND}}
    """
    try:
        from core.orchestrator import ModuleTier
    except ImportError:
        from enum import Enum
        class ModuleTier(Enum):  # type: ignore
            ALWAYS_ON = 0
            ON_DEMAND = 1

    root = Path(repo_root).resolve()
    discovered: Dict[str, Dict[str, Any]] = {}

    search_dirs = [
        (root / "custom" / "modules", "custom.modules"),
        (root / "modules" / "custom", "modules.custom"),
    ]

    for dir_path, module_prefix in search_dirs:
        if not dir_path.is_dir():
            continue

        # Ensure package markers (__init__.py) exist so Python can import them
        for p in (dir_path.parent, dir_path):
            init_file = p / "__init__.py"
            if not init_file.exists():
                try:
                    init_file.write_text("# Auto-generated package marker\n", encoding="utf-8")
                except Exception:
                    pass

        for py_file in dir_path.glob("*.py"):
            if py_file.name.startswith("__"):
                continue
            mod_name = f"{module_prefix}.{py_file.stem}"
            tier = ModuleTier.ON_DEMAND
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                if "MODULE_TIER = 0" in content or "ModuleTier.ALWAYS_ON" in content:
                    tier = ModuleTier.ALWAYS_ON
            except Exception:
                pass
            discovered[mod_name] = {"tier": tier}
            logger.info(f"🧩 Discovered custom module: {mod_name} (Tier: {tier.name})")

    return discovered


def check_project_integrity(
    branch: str = "main",
    repo_root: Path | str = ".",
    fetch: bool = False,
) -> IntegrityReport:
    """
    Perform a complete SHA-256 integrity check of local project files against origin/{branch}.
    """
    root = Path(repo_root).resolve()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Fetch latest upstream branch if requested
    if fetch:
        try:
            subprocess.run(
                ["git", "fetch", "origin", branch],
                cwd=str(root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception as e:
            logger.warning(f"Failed to fetch origin {branch}: {e}")

    # Check git availability
    if not (root / ".git").is_dir():
        return IntegrityReport(
            branch=branch,
            timestamp=now_str,
            status="ERROR",
            total_checked=0,
            matches_count=0,
            error_message="Git repository (.git) not found in project directory.",
        )

    tracked_files = get_git_tracked_files(root, branch)
    if not tracked_files:
        # Fallback: try checking if origin/{branch} exists
        return IntegrityReport(
            branch=branch,
            timestamp=now_str,
            status="ERROR",
            total_checked=0,
            matches_count=0,
            error_message=f"No tracked files found for origin/{branch}. Run 'git fetch origin' first.",
        )

    custom_files = find_custom_extensions(root)
    modified_list: List[ModifiedFileEntry] = []
    total_checked = 0
    matches_count = 0

    for rel_path in tracked_files:
        if not is_system_file(rel_path):
            continue

        total_checked += 1
        local_path = root / rel_path

        if not local_path.is_file():
            # If the file is an optional deploy artifact (deleted by cleanup_common_trash/systemd), ignore missing
            if rel_path in OPTIONAL_DEPLOY_PATTERNS or any(
                rel_path == p or rel_path.startswith(f"{p}/") for p in OPTIONAL_DEPLOY_PATTERNS
            ):
                total_checked -= 1
                continue

            modified_list.append(
                ModifiedFileEntry(
                    rel_path=rel_path,
                    local_sha256="MISSING",
                    remote_sha256="",
                    status="MISSING_LOCAL",
                )
            )
            continue

        remote_bytes = get_git_remote_blob(rel_path, branch, root)
        if remote_bytes is None:
            continue

        remote_sha = hashlib.sha256(_normalize_content(remote_bytes)).hexdigest()
        local_sha = compute_sha256(local_path, normalize_text=True)

        if local_sha == remote_sha:
            matches_count += 1
        else:
            modified_list.append(
                ModifiedFileEntry(
                    rel_path=rel_path,
                    local_sha256=local_sha,
                    remote_sha256=remote_sha,
                    status="MODIFIED",
                )
            )

    # Determine overall status
    if modified_list:
        status = "MODIFIED"
    elif custom_files:
        status = "CUSTOM_ACTIVE"
    else:
        status = "OK"

    return IntegrityReport(
        branch=branch,
        timestamp=now_str,
        status=status,
        total_checked=total_checked,
        matches_count=matches_count,
        modified_files=modified_list,
        custom_files=custom_files,
    )


def backup_modified_files(
    repo_root: Path | str = ".",
    modified_entries: Optional[List[ModifiedFileEntry]] = None,
    branch: str = "main",
) -> Tuple[bool, str, List[str]]:
    """
    Back up modified files to .backups/pre_update_YYYYMMDD_HHMMSS/ preserving directory tree.
    Returns (success, backup_dir_path, list_of_backed_up_files).
    """
    root = Path(repo_root).resolve()
    if modified_entries is None:
        report = check_project_integrity(branch=branch, repo_root=root)
        modified_entries = report.modified_files

    if not modified_entries:
        return True, "", []

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / ".backups" / f"pre_update_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    backed_up: List[str] = []
    manifest: Dict[str, Any] = {
        "timestamp": datetime.datetime.now().isoformat(),
        "branch": branch,
        "files": [],
    }

    for entry in modified_entries:
        if entry.status == "MISSING_LOCAL":
            continue
        src = root / entry.rel_path
        if not src.is_file():
            continue
        dst = backup_dir / entry.rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        backed_up.append(entry.rel_path)
        manifest["files"].append(
            {
                "rel_path": entry.rel_path,
                "local_sha256": entry.local_sha256,
                "remote_sha256": entry.remote_sha256,
            }
        )

    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return True, str(backup_dir), backed_up


def create_custom_module_template(
    module_name: str, repo_root: Path | str = "."
) -> str:
    """Generate a boilerplate custom bot module in custom/modules/{module_name}.py."""
    root = Path(repo_root).resolve()
    target_dir = root / "custom" / "modules"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize module name
    clean_name = "".join(c if c.isalnum() or c == "_" else "_" for c in module_name.lower())
    if not clean_name.endswith(".py"):
        clean_name += ".py"

    target_file = target_dir / clean_name
    if target_file.exists():
        raise FileExistsError(f"Module file already exists: {target_file}")

    content = f'''"""
Custom Module: {clean_name[:-3]}
Automatically loaded by VPS Manager Bot Orchestrator.
"""
from aiogram import Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Tier configuration:
# 0 = ALWAYS_ON (loaded at startup, never unloaded)
# 1 = ON_DEMAND (loaded when triggered, freed after inactivity)
MODULE_TIER = 1

def register_handlers(dp: Dispatcher):
    """Register message and callback handlers for this custom module."""
    @dp.message(Command("{clean_name[:-3]}"))
    async def custom_command_handler(message: types.Message):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Ping Custom", callback_data="{clean_name[:-3]}_ping")],
                [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")]
            ]
        )
        await message.answer(
            "<b>🧩 Кастомный модуль: {clean_name[:-3]}</b>\\n\\nМодуль успешно подключен и изолирован от обновлений main!",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    @dp.callback_query(F.data == "{clean_name[:-3]}_ping")
    async def custom_ping_callback(callback: types.CallbackQuery):
        await callback.answer("Pong! Кастомный модуль работает корректно 🚀", show_alert=True)
'''
    target_file.write_text(content, encoding="utf-8")
    return str(target_file)


def create_custom_web_page_template(
    page_name: str, repo_root: Path | str = "."
) -> Tuple[str, str]:
    """Generate a boilerplate custom WebUI route and template."""
    root = Path(repo_root).resolve()
    routes_dir = root / "custom" / "web" / "routes"
    templates_dir = root / "custom" / "web" / "templates"
    routes_dir.mkdir(parents=True, exist_ok=True)
    templates_dir.mkdir(parents=True, exist_ok=True)

    clean_name = "".join(c if c.isalnum() or c == "_" else "_" for c in page_name.lower())
    route_file = routes_dir / f"{clean_name}.py"
    template_file = templates_dir / f"{clean_name}.html"

    if route_file.exists():
        raise FileExistsError(f"Route file already exists: {route_file}")

    route_code = f'''"""
Custom WebUI Route: {clean_name}
"""
from aiohttp import web
from core.web.auth import require_auth
from core.web.views import JINJA_ENV, ASSET_VER, APP_VERSION

routes = web.RouteTableDef()

@routes.get("/custom/{clean_name}")
@require_auth
async def custom_page_view(request: web.Request) -> web.Response:
    template = JINJA_ENV.get_template("{clean_name}.html")
    context = {{
        "title": "Custom: {clean_name}",
        "asset_ver": ASSET_VER,
        "app_ver": APP_VERSION,
        "page_name": "{clean_name}",
    }}
    content = template.render(context)
    return web.Response(text=content, content_type="text/html")
'''
    template_html = f'''{{% extends "base.html" %}}

{{% block title %}}{clean_name} — Custom Module{{% endblock %}}

{{% block content %}}
<div class="content-header">
    <div class="page-title">
        <i class="fas fa-puzzle-piece"></i>
        <span>Кастомная страница: {clean_name}</span>
    </div>
</div>

<div class="dashboard-grid">
    <div class="card">
        <div class="card-header">
            <h3><i class="fas fa-info-circle"></i> О странице</h3>
        </div>
        <div class="card-body">
            <p>Эта страница создана в изолированной директории <code>custom/web/</code>.</p>
            <p>Она автоматически защищена от затирания при обновлениях из ветки <code>main</code>.</p>
        </div>
    </div>
</div>
{{% endblock %}}
'''
    route_file.write_text(route_code, encoding="utf-8")
    template_file.write_text(template_html, encoding="utf-8")
    return str(route_file), str(template_file)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        prog="integrity",
        description="VPS Bot Integrity & Custom Extensions CLI",
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="check",
        choices=["check", "backup", "new-module", "new-page", "list-custom"],
        help="Действие: check, backup, new-module, new-page, list-custom",
    )
    parser.add_argument("name", nargs="?", default="", help="Имя модуля или страницы")
    parser.add_argument("--branch", default="main", help="Ветка git")
    parser.add_argument("--fetch", action="store_true", help="Сделать git fetch origin перед проверкой")
    parser.add_argument("--json", action="store_true", help="Вывод в формате JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод")
    parser.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), help="Корень репозитория")

    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    if args.action == "check":
        report = check_project_integrity(branch=args.branch, repo_root=repo_root, fetch=args.fetch)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return 0 if report.status in ("OK", "CUSTOM_ACTIVE") else 1

        print(f"\n🔍 Проверка целостности проекта (SHA-256 vs origin/{args.branch})")
        print(f"   Проверено системных файлов: {report.total_checked}")
        print(f"   Совпадений SHA-256: {report.matches_count}")

        if report.status == "OK":
            print("   ✅ Целостность подтверждена: системный код полностью совпадает с веткой.")
        elif report.status == "CUSTOM_ACTIVE":
            print("   ✅ Системные файлы чисты. Активны кастомные дополнения (изолированы от Git):")
            for cf in report.custom_files:
                print(f"      🧩 [{cf.category}] {cf.rel_path}")
        elif report.status == "MODIFIED":
            print(f"   ⚠️ Обнаружены локальные изменения системных файлов ({len(report.modified_files)}):")
            for mf in report.modified_files:
                if args.verbose:
                    print(f"      • {mf.rel_path} (Локальный: {mf.local_sha256[:10]}..., Upstream: {mf.remote_sha256[:10]}...)")
                else:
                    print(f"      • {mf.rel_path} [{mf.status}]")
            print("   💡 Используйте 'integrity backup' для сохранения копии перед обновлением.")
        elif report.status == "ERROR":
            print(f"   ❌ Ошибка: {report.error_message}")
            return 1

        if report.custom_files and report.status == "MODIFIED":
            print(f"\n   🧩 Также обнаружены кастомные дополнения ({len(report.custom_files)}):")
            for cf in report.custom_files:
                print(f"      • [{cf.category}] {cf.rel_path}")

        return 0 if report.status in ("OK", "CUSTOM_ACTIVE") else 1

    elif args.action == "backup":
        success, backup_dir, backed_up = backup_modified_files(repo_root=repo_root, branch=args.branch)
        if backed_up:
            print(f"📦 Бэкап успешно создан ({len(backed_up)} файлов):")
            print(f"   Папка: {backup_dir}")
            for f in backed_up:
                print(f"   • {f}")
        else:
            print("ℹ️ Нет модифицированных системных файлов для бэкапа.")
        return 0

    elif args.action == "new-module":
        name = args.name
        if not name:
            print("❌ Укажите имя модуля: integrity new-module <имя>")
            return 1
        try:
            path = create_custom_module_template(name, repo_root=repo_root)
            print(f"✨ Создан шаблон кастомного модуля: {path}")
            return 0
        except Exception as e:
            print(f"❌ Ошибка создания модуля: {e}")
            return 1

    elif args.action == "new-page":
        name = args.name
        if not name:
            print("❌ Укажите имя страницы: integrity new-page <имя>")
            return 1
        try:
            r_path, t_path = create_custom_web_page_template(name, repo_root=repo_root)
            print(f"✨ Создан шаблон WebUI страницы:")
            print(f"   Маршрут: {r_path}")
            print(f"   Шаблон:  {t_path}")
            print(f"   URL:     /custom/{name}")
            return 0
        except Exception as e:
            print(f"❌ Ошибка создания страницы: {e}")
            return 1

    elif args.action == "list-custom":
        custom_files = find_custom_extensions(repo_root=repo_root)
        if not custom_files:
            print("ℹ️ Кастомных дополнений пока нет.")
        else:
            print(f"🧩 Найдено кастомных файлов: {len(custom_files)}")
            for cf in custom_files:
                print(f"   • [{cf.category}] {cf.rel_path} (изменен: {cf.modified_time})")
        return 0


if __name__ == "__main__":
    sys.exit(main())
