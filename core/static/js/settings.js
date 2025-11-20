document.addEventListener("DOMContentLoaded", () => {
    renderUsers();
});

// --- УВЕДОМЛЕНИЯ ---
async function saveNotifications() {
    const btn = document.getElementById('saveNotifBtn');
    const originalText = btn.innerText;
    btn.innerText = "Сохранение...";
    btn.disabled = true;

    const data = {
        resources: document.getElementById('alert_resources').checked,
        logins: document.getElementById('alert_logins').checked,
        bans: document.getElementById('alert_bans').checked,
        downtime: document.getElementById('alert_downtime').checked
    };

    try {
        const res = await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });
        if(res.ok) {
            btn.innerText = "Сохранено!";
            btn.classList.replace('bg-green-600', 'bg-blue-600');
            setTimeout(() => {
                btn.innerText = originalText;
                btn.classList.replace('bg-blue-600', 'bg-green-600');
                btn.disabled = false;
            }, 2000);
        } else {
            alert("Ошибка сохранения");
            btn.disabled = false;
        }
    } catch(e) {
        console.error(e);
        alert("Ошибка сети");
        btn.disabled = false;
    }
}

// --- ПОЛЬЗОВАТЕЛИ ---
function renderUsers() {
    const tbody = document.getElementById('usersTableBody');
    const section = document.getElementById('usersSection');
    
    // Если данных нет (не админ), скрываем секцию
    if(!USERS_DATA || USERS_DATA.length === 0) {
        // Проверка на пустой массив - может быть и просто нет юзеров, 
        // но в данном случае сервер передает [] если не админ.
        // Лучше проверить роль через куки или отдельный флаг, 
        // но пока так: если USERS_DATA пуст, считаем, что доступа нет или юзеров нет.
        // Если массив пуст но админ - покажем пустую таблицу.
        // Для простоты: если переменная определена и массив, показываем.
    }
    
    if(USERS_DATA && Array.isArray(USERS_DATA) && USERS_DATA.length > 0) {
        section.classList.remove('hidden');
        tbody.innerHTML = USERS_DATA.map(u => `
            <tr class="border-b border-white/5 hover:bg-white/5 transition">
                <td class="px-4 py-3 font-mono text-xs">${u.id}</td>
                <td class="px-4 py-3 font-medium text-white">${u.name}</td>
                <td class="px-4 py-3">
                    <span class="px-2 py-0.5 rounded text-[10px] border ${u.role === 'admins' ? 'border-green-500/30 bg-green-500/20 text-green-400' : 'border-gray-500/30 bg-gray-500/20 text-gray-300'}">
                        ${u.role}
                    </span>
                </td>
                <td class="px-4 py-3 text-right">
                    <button onclick="deleteUser(${u.id})" class="text-red-400 hover:text-red-300 transition p-1">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                    </button>
                </td>
            </tr>
        `).join('');
    }
}

async function deleteUser(id) {
    if(!confirm(`Удалить пользователя ${id}?`)) return;
    
    try {
        const res = await fetch('/api/users/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'delete', id: id})
        });
        
        if(res.ok) {
            // Удаляем из локального массива и перерисовываем
            const idx = USERS_DATA.findIndex(u => u.id == id);
            if(idx > -1) USERS_DATA.splice(idx, 1);
            renderUsers();
        } else {
            alert("Ошибка удаления");
        }
    } catch(e) {
        alert("Ошибка сети");
    }
}

async function openAddUserModal() {
    const id = prompt("Введите Telegram ID пользователя:");
    if(!id) return;
    
    try {
        const res = await fetch('/api/users/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'add', id: id, role: 'users'})
        });
        
        const data = await res.json();
        if(res.ok) {
            USERS_DATA.push({id: id, name: data.name || `ID: ${id}`, role: 'users'});
            renderUsers();
        } else {
            alert("Ошибка: " + (data.error || "Unknown"));
        }
    } catch(e) {
        alert("Ошибка сети");
    }
}

// --- НОДЫ ---
async function addNode() {
    const nameInput = document.getElementById('newNodeName');
    const name = nameInput.value.trim();
    if(!name) return alert("Введите имя");
    
    try {
        const res = await fetch('/api/nodes/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name})
        });
        
        const data = await res.json();
        if(res.ok) {
            document.getElementById('nodeResult').classList.remove('hidden');
            document.getElementById('newNodeToken').innerText = data.token;
            document.getElementById('newNodeCmd').innerText = data.command;
            nameInput.value = "";
        } else {
            alert("Ошибка: " + data.error);
        }
    } catch(e) {
        alert("Ошибка сети");
    }
}