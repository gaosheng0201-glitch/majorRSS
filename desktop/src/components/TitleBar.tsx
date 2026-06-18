import { useEffect, useState } from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { Minus, Square, Copy, X, ShieldAlert } from 'lucide-react';
import { useMantineColorScheme } from '@mantine/core';
import './TitleBar.css';

export default function TitleBar() {
  const [isMaximized, setIsMaximized] = useState(false);
  const [isTauri, setIsTauri] = useState(false);
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  useEffect(() => {
    // Check if running inside Tauri
    const checkTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
    setIsTauri(checkTauri);

    if (checkTauri) {
      document.documentElement.classList.add('is-tauri');
      document.body.classList.add('is-tauri');
      const appWindow = getCurrentWindow();
      
      const updateMaximized = async () => {
        const maximized = await appWindow.isMaximized();
        setIsMaximized(maximized);
        if (maximized) {
          document.documentElement.classList.add('window-maximized');
          document.body.classList.add('window-maximized');
        } else {
          document.documentElement.classList.remove('window-maximized');
          document.body.classList.remove('window-maximized');
        }
      };
      
      updateMaximized();
      
      // Listen to window resize events to keep maximized state in sync
      const unlistenPromise = appWindow.onResized(() => {
        updateMaximized();
      });

      return () => {
        unlistenPromise.then(unlisten => unlisten());
      };
    }
  }, []);

  if (!isTauri) return null;

  const appWindow = getCurrentWindow();

  const handleMinimize = () => {
    appWindow.minimize();
  };

  const handleMaximize = async () => {
    await appWindow.toggleMaximize();
    const maximized = await appWindow.isMaximized();
    setIsMaximized(maximized);
    if (maximized) {
      document.documentElement.classList.add('window-maximized');
      document.body.classList.add('window-maximized');
    } else {
      document.documentElement.classList.remove('window-maximized');
      document.body.classList.remove('window-maximized');
    }
  };

  const handleClose = () => {
    appWindow.close();
  };

  return (
    <div className={`custom-titlebar ${isDark ? 'dark' : 'light'}`} data-tauri-drag-region>
      <div className="titlebar-left" data-tauri-drag-region>
        <ShieldAlert size={16} color="var(--mantine-color-indigo-6)" style={{ marginRight: '8px' }} />
        <span className="titlebar-title" data-tauri-drag-region>MajorRSS</span>
      </div>
      
      <div className="titlebar-middle" data-tauri-drag-region>
        {/* Drag region */}
      </div>

      <div className="titlebar-right">
        <button className="titlebar-btn" onClick={handleMinimize} title="最小化">
          <Minus size={14} />
        </button>
        <button className="titlebar-btn" onClick={handleMaximize} title={isMaximized ? '还原' : '最大化'}>
          {isMaximized ? <Copy size={12} /> : <Square size={12} />}
        </button>
        <button className="titlebar-btn btn-close" onClick={handleClose} title="关闭">
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
