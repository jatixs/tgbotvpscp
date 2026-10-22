// Terminal Web Client Logic
(function () {
    const I18N = window.I18N || {};

    if (window.visualViewport) {
        function updateViewport() {
            document.body.style.height = window.visualViewport.height + 'px';
            window.scrollTo(0, 0);
        }
        window.visualViewport.addEventListener('resize', updateViewport);
        window.visualViewport.addEventListener('scroll', updateViewport);
        updateViewport();
    }

    const term = new Terminal({
        cursorBlink: true,
        theme: {
            background: '#09090b',
            foreground: '#f8fafc',
            cursor: '#3b82f6',
            selectionBackground: 'rgba(59, 130, 246, 0.3)',
            black: '#000000',
            red: '#ef4444',
            green: '#22c55e',
            yellow: '#eab308',
            blue: '#3b82f6',
            magenta: '#d946ef',
            cyan: '#06b6d4',
            white: '#ffffff',
            brightBlack: '#64748b',
            brightRed: '#f87171',
            brightGreen: '#4ade80',
            brightYellow: '#fde047',
            brightBlue: '#60a5fa',
            brightMagenta: '#e879f9',
            brightCyan: '#22d3ee',
            brightWhite: '#ffffff'
        },
        fontFamily: 'Consolas, "Courier New", monospace',
        fontSize: 14,
        rendererType: 'canvas'
    });

    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon.WebLinksAddon());

    const termDiv = document.getElementById('termDiv');
    if (termDiv) {
        term.open(termDiv);
        fitAddon.fit();
    }

    let ws = null;
    let pinger = null;
    let ctrlMode = false;

    window.addEventListener('resize', () => {
        fitAddon.fit();
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: "resize",
                cols: term.cols,
                rows: term.rows
            }));
        }
    });

    term.onData(data => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            if (ctrlMode && data.length === 1) {
                let charCode = data.charCodeAt(0);
                if (charCode >= 97 && charCode <= 122) { // a-z
                    data = String.fromCharCode(charCode - 96);
                } else if (charCode >= 65 && charCode <= 90) { // A-Z
                    data = String.fromCharCode(charCode - 64);
                }
                toggleCtrlMode(); // Disable after one char
            }
            ws.send(JSON.stringify({
                type: "data",
                data: data
            }));
        }
    });

    function toggleCtrlMode() {
        ctrlMode = !ctrlMode;
        const btn = document.getElementById('btnCtrl');
        if (!btn) return;
        if (ctrlMode) {
            btn.classList.add('bg-blue-600', 'text-white');
            btn.classList.remove('text-gray-300');
        } else {
            btn.classList.remove('bg-blue-600', 'text-white');
            btn.classList.add('text-gray-300');
        }
    }

    const statusBadge = document.getElementById('statusBadge');
    const modal = document.getElementById('connectModal');
    const btnDisconnect = document.getElementById('btnDisconnect');
    const connError = document.getElementById('connError');

    function toggleAuthFields() {
        const methodElem = document.getElementById('inpAuthMethod');
        if (!methodElem) return;
        const method = methodElem.value;
        const fieldKey = document.getElementById('fieldKey');
        const fieldPassword = document.getElementById('fieldPassword');
        if (method === 'key') {
            if (fieldKey) fieldKey.classList.remove('hidden');
            if (fieldPassword) fieldPassword.classList.add('hidden');
        } else {
            if (fieldKey) fieldKey.classList.add('hidden');
            if (fieldPassword) fieldPassword.classList.remove('hidden');
        }
    }

    function isEncryptedKey(text) {
        if (!text || typeof text !== 'string') return false;
        const str = text.trim();
        // 1. Classic PEM / PKCS#8 encrypted keys
        if (/BEGIN ENCRYPTED PRIVATE KEY|Proc-Type:\s*4,ENCRYPTED|ENCRYPTED/i.test(str)) {
            return true;
        }
        // 2. OpenSSH private key format (RFC 4251 / modern ssh-keygen)
        if (str.includes('BEGIN OPENSSH PRIVATE KEY')) {
            try {
                const clean = str.replace(/-----[^-]+-----/g, '').replace(/\s+/g, '');
                const len = Math.floor(Math.min(clean.length, 64) / 4) * 4;
                if (len >= 32) {
                    const raw = atob(clean.slice(0, len));
                    if (raw.startsWith('openssh-key-v1\0')) {
                        // Ciphername length is a 4-byte big-endian uint at offset 15
                        const cLen = (raw.charCodeAt(15) << 24) |
                                     (raw.charCodeAt(16) << 16) |
                                     (raw.charCodeAt(17) << 8) |
                                     raw.charCodeAt(18);
                        if (cLen > 0 && raw.length >= 19 + cLen) {
                            const cipher = raw.slice(19, 19 + cLen);
                            return cipher !== 'none';
                        }
                    }
                }
            } catch {
                // Ignore parse error
            }
        }
        return false;
    }

    function loadKeyFile(event) {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = function(e) {
            const content = e.target.result;
            const inpKey = document.getElementById('inpKey');
            if (inpKey) inpKey.value = content;
            clearPassphrase();
            if (isEncryptedKey(content)) {
                openPassphraseModal();
            }
        };
        reader.readAsText(file);
    }

    const inpKeyElem = document.getElementById('inpKey');
    if (inpKeyElem) {
        inpKeyElem.addEventListener('input', function() {
            const content = this.value;
            clearPassphrase();
            if (content && isEncryptedKey(content)) {
                setTimeout(() => openPassphraseModal(), 200);
            }
        });
    }

    function clearPassphrase() {
        const p1 = document.getElementById('inpKeyPassphrase');
        const p2 = document.getElementById('inpPassphrase');
        const badge = document.getElementById('passphraseBadge');
        if (p1) p1.value = '';
        if (p2) p2.value = '';
        if (badge) badge.classList.add('hidden');
    }

    function openPassphraseModal(errorMsg = '') {
        const passModal = document.getElementById('passphraseModal');
        const errBox = document.getElementById('passphraseError');
        const input = document.getElementById('inpPassphrase');
        if (!passModal || !input) return;

        const connModal = document.getElementById('connectModal');
        if (connModal) {
            connModal.classList.add('hidden');
        }

        if (errBox) {
            if (errorMsg) {
                errBox.textContent = errorMsg;
                errBox.classList.remove('hidden');
            } else {
                errBox.classList.add('hidden');
            }
        }

        const stored = document.getElementById('inpKeyPassphrase') ? document.getElementById('inpKeyPassphrase').value : '';
        if (stored && stored !== '*** SAVED PASSPHRASE ***' && !input.value) {
            input.value = stored;
        }

        passModal.classList.remove('hidden');
        passModal.classList.add('flex');

        requestAnimationFrame(() => {
            passModal.classList.remove('modal-closed');
            passModal.classList.add('modal-open');
        });

        setTimeout(() => {
            input.focus();
            input.select();
        }, 100);
    }

    function closePassphraseModal(restoreConnModal = true) {
        const passModal = document.getElementById('passphraseModal');
        if (!passModal) return;

        passModal.classList.remove('modal-open');
        passModal.classList.add('modal-closed');

        setTimeout(() => {
            passModal.classList.add('hidden');
            passModal.classList.remove('flex');
            if (restoreConnModal) {
                const connModal = document.getElementById('connectModal');
                if (connModal) {
                    connModal.classList.remove('hidden');
                }
            }
        }, 220);
    }

    function togglePassphraseVisibility() {
        const input = document.getElementById('inpPassphrase');
        const eyeOpen = document.getElementById('eyeIconOpen');
        const eyeClosed = document.getElementById('eyeIconClosed');
        if (!input) return;
        if (input.type === 'password') {
            input.type = 'text';
            if (eyeOpen) eyeOpen.classList.add('hidden');
            if (eyeClosed) eyeClosed.classList.remove('hidden');
        } else {
            input.type = 'password';
            if (eyeOpen) eyeOpen.classList.remove('hidden');
            if (eyeClosed) eyeClosed.classList.add('hidden');
        }
    }

    function submitPassphrase() {
        const input = document.getElementById('inpPassphrase');
        const pass = input ? input.value : '';
        const hiddenPass = document.getElementById('inpKeyPassphrase');
        if (hiddenPass) hiddenPass.value = pass;
        closePassphraseModal(false);
        const badge = document.getElementById('passphraseBadge');
        if (pass && badge) {
            badge.classList.remove('hidden');
        }
        connect(pass);
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const passModal = document.getElementById('passphraseModal');
            if (passModal && !passModal.classList.contains('hidden')) {
                closePassphraseModal(true);
            }
        }
    });

    const inpIpElem = document.getElementById('inpIp');
    if (inpIpElem) {
        inpIpElem.addEventListener('blur', function() {
            const ip = this.value.trim();
            if (!ip || ip === 'Loading...' || ip === 'Unknown' || ip === '-') return;
            fetch(`/api/terminal/creds?ip=${encodeURIComponent(ip)}`)
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'ok' && data.saved) {
                        const u = document.getElementById('inpUser');
                        const m = document.getElementById('inpAuthMethod');
                        const p = document.getElementById('inpPort');
                        const rmb = document.getElementById('inpRemember');
                        if (u) u.value = data.user || 'root';
                        if (m) m.value = data.type;
                        if (p) p.value = data.port || '';
                        toggleAuthFields();
                        if (rmb) rmb.checked = true;
                        if (data.type === 'key') {
                            const k = document.getElementById('inpKey');
                            const kp = document.getElementById('inpKeyPassphrase');
                            const badge = document.getElementById('passphraseBadge');
                            if (k) k.value = '*** SAVED SECURE KEY ***';
                            if (data.has_passphrase) {
                                if (kp) kp.value = '*** SAVED PASSPHRASE ***';
                                if (badge) badge.classList.remove('hidden');
                            } else {
                                if (kp) kp.value = '';
                                if (badge) badge.classList.add('hidden');
                            }
                        } else {
                            const passElem = document.getElementById('inpPass');
                            if (passElem) passElem.value = '*** SAVED PASSWORD ***';
                        }
                    }
                })
                .catch(() => {});
        });
    }

    const urlParams = new URLSearchParams(window.location.search);
    const paramIp = (urlParams.get('ip') || '').trim();
    if (paramIp && paramIp !== 'Loading...' && paramIp !== 'Unknown' && paramIp !== '-') {
        if (inpIpElem) inpIpElem.value = paramIp;
    }
    if (inpIpElem && inpIpElem.value.trim()) {
        inpIpElem.dispatchEvent(new Event('blur'));
    }

    if (I18N.banner) {
        term.writeln('\x1b[1;36m' + I18N.banner + '\x1b[0m');
    }
    if (I18N.welcomeHint) {
        term.writeln(I18N.welcomeHint);
    }

    function setStatus(state, msg = "") {
        if (!statusBadge) return;
        if (state === 'disconnected') {
            statusBadge.className = "px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-gray-700 text-gray-300";
            statusBadge.innerText = I18N.disconnected || 'Disconnected';
            if (btnDisconnect) btnDisconnect.classList.add('hidden');
            
            if (pinger) {
                clearInterval(pinger);
                pinger = null;
            }
        } else if (state === 'connecting') {
            statusBadge.className = "px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-yellow-500/20 text-yellow-500 border border-yellow-500/30";
            statusBadge.innerText = I18N.connecting || 'Connecting...';
            if (connError) connError.classList.add('hidden');
        } else if (state === 'connected') {
            statusBadge.className = "px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-green-500/20 text-green-500 border border-green-500/30";
            statusBadge.innerText = I18N.connected || 'Connected';
            if (btnDisconnect) btnDisconnect.classList.remove('hidden');
            if (modal) modal.classList.add('hidden');
        } else if (state === 'error') {
            statusBadge.className = "px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-red-500/20 text-red-500 border border-red-500/30";
            statusBadge.innerText = I18N.error || 'Error';
            
            if (msg && connError) {
                connError.innerText = msg;
                connError.classList.remove('hidden');
                if (modal) modal.classList.remove('hidden');
            }
        }
    }

    function connect(overridePassphrase) {
        if (ws) ws.close();
        
        const ipElem = document.getElementById('inpIp');
        const portElem = document.getElementById('inpPort');
        const userElem = document.getElementById('inpUser');
        const methodElem = document.getElementById('inpAuthMethod');
        const rememberElem = document.getElementById('inpRemember');
        const passElem = document.getElementById('inpPass');
        const keyElem = document.getElementById('inpKey');
        const keyPassElem = document.getElementById('inpKeyPassphrase');

        const ip = ipElem ? ipElem.value.trim() : '';
        const port = (portElem && portElem.value) ? portElem.value : 22;
        const user = userElem ? userElem.value.trim() : '';
        const method = methodElem ? methodElem.value : 'password';
        const remember = rememberElem ? rememberElem.checked : false;
        
        let password = passElem ? passElem.value : '';
        let privateKey = keyElem ? keyElem.value : '';
        let passphrase = (overridePassphrase !== undefined)
            ? overridePassphrase
            : (keyPassElem ? keyPassElem.value : '');
        
        const isSavedPass = password === '*** SAVED PASSWORD ***';
        const isSavedKey = privateKey === '*** SAVED SECURE KEY ***';
        const isSavedPassphrase = passphrase === '*** SAVED PASSPHRASE ***';

        if (!ip || ip === 'Loading...' || ip === 'Unknown' || ip === '-') {
            setStatus('error', I18N.errInvalidIp);
            return;
        }
        if (!user) {
            setStatus('error', I18N.errInvalidUser);
            return;
        }

        if (method === 'key' && !isSavedKey && isEncryptedKey(privateKey) && !passphrase) {
            openPassphraseModal();
            return;
        }
        
        // Synchronize credentials with encrypted backend storage
        if (remember) {
            fetch('/api/terminal/creds', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    ip: ip,
                    port: port,
                    user: user,
                    type: method,
                    password: isSavedPass ? '*** SAVED PASSWORD ***' : (method === 'password' ? password : ''),
                    private_key: isSavedKey ? '*** SAVED SECURE KEY ***' : (method === 'key' ? privateKey : ''),
                    passphrase: isSavedPassphrase ? '*** SAVED PASSPHRASE ***' : ((method === 'key') ? passphrase : ''),
                    remember: true
                })
            }).catch(e => console.error(e));
        } else {
            // If remember is unchecked, securely wipe saved credentials for this IP from server
            fetch('/api/terminal/creds', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    ip: ip,
                    remember: false
                })
            }).catch(e => console.error(e));
        }

        setStatus('connecting');
        term.reset();
        term.writeln('\x1b[1;34m[*] ' + (I18N.connectingTo || 'Connecting to') + ' ' + ip + ':' + port + '...\x1b[0m');
        
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/terminal/ws`;
        
        ws = new WebSocket(wsUrl);
        window.ws = ws;
        
        ws.onopen = () => {
            ws.send(JSON.stringify({
                type: "auth",
                host: ip,
                port: parseInt(port),
                user: user,
                use_saved: (isSavedPass || isSavedKey),
                auth_type: method,
                password: password,
                private_key: privateKey,
                passphrase: isSavedPassphrase ? '*** SAVED PASSPHRASE ***' : passphrase,
                cols: term.cols,
                rows: term.rows
            }));
        };
        
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "connected") {
                    setStatus('connected');
                    pinger = setInterval(() => {
                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({type: "ping"}));
                        }
                    }, 20000);
                } else if (data.type === "error") {
                    const isPassphraseRequired = data.code === "passphrase_required" ||
                        (data.message && (
                            data.message.toLowerCase().includes("passphrase") ||
                            data.message.toLowerCase().includes("bad passphrase") ||
                            data.message.toLowerCase().includes("keyencryptionerror") ||
                            data.message.toLowerCase().includes("encrypted private keys")
                        ));

                    if (isPassphraseRequired) {
                        setStatus('error');
                        term.writeln('\r\n\x1b[1;33m[!] ' + (data.message || I18N.passphraseRequired) + '\x1b[0m');
                        openPassphraseModal(data.message || I18N.passphraseRequired);
                    } else {
                        setStatus('error', data.message);
                        term.writeln('\r\n\x1b[1;31m[!] Error: ' + data.message + '\x1b[0m');
                    }
                    ws.close();
                }
            } catch (e) {
                 term.write(event.data);
            }
        };
        
        ws.onclose = () => {
            setStatus('disconnected');
            term.writeln('\r\n\x1b[1;33m[*] ' + (I18N.connectionClosed || 'Connection closed.') + '\x1b[0m');
        };
        
        ws.onerror = () => {
            setStatus('error', I18N.errWs);
            term.writeln('\r\n\x1b[1;31m[!] ' + (I18N.errWsShort || 'WebSocket error') + '\x1b[0m');
        };
    }
    
    function disconnect() {
        if (ws) ws.close();
    }

    // --- Context Menu Logic ---
    const termCtxMenu = document.getElementById('termCtxMenu');
    
    if (termDiv) {
        termDiv.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            if (termCtxMenu) {
                termCtxMenu.style.left = e.clientX + 'px';
                termCtxMenu.style.top = e.clientY + 'px';
                termCtxMenu.classList.remove('hidden');
            }
        });
    }
    
    document.addEventListener('click', () => {
        if (termCtxMenu) termCtxMenu.classList.add('hidden');
    });
    
    function termCopy() {
        const sel = term.getSelection();
        if (sel) navigator.clipboard.writeText(sel);
        term.focus();
    }
    function termCut() {
        termCopy();
        term.clearSelection();
        term.focus();
    }
    function termPaste() {
        navigator.clipboard.readText().then(text => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "data", data: text }));
            }
        });
        term.focus();
    }

    // --- Stats Polling Logic ---
    function updateStats() {
        if (ws && ws.readyState === WebSocket.OPEN) {
            const ipElem = document.getElementById('inpIp');
            const ip = ipElem ? ipElem.value.trim() : '';
            if (!ip || ip === 'Loading...' || ip === 'Unknown' || ip === '-') return;
            fetch(`/api/terminal/stats?ip=${encodeURIComponent(ip)}`)
                .then(r => r.json())
                .then(d => {
                    if (!d.error) {
                        let uptimeStr = "--";
                        if (d.uptime > 0) {
                            const h = Math.floor(d.uptime / 3600);
                            const m = Math.floor((d.uptime % 3600) / 60);
                            uptimeStr = `${h}${I18N.unitH || 'h'} ${m}${I18N.unitM || 'm'}`;
                        }
                        const elCpu = document.getElementById('statCpu');
                        const elRam = document.getElementById('statRam');
                        const elRom = document.getElementById('statRom');
                        const elUptime = document.getElementById('statUptime');
                        const elPing = document.getElementById('statPing');
                        if (elCpu) elCpu.innerText = d.cpu.toFixed(1) + '%';
                        if (elRam) elRam.innerText = Math.round(d.ram) + '%';
                        if (elRom) elRom.innerText = Math.round(d.rom) + '%';
                        if (elUptime) elUptime.innerText = uptimeStr;
                        if (elPing) elPing.innerText = Math.round(d.ping) + 'ms';
                    }
                }).catch(() => {});
        }
    }
    setInterval(updateStats, 2000);

    // Expose global handles and functions for HTML event attributes
    window.term = term;
    window.ws = ws;
    window.toggleCtrlMode = toggleCtrlMode;
    window.toggleAuthFields = toggleAuthFields;
    window.isEncryptedKey = isEncryptedKey;
    window.loadKeyFile = loadKeyFile;
    window.clearPassphrase = clearPassphrase;
    window.openPassphraseModal = openPassphraseModal;
    window.closePassphraseModal = closePassphraseModal;
    window.togglePassphraseVisibility = togglePassphraseVisibility;
    window.submitPassphrase = submitPassphrase;
    window.connect = connect;
    window.disconnect = disconnect;
    window.termCopy = termCopy;
    window.termCut = termCut;
    window.termPaste = termPaste;
    window.updateStats = updateStats;
})();
