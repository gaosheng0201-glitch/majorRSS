import { useEffect, useState } from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { Minus, Square, Copy, X, ShieldAlert } from 'lucide-react';
import { useMantineColorScheme } from '@mantine/core';
import './TitleBar.css';

// macOS draws its own window controls (see tauri.macos.conf.json:
// decorations + titleBarStyle Overlay), so this component renders BUTTONS only
// on Windows/Linux. Reimplementing the traffic lights was considered and
// rejected: they are not three circles. Hover reveals the glyphs, they grey out
// together when the window loses focus, ⌥-click zooms instead of full-screening,
// right-clicking green offers Tile Left/Right, and VoiceOver names them. A CSS
// copy gets none of that, and the difference is felt even when it can't be named.
// navigator.userAgent rather than @tauri-apps/plugin-os: same answer, no extra
// plugin and no capability to declare.
const IS_MAC = typeof navigator !== 'undefined' && /Mac|Macintosh/i.test(navigator.userAgent);

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
      if (IS_MAC) {
        // Marks the platform whose window frame is the SYSTEM's, so the CSS can
        // stand down: no self-drawn radius, no border, and room reserved at the
        // top-left where the traffic lights actually sit.
        document.documentElement.classList.add('is-macos');
        document.body.classList.add('is-macos');
      }
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
    <div className={`custom-titlebar ${isDark ? 'dark' : 'light'}${IS_MAC ? ' mac' : ''}`} data-tauri-drag-region>
      <div className="titlebar-left" data-tauri-drag-region>
        <ShieldAlert size={16} color="var(--mantine-color-indigo-6)" style={{ marginRight: '8px' }} />
        <span className="titlebar-title" data-tauri-drag-region>MajorRSS</span>
      </div>
      
      <div className="titlebar-middle" data-tauri-drag-region>
        {/* Drag region */}
      </div>

      {/* macOS supplies these itself. Note the middle button is deliberately
          absent rather than remapped: the green light is ZOOM (fit to content),
          not Windows' maximize, and ⌃⌘F is full-screen — wiring toggleMaximize
          to it would import Windows semantics onto a control users already know. */}
      {!IS_MAC && (
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
      )}
    </div>
  );
}
