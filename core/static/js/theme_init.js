tailwind.config = {
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