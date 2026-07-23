import { useEffect, useState, type FormEvent } from 'react';
import {
  Text, Group, Stack, Button, TextInput, Paper, ScrollArea, Divider, Select,
  SimpleGrid, useMantineColorScheme, Checkbox, Badge
} from '@mantine/core';
import { Terminal, Settings as SettingsIcon, Save, AlertTriangle, ShieldAlert, Database, Activity } from 'lucide-react';
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

export interface SchedulerState {
  status: 'running' | 'starting' | 'stalled' | 'error';
  started_at: string | null;
  last_heartbeat_at: string | null;
  error: string | null;
  jobs: { name: string; next_run_time: string | null }[];
}

export interface DbStatus {
  engine_type: 'sqlite' | 'postgres';
  postgres_info: any | null;
  db_size_mb: number;
  row_counts: {
    raw_articles: number;
    intel_reports: number;
    daily_briefings: number;
    trend_alerts: number;
    token_usages: number;
  };
  retention_days: number;
  max_size_mb: number;
  is_over_size_limit: boolean;
  expired_articles_count: number;
}

export default function Settings({ appMode, setAppMode, setOnboardingOpen }: { appMode: 'ai_fusion' | 'pure_rss'; setAppMode: (m: 'ai_fusion' | 'pure_rss') => void; setOnboardingOpen: (o: boolean) => void; }) {
  const { lang, changeLanguage, t } = useLanguage();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';


  const [apiKey, setApiKey] = useState('');
  const [hasApiKey, setHasApiKey] = useState(false);
  const [maskedApiKey, setMaskedApiKey] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // Model & backend selection (docs/semantic_layer_audit.md §2/§3)
  const [llmProvider, setLlmProvider] = useState('gemini');
  const [llmBaseUrl, setLlmBaseUrl] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [llmEmbedModel, setLlmEmbedModel] = useState('');
  const [llmDefaults, setLlmDefaults] = useState<Record<string, { model: string; embed_model: string }>>({});
  const [savingLlm, setSavingLlm] = useState(false);
  const [logs, setLogs] = useState<PipelineLog[]>([]);
  const [scheduler, setScheduler] = useState<SchedulerState | null>(null);
  const [accountGuards, setAccountGuards] = useState<any[]>([]);
  const [devMode, setDevMode] = useState(() => localStorage.getItem('developer_mode') === 'true');

  // Database settings states
  const [dbStatus, setDbStatus] = useState<DbStatus | null>(null);
  const [retentionDays, setRetentionDays] = useState<string>('0');
  const [maxSizeMb, setMaxSizeMb] = useState<string>('0');
  const [dbEngineType, setDbEngineType] = useState<'sqlite' | 'postgres'>('sqlite');
  
  // Postgres connection form states
  const [pgHost, setPgHost] = useState('');
  const [pgPort, setPgPort] = useState('5432');
  const [pgUser, setPgUser] = useState('');
  const [pgPass, setPgPass] = useState('');
  const [pgName, setPgName] = useState('');
  
  // Loadings
  const [savingDbConfig, setSavingDbConfig] = useState(false);
  const [cleaningDb, setCleaningDb] = useState(false);
  const [testingConn, setTestingConn] = useState(false);
  const [switchingEngine, setSwitchingEngine] = useState(false);

  const fetchLogs = async () => {
    try {
      const res = await client.get<PipelineLog[]>('/settings/pipeline-logs');
      setLogs(res.data);
    } catch (err) {
      console.error("Failed to fetch logs:", err);
    }
  };

  const fetchEngineStatus = async () => {
    try {
      const res = await client.get<{ scheduler: SchedulerState }>('/settings/health');
      setScheduler(res.data.scheduler ?? null);
    } catch (err) {
      console.error("Failed to fetch engine status:", err);
    }
    try {
      const g = await client.get<any[]>('/settings/account-guards');
      setAccountGuards(g.data || []);
    } catch { /* optional */ }
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

  const fetchDbStatus = async () => {
    try {
      const res = await client.get<DbStatus>('/settings/db-status');
      setDbStatus(res.data);
      setRetentionDays(res.data.retention_days.toString());
      setMaxSizeMb(res.data.max_size_mb.toString());
      setDbEngineType(res.data.engine_type);
      if (res.data.postgres_info) {
        setPgHost(res.data.postgres_info.host || '');
        setPgPort(res.data.postgres_info.port?.toString() || '5432');
        setPgUser(res.data.postgres_info.username || '');
        setPgPass(res.data.postgres_info.password || '');
        setPgName(res.data.postgres_info.database || '');
      }
    } catch (err) {
      console.error("Failed to fetch DB status:", err);
    }
  };

  const fetchLlmConfig = async () => {
    try {
      const res = await client.get<any>('/settings/llm-config');
      setLlmProvider(res.data.provider || 'gemini');
      setLlmBaseUrl(res.data.base_url || '');
      setLlmModel(res.data.model || '');
      setLlmEmbedModel(res.data.embed_model || '');
      setLlmDefaults(res.data.defaults || {});
    } catch (err) {
      console.error("Failed to fetch LLM config:", err);
    }
  };

  const handleSaveLlm = async () => {
    setSavingLlm(true);
    try {
      await client.post('/settings/llm-config', {
        provider: llmProvider, base_url: llmBaseUrl, model: llmModel, embed_model: llmEmbedModel,
      });
      alert('模型配置已保存，下次 AI 操作生效');
    } catch (err) {
      alert('保存失败');
    } finally {
      setSavingLlm(false);
    }
  };

  useEffect(() => {
    fetchLogs();
    fetchApiKeyStatus();
    fetchLlmConfig();
    fetchDbStatus();
    fetchEngineStatus();
    const interval = setInterval(() => {
      fetchLogs();
      fetchEngineStatus();
    }, 5000); // Poll logs + engine heartbeat every 5s
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

  const handleSaveDbSettings = async () => {
    setSavingDbConfig(true);
    try {
      await client.post('/settings/db-settings', {
        retention_days: parseInt(retentionDays, 10),
        max_size_mb: parseInt(maxSizeMb, 10)
      });
      alert(t('set_db_save_success'));
      fetchDbStatus();
    } catch (err: any) {
      alert("Failed to save settings: " + (err.response?.data?.detail || err.message));
    } finally {
      setSavingDbConfig(false);
    }
  };

  const handleDbCleanup = async () => {
    setCleaningDb(true);
    try {
      await client.post('/settings/db-cleanup');
      alert(t('set_db_clean_success'));
      setTimeout(fetchDbStatus, 2000);
    } catch (err: any) {
      alert("Failed to trigger cleanup: " + (err.response?.data?.detail || err.message));
    } finally {
      setCleaningDb(false);
    }
  };

  const handleTestConnection = async () => {
    if (!pgHost || !pgPort || !pgUser || !pgName) {
      alert("Please fill in Host, Port, Username and Database Name");
      return;
    }
    setTestingConn(true);
    try {
      const res = await client.post<{ success: boolean; message: string }>('/settings/db-test-connection', {
        host: pgHost,
        port: parseInt(pgPort, 10),
        username: pgUser,
        password: pgPass,
        database: pgName
      });
      if (res.data.success) {
        alert(t('set_db_test_success'));
      } else {
        alert(t('set_db_test_fail') + res.data.message);
      }
    } catch (err: any) {
      alert(t('set_db_test_fail') + (err.response?.data?.detail || err.message));
    } finally {
      setTestingConn(false);
    }
  };

  const handleSwitchEngine = async () => {
    setSwitchingEngine(true);
    try {
      const payload: any = {
        engine_type: dbEngineType
      };
      if (dbEngineType === 'postgres') {
        if (!pgHost || !pgPort || !pgUser || !pgName) {
          alert("Please fill in all Postgres connection details");
          setSwitchingEngine(false);
          return;
        }
        payload.postgres_info = {
          host: pgHost,
          port: parseInt(pgPort, 10),
          username: pgUser,
          password: pgPass,
          database: pgName
        };
      }
      await client.post('/settings/db-switch', payload);
      alert(t('set_db_switch_success'));
      fetchDbStatus();
    } catch (err: any) {
      alert(t('set_db_switch_fail') + (err.response?.data?.detail || err.message));
    } finally {
      setSwitchingEngine(false);
    }
  };

  const formatWarnBanner = (text: string, size: number, limit: number, count: number) => {
    return text
      .replace('{size}', size.toFixed(2))
      .replace('{limit}', limit.toString())
      .replace('{count}', count.toString());
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
        <Text size="xl" fw={700} className="title-text-color">{t('nav_settings')}</Text>
        <Text size="sm" c="dimmed">{t('set_desc')}</Text>
      </Stack>

      {/* Scraping Engine Status */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="xs">
              <Activity size={18} className="text-indigo-400" />
              <Text size="md" fw={700} className="title-text-color">
                {lang === 'zh' ? '抓取引擎状态' : 'Scraping Engine'}
              </Text>
            </Group>
            <Badge
              size="md"
              color={
                scheduler?.status === 'running' ? 'green'
                : scheduler?.status === 'starting' ? 'yellow'
                : scheduler?.status === 'stalled' ? 'orange'
                : scheduler?.status === 'error' ? 'red'
                : 'gray'
              }
            >
              {scheduler
                ? (lang === 'zh'
                    ? { running: '运行中', starting: '启动中', stalled: '已停滞', error: '启动失败' }[scheduler.status]
                    : scheduler.status.toUpperCase())
                : (lang === 'zh' ? '未知' : 'UNKNOWN')}
            </Badge>
          </Group>
          {scheduler?.error && (
            <Paper p="sm" radius="xs" style={{ background: isDark ? 'rgba(240,62,62,0.1)' : '#fff5f5', border: `1px solid ${isDark ? 'rgba(240,62,62,0.25)' : '#ffc9c9'}` }}>
              <Text size="xs" c="red">{scheduler.error}</Text>
            </Paper>
          )}
          {scheduler?.last_heartbeat_at && (
            <Text size="xs" c="dimmed">
              {lang === 'zh' ? '最近心跳：' : 'Last heartbeat: '}
              {new Date(scheduler.last_heartbeat_at).toLocaleString()}
            </Text>
          )}
          {scheduler && scheduler.jobs.length > 0 && (
            <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="xs">
              {scheduler.jobs.filter(j => j.name !== 'heartbeat').map(job => (
                <Paper key={job.name} p="xs" radius="xs" withBorder style={{ background: isDark ? 'rgba(0,0,0,0.2)' : '#f8f9fa' }}>
                  <Text size="10px" fw={600}>{job.name}</Text>
                  <Text size="10px" c="dimmed">
                    {lang === 'zh' ? '下次：' : 'Next: '}
                    {job.next_run_time ? new Date(job.next_run_time).toLocaleTimeString() : '—'}
                  </Text>
                </Paper>
              ))}
            </SimpleGrid>
          )}
        </Stack>
      </Paper>

      {/* Authorized account protection (愿景 #10) */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <Stack gap="sm">
          <Group gap="xs">
            <ShieldAlert size={18} className="text-indigo-400" />
            <Text size="md" fw={700} className="title-text-color">
              {lang === 'zh' ? '授权账号保护' : 'Account Protection'}
            </Text>
          </Group>
          <Text size="xs" c="dimmed">
            {lang === 'zh'
              ? '用你的社媒账号抓取时，系统按每账号预算限速、拟人化节奏、风控熔断，尽量像真人以保护账号。'
              : 'When scraping with your social accounts, the radar rations per-account budget, paces humanly, and trips a circuit on risk signals to protect the account.'}
          </Text>
          {accountGuards.length === 0 ? (
            <Text size="xs" c="dimmed">
              {lang === 'zh' ? '尚无授权账号。授权某个平台后，其保护状态会显示在这里。' : 'No authorized accounts yet. Once you authorize a platform, its protection status appears here.'}
            </Text>
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
              {accountGuards.map((g) => (
                <Paper key={g.account_key} p="sm" radius="sm" withBorder style={{ background: isDark ? 'rgba(0,0,0,0.2)' : '#f8f9fa' }}>
                  <Group justify="space-between" mb={4}>
                    <Text size="xs" fw={700}>{g.account_key}</Text>
                    <Badge size="xs" color={g.circuit_state === 'closed' ? 'teal' : g.circuit_state === 'open' ? 'red' : 'yellow'}>
                      {g.circuit_state === 'closed' ? (lang === 'zh' ? '正常' : 'OK')
                        : g.circuit_state === 'open' ? (lang === 'zh' ? '已熔断' : 'Tripped')
                        : (lang === 'zh' ? '探测中' : 'Probing')}
                    </Badge>
                  </Group>
                  <Text size="10px" c="dimmed">
                    {lang === 'zh' ? '本时预算：' : 'Hourly: '}{g.window_count}/{g.hourly_budget}
                    {' · '}{lang === 'zh' ? '利用率' : 'util'} {Math.round((g.utilization || 0) * 100)}%
                  </Text>
                  {g.underused_warning && (
                    <Text size="10px" c="yellow">{lang === 'zh' ? '⚠ 利用率偏低，可能保护过度' : '⚠ Under-used — possibly over-protecting'}</Text>
                  )}
                  {g.stale_yield_warning && (
                    <Text size="10px" c="orange">{lang === 'zh' ? '⚠ 一周无产出，检查授权' : '⚠ No yield in a week — check auth'}</Text>
                  )}
                </Paper>
              ))}
            </SimpleGrid>
          )}
        </Stack>
      </Paper>

      {/* Language Selector */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <Stack gap="md">
          <Group gap="xs">
            <SettingsIcon size={18} className="text-indigo-400" />
            <Text size="md" fw={700} className="title-text-color">{t('set_lang')}</Text>
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
              input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black', maxWidth: 300 },
              dropdown: { background: isDark ? '#1a1b1e' : '#ffffff', border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)'}` }
            }}
          />
        </Stack>
      </Paper>

      {/* System Mode Switcher */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <Stack gap="md">
          <Group gap="xs">
            <SettingsIcon size={18} className="text-indigo-400" />
            <Text size="md" fw={700} className="title-text-color">{t('set_mode_title')}</Text>
          </Group>
          <Text size="xs" c="dimmed">{t('set_mode_desc')}</Text>
          <Select
            label={t('set_mode_label')}
            data={[
              { value: 'ai_fusion', label: lang === 'zh' ? 'AI 智能融合提炼模式 (AI Mode)' : 'AI Intelligence Fusion Mode' },
              { value: 'pure_rss', label: lang === 'zh' ? '纯本地 RSS 订阅阅读模式 (Local Mode)' : 'Pure Local RSS Reader Mode' }
            ]}
            value={appMode}
            onChange={async (value) => {
              if (value) {
                const targetMode = value as 'ai_fusion' | 'pure_rss';
                try {
                  await client.post('/settings/app-mode', { app_mode: targetMode });
                  setAppMode(targetMode);
                  localStorage.setItem('app_mode', targetMode);
                  alert(t('set_mode_switch_success'));
                } catch (err: any) {
                  alert("Failed to switch app mode: " + err.message);
                }
              }
            }}
            styles={{ 
              input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black', maxWidth: 400 },
              dropdown: { background: isDark ? '#1a1b1e' : '#ffffff', border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)'}` }
            }}
          />
          <Button 
            variant="light" 
            color="indigo" 
            size="xs"
            onClick={() => setOnboardingOpen(true)}
            style={{ alignSelf: 'flex-start' }}
          >
            {t('set_mode_reopen_guide')}
          </Button>
        </Stack>
      </Paper>

      {/* Enable Developer Mode Toggle */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <Stack gap="md">
          <Group gap="xs">
            <ShieldAlert size={18} className="text-indigo-400" />
            <Text size="md" fw={700} className="title-text-color">{t('set_developer_mode')}</Text>
          </Group>
          <Text size="xs" c="dimmed">启用开发人员模式将解锁 Pipeline Trace 诊断分析弹窗，并在订阅和探测配置时展开底层工程策略设置。 (Enables diagnostics traces and engineering settings accordion)</Text>
          <Checkbox
            label="启用开发人员模式 (Enable Developer Mode)"
            checked={devMode}
            onChange={(e) => {
              const checked = e.currentTarget.checked;
              setDevMode(checked);
              localStorage.setItem('developer_mode', checked ? 'true' : 'false');
              window.dispatchEvent(new Event('developer_mode_changed'));
            }}
            styles={{ label: { color: isDark ? 'white' : 'black' } }}
          />
        </Stack>
      </Paper>

      {/* API Configuration */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <form onSubmit={handleSaveApiKey}>
          <Stack gap="md">
            <Group gap="xs">
              <SettingsIcon size={18} className="text-indigo-400" />
              <Text size="md" fw={700} className="title-text-color">{t('set_api')}</Text>
            </Group>
            <Text size="xs" c="dimmed">{t('set_api_desc')}</Text>
            {appMode === 'pure_rss' ? (
              <Paper p="sm" radius="xs" style={{ background: isDark ? 'rgba(255, 169, 0, 0.1)' : '#fff9db', border: `1px solid ${isDark ? 'rgba(255, 169, 0, 0.2)' : '#ffe066'}` }}>
                <Text size="xs" style={{ color: isDark ? '#ffe066' : '#f59f00', display: 'flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
                  <ShieldAlert size={14} style={{ flexShrink: 0 }} />
                  {t('set_api_disabled_mode')}
                </Text>
              </Paper>
            ) : (
              <>
                <TextInput
                  required={!hasApiKey}
                  placeholder={hasApiKey ? `${t('set_auth_status_ok')} (${maskedApiKey})` : t('set_api_ph')}
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  styles={{ input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black', maxWidth: 500 } }}
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
              </>
            )}
          </Stack>
        </form>
      </Paper>

      {/* Model & Backend selection */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <Stack gap="md">
          <Text size="md" fw={700} className="title-text-color">模型与后端 (Model & Backend)</Text>
          <Text size="xs" c="dimmed">
            选择 AI 后端与生成/嵌入模型。可指向本地模型（Ollama / LM Studio / vLLM：选「OpenAI 兼容」+ 填 Base URL），隐私优先、免 token 费用。留空则用该后端默认模型。
          </Text>
          <Select
            label="后端 (Provider)"
            data={[
              { value: 'gemini', label: 'Gemini（云端）' },
              { value: 'openai_compatible', label: 'OpenAI 兼容 / 本地（Ollama · LM Studio · vLLM）' },
            ]}
            value={llmProvider}
            onChange={(v) => setLlmProvider(v || 'gemini')}
            styles={{ input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black', maxWidth: 500 } }}
          />
          {llmProvider === 'openai_compatible' && (
            <TextInput
              label="Base URL"
              placeholder="http://localhost:11434/v1"
              value={llmBaseUrl}
              onChange={(e) => setLlmBaseUrl(e.target.value)}
              styles={{ input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black', maxWidth: 500 } }}
            />
          )}
          <TextInput
            label="生成模型 (Generation Model)"
            placeholder={llmDefaults[llmProvider]?.model || '默认'}
            value={llmModel}
            onChange={(e) => setLlmModel(e.target.value)}
            styles={{ input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black', maxWidth: 500 } }}
          />
          <TextInput
            label="嵌入模型 (Embedding Model)"
            placeholder={llmDefaults[llmProvider]?.embed_model || '默认'}
            value={llmEmbedModel}
            onChange={(e) => setLlmEmbedModel(e.target.value)}
            styles={{ input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black', maxWidth: 500 } }}
          />
          <Button color="indigo" loading={savingLlm} leftSection={<Save size={14} />} onClick={handleSaveLlm} style={{ alignSelf: 'flex-start' }}>
            保存模型配置
          </Button>
        </Stack>
      </Paper>

      {/* Database & Storage Management */}
      {dbStatus && (
        <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
          <Stack gap="md">
            <Group gap="xs">
              <Database size={18} className="text-indigo-400" />
              <Text size="md" fw={700} className="title-text-color">{t('set_db_title')}</Text>
            </Group>
            <Text size="xs" c="dimmed">{t('set_db_desc')}</Text>

            {/* Warning Banner */}
            {(dbStatus.is_over_size_limit || dbStatus.expired_articles_count > 0) && (
              <Paper p="md" radius="md" style={{ 
                background: isDark ? 'rgba(240, 62, 62, 0.15)' : '#fff5f5', 
                border: `1px solid ${isDark ? 'rgba(240, 62, 62, 0.3)' : '#ffe3e3'}` 
              }}>
                <Stack gap="sm">
                  <Group gap="xs">
                    <AlertTriangle color="var(--mantine-color-red-6)" size={16} />
                    <Text size="sm" c="red" fw={600}>
                      {formatWarnBanner(t('set_db_warn_banner'), dbStatus.db_size_mb, dbStatus.max_size_mb, dbStatus.expired_articles_count)}
                    </Text>
                  </Group>
                  <Button 
                    size="xs" 
                    color="red" 
                    loading={cleaningDb} 
                    onClick={handleDbCleanup}
                    style={{ alignSelf: 'flex-start' }}
                  >
                    {t('set_db_clean_now')}
                  </Button>
                </Stack>
              </Paper>
            )}

            {/* Storage Board */}
            <Paper withBorder p="sm" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.005)' : '#f8f9fa' }}>
              <Stack gap="xs">
                <Text size="xs" fw={700} c="dimmed">{t('set_db_size')}</Text>
                <Text size="xl" fw={800} className="title-text-color">{dbStatus.db_size_mb.toFixed(2)} MB</Text>
                <Divider my="xs" style={{ borderColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }} />
                <SimpleGrid cols={{ base: 2, sm: 3, md: 5 }} spacing="xs">
                  <Paper p="xs" radius="xs" withBorder style={{ textAlign: 'center', background: isDark ? 'rgba(0,0,0,0.2)' : '#ffffff' }}>
                    <Text size="xs" c="dimmed">{t('set_db_col_raw_articles')}</Text>
                    <Text size="md" fw={700} className="title-text-color">{dbStatus.row_counts.raw_articles}</Text>
                  </Paper>
                  <Paper p="xs" radius="xs" withBorder style={{ textAlign: 'center', background: isDark ? 'rgba(0,0,0,0.2)' : '#ffffff' }}>
                    <Text size="xs" c="dimmed">{t('set_db_col_intel_reports')}</Text>
                    <Text size="md" fw={700} className="title-text-color">{dbStatus.row_counts.intel_reports}</Text>
                  </Paper>
                  <Paper p="xs" radius="xs" withBorder style={{ textAlign: 'center', background: isDark ? 'rgba(0,0,0,0.2)' : '#ffffff' }}>
                    <Text size="xs" c="dimmed">{t('set_db_col_daily_briefings')}</Text>
                    <Text size="md" fw={700} className="title-text-color">{dbStatus.row_counts.daily_briefings}</Text>
                  </Paper>
                  <Paper p="xs" radius="xs" withBorder style={{ textAlign: 'center', background: isDark ? 'rgba(0,0,0,0.2)' : '#ffffff' }}>
                    <Text size="xs" c="dimmed">{t('set_db_col_trend_alerts')}</Text>
                    <Text size="md" fw={700} className="title-text-color">{dbStatus.row_counts.trend_alerts}</Text>
                  </Paper>
                  <Paper p="xs" radius="xs" withBorder style={{ textAlign: 'center', background: isDark ? 'rgba(0,0,0,0.2)' : '#ffffff' }}>
                    <Text size="xs" c="dimmed">{t('set_db_col_token_usages')}</Text>
                    <Text size="md" fw={700} className="title-text-color">{dbStatus.row_counts.token_usages}</Text>
                  </Paper>
                </SimpleGrid>
              </Stack>
            </Paper>

            {/* Cleanup Settings Form */}
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
              <Select
                label={t('set_db_retention')}
                data={[
                  { value: '0', label: lang === 'zh' ? '从不清理' : 'Never' },
                  { value: '7', label: lang === 'zh' ? '7 天' : '7 Days' },
                  { value: '15', label: lang === 'zh' ? '15 天' : '15 Days' },
                  { value: '30', label: lang === 'zh' ? '30 天' : '30 Days' },
                  { value: '60', label: lang === 'zh' ? '60 天' : '60 Days' },
                  { value: '90', label: lang === 'zh' ? '90 天' : '90 Days' },
                  { value: '180', label: lang === 'zh' ? '180 天' : '180 Days' },
                  { value: '365', label: lang === 'zh' ? '1 年' : '1 Year' }
                ]}
                value={retentionDays}
                onChange={(val) => val && setRetentionDays(val)}
                styles={{ 
                  input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black' },
                  dropdown: { background: isDark ? '#1a1b1e' : '#ffffff', border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)'}` }
                }}
              />
              <Select
                label={t('set_db_max_size')}
                data={[
                  { value: '0', label: lang === 'zh' ? '无限制' : 'Unlimited' },
                  { value: '100', label: '100 MB' },
                  { value: '250', label: '250 MB' },
                  { value: '500', label: '500 MB' },
                  { value: '1000', label: '1 GB (1000 MB)' },
                  { value: '2000', label: '2 GB (2000 MB)' },
                  { value: '5000', label: '5 GB (5000 MB)' }
                ]}
                value={maxSizeMb}
                onChange={(val) => val && setMaxSizeMb(val)}
                styles={{ 
                  input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black' },
                  dropdown: { background: isDark ? '#1a1b1e' : '#ffffff', border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)'}` }
                }}
              />
            </SimpleGrid>

            <Group gap="xs" style={{ alignSelf: 'flex-start' }}>
              <Button 
                size="sm" 
                color="indigo" 
                loading={savingDbConfig} 
                onClick={handleSaveDbSettings}
                leftSection={<Save size={14} />}
              >
                {t('set_db_save_btn')}
              </Button>
              <Button 
                size="sm" 
                variant="light" 
                color="indigo" 
                loading={cleaningDb} 
                onClick={handleDbCleanup}
              >
                {t('set_db_vacuum_btn')}
              </Button>
            </Group>

            <Divider my="xs" style={{ borderColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.08)' }} />

            {/* Database Engine Switcher */}
            <Stack gap="sm">
              <Stack gap={2}>
                <Text size="sm" fw={700} className="title-text-color">{t('set_db_engine_title')}</Text>
                <Text size="xs" c="dimmed">{t('set_db_engine_desc')}</Text>
              </Stack>

              <Select
                label={t('set_db_engine_type')}
                data={[
                  { value: 'sqlite', label: 'SQLite (Default, Zero-config Local)' },
                  { value: 'postgres', label: 'PostgreSQL (High Concurrency Database Server)' }
                ]}
                value={dbEngineType}
                onChange={(val) => val && setDbEngineType(val as 'sqlite' | 'postgres')}
                styles={{ 
                  input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#f1f3f5', color: isDark ? 'white' : 'black', maxWidth: 400 },
                  dropdown: { background: isDark ? '#1a1b1e' : '#ffffff', border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)'}` }
                }}
              />

              {dbEngineType === 'postgres' && (
                <Paper withBorder p="md" radius="sm" style={{ background: isDark ? 'rgba(0,0,0,0.1)' : '#f8f9fa', maxWidth: 600 }}>
                  <Stack gap="sm">
                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                      <TextInput
                        required
                        label={t('set_db_host')}
                        placeholder="localhost"
                        value={pgHost}
                        onChange={(e) => setPgHost(e.target.value)}
                        styles={{ input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#ffffff', color: isDark ? 'white' : 'black' } }}
                      />
                      <TextInput
                        required
                        label={t('set_db_port')}
                        placeholder="5432"
                        value={pgPort}
                        onChange={(e) => setPgPort(e.target.value)}
                        styles={{ input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#ffffff', color: isDark ? 'white' : 'black' } }}
                      />
                    </SimpleGrid>
                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                      <TextInput
                        required
                        label={t('set_db_user')}
                        placeholder="postgres"
                        value={pgUser}
                        onChange={(e) => setPgUser(e.target.value)}
                        styles={{ input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#ffffff', color: isDark ? 'white' : 'black' } }}
                      />
                      <TextInput
                        required
                        label={t('set_db_pass')}
                        type="password"
                        placeholder="password"
                        value={pgPass}
                        onChange={(e) => setPgPass(e.target.value)}
                        styles={{ input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#ffffff', color: isDark ? 'white' : 'black' } }}
                      />
                    </SimpleGrid>
                    <TextInput
                      required
                      label={t('set_db_name')}
                      placeholder="major_rss"
                      value={pgName}
                      onChange={(e) => setPgName(e.target.value)}
                      styles={{ input: { background: isDark ? 'rgba(255,255,255,0.05)' : '#ffffff', color: isDark ? 'white' : 'black' } }}
                    />
                    <Button 
                      size="xs" 
                      variant="subtle" 
                      color="indigo" 
                      loading={testingConn} 
                      onClick={handleTestConnection}
                      style={{ alignSelf: 'flex-start' }}
                    >
                      {t('set_db_test_conn')}
                    </Button>
                  </Stack>
                </Paper>
              )}

              <Button 
                size="sm" 
                color="indigo" 
                loading={switchingEngine} 
                onClick={handleSwitchEngine}
                style={{ alignSelf: 'flex-start' }}
              >
                {t('set_db_switch_btn')}
              </Button>
            </Stack>
          </Stack>
        </Paper>
      )}

      {/* Pipeline Logs */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <Stack gap="md">
          <Group justify="space-between">
            <Group gap="xs">
              <Terminal size={18} className="text-indigo-400" />
              <Text size="md" fw={700} className="title-text-color">{t('set_logs_title')}</Text>
            </Group>
            <Text size="xs" c="dimmed">{t('set_logs_desc')}</Text>
          </Group>
          <Divider style={{ borderColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.08)' }} />
          <ScrollArea h="30vh" p="md" style={{ background: isDark ? 'rgba(0,0,0,0.3)' : '#f1f3f5', borderRadius: 8 }}>
            <Stack gap="xs" style={{ fontFamily: 'monospace' }}>
              {logs.length === 0 ? (
                <Text size="xs" c="dimmed" ta="center" py="lg">{t('set_no_logs')}</Text>
              ) : (
                logs.map((log) => (
                  <Text key={log.id} size="xs" style={{ lineHeight: 1.6, color: isDark ? '#d8dee9' : '#2e3440' }}>
                    <span style={{ color: '#88c0d0' }}>[{new Date(log.updated_at).toLocaleTimeString()}]</span>{' '}
                    <span style={{ color: '#ebcb8b' }}>[{log.tracker_name}]</span>{' '}
                    <span style={{ color: '#8fbcbb', fontWeight: 700 }}>{log.action_type}</span>{' '}
                    <span style={{ color: isDark ? '#e5e9f0' : '#4c566a' }}>- {log.detail}</span>
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
