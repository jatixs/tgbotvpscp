/* VNC dialog controls shared by full loads and panel navigation. */
window.openVncModal = function () {
    const modal = document.getElementById('vncNodeSelectModal');
    if (!modal) return;
    if (window.animateModalOpen) window.animateModalOpen(modal);
    else { modal.classList.remove('hidden'); modal.classList.add('flex'); }
};

window.closeVncModal = function () {
    const modal = document.getElementById('vncNodeSelectModal');
    if (!modal) return;
    if (window.animateModalClose) window.animateModalClose(modal);
    else { modal.classList.add('hidden'); modal.classList.remove('flex'); }
};

window.openVncTerminal = function (ip) {
    window.closeVncModal();
    const target = !ip || ['Loading...', 'Unknown', '-'].includes(ip)
        ? '/terminal' : '/terminal?ip=' + encodeURIComponent(ip);
    window.open(target, '_blank');
};
