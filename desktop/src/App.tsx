import { useState, useEffect, useCallback } from 'react';
import { 
  MantineProvider, createTheme, AppShell, Group, Text, UnstyledButton, Stack, rem, ActionIcon, Select, useMantineColorScheme,
  Loader, Button, Modal, Checkbox, Badge, Card, SimpleGrid, SegmentedControl, Paper
} from '@mantine/core';
import { 
  LayoutDashboard, Satellite, Settings as SettingsIcon, ShieldAlert, BookOpen, Coins, Sun, Moon,
  PanelLeftClose, PanelLeftOpen, Sparkles, Rss, Globe, Database, Radar as RadarIcon
} from 'lucide-react';
import Dashboard from './pages/Dashboard';
import Radar from './pages/Radar';
import Discovery from './pages/Discovery';
import Subscriptions from './pages/Subscriptions';
import Settings from './pages/Settings';
import Briefing from './pages/Briefing';
import FactChecker from './pages/FactChecker';
import Billing from './pages/Billing';
import Sources from './pages/Sources';
import { useLanguage, type Language, LanguageProvider } from './i18n/translations';
import TitleBar from './components/TitleBar';
import client from './api/client';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';

// Mantine v7 custom dark theme config
const theme = createTheme({
  primaryColor: 'indigo',
  fontFamily: 'Outfit, Inter, sans-serif',
  headings: {
    fontFamily: 'Outfit, Inter, sans-serif',
  },
  colors: {
    dark: [
      '#C1C2C5',
      '#A6A7AB',
      '#909296',
      '#5C5F66',
      '#373A40',
      '#2C2E33',
      '#25262B',
      '#1A1B1E', // Dark card backgrounds
      '#141517', // Main background
      '#101113', // Header / Sidebar background
    ],
  },
});

type PageName = 'dashboard' | 'radar' | 'briefing' | 'factcheck' | 'billing' | 'trackers' | 'monitors' | 'sources' | 'settings';
type StartupStage = 'info' | 'checking' | 'success' | 'warning' | 'error';

type BackendStartupStatus = {
  phase: string;
  message: string;
  detail?: string | null;
  level: StartupStage | string;
  timestamp_ms?: number;
};

type StartupViewStatus = {
  stage: StartupStage;
  title: string;
  detail: string;
  timestamp: number;
};

type BackendRuntimeSnapshot = {
  processes: string;
  port_8765: string;
};

const BACKEND_HEALTH_URL = 'http://127.0.0.1:8765/api/settings/health';
const STARTUP_ERROR_AFTER_MS = 45000;
const HEALTH_RETRY_MS = 1500;

