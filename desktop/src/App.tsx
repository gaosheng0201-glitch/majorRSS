import { useState } from 'react';
import { 
  MantineProvider, createTheme, AppShell, Group, Text, UnstyledButton, Stack, rem, ActionIcon, Select, useMantineColorScheme
} from '@mantine/core';
import { 
  LayoutDashboard, Satellite, Eye, Settings as SettingsIcon, ShieldAlert, BookOpen, Coins, Sun, Moon
} from 'lucide-react';
import Dashboard from './pages/Dashboard';
import Trackers from './pages/Trackers';
import Monitors from './pages/Monitors';
import Settings from './pages/Settings';
import Briefing from './pages/Briefing';
import FactChecker from './pages/FactChecker';
import Billing from './pages/Billing';
import { useLanguage, type Language, LanguageProvider } from './i18n/translations';

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

type PageName = 'dashboard' | 'briefing' | 'factcheck' | 'billing' | 'trackers' | 'monitors' | 'settings';

function MainAppShell() {
  const { lang, changeLanguage, t } = useLanguage();
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();
  const [activePage, setActivePage] = useState<PageName>('dashboard');

  const isDark = colorScheme === 'dark';

  const navItems = [
    { labelKey: 'nav_dashboard', page: 'dashboard', icon: LayoutDashboard },
    { labelKey: 'nav_briefing', page: 'briefing', icon: BookOpen },
    { labelKey: 'nav_factcheck', page: 'factcheck', icon: ShieldAlert },
    { labelKey: 'nav_billing', page: 'billing', icon: Coins },
    { labelKey: 'nav_trackers', page: 'trackers', icon: Satellite },
    { labelKey: 'nav_monitors', page: 'monitors', icon: Eye },
    { labelKey: 'nav_settings', page: 'settings', icon: SettingsIcon },
  ] as const;

  const renderActivePage = () => {
    switch (activePage) {
      case 'dashboard':
        return <Dashboard />;
      case 'briefing':
        return <Briefing />;
      case 'factcheck':
        return <FactChecker />;
      case 'billing':
        return <Billing />;
      case 'trackers':
        return <Trackers />;
      case 'monitors':
        return <Monitors />;
      case 'settings':
        return <Settings />;
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
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 240, breakpoint: 'sm' }}
      padding="lg"
      styles={{
        main: { background: isDark ? '#141517' : '#f8f9fa', color: isDark ? 'white' : '#212529' },
        header: { 
          background: isDark ? '#101113' : '#ffffff', 
          borderBottom: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.08)' 
        },
        navbar: { 
          background: isDark ? '#101113' : '#ffffff', 
          borderRight: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.08)' 
        },
      }}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <ShieldAlert size={22} color="var(--mantine-color-indigo-6)" />
            <Text size="lg" fw={800} style={{ letterSpacing: rem(0.5) }} c={isDark ? 'white' : 'dark'}>
              {t('nav_title')}
            </Text>
          </Group>
          
          <Group gap="md">
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

      <AppShell.Navbar p="xs">
        <Stack gap={4} mt="md">
          {navItems.map((item) => {
            const IconComponent = item.icon;
            const isActive = activePage === item.page;
            return (
              <UnstyledButton
                key={item.page}
                onClick={() => setActivePage(item.page)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  padding: `${rem(10)} ${rem(14)}`,
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
              >
                <IconComponent size={18} style={{ marginRight: rem(12) }} />
                <Text size="sm" fw={isActive ? 700 : 500}>
                  {t(item.labelKey)}
                </Text>
              </UnstyledButton>
            );
          })}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main>
        {renderActivePage()}
      </AppShell.Main>
    </AppShell>
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
