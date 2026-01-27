import asyncio
import logging
import subprocess
import json
import os
import aiohttp
from aiogram import types, F, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from core.i18n import _, get_user_lang, I18nFilter
from core import config
from core.config import MANAGED_SERVICES
from core.auth import is_allowed, send_access_denied_message, ALLOWED_USERS, ADMIN_USER_ID
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS

# Cache for Docker Hub descriptions
_docker_descriptions_cache = {}

# --- Helpers ---

def get_user_role_level(user_id):
    """
    Returns permission level:
    0: View only (Users)
    1: Start/Restart only (Admins)
    2: Full Control (Main Admin)
    """
    if user_id == ADMIN_USER_ID:
        return 2
        
    user_data = ALLOWED_USERS.get(user_id)
    if not user_data:
        return 0
        
    group = user_data.get("group", "users") if isinstance(user_data, dict) else user_data
    
    if group == "admins":
        return 1
    return 0

# --- Backend Logic ---

def get_systemd_status(service_name):
    try:
        # Check ActiveState and SubState and LoadState
        cmd = ["systemctl", "show", service_name, "-p", "ActiveState,SubState,LoadState"]
        # Use stdout/stderr pipe for compatibility with older python (capture_output added in 3.7)
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            return "unknown"
        
        props = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v.strip()
        
        load_state = props.get("LoadState", "unknown")
        if load_state == "not-found":
            return "not_found"
            
        active = props.get("ActiveState", "unknown")
        sub = props.get("SubState", "unknown")
        
        if active == "active" and sub == "running":
            return "running"
        elif active == "active": # exited but considered active sometimes?
            return active
        else:
            return "stopped" # inactive, failed, etc
    except Exception as e:
        logging.error(f"Error checking systemd service {service_name}: {e}")
        return "error"

