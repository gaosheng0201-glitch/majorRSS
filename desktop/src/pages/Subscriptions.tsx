import { useEffect, useState } from 'react';
import { 
  Text, Table, Group, Stack, Button, Badge, ActionIcon,
  Modal, TextInput, Select, NumberInput, Textarea, Paper, Menu,
  Tabs, Card, ScrollArea, Accordion, Switch, SegmentedControl, Stepper, Alert, SimpleGrid, Loader
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { 
  Plus, Play, Trash2, Power, MoreVertical, Edit, Eye, Rss,
  Activity, Clock, FileText, Download, RefreshCw, AlertCircle
} from 'lucide-react';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';

interface Tracker {
  id: number;
  name: string;
  tracker_type: string;
  target: string;
  tier: number;
  radar_section: string;
  is_active: boolean;
  fetch_interval_minutes: number;
  prompt_override?: string;
  source_intent?: string;
  fetch_policy?: string;
  auth_profile_id?: number;
  created_at: string;
  last_scraped_at?: string;
}

interface Subscription {
  id: number;
  name: string;
  target_url: string;
  is_active: boolean;
  fetch_interval_minutes: number;
  diff_policy?: string;
  created_at: string;
  last_scraped_at?: string;
  last_status: string;
}

interface SubscriptionUpdate {
  id: number;
  subscription_id: number;
  subscription_name: string;
  diff_text: string;
  is_read: boolean;
  llm_summary?: string;
  created_at: string;
}

interface AuthProfile {
  id: number;
  platform: string;
  display_name: string;
}

interface PipelineEvent {
  id: number;
  run_id: number;
  step_index: number;
  created_at: string;
  stage: string;
  route_id?: string;
  adapter?: string;
  input_data?: string;
  output_summary?: string;
  status: string;
  duration_ms: number;
  error?: string;
}

interface PipelineRun {
  id: number;
  tracker_id?: number;
  subscription_id?: number;
  status: string;
  normalized_intent?: string;
  started_at: string;
  finished_at?: string;
  total_routes: number;
  total_items: number;
  accepted_items: number;
  error_summary?: string;
  cost_flag_browser: boolean;
  cost_flag_llm: boolean;
  events?: PipelineEvent[];
}

export default function Subscriptions() {
  const { t } = useLanguage();
  const [activeTab, setActiveTab] = useState<string>('feeds_accounts');
  const [trackers, setTrackers] = useState<Tracker[]>([]);
  const [monitors, setMonitors] = useState<Subscription[]>([]);
  const [updates, setUpdates] = useState<SubscriptionUpdate[]>([]);
  const [opened, { open, close }] = useDisclosure(false);
  const [editingItem, setEditingItem] = useState<{ type: 'tracker' | 'monitor'; id: number } | null>(null);

  // Developer Mode state
  const [devMode, setDevMode] = useState(() => localStorage.getItem('developer_mode') === 'true');

  // Tracing Modal states
  const [traceOpened, { open: openTrace, close: closeTrace }] = useDisclosure(false);
  const [tracingItem, setTracingItem] = useState<{ type: 'tracker' | 'monitor'; id: number; name: string } | null>(null);
  const [traceRuns, setTraceRuns] = useState<PipelineRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<PipelineRun | null>(null);
  const [loadingTraces, setLoadingTraces] = useState(false);
  const [runningTrace, setRunningTrace] = useState(false);

  // Stepper Wizard states
  const [activeStep, setActiveStep] = useState(0);

  // Common UI configs
  const isDark = true;
  const modalInputStyles = {
    input: {
      background: isDark ? 'rgba(255, 255, 255, 0.05)' : '#f8f9fa',
      color: isDark ? 'white' : '#1a1b1e',
      border: isDark ? '1px solid rgba(255, 255, 255, 0.1)' : '1px solid rgba(0, 0, 0, 0.15)'
    },
    label: {
      color: isDark ? 'white' : '#1a1b1e'
    }
  };

  // Auth Profiles
  const [authProfiles, setAuthProfiles] = useState<AuthProfile[]>([]);
  
  // Wizard state: type selector
  const [subType, setSubType] = useState<'rss' | 'account' | 'diff'>('rss');

  // Form states
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [section, setSection] = useState('Frontier Outpost');
  const [interval, setIntervalVal] = useState<number | string>(60);
  
  // Filter states
  const [keepKeywords, setKeepKeywords] = useState('');
  const [ignoreKeywords, setIgnoreKeywords] = useState('');

  // Webpage Monitor Scope Target
  const [scopeType, setScopeType] = useState<'text' | 'price' | 'custom'>('text');

  // Page Diff Advanced Settings
  const [extractSelector, setExtractSelector] = useState('');
  const [ignoreSelector, setIgnoreSelector] = useState('');
  const [jsRendering, setJsRendering] = useState(false);

  // Feed Advanced Settings
  const [promptOverride, setPromptOverride] = useState('');
  const [urlStrategy, setUrlStrategy] = useState('auto');
  const [maxItems, setMaxItems] = useState<number | string>(20);
  const [maxDays, setMaxDays] = useState<number | string>(7);
  const [authProfileId, setAuthProfileId] = useState<string | null>(null);

  // Connection Test / Preview state
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const fetchData = async () => {
    try {
      const [trackersRes, monitorsRes, updatesRes, authRes] = await Promise.all([
        client.get<Tracker[]>('/trackers/'),
        client.get<Subscription[]>('/monitors/'),
        client.get<SubscriptionUpdate[]>('/monitors/updates'),
        client.get<AuthProfile[]>('/auth/profiles/')
      ]);
      setTrackers(trackersRes.data.filter(t => t.source_intent === 'RSS_FEED' || t.source_intent === 'ACCOUNT_TRACKING'));
      setMonitors(monitorsRes.data);
      setUpdates(updatesRes.data);
      setAuthProfiles(authRes.data);
    } catch (err) {
      console.error("Failed to fetch subscriptions data:", err);
    }
  };

  useEffect(() => {
    fetchData();

    const handleDevModeChange = () => {
      setDevMode(localStorage.getItem('developer_mode') === 'true');
    };
    window.addEventListener('developer_mode_changed', handleDevModeChange);
    return () => window.removeEventListener('developer_mode_changed', handleDevModeChange);
  }, []);

  // Recommend auth profile for accounts
  useEffect(() => {
    if (subType === 'account' && target) {
      const lowerTarget = target.toLowerCase().trim();
      let platform = '';
      if (lowerTarget.startsWith('bilibili:') || lowerTarget.match(/^\d+$/)) {
        platform = 'bilibili';
      } else if (lowerTarget.startsWith('twitter:') || lowerTarget.startsWith('x:') || lowerTarget.startsWith('@') || lowerTarget.includes('twitter.com') || lowerTarget.includes('x.com')) {
        platform = 'twitter';
      } else if (lowerTarget.startsWith('weibo:') || lowerTarget.includes('weibo.com')) {
        platform = 'weibo';
      }

      if (platform) {
        const matchingProfile = authProfiles.find(p => p.platform === platform);
        if (matchingProfile) {
          setAuthProfileId(String(matchingProfile.id));
        }
      }
    }
  }, [target, subType, authProfiles]);

  // Handle monitor scope presets mapping
  useEffect(() => {
    if (scopeType === 'text') {
      setExtractSelector('');
    } else if (scopeType === 'price') {
      setExtractSelector('.price, #price, .amount, [class*="price"], [id*="price"]');
    }
  }, [scopeType]);

  const handleToggleTracker = async (id: number) => {
    try {
      const res = await client.post<Tracker>(`/trackers/${id}/toggle`);
      setTrackers(trackers.map(t => t.id === id ? res.data : t));
    } catch (err) {
      alert("Failed to toggle tracker status");
    }
  };

  const handleToggleMonitor = async (id: number) => {
    try {
      const res = await client.post<Subscription>(`/monitors/${id}/toggle`);
      setMonitors(monitors.map(m => m.id === id ? res.data : m));
    } catch (err) {
      alert("Failed to toggle monitor status");
    }
  };

  const handleRunTracker = async (id: number) => {
    try {
      await client.post(`/trackers/${id}/run`);
      alert("Scraping task started in background");
    } catch (err) {
      alert("Failed to execute scraping task");
    }
  };

  const handleRunMonitor = async (id: number) => {
    try {
      await client.post(`/monitors/${id}/run-trace`);
      alert("Diff check completed!");
      fetchData();
    } catch (err) {
      alert("Failed to execute webpage diff check");
    }
  };

  const handleDeleteTracker = async (id: number) => {
    if (!window.confirm("Are you sure you want to delete this subscription?")) return;
    try {
      await client.delete(`/trackers/${id}`);
      setTrackers(trackers.filter(t => t.id !== id));
    } catch (err) {
      alert("Failed to delete subscription");
    }
  };

  const handleDeleteMonitor = async (id: number) => {
    if (!window.confirm("Are you sure you want to delete this page monitor?")) return;
    try {
      await client.delete(`/monitors/${id}`);
      setMonitors(monitors.filter(m => m.id !== id));
    } catch (err) {
      alert("Failed to delete page monitor");
    }
  };

  const handleMarkAsRead = async (updateId: number) => {
    try {
      await client.post(`/monitors/updates/${updateId}/read`);
      setUpdates(updates.map(u => u.id === updateId ? { ...u, is_read: true } : u));
    } catch (err) {
      alert("Failed to mark update as read");
    }
  };

  const handleStartEdit = (item: any, type: 'tracker' | 'monitor') => {
    setEditingItem({ type, id: item.id });
    setName(item.name);
    setIntervalVal(item.fetch_interval_minutes);
    setTestResult(null);
    setActiveStep(0);

    if (type === 'tracker') {
      const tr = item as Tracker;
      setSubType(tr.source_intent === 'ACCOUNT_TRACKING' ? 'account' : 'rss');
      setTarget(tr.target.startsWith('[') ? JSON.parse(tr.target).join('\n') : tr.target);
      setSection(tr.radar_section);
      setPromptOverride(tr.prompt_override || '');
      setAuthProfileId(tr.auth_profile_id ? String(tr.auth_profile_id) : null);

      if (tr.fetch_policy) {
        try {
          const p = JSON.parse(tr.fetch_policy);
          setUrlStrategy(p.url_strategy || 'auto');
          setMaxItems(p.max_items_per_route || 20);
          setMaxDays(p.max_days || 7);
          setKeepKeywords(p.keep_keywords ? p.keep_keywords.join('\n') : '');
          setIgnoreKeywords(p.ignore_keywords ? p.ignore_keywords.join('\n') : '');
        } catch {}
      }
    } else {
      const mon = item as Subscription;
      setSubType('diff');
      setTarget(mon.target_url);
      setExtractSelector('');
      setIgnoreSelector('');
      setJsRendering(false);
      setScopeType('text');

      if (mon.diff_policy) {
        try {
          const p = JSON.parse(mon.diff_policy);
          setExtractSelector(p.extract_selector || '');
          setIgnoreSelector(p.ignore_selector || '');
          setJsRendering(p.js_rendering === true);
          setKeepKeywords(p.keep_keywords ? p.keep_keywords.join('\n') : '');
          setIgnoreKeywords(p.ignore_keywords ? p.ignore_keywords.join('\n') : '');
          
          if (p.extract_selector === '.price, #price, .amount, [class*="price"], [id*="price"]') {
            setScopeType('price');
          } else if (p.extract_selector) {
            setScopeType('custom');
          } else {
            setScopeType('text');
          }
        } catch {}
      }
    }
    open();
  };

  const handleClose = () => {
    close();
    setEditingItem(null);
    setName('');
    setTarget('');
    setSection('Frontier Outpost');
    setIntervalVal(60);
    setPromptOverride('');
    setAuthProfileId(null);
    setUrlStrategy('auto');
    setMaxItems(20);
    setMaxDays(7);
    setKeepKeywords('');
    setIgnoreKeywords('');
    setExtractSelector('');
    setIgnoreSelector('');
    setJsRendering(false);
    setScopeType('text');
    setTestResult(null);
    setActiveStep(0);
  };

  // Test connection dry-run
  const testDiffConnection = async () => {
    if (!target) {
      alert("Please fill in the target URL first");
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const policy = JSON.stringify({
        js_rendering: jsRendering,
        extract_selector: extractSelector || null,
        ignore_selector: ignoreSelector || null
      });

      if (subType === 'diff') {
        const res = await client.post('/monitors/test-diff-route-trace', {
          target_url: target,
          diff_policy: policy
        });
        setTestResult(res.data);
      } else {
        // Trackers resolution
        const trPolicy = JSON.stringify({
          url_strategy: urlStrategy,
          max_items_per_route: Number(maxItems),
          max_days: Number(maxDays),
          fallback_enabled: true
        });
        const res = await client.post('/trackers/test-resolve-intent', {
          target: target.includes('\n') ? JSON.stringify(target.split('\n').map(x => x.trim()).filter(Boolean)) : JSON.stringify([target.trim()]),
          source_intent: subType === 'rss' ? 'RSS_FEED' : 'ACCOUNT_TRACKING',
          fetch_policy: trPolicy
        });
        setTestResult(res.data);
      }
    } catch (err: any) {
      setTestResult({
        status: 'FAILED',
        error_summary: err.response?.data?.detail || err.message
      });
    } finally {
      setTesting(false);
    }
  };

  const getNormalizedIntent = () => {
    const keepList = keepKeywords.split('\n').map(x => x.trim()).filter(Boolean);
    const ignoreList = ignoreKeywords.split('\n').map(x => x.trim()).filter(Boolean);

    return JSON.stringify({
      intent_type: subType === 'diff' ? 'page_change_monitor' : subType === 'rss' ? 'single_feed_subscription' : 'single_account_subscription',
      target: target,
      monitor_goal: subType === 'diff' ? (scopeType === 'text' ? 'article_change' : scopeType === 'price' ? 'price_version_change' : 'whole_page_change') : 'none',
      filters: {
        keep: keepList,
        ignore: ignoreList
      },
      frequency_minutes: Number(interval)
    });
  };

  const handleSaveSubmit = async () => {
    if (!name || !target) {
      alert("Please fill in the name and target URL/account");
      return;
    }

    setSubmitting(true);
    const keepList = keepKeywords.split('\n').map(x => x.trim()).filter(Boolean);
    const ignoreList = ignoreKeywords.split('\n').map(x => x.trim()).filter(Boolean);

    try {
      if (subType === 'diff') {
        const payload = {
          name,
          target_url: target,
          fetch_interval_minutes: Number(interval),
          diff_policy: JSON.stringify({
            js_rendering: jsRendering,
            extract_selector: extractSelector || null,
            ignore_selector: ignoreSelector || null,
            keep_keywords: keepList,
            ignore_keywords: ignoreList
          }),
          normalized_intent: getNormalizedIntent()
        };

        if (editingItem && editingItem.type === 'monitor') {
          await client.delete(`/monitors/${editingItem.id}`);
          await client.post('/monitors/', payload);
        } else {
          await client.post('/monitors/', payload);
        }
      } else {
        // Feeds or Accounts
        let finalTarget = target;
        if (target.includes('\n')) {
          finalTarget = JSON.stringify(target.split('\n').map(x => x.trim()).filter(Boolean));
        } else if (!target.startsWith('[')) {
          finalTarget = JSON.stringify([target.trim()]);
        }

        const policy = JSON.stringify({
          url_strategy: urlStrategy,
          max_items_per_route: Number(maxItems),
          max_days: Number(maxDays),
          fallback_enabled: true,
          keep_keywords: keepList,
          ignore_keywords: ignoreList
        });

        const payload = {
          name,
          tracker_type: subType === 'rss' ? 'URL' : 'ACCOUNT',
          target: finalTarget,
          tier: urlStrategy === 'agentic' ? 3 : 1,
          radar_section: section,
          fetch_interval_minutes: Number(interval),
          prompt_override: promptOverride || null,
          source_intent: subType === 'rss' ? 'RSS_FEED' : 'ACCOUNT_TRACKING',
          fetch_policy: policy,
          auth_profile_id: authProfileId ? Number(authProfileId) : null,
          normalized_intent: getNormalizedIntent()
        };

        if (editingItem && editingItem.type === 'tracker') {
          await client.put(`/trackers/${editingItem.id}`, payload);
        } else {
          await client.post('/trackers/', payload);
        }
      }

      handleClose();
      fetchData();
    } catch (err: any) {
      alert("Failed to save subscription: " + (err.response?.data?.detail || err.message));
    } finally {
      setSubmitting(false);
    }
  };

  const getDisplayTarget = (tr: Tracker) => {
    try {
      const data = JSON.parse(tr.target);
      if (Array.isArray(data)) {
        return data.length === 1 ? data[0] : `${data.length} sources`;
      }
      return tr.target;
    } catch {
      return tr.target;
    }
  };

  // Tracing Modal actions
  const handleOpenTrace = async (item: any, type: 'tracker' | 'monitor') => {
    setTracingItem({ type, id: item.id, name: item.name });
    setTraceRuns([]);
    setSelectedRun(null);
    openTrace();
    setLoadingTraces(true);
    
    try {
      const endpoint = type === 'tracker' ? `/trackers/${item.id}/traces` : `/monitors/${item.id}/traces`;
      const res = await client.get<PipelineRun[]>(endpoint);
      setTraceRuns(res.data);
      if (res.data.length > 0) {
        setSelectedRun(res.data[0]);
      }
    } catch (err) {
      console.error("Failed to load traces:", err);
    } finally {
      setLoadingTraces(false);
    }
  };

  const handleRunTraceNow = async () => {
    if (!tracingItem) return;
    setRunningTrace(true);
    try {
      const endpoint = tracingItem.type === 'tracker' ? `/trackers/${tracingItem.id}/run-trace` : `/monitors/${tracingItem.id}/run-trace`;
      const res = await client.post<PipelineRun>(endpoint);
      
      const freshEndpoint = tracingItem.type === 'tracker' ? `/trackers/${tracingItem.id}/traces` : `/monitors/${tracingItem.id}/traces`;
      const freshRuns = await client.get<PipelineRun[]>(freshEndpoint);
      setTraceRuns(freshRuns.data);
      
      const matched = freshRuns.data.find(r => r.id === res.data.id) || res.data;
      setSelectedRun(matched);
      alert("Pipeline run trace completed!");
      fetchData();
    } catch (err: any) {
      alert("Pipeline trace run failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setRunningTrace(false);
    }
  };

  const handleExportTrace = async (runId: number) => {
    if (!tracingItem) return;
    try {
      const endpoint = tracingItem.type === 'tracker' ? `/trackers/traces/${runId}/export` : `/monitors/traces/${runId}/export`;
      const res = await client.get(endpoint);
      const fileBlob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(fileBlob);
      link.download = `monitor_run_${runId}_export.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err: any) {
      alert("Failed to export trace logs: " + err.message);
    }
  };

  const handleNextStep = () => {
    if (activeStep === 0) {
      if (!name) {
        alert("Please enter a name for this subscription");
        return;
      }
      if (!target) {
        alert("Please enter target link/account");
        return;
      }
    }
    setActiveStep(prev => prev + 1);
  };

  const handlePrevStep = () => {
    setActiveStep(prev => prev - 1);
  };

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Stack gap={0}>
          <Text size="xl" fw={700} className="title-text-color">{t('nav_monitors') || "订阅管理"}</Text>
          <Text size="sm" c="dimmed">基于意图的订阅管理：稳定监听已知的新闻博客 RSS、社交账号与特定网页的变动对比。 (Ingestion & Change Monitoring Hub)</Text>
        </Stack>
        <Button 
          variant="filled" 
          color="indigo" 
          leftSection={<Plus size={16} />}
          onClick={() => { handleClose(); open(); }}
        >
          添加订阅源
        </Button>
      </Group>

      <Tabs value={activeTab} onChange={(val) => val && setActiveTab(val)} variant="outline" radius="md">
        <Tabs.List>
          <Tabs.Tab value="feeds_accounts" leftSection={<Rss size={14} />}>
            内容流与账号 (Feeds & Accounts)
          </Tabs.Tab>
          <Tabs.Tab value="page_diff" leftSection={<Eye size={14} />}>
            网页变动监控 (Page Diff Monitors)
          </Tabs.Tab>
        </Tabs.List>

        {/* Panel 1: Feeds & Accounts */}
        <Tabs.Panel value="feeds_accounts" pt="md">
          <Paper withBorder radius="md" style={{ background: 'rgba(255,255,255,0.01)', overflow: 'hidden' }}>
            <Table verticalSpacing="md" horizontalSpacing="lg" highlightOnHover style={{ color: 'var(--mantine-color-gray-3)' }}>
              <Table.Thead style={{ background: 'rgba(255,255,255,0.02)' }}>
                <Table.Tr>
                  <Table.Th>订阅名称</Table.Th>
                  <Table.Th>订阅类型</Table.Th>
                  <Table.Th>目标源</Table.Th>
                  <Table.Th>雷达版块</Table.Th>
                  <Table.Th>抓取间隔(分)</Table.Th>
                  <Table.Th>状态</Table.Th>
                  <Table.Th>最近更新时间</Table.Th>
                  <Table.Th></Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {trackers.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={8} style={{ textAlign: 'center' }}>
                      <Text c="dimmed" py="lg">无活动内容流订阅</Text>
                    </Table.Td>
                  </Table.Tr>
                ) : (
                  trackers.map((tr) => (
                    <Table.Tr key={tr.id}>
                      <Table.Td fw={700} className="title-text-color">{tr.name}</Table.Td>
                      <Table.Td>
                        <Badge variant="light" color={tr.source_intent === 'ACCOUNT_TRACKING' ? 'cyan' : 'indigo'}>
                          {tr.source_intent === 'ACCOUNT_TRACKING' ? '社交账号' : 'RSS / Feeds'}
                        </Badge>
                      </Table.Td>
                      <Table.Td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {getDisplayTarget(tr)}
                      </Table.Td>
                      <Table.Td>{tr.radar_section}</Table.Td>
                      <Table.Td>{tr.fetch_interval_minutes} 分钟</Table.Td>
                      <Table.Td>
                        <Badge color={tr.is_active ? 'teal' : 'red'} variant="dot">
                          {tr.is_active ? '活动' : '已暂停'}
                        </Badge>
                      </Table.Td>
                      <Table.Td style={{ fontSize: 'var(--mantine-font-size-xs)' }}>
                        {tr.last_scraped_at ? new Date(tr.last_scraped_at).toLocaleString() : '从不'}
                      </Table.Td>
                      <Table.Td>
                        <Group gap="xs" justify="flex-end">
                          <ActionIcon 
                            variant="subtle" 
                            color="teal" 
                            title="立即运行"
                            onClick={() => handleRunTracker(tr.id)}
                          >
                            <Play size={16} />
                          </ActionIcon>
                          
                          {devMode && (
                            <ActionIcon
                              variant="subtle"
                              color="indigo"
                              title="管道诊断 (Pipeline Trace)"
                              onClick={() => handleOpenTrace(tr, 'tracker')}
                            >
                              <Activity size={16} />
                            </ActionIcon>
                          )}
                          
                          <Menu position="bottom-end" shadow="md">
                            <Menu.Target>
                              <ActionIcon variant="subtle" color="gray">
                                <MoreVertical size={16} />
                              </ActionIcon>
                            </Menu.Target>
                            <Menu.Dropdown style={{ background: 'rgba(20,20,20,0.95)', border: '1px solid rgba(255,255,255,0.1)' }}>
                              <Menu.Item 
                                leftSection={<Edit size={14} />} 
                                onClick={() => handleStartEdit(tr, 'tracker')}
                                style={{ color: 'white' }}
                              >
                                编辑订阅
                              </Menu.Item>
                              {devMode && (
                                <Menu.Item
                                  leftSection={<Activity size={14} />}
                                  onClick={() => handleOpenTrace(tr, 'tracker')}
                                  style={{ color: 'white' }}
                                >
                                  诊断 / Trace
                                </Menu.Item>
                              )}
                              <Menu.Item 
                                leftSection={<Power size={14} />} 
                                onClick={() => handleToggleTracker(tr.id)}
                                style={{ color: 'white' }}
                              >
                                {tr.is_active ? '暂停' : '启动'}
                              </Menu.Item>
                              <Menu.Item 
                                leftSection={<Trash2 size={14} />} 
                                color="red"
                                onClick={() => handleDeleteTracker(tr.id)}
                              >
                                删除
                              </Menu.Item>
                            </Menu.Dropdown>
                          </Menu>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))
                )}
              </Table.Tbody>
            </Table>
          </Paper>
        </Tabs.Panel>

        {/* Panel 2: Page Diff Monitors */}
        <Tabs.Panel value="page_diff" pt="md">
          <Stack gap="lg">
            <Paper withBorder radius="md" style={{ background: 'rgba(255,255,255,0.01)', overflow: 'hidden' }}>
              <Table verticalSpacing="md" horizontalSpacing="lg" highlightOnHover style={{ color: 'var(--mantine-color-gray-3)' }}>
                <Table.Thead style={{ background: 'rgba(255,255,255,0.02)' }}>
                  <Table.Tr>
                    <Table.Th>监测名称</Table.Th>
                    <Table.Th>监控网址</Table.Th>
                    <Table.Th>监控频率(分)</Table.Th>
                    <Table.Th>状态</Table.Th>
                    <Table.Th>上次抓取状态</Table.Th>
                    <Table.Th>上次监测时间</Table.Th>
                    <Table.Th></Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {monitors.length === 0 ? (
                    <Table.Tr>
                      <Table.Td colSpan={7} style={{ textAlign: 'center' }}>
                        <Text c="dimmed" py="lg">无网页变动监控任务</Text>
                      </Table.Td>
                    </Table.Tr>
                  ) : (
                    monitors.map((m) => (
                      <Table.Tr key={m.id}>
                        <Table.Td fw={700} className="title-text-color">{m.name}</Table.Td>
                        <Table.Td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {m.target_url}
                        </Table.Td>
                        <Table.Td>{m.fetch_interval_minutes} 分钟</Table.Td>
                        <Table.Td>
                          <Badge color={m.is_active ? 'teal' : 'red'} variant="dot">
                            {m.is_active ? '激活' : '已暂停'}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          <Badge variant="light" color={m.last_status === 'Success' || m.last_status === 'No Changes' || m.last_status === 'Update Detected' ? 'teal' : 'red'}>
                            {m.last_status}
                          </Badge>
                        </Table.Td>
                        <Table.Td style={{ fontSize: 'var(--mantine-font-size-xs)' }}>
                          {m.last_scraped_at ? new Date(m.last_scraped_at).toLocaleString() : '从不'}
                        </Table.Td>
                        <Table.Td>
                          <Group gap="xs" justify="flex-end">
                            <ActionIcon 
                              variant="subtle" 
                              color="teal" 
                              title="立即核对"
                              onClick={() => handleRunMonitor(m.id)}
                            >
                              <Play size={16} />
                            </ActionIcon>

                            {devMode && (
                              <ActionIcon
                                variant="subtle"
                                color="indigo"
                                title="管道诊断 (Pipeline Trace)"
                                onClick={() => handleOpenTrace(m, 'monitor')}
                              >
                                <Activity size={16} />
                              </ActionIcon>
                            )}

                            <Menu position="bottom-end" shadow="md">
                              <Menu.Target>
                                <ActionIcon variant="subtle" color="gray">
                                  <MoreVertical size={16} />
                                </ActionIcon>
                              </Menu.Target>
                              <Menu.Dropdown style={{ background: 'rgba(20,20,20,0.95)', border: '1px solid rgba(255,255,255,0.1)' }}>
                                <Menu.Item 
                                  leftSection={<Edit size={14} />} 
                                  onClick={() => handleStartEdit(m, 'monitor')}
                                  style={{ color: 'white' }}
                                >
                                  编辑配置
                                </Menu.Item>
                                {devMode && (
                                  <Menu.Item
                                    leftSection={<Activity size={14} />}
                                    onClick={() => handleOpenTrace(m, 'monitor')}
                                    style={{ color: 'white' }}
                                  >
                                    诊断 / Trace
                                  </Menu.Item>
                                )}
                                <Menu.Item 
                                  leftSection={<Power size={14} />} 
                                  onClick={() => handleToggleMonitor(m.id)}
                                  style={{ color: 'white' }}
                                >
                                  {m.is_active ? '暂停' : '激活'}
                                </Menu.Item>
                                <Menu.Item 
                                  leftSection={<Trash2 size={14} />} 
                                  color="red"
                                  onClick={() => handleDeleteMonitor(m.id)}
                                >
                                  删除
                                </Menu.Item>
                              </Menu.Dropdown>
                            </Menu>
                          </Group>
                        </Table.Td>
                      </Table.Tr>
                    ))
                  )}
                </Table.Tbody>
              </Table>
            </Paper>

            {/* Updates Stream section */}
            <Stack gap="xs" mt="md">
              <Text size="lg" fw={700} className="title-text-color">变动监控历史流 (Page Diff Updates)</Text>
              <ScrollArea h="40vh" scrollbarSize={6}>
                <Stack gap="md">
                  {updates.length === 0 ? (
                    <Paper withBorder p="xl" radius="md" style={{ background: 'transparent', textAlign: 'center' }}>
                      <Text c="dimmed">尚无网页内容更新通知</Text>
                    </Paper>
                  ) : (
                    updates.map((up) => (
                      <Card 
                        key={up.id} 
                        withBorder 
                        p="md" 
                        radius="md" 
                        style={{ 
                          background: 'rgba(255,255,255,0.015)',
                          opacity: up.is_read ? 0.7 : 1,
                          borderLeft: up.is_read ? 'none' : '3px solid var(--mantine-color-indigo-6)'
                        }}
                      >
                        <Group justify="space-between">
                          <Stack gap={2}>
                            <Group gap="xs">
                              <Text size="sm" fw={700} className="title-text-color">{up.subscription_name}</Text>
                              {!up.is_read && <Badge size="xs" color="indigo">NEW</Badge>}
                            </Group>
                            <Text size="xs" c="dimmed">{new Date(up.created_at).toLocaleString()}</Text>
                          </Stack>
                          
                          {!up.is_read && (
                            <ActionIcon 
                              variant="subtle" 
                              color="indigo" 
                              title="标为已读"
                              onClick={() => handleMarkAsRead(up.id)}
                            >
                              <Eye size={16} />
                            </ActionIcon>
                          )}
                        </Group>

                        <Stack gap="xs" mt="sm">
                          {up.llm_summary ? (
                            <Text size="sm" c="gray.3" style={{ lineHeight: 1.5 }}>
                              <strong>AI 智能变动总结：</strong> {up.llm_summary}
                            </Text>
                          ) : (
                            <Text size="sm" c="gray.3" style={{ fontStyle: 'italic' }}>
                              暂无 AI 生成的变动简报
                            </Text>
                          )}
                          
                          {up.diff_text && (
                            <ScrollArea h={120} p="xs" style={{ background: 'rgba(0,0,0,0.2)', borderRadius: 4 }}>
                              <Text size="xs" style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', color: '#a3be8c' }}>
                                {up.diff_text}
                              </Text>
                            </ScrollArea>
                          )}
                        </Stack>
                      </Card>
                    ))
                  )}
                </Stack>
              </ScrollArea>
            </Stack>
          </Stack>
        </Tabs.Panel>
      </Tabs>

      {/* Unified Add Subscription Modal */}
      <Modal 
        opened={opened} 
        onClose={handleClose} 
        title={editingItem ? "编辑订阅配置" : "添加订阅"}
        size="md"
        centered
        styles={{
          content: { background: 'rgba(25,25,25,0.95)', border: '1px solid rgba(255,255,255,0.1)', color: 'white' },
          header: { background: 'rgba(25,25,25,0.95)', color: 'white' }
        }}
      >
        <Stepper active={activeStep} color="indigo" size="xs">
          {/* Step 1: Select Type & Target */}
          <Stepper.Step label="选择意图" description="基本抓取对象">
            <Stack gap="md" mt="md">
              {!editingItem && (
                <Stack gap="xs">
                  <Text size="xs" fw={600} c="dimmed">订阅类型 (Intent)</Text>
                  <SegmentedControl
                    data={[
                      { label: 'RSS/博客流', value: 'rss' },
                      { label: '社交账号', value: 'account' },
                      { label: '网页变动监测', value: 'diff' }
                    ]}
                    value={subType}
                    onChange={(val) => {
                      setSubType(val as any);
                      if (val === 'diff') setIntervalVal(60);
                      else setIntervalVal(30);
                    }}
                    fullWidth
                  />
                </Stack>
              )}

              <TextInput
                label="订阅名称"
                placeholder={
                  subType === 'rss' ? '例如：NVIDIA 博客' :
                  subType === 'account' ? '例如：极客公园 微博' : '例如：OpenAI 价格页面'
                }
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                styles={modalInputStyles}
              />

              <TextInput
                label={
                  subType === 'rss' ? 'Feed / 博客网址 (Target URL)' :
                  subType === 'account' ? '社交账号标识 (Account ID)' : '目标网址 (Target URL)'
                }
                placeholder={
                  subType === 'rss' ? 'https://example.com/feed.xml' :
                  subType === 'account' ? '@username 或 weibo:123456' : 'https://example.com/pricing'
                }
                required
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                styles={modalInputStyles}
              />

              <NumberInput
                label="抓取/核对频率（分钟）"
                min={5}
                required
                value={Number(interval)}
                onChange={(v) => setIntervalVal(v || 60)}
                styles={modalInputStyles}
              />

              {subType !== 'diff' && (
                <TextInput
                  label="归属雷达板块"
                  placeholder="Frontier Outpost"
                  required
                  value={section}
                  onChange={(e) => setSection(e.target.value)}
                  styles={modalInputStyles}
                />
              )}
            </Stack>
          </Stepper.Step>

          {/* Step 2: Content filtering & monitors scope */}
          <Stepper.Step label="过滤与范围" description="精准过滤噪音">
            <Stack gap="md" mt="md">
              {subType === 'diff' ? (
                <Select
                  label="变动监测范围 (Monitor Goal)"
                  data={[
                    { value: 'text', label: '主要正文 (Smart Article Text - Auto-filtered)' },
                    { value: 'price', label: '价格与数值异动监控 (Price & Numbers Only)' },
                    { value: 'custom', label: '自定义网页节点监控 (Custom CSS Selector)' }
                  ]}
                  value={scopeType}
                  onChange={(val) => val && setScopeType(val as any)}
                  styles={modalInputStyles}
                />
              ) : (
                subType === 'account' && (
                  <Select
                    label="账号关联登录凭证 (Auth Profile)"
                    placeholder="无凭证 (公共匿名拉取)"
                    data={authProfiles.map(p => ({ value: String(p.id), label: `${p.display_name} (${p.platform})` }))}
                    value={authProfileId}
                    onChange={setAuthProfileId}
                    clearable
                    styles={modalInputStyles}
                  />
                )
              )}

              <Textarea
                label="包含以下词时才保留 (只保留包含这些词的内容)"
                placeholder="例如：AI, ASIC (每行一个词)"
                value={keepKeywords}
                onChange={(e) => setKeepKeywords(e.target.value)}
                minRows={2}
                styles={modalInputStyles}
              />

              <Textarea
                label="包含以下词时予以排除 (忽略包含这些词的内容)"
                placeholder="例如：广告, 推广 (每行一个词)"
                value={ignoreKeywords}
                onChange={(e) => setIgnoreKeywords(e.target.value)}
                minRows={2}
                styles={modalInputStyles}
              />

              {/* Developer Accordion */}
              {devMode && (
                <Accordion variant="separated" radius="md" mt="xs" styles={{
                  item: { background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' },
                  control: { color: 'white' }
                }}>
                  <Accordion.Item value="dev_subscription_settings">
                    <Accordion.Control>⚙️ 开发者抓取策略 Override (Developer Overrides)</Accordion.Control>
                    <Accordion.Panel>
                      <Stack gap="sm" pt="xs">
                        {subType === 'diff' ? (
                          <>
                            <TextInput
                              label="自定义网页选择器 (CSS selector)"
                              placeholder="例如: .article-body 或 #main"
                              value={extractSelector}
                              onChange={(e) => setExtractSelector(e.target.value)}
                              styles={modalInputStyles}
                            />
                            <TextInput
                              label="忽略元素选择器 (CSS selector)"
                              placeholder="例如: .comments 或 .ad-box"
                              value={ignoreSelector}
                              onChange={(e) => setIgnoreSelector(e.target.value)}
                              styles={modalInputStyles}
                            />
                            <Switch
                              label="使用无头浏览器动态快照 (JS Rendering)"
                              checked={jsRendering}
                              onChange={(e) => setJsRendering(e.currentTarget.checked)}
                              styles={{ label: { color: 'white' } }}
                            />
                          </>
                        ) : (
                          <>
                            <Select
                              label="抓取嗅探策略 (Probe Strategy)"
                              data={[
                                { value: 'auto', label: '自动嗅探 (Auto)' },
                                { value: 'rss_first', label: '优先 RSS Feeds' },
                                { value: 'agentic', label: '浏览器渲染抓取 (Agentic Scrape)' }
                              ]}
                              value={urlStrategy}
                              onChange={(v) => setUrlStrategy(v || 'auto')}
                              styles={modalInputStyles}
                            />
                            <NumberInput
                              label="单次最大保存数 (Max Items per Route)"
                              min={1}
                              value={Number(maxItems)}
                              onChange={(v) => setMaxItems(Number(v) || 20)}
                              styles={modalInputStyles}
                            />
                            <NumberInput
                              label="数据保存天数 (Max Days)"
                              min={1}
                              value={Number(maxDays)}
                              onChange={(v) => setMaxDays(Number(v) || 7)}
                              styles={modalInputStyles}
                            />
                            <Textarea
                              label="定制 AI 提取 Prompt"
                              placeholder="例如：'仅抽取开源软件发布的资讯'"
                              value={promptOverride}
                              onChange={(e) => setPromptOverride(e.target.value)}
                              styles={modalInputStyles}
                              minRows={2}
                            />
                          </>
                        )}
                      </Stack>
                    </Accordion.Panel>
                  </Accordion.Item>
                </Accordion>
              )}
            </Stack>
          </Stepper.Step>

          {/* Step 3: Test Preview */}
          <Stepper.Step label="试运行" description="连接反馈预览">
            <Stack gap="md" mt="md">
              <Paper withBorder p="md" style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.05)', textAlign: 'center' }}>
                <Text size="xs" mb="md" c="dimmed">
                  试运行探测会动态测试抓取管线，如果静态 HTML 抓取为空，建议在“高级选项”中启用动态快照 (JS Rendering)。
                </Text>
                <Button color="indigo" size="sm" onClick={testDiffConnection} loading={testing}>
                  开始测试拉取连接
                </Button>
              </Paper>

              {testResult && (
                <Stack gap="xs">
                  {subType === 'diff' ? (
                    testResult.ok ? (
                      <>
                        <Badge color="teal" size="xs">测试通过 (SUCCESS)</Badge>
                        <Text size="xs" c="dimmed">
                          提取字符数: {testResult.extracted_text_length}，忽略排除节点数: {testResult.ignored_nodes_count}
                        </Text>
                        <ScrollArea h={120} p="xs" style={{ background: 'rgba(0,0,0,0.3)', borderRadius: 4 }}>
                          <Text size="11px" style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
                            {testResult.sample_text}
                          </Text>
                        </ScrollArea>
                      </>
                    ) : (
                      <>
                        <Badge color="red" size="xs">测试失败 (FAILED)</Badge>
                        <Text size="xs" c="red">{testResult.error_message}</Text>
                      </>
                    )
                  ) : (
                    // Feed / Account test result
                    testResult.error_message ? (
                      <>
                        <Badge color="red" size="xs">测试失败 (FAILED)</Badge>
                        <Text size="xs" c="red">{testResult.error_message}</Text>
                      </>
                    ) : (
                      <>
                        <Badge color="teal" size="xs">测试成功 (SUCCESS) — 共抓取 {testResult.item_count} 条</Badge>
                        <ScrollArea h={120} p="xs" style={{ background: 'rgba(0,0,0,0.3)', borderRadius: 4 }}>
                          <Stack gap={4}>
                            {testResult.sample_titles?.map((title: string, i: number) => (
                              <Text key={i} size="11px" style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                                [{i+1}] {title}
                              </Text>
                            ))}
                          </Stack>
                        </ScrollArea>
                      </>
                    )
                  )}
                </Stack>
              )}
            </Stack>
          </Stepper.Step>
        </Stepper>

        <Group justify="space-between" mt="xl">
          <Button variant="outline" color="gray" onClick={handlePrevStep} disabled={activeStep === 0}>
            上一步
          </Button>
          {activeStep < 2 ? (
            <Button color="indigo" onClick={handleNextStep}>
              下一步
            </Button>
          ) : (
            <Button color="indigo" onClick={handleSaveSubmit} loading={submitting}>
              {editingItem ? '保存订阅配置' : '完成并开启监控'}
            </Button>
          )}
        </Group>
      </Modal>

      {/* Tracing Modal (Developer Diagnostics) */}
      <Modal
        opened={traceOpened}
        onClose={closeTrace}
        title={tracingItem ? `订阅管线诊断与 Trace - ${tracingItem.name}` : '订阅管线 Trace 诊断'}
        size="xl"
        centered
        styles={{
          content: { background: 'rgba(25,25,25,0.98)', border: '1px solid rgba(255,255,255,0.15)', color: 'white' },
          header: { background: 'rgba(25,25,25,0.98)', color: 'white' }
        }}
      >
        <Group justify="space-between" mb="md">
          <Text size="xs" c="dimmed">
            展示订阅网页变动对比或内容流拉取在后台的完整运行分析、耗时拆分与脱敏缓存片段。
          </Text>
          <Group gap="xs">
            <Button 
              size="xs" 
              variant="light" 
              color="indigo" 
              leftSection={<RefreshCw size={12} />} 
              onClick={() => tracingItem && handleOpenTrace(tracingItem, tracingItem.type)}
            >
              刷新历史
            </Button>
            <Button 
              size="xs" 
              color="indigo" 
              leftSection={<Play size={12} />} 
              onClick={handleRunTraceNow} 
              loading={runningTrace}
            >
              立即运行诊断
            </Button>
          </Group>
        </Group>

        {loadingTraces ? (
          <Group justify="center" py="xl">
            <Loader size="md" />
          </Group>
        ) : traceRuns.length === 0 ? (
          <Alert color="blue" icon={<AlertCircle size={16} />}>
            该订阅器尚无历史管道运行记录。您可以点击上方“立即运行诊断”以触发一次新抓取测试。
          </Alert>
        ) : (
          <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
            {/* Left Runs list */}
            <Stack gap="xs" style={{ borderRight: '1px solid rgba(255,255,255,0.08)', paddingRight: '12px' }}>
              <Text size="xs" fw={700}>运行历史 (Runs History)</Text>
              <ScrollArea h={320}>
                <Stack gap="xs">
                  {traceRuns.map(run => (
                    <Paper
                      key={run.id}
                      onClick={() => setSelectedRun(run)}
                      withBorder
                      p="xs"
                      radius="sm"
                      style={{
                        background: selectedRun?.id === run.id ? 'rgba(99, 102, 241, 0.15)' : 'rgba(255,255,255,0.02)',
                        borderColor: selectedRun?.id === run.id ? 'var(--mantine-color-indigo-6)' : 'rgba(255,255,255,0.05)',
                        cursor: 'pointer'
                      }}
                    >
                      <Group justify="space-between">
                        <Text size="11px" fw={700}>Run #{run.id}</Text>
                        <Badge size="xs" color={run.status === 'SUCCESS' ? 'green' : run.status === 'NO_NEW_ITEMS' ? 'gray' : 'red'}>
                          {run.status}
                        </Badge>
                      </Group>
                      <Text size="10px" c="dimmed">
                        {new Date(run.started_at).toLocaleString()}
                      </Text>
                      <Text size="10px" c="dimmed">
                        Diff Detected: {run.accepted_items > 0 ? "YES" : "NO"}
                      </Text>
                    </Paper>
                  ))}
                </Stack>
              </ScrollArea>
            </Stack>

            {/* Right Run Detail */}
            <Stack gap="md" style={{ gridColumn: 'span 2' }}>
              {selectedRun ? (
                <>
                  <Group justify="space-between">
                    <Text size="sm" fw={700}>运行详情 (Run Details - #{selectedRun.id})</Text>
                    <Button 
                      size="xs" 
                      variant="subtle" 
                      color="indigo" 
                      leftSection={<Download size={12} />} 
                      onClick={() => handleExportTrace(selectedRun.id)}
                    >
                      导出脱敏日志
                    </Button>
                  </Group>

                  {/* Summary stats */}
                  <SimpleGrid cols={3} spacing="xs">
                    <Paper p="xs" withBorder style={{ textAlign: 'center', background: 'rgba(0,0,0,0.2)' }}>
                      <Text size="9px" c="dimmed" fw={700}>耗时 (Duration)</Text>
                      <Group gap="xs" justify="center" mt={4}>
                        <Clock size={12} className="text-amber-400" />
                        <Text size="xs" fw={700}>
                          {selectedRun.finished_at 
                            ? `${Math.max(1, Math.round((new Date(selectedRun.finished_at).getTime() - new Date(selectedRun.started_at).getTime())))} ms` 
                            : 'N/A'}
                        </Text>
                      </Group>
                    </Paper>
                    <Paper p="xs" withBorder style={{ textAlign: 'center', background: 'rgba(0,0,0,0.2)' }}>
                      <Text size="9px" c="dimmed" fw={700}>更新/变化条数</Text>
                      <Group gap="xs" justify="center" mt={4}>
                        <FileText size={12} className="text-sky-400" />
                        <Text size="xs" fw={700}>{selectedRun.accepted_items} 条</Text>
                      </Group>
                    </Paper>
                    <Paper p="xs" withBorder style={{ textAlign: 'center', background: 'rgba(0,0,0,0.2)' }}>
                      <Text size="9px" c="dimmed" fw={700}>开销标记 (Cost)</Text>
                      <Group gap={4} justify="center" mt={4}>
                        {selectedRun.cost_flag_browser && <Badge size="9px" color="orange">Browser</Badge>}
                        {selectedRun.cost_flag_llm && <Badge size="9px" color="blue">LLM</Badge>}
                        {!selectedRun.cost_flag_browser && !selectedRun.cost_flag_llm && <Text size="10px" c="dimmed">None</Text>}
                      </Group>
                    </Paper>
                  </SimpleGrid>

                  {selectedRun.error_summary && (
                    <Alert color="red" variant="light" icon={<AlertCircle size={14} />}>
                      <Text size="xs">{selectedRun.error_summary}</Text>
                    </Alert>
                  )}

                  {/* Events list */}
                  <Text size="xs" fw={700}>步骤流水事件 (Pipeline Steps Tree)</Text>
                  <ScrollArea h={180}>
                    <Stack gap="xs">
                      {selectedRun.events && selectedRun.events.length > 0 ? (
                        selectedRun.events.map((ev) => (
                          <Paper 
                            key={ev.id} 
                            p="xs" 
                            style={{ 
                              background: 'rgba(255,255,255,0.01)', 
                              border: `1px solid ${ev.status === 'FAILED' ? 'rgba(240,62,62,0.2)' : 'rgba(255,255,255,0.04)'}` 
                            }}
                          >
                            <Group justify="space-between">
                              <Group gap="xs">
                                <Text size="11px" fw={700} c={ev.status === 'FAILED' ? 'red' : 'indigo'}>
                                  Step {ev.step_index}: [{ev.stage}]
                                </Text>
                                {ev.adapter && <Badge size="9px" color="gray">{ev.adapter}</Badge>}
                              </Group>
                              <Group gap="xs">
                                <Text size="10px" c="dimmed">{ev.duration_ms} ms</Text>
                                <Badge size="9px" color={ev.status === 'SUCCESS' ? 'teal' : 'red'}>
                                  {ev.status}
                                </Badge>
                              </Group>
                            </Group>
                            
                            {ev.input_data && (
                              <Text size="10px" mt={4} style={{ wordBreak: 'break-all', fontFamily: 'monospace' }} c="dimmed">
                                Target: {ev.input_data}
                              </Text>
                            )}

                            {ev.output_summary && (
                              <Text size="10px" mt={2} style={{ fontFamily: 'monospace' }} c="indigo">
                                Output: {ev.output_summary}
                              </Text>
                            )}

                            {ev.error && (
                              <Text size="10px" mt={2} style={{ fontFamily: 'monospace' }} c="red">
                                Error: {ev.error}
                              </Text>
                            )}
                          </Paper>
                        ))
                      ) : (
                        <Text size="xs" c="dimmed" fs="italic" ta="center" py="md">
                          该次运行无细化步骤事件记录 (No trace events found)
                        </Text>
                      )}
                    </Stack>
                  </ScrollArea>
                </>
              ) : (
                <Group justify="center" py="xl">
                  <Text size="xs" c="dimmed">请在左侧选择一次运行历史查看诊断</Text>
                </Group>
              )}
            </Stack>
          </SimpleGrid>
        )}
      </Modal>
    </Stack>
  );
}
