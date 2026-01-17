import logging
import asyncio
import aiohttp
import os
import re
from core import config, utils

async def get_remote_version(branch="main"):
    url = f"https://raw.githubusercontent.com/jatixs/tgbotvpscp/{branch}/README.md"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    text = await response.text()
                    match = re.search(r'img\.shields\.io/badge/version-v([\d\.]+)', text)
                    if match:
                        return f"v{match.group(1)}"
    except Exception as e:
        logging.error(f"Error checking remote version: {e}")
    return None

def compare_versions(ver1, ver2):
    """
    Сравнивает версии v1.2.3.
    Возвращает:
     1 если ver1 > ver2
    -1 если ver1 < ver2
     0 если равны
    """
    def normalize(v):
        return [int(x) for x in v.lstrip('v').split('.')]

    try:
        v1_parts = normalize(ver1)
        v2_parts = normalize(ver2)
        
        if v1_parts > v2_parts: return 1
        if v1_parts < v2_parts: return -1
        return 0
    except Exception:
        return 0

async def get_update_info():
    """
    Возвращает (local_ver, remote_ver, target_branch, update_available)
    """
    local_ver = utils.get_app_version()
    
    branch = "main"
    try:
        proc = await asyncio.create_subprocess_shell(
            "git rev-parse --abbrev-ref HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if stdout:
            b = stdout.decode().strip()
            if b: branch = b
    except Exception:
        pass

    remote_ver = await get_remote_version(branch)
    
    update_available = False
    
    if remote_ver:
        cmp = compare_versions(remote_ver, local_ver)
        if cmp > 0:
            update_available = True
        else:
            update_available = False
    else:
        remote_ver = "Unknown"

    return local_ver, remote_ver, branch, update_available

async def execute_bot_update(branch="main", restart_source="user"):
    with open(config.RESTART_FLAG_FILE, "w") as f:
        f.write(f"{restart_source}")
        
    cmd = f"bash {config.BASE_DIR}/deploy.sh"    
    logging.info(f"Starting update process... Branch: {branch}")
    asyncio.create_task(asyncio.create_subprocess_shell(cmd))