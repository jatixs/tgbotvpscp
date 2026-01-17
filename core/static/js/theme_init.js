/* /core/static/js/theme_init.js */

(function() {
    const originalWarn = console.warn;
    console.warn = function(...args) {
        if (args[0] && typeof args[0] === 'string' && args[0].includes('cdn.tailwindcss.com')) {
            return;
        }
        originalWarn.apply(console, args);
    };
})();

window.tailwind = window.tailwind || {};
window.tailwind.config = {
    darkMode: 'class',
    theme: {
        extend: {
            colors: {
                gray: {
                    850: '#1f2937',
                    900: '#111827',
                    950: '#0b0f19',
                }
            }
        }
    }
};


(function() {
    try {
        const theme = localStorage.getItem('theme') || 'system';
        const isDark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
        if (isDark) {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }
    } catch (e) { console.error(e); }
})();