def get_docker_status(container_name):
    try:
        import docker
        client = docker.from_env()
        try:
            container = client.containers.get(container_name)
            if container.status == "running":
                return "running"
            return "stopped"
        except docker.errors.NotFound:
            return "not_found"
        except Exception:
            return "not_found"
    except ImportError:
         # Fallback to CLI
        try:
            cmd = ["docker", "inspect", "-f", "{{.State.Status}}", container_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                status = result.stdout.strip()
                return "running" if status == "running" else "stopped"
            # If docker inspect fails with non-zero, assume not found
            return "not_found"
        except Exception:
            return "not_found"
    except Exception as e:
        # Docker not available or connection error - treat as not found
        return "not_found"

def discover_all_systemd_services():
    """Discover all running/available systemd services"""
    services = []
    try:
        # Get list of all services (running and available)
        cmd = ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 1:
                    unit = parts[0]
                    # Remove .service suffix
                    if unit.endswith(".service"):
                        name = unit[:-8]
                        services.append(name)
    except Exception as e:
        logging.error(f"Error discovering systemd services: {e}")
    return services

def discover_all_docker_containers():
    """Discover all docker containers (running and stopped)"""
    containers = []
    try:
        import docker
        client = docker.from_env()
        for c in client.containers.list(all=True):
            containers.append(c.name)
    except ImportError:
        # Fallback to CLI
        try:
            cmd = ["docker", "ps", "-a", "--format", "{{.Names}}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        containers.append(line.strip())
        except Exception:
            pass
    except Exception as e:
        logging.debug(f"Docker not available: {e}")
    return containers

def get_all_available_services():
    """Get all available services/containers with their managed status"""
    managed_names = {s["name"]: s["type"] for s in MANAGED_SERVICES}
    
    result = []
    
    # Systemd services
    systemd_services = discover_all_systemd_services()
    for name in systemd_services:
        status = get_systemd_status(name)
        if status != "not_found":
            result.append({
                "name": name,
                "type": "systemd",
                "status": status,
                "managed": name in managed_names
            })
    
    # Docker containers
    docker_containers = discover_all_docker_containers()
    for name in docker_containers:
        status = get_docker_status(name)
        if status != "not_found":
            result.append({
                "name": name,
                "type": "docker",
                "status": status,
                "managed": name in managed_names
            })
    
    # Sort: managed first, then by name
    result.sort(key=lambda x: (not x["managed"], x["name"].lower()))
    return result

def add_managed_service(name, sType):
    """Add a service to MANAGED_SERVICES config"""
    # Check if already managed
    for s in config.MANAGED_SERVICES:
        if s["name"] == name:
            return False, "Already managed"
    
    config.MANAGED_SERVICES.append({"name": name, "type": sType})
    save_managed_services()
    return True, "Added"

def remove_managed_service(name):
    """Remove a service from MANAGED_SERVICES config"""
    for i, s in enumerate(config.MANAGED_SERVICES):
        if s["name"] == name:
            config.MANAGED_SERVICES.pop(i)
            save_managed_services()
            return True, "Removed"
    return False, "Not found"

def save_managed_services():
    """Save MANAGED_SERVICES to encrypted config file"""
    from core.utils import save_services_config
    return save_services_config()

def get_all_services_status():
    try:
        services = MANAGED_SERVICES
        results = []
        for s in services:
            name = s.get("name")
            sType = s.get("type", "systemd")
            
            status = "unknown"
            if sType == "systemd":
                status = get_systemd_status(name)
            elif sType == "docker":
                status = get_docker_status(name)
                
            if status != "not_found":
                results.append({
                    "name": name,
                    "type": sType,
                    "status": status
                })
        return results
    except Exception as e:
        logging.error(f"Error in get_all_services_status: {e}")
        return []
    return results

async def perform_service_action(name, sType, action):
    # action: start, stop, restart
    if action not in ["start", "stop", "restart"]:
        return False, "Invalid action"
    
    cmd = []
    if sType == "systemd":
        cmd = ["sudo", "systemctl", action, name]
    elif sType == "docker":
        cmd = ["docker", action, name]
    else:
        return False, "Unknown type"
        
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            return True, "OK"
        else:
            err_msg = stderr.decode().strip() or stdout.decode().strip()
            return False, err_msg
    except Exception as e:
        return False, str(e)

def get_systemd_service_description(service_name):
    """Get description of a systemd service"""
    try:
        cmd = ["systemctl", "show", service_name, "-p", "Description"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("Description="):
                    return line.split("=", 1)[1].strip()
        return None
    except Exception as e:
        logging.debug(f"Error getting systemd description for {service_name}: {e}")
        return None

def get_systemd_service_info(service_name):
    """Get detailed information about a systemd service"""
    info = {
        "name": service_name,
        "type": "systemd",
        "status": "unknown",
        "description": None,
        "load_state": None,
        "active_state": None,
        "main_pid": None,
        "memory": None,
        "uptime": None
    }
    try:
        cmd = ["systemctl", "show", service_name, "-p", 
               "Description,LoadState,ActiveState,SubState,MainPID,MemoryCurrent,ActiveEnterTimestamp"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            props = {}
            for line in result.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k] = v.strip()
            
            info["description"] = props.get("Description")
            info["load_state"] = props.get("LoadState")
            info["active_state"] = props.get("ActiveState")
            
            # Determine status
            active = props.get("ActiveState", "unknown")
            sub = props.get("SubState", "unknown")
            if active == "active" and sub == "running":
                info["status"] = "running"
            elif active == "active":
                info["status"] = "active"
            else:
                info["status"] = "stopped"
            
            # PID and memory
            pid = props.get("MainPID", "0")
            if pid and pid != "0":
                info["main_pid"] = pid
            
            mem = props.get("MemoryCurrent")
            if mem and mem != "[not set]":
                try:
                    mem_bytes = int(mem)
                    if mem_bytes > 1024*1024*1024:
                        info["memory"] = f"{mem_bytes / (1024*1024*1024):.1f} GB"
                    elif mem_bytes > 1024*1024:
                        info["memory"] = f"{mem_bytes / (1024*1024):.1f} MB"
                    else:
                        info["memory"] = f"{mem_bytes / 1024:.1f} KB"
                except:
                    pass
            
            # Uptime from ActiveEnterTimestamp
            timestamp = props.get("ActiveEnterTimestamp")
            if timestamp and timestamp != "n/a":
                info["uptime"] = timestamp
                
    except Exception as e:
        logging.debug(f"Error getting systemd info for {service_name}: {e}")
    
    return info

async def get_docker_image_from_container(container_name):
    """Get Docker image name from a running container"""
    try:
        cmd = ["docker", "inspect", "-f", "{{.Config.Image}}", container_name]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None

async def get_docker_hub_description(image_name):
    """Get description from Docker Hub API"""
    global _docker_descriptions_cache  # noqa: F824
    
    # Check cache first
    if image_name in _docker_descriptions_cache:
        return _docker_descriptions_cache[image_name]
    
    try:
        # Parse image name (handle namespace/repo:tag format)
        image_parts = image_name.split(":")[0]  # Remove tag
        if "/" not in image_parts:
            # Official image - use library namespace
            namespace = "library"
            repo = image_parts
        else:
            parts = image_parts.split("/")
            if len(parts) == 2:
                namespace, repo = parts
            else:
                # registry/namespace/repo format
                namespace = parts[-2]
                repo = parts[-1]
        
        url = f"https://hub.docker.com/v2/repositories/{namespace}/{repo}/"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    description = data.get("description") or data.get("full_description", "")
                    # Truncate long descriptions
                    if description and len(description) > 500:
                        description = description[:500] + "..."
                    _docker_descriptions_cache[image_name] = description
                    return description
    except Exception as e:
        logging.debug(f"Error fetching Docker Hub description for {image_name}: {e}")
    
    _docker_descriptions_cache[image_name] = None
    return None

async def get_docker_container_info(container_name):
    """Get detailed information about a Docker container"""
    info = {
        "name": container_name,
        "type": "docker",
        "status": "unknown",
        "description": None,
        "image": None,
        "created": None,
        "ports": None,
        "uptime": None
    }
    try:
        cmd = ["docker", "inspect", container_name]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data and len(data) > 0:
                container = data[0]
                
                # Status
                state = container.get("State", {})
                if state.get("Running"):
                    info["status"] = "running"
                else:
                    info["status"] = "stopped"
                
                # Image
                info["image"] = container.get("Config", {}).get("Image")
                
                # Created
                info["created"] = container.get("Created", "")[:19].replace("T", " ")
                
                # Ports
                ports = container.get("NetworkSettings", {}).get("Ports", {})
                if ports:
                    port_list = []
                    for container_port, host_bindings in ports.items():
                        if host_bindings:
                            for binding in host_bindings:
                                port_list.append(f"{binding.get('HostPort', '?')}->{container_port}")
                        else:
                            port_list.append(container_port)
                    if port_list:
                        info["ports"] = ", ".join(port_list[:3])  # Limit to 3 ports
                
                # Uptime
                if state.get("Running"):
                    started_at = state.get("StartedAt", "")
                    if started_at:
                        info["uptime"] = started_at[:19].replace("T", " ")
                
                # Try to get description from Docker Hub
                if info["image"]:
                    info["description"] = await get_docker_hub_description(info["image"])
                    
    except Exception as e:
        logging.debug(f"Error getting docker info for {container_name}: {e}")
    
    return info

async def get_service_info(name, sType):
    """Get detailed service information"""
    if sType == "systemd":
        return get_systemd_service_info(name)
    elif sType == "docker":
        return await get_docker_container_info(name)
    return {"name": name, "type": sType, "status": "unknown", "description": None}

# --- Telegram Bot Handlers ---

SERVICES_PER_PAGE = 5  # Number of services per page

def get_services_keyboard(user_id, page=0):
    lang = get_user_lang(user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    
    services = get_all_services_status()
    level = get_user_role_level(user_id)
    
    if not services:
        return None, 0, 0  # Indicate empty state
    
    total_services = len(services)
    total_pages = (total_services + SERVICES_PER_PAGE - 1) // SERVICES_PER_PAGE
    
    # Clamp page
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1
    
    start_idx = page * SERVICES_PER_PAGE
    end_idx = min(start_idx + SERVICES_PER_PAGE, total_services)
    page_services = services[start_idx:end_idx]
    
    for s in page_services:
        name = s["name"]
        sType = s["type"]
        status = s["status"]
        
        is_running = status == "running"
        icon = "🟢" if is_running else "🔴"
        
        # Row 1: Status (Always visible)
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"{icon} {name} ({sType})", callback_data="noop")
        ])
        
        # Row 2: Controls (Depending on permissions and status)
        controls = []
        
        if level >= 1: # Admins and Main Admin
            if not is_running:
                # Show Start only if NOT running
                controls.append(InlineKeyboardButton(text="▶️", callback_data=f"srv_start_{name}"))
            else:
                # Show Restart only if running
                controls.append(InlineKeyboardButton(text="🔄", callback_data=f"srv_restart_{name}"))
        
        if level >= 2 and is_running: # Only Main Admin can Stop, and only if running
             controls.append(InlineKeyboardButton(text="⏹", callback_data=f"srv_stop_{name}"))
             
        if controls:
            kb.inline_keyboard.append(controls)
    
    # Navigation row
    nav_row = []
    if total_pages > 1:
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"srv_page_{page - 1}"))
        nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"srv_page_{page + 1}"))
    
    if nav_row:
        kb.inline_keyboard.append(nav_row)
        
    kb.inline_keyboard.append([
        InlineKeyboardButton(text=_("btn_refresh", lang), callback_data=f"srv_refresh_{page}"),
    ])
    return kb, page, total_pages

