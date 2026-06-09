import { useEffect, useState, type FormEvent } from 'react';
import { 
  Text, Group, Stack, Button, TextInput, Paper, ScrollArea, Divider, Select,
  SimpleGrid, Badge, Loader
} from '@mantine/core';
import { Terminal, Settings as SettingsIcon, Save, CheckCircle2, AlertTriangle, XCircle, ShieldAlert, Key } from 'lucide-react';
import client from '../api/client';
import { useLanguage, type Language } from '../i18n/translations';

interface PipelineLog {
  id: number;
  tracker_name: string;
  action_type: string;
  detail: string;
  updated_at: string;
}

export interface AuthStatus {
  key: string;
  name: string;
  has_cookie: boolean;
  is_healthy: boolean;
  mtime: number | null;
}

export default function Settings() {
  const { lang, changeLanguage, t } = useLanguage();
  const [apiKey, setApiKey] = useState('');
  const [hasApiKey, setHasApiKey] = useState(false);
  const [maskedApiKey, setMaskedApiKey] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [logs, setLogs] = useState<PipelineLog[]>([]);
  const [authStatuses, setAuthStatuses] = useState<AuthStatus[]>([]);
  const [loggingInPlatform, setLoggingInPlatform] = useState<string | null>(null);

  const fetchLogs = async () => {
    try {
      const res = await client.get<PipelineLog[]>('/settings/pipeline-logs');
      setLogs(res.data);
    } catch (err) {
      console.error("Failed to fetch logs:", err);
    }
  };

  const fetchAuthStatuses = async () => {
    try {
      const res = await client.get<AuthStatus[]>('/settings/auth/status');
      setAuthStatuses(res.data);
    } catch (err) {
      console.error("Failed to fetch auth statuses:", err);
    }
  };

  const fetchApiKeyStatus = async () => {
    try {
      const res = await client.get<{ has_key: boolean; masked_key: string }>('/settings/api-key/status');
      setHasApiKey(res.data.has_key);
      setMaskedApiKey(res.data.masked_key);
    } catch (err) {
      console.error("Failed to fetch API key status:", err);
    }
  };

  useEffect(() => {
    fetchLogs();
    fetchAuthStatuses();
    fetchApiKeyStatus();
    const interval = setInterval(() => {
      fetchLogs();
      fetchAuthStatuses();
    }, 5000); // Poll logs/auth every 5s
    return () => clearInterval(interval);
  }, []);

  const handleSaveApiKey = async (e: FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) return;

    setSubmitting(true);
    try {
      await client.post('/settings/api-key', { api_key: apiKey });
      alert(t('set_api_success'));
      setApiKey('');
      fetchApiKeyStatus(); // Refresh secure key status in UI
    } catch (err) {
      alert(t('set_api_fail'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleLogin = async (platformKey: string) => {
    setLoggingInPlatform(platformKey);
    try {
      const res = await client.post<{ success: boolean; message: string }>('/settings/auth/login', { platform: platformKey });
      alert(res.data.message);
      fetchAuthStatuses();
    } catch (err) {
      alert("Auth failed: " + err);
    } finally {
      setLoggingInPlatform(null);
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
    <Stack gap="lg">
      <Stack gap={0}>
        <Text size="xl" fw={700} c="white">{t('nav_settings')}</Text>
        <Text size="sm" c="dimmed">{t('set_desc')}</Text>
      </Stack>

      {/* Language Selector */}
      <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
        <Stack gap="md">
          <Group gap="xs">
            <SettingsIcon size={18} className="text-indigo-400" />
            <Text size="md" fw={700} c="white">{t('set_lang')}</Text>
          </Group>
          <Text size="xs" c="dimmed">{t('set_lang_desc')}</Text>
          <Select
            data={languageOptions}
            value={lang}
            onChange={async (value) => {
              if (value) {
                changeLanguage(value as Language);
                try {
                  await client.post('/settings/system-language', { language: value });
                } catch (err) {
                  console.error("Failed to save language to backend:", err);
                }
              }
            }}
            styles={{ 
              input: { background: 'rgba(255,255,255,0.05)', color: 'white', maxWidth: 300 },
              dropdown: { background: '#1a1b1e', border: '1px solid rgba(255,255,255,0.08)' }
            }}
          />
        </Stack>
      </Paper>

      {/* API Configuration */}
      <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
        <form onSubmit={handleSaveApiKey}>
          <Stack gap="md">
            <Group gap="xs">
              <SettingsIcon size={18} className="text-indigo-400" />
              <Text size="md" fw={700} c="white">{t('set_api')}</Text>
            </Group>
            <Text size="xs" c="dimmed">{t('set_api_desc')}</Text>
            <TextInput
              required={!hasApiKey}
              placeholder={hasApiKey ? `${t('set_auth_status_ok')} (${maskedApiKey})` : t('set_api_ph')}
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white', maxWidth: 500 } }}
            />
            <Button 
              type="submit" 
              color="indigo" 
              loading={submitting}
              leftSection={<Save size={14} />}
              style={{ alignSelf: 'flex-start' }}
            >
              {t('set_save_api')}
            </Button>
          </Stack>
        </form>
      </Paper>

      {/* Interactive Cookie Auth Portal */}
      <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
        <Stack gap="md">
          <Group gap="xs">
            <Key size={18} className="text-indigo-400" />
            <Text size="md" fw={700} c="white">{t('set_auth_title')}</Text>
          </Group>
          <Text size="xs" c="dimmed">{t('set_auth_desc')}</Text>
          <Text size="xs" style={{ color: '#ebcb8b', display: 'flex', alignItems: 'center', gap: 6, lineHeight: 1.5 }}>
            <ShieldAlert size={14} style={{ flexShrink: 0 }} />
            💡 架构提示: 社交媒体(B站/推特/微博等)的主页追踪现已全面由底层 RSSHub 隐形代理，免登录永不封号。此处的强制授权仅为情报溯源系统 (Fact-Checker) 提供底层的单篇深度穿透能力。
          </Text>

          {loggingInPlatform && (
            <Paper p="sm" radius="sm" style={{ background: 'rgba(224, 49, 49, 0.15)', border: '1px solid rgba(224, 49, 49, 0.3)' }}>
              <Group gap="sm">
                <Loader size="xs" color="red" />
                <Text size="xs" c="red" fw={600}>
                  {t('set_auth_waiting')} ({loggingInPlatform})
                </Text>
              </Group>
            </Paper>
          )}

          <SimpleGrid cols={{ base: 1, sm: 2, md: 3, lg: 4 }} spacing="md">
            {authStatuses.map((p) => {
              let statusColor = "gray";
              let statusText = t('set_auth_status_none');
              let statusIcon = <XCircle size={16} className="text-gray-400" />;
              
              if (p.has_cookie && p.is_healthy) {
                statusColor = "green";
                statusText = t('set_auth_status_ok');
                statusIcon = <CheckCircle2 size={16} className="text-emerald-400" />;
              } else if (p.has_cookie && !p.is_healthy) {
                statusColor = "yellow";
                statusText = t('set_auth_status_expired');
                statusIcon = <AlertTriangle size={16} className="text-amber-400" />;
              }

              const formattedTime = p.mtime 
                ? new Date(p.mtime * 1000).toLocaleString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
                : null;

              return (
                <Paper 
                  key={p.key} 
                  withBorder 
                  p="sm" 
                  radius="md" 
                  style={{ 
                    background: 'rgba(255,255,255,0.01)', 
                    display: 'flex', 
                    flexDirection: 'column', 
                    justifyContent: 'space-between',
                    minHeight: 120
                  }}
                >
                  <Stack gap="xs">
                    <Group justify="space-between" align="center">
                      <Text size="sm" fw={700} c="white">{p.name}</Text>
                      {statusIcon}
                    </Group>
                    <Group gap={6}>
                      <Badge size="xs" color={statusColor} variant="light">
                        {statusText}
                      </Badge>
                      {formattedTime && (
                        <Text size="10px" c="dimmed">
                          ({formattedTime})
                        </Text>
                      )}
                    </Group>
                  </Stack>
                  <Button
                    size="xs"
                    variant={p.has_cookie && p.is_healthy ? "subtle" : "light"}
                    color={p.has_cookie && p.is_healthy ? "gray" : "indigo"}
                    onClick={() => handleLogin(p.key)}
                    loading={loggingInPlatform === p.key}
                    disabled={loggingInPlatform !== null}
                    mt="sm"
                    fullWidth
                  >
                    {p.has_cookie ? t('set_auth_relogin') : t('set_auth_login')}
                  </Button>
                </Paper>
              );
            })}
          </SimpleGrid>
        </Stack>
      </Paper>

      {/* Pipeline Logs */}
      <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
        <Stack gap="md">
          <Group justify="space-between">
            <Group gap="xs">
              <Terminal size={18} className="text-indigo-400" />
              <Text size="md" fw={700} c="white">{t('set_logs_title')}</Text>
            </Group>
            <Text size="xs" c="dimmed">{t('set_logs_desc')}</Text>
          </Group>
          <Divider style={{ borderColor: 'rgba(255,255,255,0.05)' }} />
          <ScrollArea h="30vh" p="md" style={{ background: 'rgba(0,0,0,0.3)', borderRadius: 8 }}>
            <Stack gap="xs" style={{ fontFamily: 'monospace' }}>
              {logs.length === 0 ? (
                <Text size="xs" c="dimmed" ta="center" py="lg">{t('set_no_logs')}</Text>
              ) : (
                logs.map((log) => (
                  <Text key={log.id} size="xs" style={{ lineHeight: 1.6, color: '#d8dee9' }}>
                    <span style={{ color: '#88c0d0' }}>[{new Date(log.updated_at).toLocaleTimeString()}]</span>{' '}
                    <span style={{ color: '#ebcb8b' }}>[{log.tracker_name}]</span>{' '}
                    <span style={{ color: '#8fbcbb', fontWeight: 700 }}>{log.action_type}</span>{' '}
                    <span style={{ color: '#e5e9f0' }}>- {log.detail}</span>
                  </Text>
                ))
              )}
            </Stack>
          </ScrollArea>
        </Stack>
      </Paper>
    </Stack>
  );
}
