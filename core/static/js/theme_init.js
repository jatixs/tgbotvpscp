/* /core/static/js/theme_init.js */

(function() {
    const originalWarn = console.warn;
    console.warn = function(...args) {
        if (args[0] && typeof args[0] === 'string' && /\bcdn\.tailwindcss\.com\b/.test(args[0])) {
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
        const isDark = theme === 'dark' || theme === 'amoled' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
        if (isDark) {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }

        if (theme === 'amoled') {
            document.documentElement.classList.add('amoled');
        } else {
            document.documentElement.classList.remove('amoled');
        }

        const perfMode = localStorage.getItem('perf_mode') === '1';
        if (perfMode) {
            document.documentElement.classList.add('perf-mode');
        }

        const a11yMode = localStorage.getItem('a11y_mode') === '1';
        if (a11yMode) {
            document.documentElement.classList.add('a11y-mode');
        }
    } catch (e) {
        console.error(e);
    }
})();