async def services_handler(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    command = "services"
    
    if not is_allowed(user_id, "enable_services"):
        await send_access_denied_message(message.bot, user_id, message.chat.id, command)
        return

    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    
    result = get_services_keyboard(user_id, page=0)
    
    if result[0] is None:
         text = _("services_empty", lang)
         sent = await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
             [InlineKeyboardButton(text=_("btn_refresh", lang), callback_data="srv_refresh_0")]
         ]))
    else:
        kb, page, total_pages = result
        text = _("services_title", lang)
        sent = await message.answer(text, reply_markup=kb)
        
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent.message_id

async def cq_services_page(callback: types.CallbackQuery):
    """Handle pagination"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    # Extract page number from callback data: srv_page_N
    try:
        page = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        page = 0
    
    result = get_services_keyboard(user_id, page=page)
    
    try:
        if result[0] is None:
            text = _("services_empty", lang)
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
             [InlineKeyboardButton(text=_("btn_refresh", lang), callback_data="srv_refresh_0")]
            ]))
        else:
            kb, page, total_pages = result
            text = _("services_title", lang)
            await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()

async def cq_services_refresh(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    # Extract page number from callback data: srv_refresh_N
    try:
        page = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        page = 0
    
    result = get_services_keyboard(user_id, page=page)
    
    try:
        if result[0] is None:
            text = _("services_empty", lang)
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
             [InlineKeyboardButton(text=_("btn_refresh", lang), callback_data="srv_refresh_0")]
            ]))
        else:
            kb, page, total_pages = result
            text = _("services_title", lang) 
            await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer(_("btn_refresh", lang))

async def cq_service_action(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    level = get_user_role_level(user_id)
    
    if not is_allowed(user_id, "enable_services"):
        await callback.answer(_("access_denied", lang), show_alert=True)
        return
        
    data = callback.data # srv_start_name
    parts = data.split("_", 2)
    action = parts[1]
    name = parts[2]
    
    # Permission Check
    if level == 0:
        await callback.answer(_("access_denied", lang), show_alert=True)
        return
    if action == "stop" and level < 2:
        await callback.answer(_("access_denied", lang), show_alert=True)
        return
    
    # Find service type
    sType = "systemd"
    found = False
    for s in config.MANAGED_SERVICES:
        if s["name"] == name:
            sType = s.get("type", "systemd")
            found = True
            break
    
    if not found:
         await callback.answer("Service not found config", show_alert=True)
         return
            
    await callback.answer(_("services_action_started", lang, action=action, name=name), show_alert=False)
    
    success, msg = await perform_service_action(name, sType, action)
    
    if success:
        # success message map?
        if action == "start": key = "services_started"
        elif action == "stop": key = "services_stopped"
        else: key = "services_restarted"
        
        await callback.answer(_(key, lang, name=name), show_alert=True)
        # Refresh keyboard after action (stay on page 0 since we don't track current page)
        await asyncio.sleep(1.5)
        # Create a mock callback with refresh data
        callback.data = "srv_refresh_0"
        await cq_services_refresh(callback)
    else:
        await callback.answer(_("services_error", lang, action=action, name=name, error=msg), show_alert=True)


BUTTON_KEY = "btn_services"

def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(services_handler)
    
    dp.callback_query.register(cq_services_page, F.data.startswith("srv_page_"))
    dp.callback_query.register(cq_services_refresh, F.data.startswith("srv_refresh_"))
    dp.callback_query.register(cq_service_action, F.data.startswith("srv_"))