function MainAppShell() {
  const { lang, changeLanguage, t } = useLanguage();
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();
  // Land on the Radar (the information itself), not the stats-heavy Dashboard —
  // content is the hero (info-design principle).
  const [activePage, setActivePage] = useState<PageName>('radar');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  const isDark = colorScheme === 'dark';
  const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

  const [isBackendReady, setIsBackendReady] = useState(false);
  const [backendError, setBackendError] = useState(false);
  const [isChecking, setIsChecking] = useState(true);
  const [startupNonce, setStartupNonce] = useState(0);
  const [startupStartedAt, setStartupStartedAt] = useState(() => Date.now());
  const [healthAttempt, setHealthAttempt] = useState(0);
  const [startupStatus, setStartupStatus] = useState<StartupViewStatus>({
    stage: 'info',
    title: 'Preparing application startup checks',
    detail: 'Waiting for the local backend process and health endpoint.',
    timestamp: Date.now(),
  });
  const [startupEvents, setStartupEvents] = useState<StartupViewStatus[]>([]);

  // App mode and onboarding states
  const [appMode, setAppMode] = useState<'ai_fusion' | 'pure_rss'>(
    (localStorage.getItem('app_mode') as 'ai_fusion' | 'pure_rss') || 'ai_fusion'
  );
  const [onboardingOpen, setOnboardingOpen] = useState(
    localStorage.getItem('onboarding_completed') !== 'true'
  );
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [onboardingMode, setOnboardingMode] = useState<'ai_fusion' | 'pure_rss'>('ai_fusion');

  const startupText = useCallback((en: string, zh: string) => (lang === 'zh' ? zh : en), [lang]);

  const pushStartupEvent = useCallback((event: StartupViewStatus) => {
    setStartupStatus(event);
    setStartupEvents((events) => [...events.slice(-7), event]);
  }, []);

  const pushBackendEvent = useCallback((payload: BackendStartupStatus) => {
    const stage = ['success', 'warning', 'error'].includes(payload.level)
      ? payload.level as StartupStage
      : 'info';

    pushStartupEvent({
      stage,
      title: payload.message,
      detail: payload.detail || `Backend startup phase: ${payload.phase}`,
      timestamp: payload.timestamp_ms || Date.now(),
    });
  }, [pushStartupEvent]);

  const describeHealthError = useCallback((err: any) => {
    if (err?.response) {
      return startupText(
        `Backend responded with HTTP ${err.response.status}.`,
        `后台服务已有响应，但返回 HTTP ${err.response.status}。`
      );
    }

    if (err?.code === 'ECONNABORTED') {
      return startupText(
        'The health request timed out. The backend may be starting slowly or blocked.',
        '健康检查请求超时，后台可能启动较慢或被系统拦截。'
      );
    }

    if (err?.code === 'ERR_NETWORK' || err?.request) {
      return startupText(
        'No HTTP response from 127.0.0.1:8765 yet. The sidecar may still be starting, blocked, or not listening.',
        '127.0.0.1:8765 暂无 HTTP 响应；侧车可能仍在启动、被拦截，或尚未监听端口。'
      );
    }

    return startupText(
      `Health check failed: ${err?.message || 'unknown error'}.`,
      `健康检查失败：${err?.message || '未知错误'}。`
    );
  }, [startupText]);

  const getRuntimeSnapshotDetail = useCallback(async () => {
    if (!isTauri) return '';

    try {
      const snapshot = await invoke<BackendRuntimeSnapshot>('get_backend_runtime_snapshot');
      return startupText(
        `\nProcess snapshot:\n${snapshot.processes}\nPort 8765 snapshot:\n${snapshot.port_8765}`,
        `\n进程快照：\n${snapshot.processes}\n8765 端口快照：\n${snapshot.port_8765}`
      );
    } catch (snapshotError: any) {
      return startupText(
        `\nRuntime snapshot unavailable: ${snapshotError?.message || snapshotError}`,
        `\n运行时快照不可用：${snapshotError?.message || snapshotError}`
      );
    }
  }, [isTauri, startupText]);

  useEffect(() => {
    const fetchMode = async () => {
      try {
        const res = await client.get<{ app_mode: 'ai_fusion' | 'pure_rss' }>('/settings/app-mode');
        setAppMode(res.data.app_mode);
        localStorage.setItem('app_mode', res.data.app_mode);
      } catch (err) {
        console.error("Failed to fetch app mode from backend:", err);
      }
    };
    if (isBackendReady) {
      fetchMode();
    }
  }, [isBackendReady]);

  useEffect(() => {
    if (!isTauri) return;

    let disposed = false;
    let unlisten: (() => void) | undefined;

    const loadBackendStartupEvents = async () => {
      try {
        const events = await invoke<BackendStartupStatus[]>('get_backend_startup_statuses');
        if (!disposed) {
          events.forEach(pushBackendEvent);
        }
      } catch (err) {
        console.warn('[Backend Startup Status] Failed to read startup events:', err);
      }
    };

    listen<BackendStartupStatus>('backend-startup-status', (event) => {
      pushBackendEvent(event.payload);
    }).then((handler) => {
      unlisten = handler;
    }).catch((err) => {
      console.warn('[Backend Startup Status] Failed to listen for startup events:', err);
    });

    loadBackendStartupEvents();

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [isTauri, pushBackendEvent]);

  useEffect(() => {
    if (!isChecking || isBackendReady) return;

    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const startedAt = Date.now();
    let attempts = 0;
    let slowStartLogged = false;

    setStartupStartedAt(startedAt);
    setHealthAttempt(0);
    pushStartupEvent({
      stage: 'checking',
      title: startupText('Checking local backend health endpoint', '正在检查本地后台健康接口'),
      detail: startupText(`GET ${BACKEND_HEALTH_URL}`, `请求 ${BACKEND_HEALTH_URL}`),
      timestamp: startedAt,
    });

    const checkHealth = async () => {
      if (!active || !isChecking) return;

      attempts += 1;
      const attempt = attempts;
      setHealthAttempt(attempt);
      // 每次轮询只更新顶部实时状态，不再往"启动跟踪"里追加——否则列表每
      // ~1.5s 重排一次，整屏抖动。轨迹只记录真正的状态转变（见下）。
      setStartupStatus({
        stage: 'checking',
        title: startupText('Waiting for backend HTTP service', '正在等待后台 HTTP 服务'),
        detail: startupText(
          `Health check attempt ${attempt}: ${BACKEND_HEALTH_URL}`,
          `第 ${attempt} 次健康检查：${BACKEND_HEALTH_URL}`
        ),
        timestamp: Date.now(),
      });

      try {
        const response = await client.get('/settings/health');
        if (response.data && response.data.status === 'ok') {
          if (active) {
            pushStartupEvent({
              stage: 'success',
              title: startupText('Backend is ready', '后台服务已就绪'),
              detail: startupText('Health endpoint returned status=ok.', '健康接口返回 status=ok。'),
              timestamp: Date.now(),
            });
            setIsBackendReady(true);
            setBackendError(false);
            setIsChecking(false);
          }
          return;
        }

        pushStartupEvent({
          stage: 'warning',
          title: startupText('Backend responded but is not healthy yet', '后台已有响应但尚未健康'),
          detail: startupText(
            `Health response: ${JSON.stringify(response.data)}`,
            `健康检查响应：${JSON.stringify(response.data)}`
          ),
          timestamp: Date.now(),
        });
      } catch (err) {
        console.warn('[Backend Health Check] Failed to connect:', err);
        const crossedError = Date.now() - startedAt > STARTUP_ERROR_AFTER_MS;
        // 常规"侧车还在起来"的失败：只更新顶部实时状态，短文案、不带那一大坨
        // 运行时快照（快照会把行高撑爆、导致面板跳动）。
        setStartupStatus({
          stage: crossedError ? 'warning' : 'checking',
          title: startupText('Backend health check is still waiting', '后台健康检查仍在等待'),
          detail: describeHealthError(err),
          timestamp: Date.now(),
        });
        // 只有当启动真的偏慢（越过错误阈值）时，才把带快照的诊断往轨迹里追加
        // 一次——进的是固定高度可滚动的轨迹区，不会撑动整屏。
        if (crossedError && !slowStartLogged) {
          slowStartLogged = true;
          const snapshot = await getRuntimeSnapshotDetail();
          pushStartupEvent({
            stage: 'warning',
            title: startupText('Backend is slow to start', '后台启动较慢'),
            detail: `${describeHealthError(err)}${snapshot}`,
            timestamp: Date.now(),
          });
        }
      }

      if (active) {
        if (Date.now() - startedAt > STARTUP_ERROR_AFTER_MS) {
          setBackendError(true);
        }
        timer = setTimeout(checkHealth, HEALTH_RETRY_MS);
      }
    };

    checkHealth();

    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [startupNonce, isChecking, isBackendReady, describeHealthError, getRuntimeSnapshotDetail, pushStartupEvent, startupText]);

  useEffect(() => {
    if (isTauri) {
      // Dynamically request notification permissions
      import('@tauri-apps/plugin-notification').then(({ isPermissionGranted, requestPermission }) => {
        isPermissionGranted().then((granted) => {
          if (!granted) {
            requestPermission().then((permission) => {
              console.log('[Tauri Notification] Permission status:', permission);
            });
          }
        });
      }).catch((err) => {
        console.error('[Tauri Notification] Failed to load notification plugin:', err);
      });
    }
  }, [isTauri]);

  // R5 alert delivery: poll for thread-level alerts the backend hasn't pushed
  // yet, fire an OS notification with the "why", then mark delivered so each
  // alert notifies exactly once. Default-quiet: only genuine increments become
  // RadarAlerts server-side, so this rarely fires. Tauri-only (no-op in browser).
  useEffect(() => {
    if (!isTauri || !isBackendReady) return;
    let cancelled = false;
    const deliver = async () => {
      try {
        const res = await client.get<any[]>('/intelligence/radar-alerts/undelivered');
        const alerts = res.data || [];
        if (!alerts.length) return;
        const { sendNotification, isPermissionGranted } = await import('@tauri-apps/plugin-notification');
        const granted = await isPermissionGranted();
        for (const a of alerts) {
          if (cancelled) break;
          if (granted) {
            sendNotification({
              title: a.title || (lang === 'zh' ? '雷达提醒' : 'Radar alert'),
              body: (a.summary || '').split('\n')[0].slice(0, 160),
            });
          }
          // Mark delivered regardless, so a permission-off user isn't spammed later.
          await client.post(`/intelligence/radar-alerts/${a.id}/delivered`).catch(() => {});
        }
      } catch { /* transient */ }
    };
    deliver();
    const t = setInterval(deliver, 60000);
    return () => { cancelled = true; clearInterval(t); };
  }, [isTauri, isBackendReady, lang]);

  if (!isBackendReady) {
    const elapsedSeconds = Math.max(0, Math.round((Date.now() - startupStartedAt) / 1000));
    const statusColor = startupStatus.stage === 'success'
      ? 'teal'
      : startupStatus.stage === 'error'
        ? 'red'
        : startupStatus.stage === 'warning' || backendError
          ? 'yellow'
          : 'indigo';

    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
        <TitleBar />
        <div style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: isDark ? '#141517' : '#f8f9fa',
          color: isDark ? 'white' : '#212529',
          padding: '24px',
          boxSizing: 'border-box'
        }}>
          <Stack align="center" gap="md" style={{ width: '100%', maxWidth: 640, textAlign: 'center' }}>
            {backendError ? (
              <ShieldAlert size={48} color="var(--mantine-color-yellow-6)" />
            ) : (
              <Loader size="xl" type="dots" color="indigo" />
            )}

            <Stack align="center" gap={6}>
              <Text size="lg" fw={700}>
                {backendError ? t('startup_error') : t('startup_loading')}
              </Text>
              <Group gap="xs" justify="center">
                <Badge color={statusColor} variant="light">
                  {startupStatus.stage}
                </Badge>
                <Badge color="gray" variant="light">
                  {startupText(`Attempt ${healthAttempt}`, `第 ${healthAttempt} 次检查`)}
                </Badge>
                <Badge color="gray" variant="light">
                  {startupText(`${elapsedSeconds}s elapsed`, `已等待 ${elapsedSeconds} 秒`)}
                </Badge>
              </Group>
            </Stack>

            {/* 固定高度 + 内部滚动：内容再变也不会撑动/收缩这个框，整屏不再弹跳。 */}
            <Paper withBorder radius="md" p="md" style={{ width: '100%', textAlign: 'left', height: 116, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <Text size="sm" fw={700} style={{ flex: '0 0 auto' }}>{startupStatus.title}</Text>
              <Text size="sm" c="dimmed" style={{ flex: '1 1 auto', overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: 6 }}>{startupStatus.detail}</Text>
              <Text size="xs" c="dimmed" style={{ flex: '0 0 auto', fontFamily: 'monospace', marginTop: 6 }}>
                {BACKEND_HEALTH_URL}
              </Text>
            </Paper>

            {startupEvents.length > 0 && (
              <Paper withBorder radius="md" p="md" style={{ width: '100%', textAlign: 'left' }}>
                <Text size="xs" fw={700} c="dimmed" mb={8}>
                  {startupText('Startup trace', '启动跟踪')}
                </Text>
                {/* 固定高度可滚动的轨迹区：追加事件时在内部滚动，不改变外层高度。 */}
                <div style={{ height: 168, overflowY: 'auto' }}>
                  <Stack gap={8}>
                    {startupEvents.slice(-6).map((event, index) => (
                      <Group key={`${event.timestamp}-${index}`} align="flex-start" gap="xs" wrap="nowrap">
                        <Badge size="xs" color={event.stage === 'error' ? 'red' : event.stage === 'warning' ? 'yellow' : event.stage === 'success' ? 'teal' : 'indigo'} variant="dot">
                          {event.stage}
                        </Badge>
                        <Stack gap={2} style={{ minWidth: 0 }}>
                          <Text size="xs" fw={600}>{event.title}</Text>
                          <Text size="xs" c="dimmed" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 52, overflow: 'auto' }}>{event.detail}</Text>
                        </Stack>
                      </Group>
                    ))}
                  </Stack>
                </div>
              </Paper>
            )}

            {backendError && (
              <Button
                variant="filled"
                color="indigo"
                onClick={() => {
                  setBackendError(false);
                  setIsBackendReady(false);
                  setIsChecking(true);
                  setStartupNonce((nonce) => nonce + 1);
                  setStartupEvents([]);
                }}
                mt="xs"
              >
                {t('startup_retry')}
              </Button>
            )}
          </Stack>

          {false && (backendError ? (
            <Stack align="center" gap="md" style={{ maxWidth: 450, textAlign: 'center' }}>
              <ShieldAlert size={48} color="var(--mantine-color-red-6)" />
              <Text size="lg" fw={700}>{t('startup_error')}</Text>
              <Text size="sm" c="dimmed">
                {lang === 'zh' ? '本地数据库加载中或后台引擎初始化超时，请稍候，或点击下方重试按钮。' : 
                 'The local database is loading or the backend initialization timed out. Please wait or click retry.'}
              </Text>
              <Button 
                variant="filled" 
                color="indigo" 
                onClick={() => {
                  setBackendError(false);
                  setIsChecking(true);
                }}
                mt="md"
              >
                {t('startup_retry')}
              </Button>
            </Stack>
          ) : (
            <Stack align="center" gap="md">
              <Loader size="xl" type="dots" color="indigo" />
              <Text size="md" fw={500} c="dimmed">{t('startup_loading')}</Text>
            </Stack>
          ))}
        </div>
      </div>
    );
  }

  const navItems = [
    { labelKey: 'nav_dashboard', page: 'dashboard', icon: LayoutDashboard },
    { labelKey: 'nav_radar', page: 'radar', icon: RadarIcon },
    { labelKey: 'nav_briefing', page: 'briefing', icon: BookOpen },
    { labelKey: 'nav_factcheck', page: 'factcheck', icon: ShieldAlert },
    { labelKey: 'nav_billing', page: 'billing', icon: Coins },
    { labelKey: 'nav_trackers', page: 'trackers', icon: Satellite },
    { labelKey: 'nav_monitors', page: 'monitors', icon: Rss },
    { labelKey: 'nav_sources', page: 'sources', icon: Database },
    { labelKey: 'nav_settings', page: 'settings', icon: SettingsIcon },
  ] as const;

  const filteredNavItems = navItems.filter(item => {
    if (appMode === 'pure_rss') {
      return !['briefing', 'factcheck', 'billing'].includes(item.page);
    }
    return true;
  });

  const renderActivePage = () => {
    switch (activePage) {
      case 'dashboard':
        return <Dashboard appMode={appMode} />;
      case 'radar':
        return <Radar />;
      case 'briefing':
        return <Briefing />;
      case 'factcheck':
        return <FactChecker />;
      case 'billing':
        return <Billing />;
      case 'trackers':
        return <Discovery />;
      case 'monitors':
        return <Subscriptions />;
      case 'sources':
        return <Sources />;
      case 'settings':
        return <Settings appMode={appMode} setAppMode={setAppMode} setOnboardingOpen={setOnboardingOpen} />;
    }
  };

  const languageOptions = [
    { value: 'en', label: 'English' },
    { value: 'zh', label: '简体中文' },
    { value: 'ko', label: '한국어' },
    { value: 'ja', label: '日本語' },
    { value: 'ru', label: 'Русский' }
  ];

  return (
    <>
      <TitleBar />
      
      {/* Onboarding Wizard Modal */}
      <Modal
        opened={onboardingOpen}
        onClose={() => setOnboardingOpen(false)}
        title={<Text fw={700} size="lg" className="title-text-color">{t('onboarding_title')}</Text>}
        size="lg"
        radius="md"
        centered
        styles={{
          content: { background: isDark ? '#1a1b1e' : '#ffffff', border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)'}` },
          header: { background: isDark ? '#1a1b1e' : '#ffffff' }
        }}
      >
        <Stack gap="md" py="xs">
          {/* Quick Language Selector */}
          <Paper withBorder p="xs" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.02)' : '#f8f9fa' }}>
            <Group gap="xs" mb="xs">
              <Globe size={16} className="text-indigo-400" />
              <Text size="xs" fw={600} c="dimmed">
                Language / 语言 / 言語 / 언어 / Язык
              </Text>
            </Group>
            <SegmentedControl
              data={[
                { label: 'English', value: 'en' },
                { label: '简体中文', value: 'zh' },
                { label: '日本語', value: 'ja' },
                { label: '한국어', value: 'ko' },
                { label: 'Русский', value: 'ru' }
              ]}
              value={lang}
              onChange={(value) => {
                if (value) changeLanguage(value as Language);
              }}
              fullWidth
              size="xs"
              styles={{
                root: { background: isDark ? 'rgba(0,0,0,0.2)' : '#f1f3f5' },
                control: { border: 'none' }
              }}
            />
          </Paper>
          
          <Text size="sm" c="dimmed">{t('onboarding_desc')}</Text>
          
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md" mt="xs">
            {/* AI Fusion Mode Card */}
            <Card
              withBorder
              padding="md"
              radius="md"
              style={{
                cursor: 'pointer',
                borderColor: onboardingMode === 'ai_fusion' ? 'var(--mantine-color-indigo-6)' : (isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)'),
                background: onboardingMode === 'ai_fusion' ? (isDark ? 'rgba(92, 124, 250, 0.08)' : '#f4f6fe') : 'transparent',
                transition: 'all 150ms ease'
              }}
              onClick={() => setOnboardingMode('ai_fusion')}
            >
              <Group gap="xs" mb="xs">
                <Sparkles size={18} className="text-indigo-400" />
                <Text size="sm" fw={700} className="title-text-color">{t('onboarding_mode_ai_title')}</Text>
              </Group>
              <Text size="xs" c="dimmed" style={{ lineHeight: 1.5 }}>{t('onboarding_mode_ai_desc')}</Text>
            </Card>

            {/* Pure RSS Mode Card */}
            <Card
              withBorder
              padding="md"
              radius="md"
              style={{
                cursor: 'pointer',
                borderColor: onboardingMode === 'pure_rss' ? 'var(--mantine-color-indigo-6)' : (isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)'),
                background: onboardingMode === 'pure_rss' ? (isDark ? 'rgba(92, 124, 250, 0.08)' : '#f4f6fe') : 'transparent',
                transition: 'all 150ms ease'
              }}
              onClick={() => setOnboardingMode('pure_rss')}
            >
              <Group gap="xs" mb="xs">
                <Rss size={18} className="text-indigo-400" />
                <Text size="sm" fw={700} className="title-text-color">{t('onboarding_mode_local_title')}</Text>
              </Group>
              <Text size="xs" c="dimmed" style={{ lineHeight: 1.5 }}>{t('onboarding_mode_local_desc')}</Text>
            </Card>
          </SimpleGrid>

          <Group justify="space-between" mt="lg">
            <Checkbox
              label={t('onboarding_dont_show')}
              checked={dontShowAgain}
              onChange={(event) => setDontShowAgain(event.currentTarget.checked)}
              styles={{
                label: { color: isDark ? 'white' : 'black', fontSize: rem(13) }
              }}
            />
            <Button
              color="indigo"
              size="sm"
              onClick={async () => {
                setAppMode(onboardingMode);
                localStorage.setItem('app_mode', onboardingMode);
                
                try {
                  await client.post('/settings/app-mode', { app_mode: onboardingMode });
                } catch (err) {
                  console.error("Failed to sync app mode to backend:", err);
                }

                if (dontShowAgain) {
                  localStorage.setItem('onboarding_completed', 'true');
                }
                
                setOnboardingOpen(false);
              }}
            >
              {t('onboarding_start_btn')}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <AppShell
        header={{ height: isTauri ? 80 : 48 }}
        navbar={{ width: isSidebarCollapsed ? 54 : 240, breakpoint: 'sm' }}
        padding="lg"
        styles={{
          main: { 
            background: isDark ? '#141517' : '#f8f9fa', 
            color: isDark ? 'white' : '#212529',
            transition: 'padding-left 150ms ease',
            height: isTauri ? 'calc(100vh - 80px)' : 'calc(100vh - 48px)',
            overflowY: 'auto',
            boxSizing: 'border-box'
          },
          header: { 
            height: isTauri ? '80px' : '48px',
            paddingTop: isTauri ? '32px' : '0px',
            paddingLeft: '0px',
            paddingRight: '0px',
            background: isDark ? '#101113' : '#ffffff', 
            borderBottom: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.08)' 
          },
          navbar: { 
            top: isTauri ? '80px' : '48px',
            height: isTauri ? 'calc(100vh - 80px)' : 'calc(100vh - 48px)',
            background: isDark ? '#101113' : '#ffffff', 
            borderRight: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.08)',
            transition: 'width 150ms ease, min-width 150ms ease'
          },
        }}
      >
      <AppShell.Header px={0}>
        <Group h="100%" px={0} justify="space-between">
          <Group gap={0}>
            <div style={{ 
              width: isSidebarCollapsed ? '54px' : '240px', 
              display: 'flex', 
              justifyContent: isSidebarCollapsed ? 'center' : 'flex-start', 
              paddingLeft: isSidebarCollapsed ? 0 : rem(16),
              alignItems: 'center',
              transition: 'width 150ms ease, padding-left 150ms ease',
              boxSizing: 'border-box'
            }}>
              <ActionIcon
                onClick={() => setIsSidebarCollapsed(prev => !prev)}
                variant="subtle"
                color="gray"
                size="lg"
                title={isSidebarCollapsed ? "展开侧边栏" : "折叠侧边栏"}
              >
                {isSidebarCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
              </ActionIcon>
            </div>
          </Group>
          
          <Group gap="md" pr="md">
            {/* AI/Local mode indicator badge */}
            <Badge 
              variant="dot" 
              color={appMode === 'ai_fusion' ? 'indigo' : 'gray'}
              style={{ cursor: 'pointer' }}
              onClick={() => {
                setActivePage('settings');
              }}
              size="sm"
            >
              {appMode === 'ai_fusion' ? t('mode_badge_ai') : t('mode_badge_local')}
            </Badge>

            {/* Language Selection Selector in Header */}
            <Select
              data={languageOptions}
              value={lang}
              onChange={(value) => {
                if (value) changeLanguage(value as Language);
              }}
              size="xs"
              style={{ width: 120 }}
              styles={{ 
                input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black' },
                dropdown: { background: isDark ? '#1a1b1e' : '#ffffff', border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)'}` }
              }}
            />

            {/* Dark/Light mode dynamic toggle */}
            <ActionIcon 
              onClick={() => toggleColorScheme()} 
              variant="subtle" 
              color={isDark ? 'yellow' : 'blue'}
              size="lg"
              title={t('nav_theme_toggle')}
            >
              {isDark ? <Sun size={18} /> : <Moon size={18} />}
            </ActionIcon>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p={isSidebarCollapsed ? 6 : 'xs'}>
        <Stack gap={4} mt={isSidebarCollapsed ? 'xs' : 'md'}>
          {filteredNavItems.map((item) => {
            const IconComponent = item.icon;
            const isActive = activePage === item.page;
            return (
              <UnstyledButton
                key={item.page}
                onClick={() => setActivePage(item.page)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                  padding: `${rem(8)} ${isSidebarCollapsed ? 0 : rem(14)}`,
                  borderRadius: 'var(--mantine-radius-md)',
                  background: isActive 
                    ? (isDark ? 'rgba(92, 124, 250, 0.1)' : 'rgba(92, 124, 250, 0.08)') 
                    : 'transparent',
                  color: isActive 
                    ? 'var(--mantine-color-indigo-4)' 
                    : (isDark ? 'var(--mantine-color-gray-5)' : 'var(--mantine-color-gray-7)'),
                  transition: 'all 0.15s ease',
                }}
                className="nav-btn-hover"
                title={isSidebarCollapsed ? t(item.labelKey) : undefined}
              >
                <IconComponent size={18} style={{ marginRight: isSidebarCollapsed ? 0 : rem(12) }} />
                {!isSidebarCollapsed && (
                  <Text size="sm" fw={isActive ? 700 : 500}>
                    {t(item.labelKey)}
                  </Text>
                )}
              </UnstyledButton>
            );
          })}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main>
        {renderActivePage()}
      </AppShell.Main>
    </AppShell>
    </>
  );
}

export default function App() {
  return (
    <LanguageProvider>
      <MantineProvider theme={theme} defaultColorScheme="dark">
        <MainAppShell />
      </MantineProvider>
    </LanguageProvider>
  );
}
