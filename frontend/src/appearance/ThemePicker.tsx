import { useEffect, useState } from 'react';

type Theme = 'system' | 'light' | 'dark';
const key = 'cloudscope.theme';
function savedTheme(): Theme {
  try {
    const saved = localStorage.getItem(key);
    return saved === 'light' || saved === 'dark' ? saved : 'system';
  } catch { return 'system'; }
}

export default function ThemePicker() {
  const [theme, setTheme] = useState<Theme>(savedTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(key, theme); } catch { /* Preference remains usable without storage. */ }
  }, [theme]);
  return <label className="theme-picker">Appearance
    <select aria-label="Appearance" value={theme} onChange={event => setTheme(event.target.value as Theme)}>
      <option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option>
    </select>
  </label>;
}
