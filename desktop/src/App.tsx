import { useState, useEffect } from 'react';
import { 
  MantineProvider, createTheme, AppShell, Group, Text, UnstyledButton, Stack, rem, ActionIcon, Select, useMantineColorScheme,
  Loader, Button, Modal, Checkbox, Badge, Card, SimpleGrid, SegmentedControl, Paper
} from '@mantine/core';
import { 
  LayoutDashboard, Satellite, Settings as SettingsIcon, ShieldAlert, BookOpen, Coins, Sun, Moon,
  PanelLeftClose, PanelLeftOpen, Sparkles, Rss, Globe, Database
} from 'lucide-react';
import Dashboard from './pages/Dashboard';
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

type PageName = 'dashboard' | 'briefing' | 'factcheck' | 'billing' | 'trackers' | 'monitors' | 'sources' | 'settings';

function MainAppShell() {
  const { lang, changeLanguage, t } = useLanguage();
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();
  const [activePage, setActivePage] = useState<PageName>('dashboard');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  const isDark = colorScheme === 'dark';
  const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

  const [isBackendReady, setIsBackendReady] = useState(false);
  const [backendError, setBackendError] = useState(false);
  const [isChecking, setIsChecking] = useState(true);

  // App mode and onboarding states
  const [appMode, setAppMode] = useState<'ai_fusion' | 'pure_rss'>(
    (localStorage.getItem('app_mode') as 'ai_fusion' | 'pure_rss') || 'ai_fusion'
  );
  const [onboardingOpen, setOnboardingOpen] = useState(
    localStorage.getItem('onboarding_completed') !== 'true'
  );
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [onboardingMode, setOnboardingMode] = useState<'ai_fusion' | 'pure_rss'>('ai_fusion');

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
    let active = true;
    let timer: any;

    const checkHealth = async () => {
      if (!isChecking) return;
      try {
        const response = await client.get('/settings/health');
        if (response.data && response.data.status === 'ok') {
          if (active) {
            setIsBackendReady(true);
            setBackendError(false);
            setIsChecking(false);
          }
          return;
        }
      } catch (err) {
        console.warn('[Backend Health Check] Failed to connect:', err);
      }

      // Retry after 1.5 seconds if we haven't succeeded
      if (active) {
        timer = setTimeout(checkHealth, 1500);
      }
    };

    checkHealth();

    // If it takes more than 45 seconds, show retry/error screen (but keep trying in background)
    const timeoutTimer = setTimeout(() => {
      if (active && !isBackendReady) {
        setBackendError(true);
      }
    }, 45000);

    return () => {
      active = false;
      clearTimeout(timer);
      clearTimeout(timeoutTimer);
    };
  }, [isBackendReady, isChecking]);

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

  if (!isBackendReady) {
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
          {backendError ? (
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
          )}
        </div>
      </div>
    );
  }

  const navItems = [
    { labelKey: 'nav_dashboard', page: 'dashboard', icon: LayoutDashboard },
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
