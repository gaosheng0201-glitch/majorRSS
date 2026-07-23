import { useEffect, useState } from 'react';
import { 
  Text, Table, Group, Stack, Button, Badge, ActionIcon,
  Modal, TextInput, Select, NumberInput, Textarea, Paper, Menu,
  Stepper, Card, ScrollArea, Accordion, Alert, SimpleGrid, Loader
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  Plus, Play, Trash2, Power, MoreVertical, Edit, AlertCircle,
  CheckCircle2, Activity, Clock, FileText, Download, RefreshCw, Star
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
  is_high_attention?: boolean;
  created_at: string;
  last_scraped_at?: string;
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

export default function Discovery() {
  const { t } = useLanguage();
  const [discoveries, setDiscoveries] = useState<Tracker[]>([]);
  const [opened, { open, close }] = useDisclosure(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  // Developer Mode state
  const [devMode, setDevMode] = useState(() => localStorage.getItem('developer_mode') === 'true');

  // Tracing Modal states
  const [traceOpened, { open: openTrace, close: closeTrace }] = useDisclosure(false);
  const [selectedTracker, setSelectedTracker] = useState<Tracker | null>(null);
  const [traceRuns, setTraceRuns] = useState<PipelineRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<PipelineRun | null>(null);
  const [loadingTraces, setLoadingTraces] = useState(false);
  const [runningTrace, setRunningTrace] = useState(false);

  // Stepper Wizard states
  const [activeStep, setActiveStep] = useState(0);

  // Common UI styles
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

  // Form states
  const [name, setName] = useState('');
  const [intensity, setIntensity] = useState<'strict' | 'balanced' | 'broad'>('balanced');
  // Portfolio planning preview (R4): show which sources will be watched & why.
  const [plan, setPlan] = useState<any>(null);
  const [planning, setPlanning] = useState(false);

  const handlePreviewPlan = async () => {
    if (!name.trim()) return;
    setPlanning(true);
    try {
      const res = await client.post('/trackers/plan', { name, intent_text: name, use_llm: true });
      setPlan(res.data);
    } catch (e) {
      console.error('plan failed', e);
    } finally {
      setPlanning(false);
    }
  };

  // Flat Signals lists
  const [keywords, setKeywords] = useState('');
  const [accounts, setAccounts] = useState('');
  const [websites, setWebsites] = useState('');
  const [keepKeywords, setKeepKeywords] = useState('');
  const [ignoreKeywords, setIgnoreKeywords] = useState('');
  
  // General Advanced Settings
  const [section, setSection] = useState('Frontier Outpost');
  const [interval, setIntervalVal] = useState<number | string>(30);
  const [promptOverride, setPromptOverride] = useState('');

  // Freshness = how recent content must be (its own first-class setting, NOT
  // tied to probe intensity/source strategy). Drives both the source-level date
  // window (Google News when:Nd) and the post-fetch age gate (max_days).
  const [freshnessDays, setFreshnessDays] = useState<number>(7);

  // Developer Accordion Overrides
  const [devRouteStrategy, setDevRouteStrategy] = useState('default');
  const [devMaxItems, setDevMaxItems] = useState<number>(20);

  // Live Route Preview
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const fetchData = async () => {
    try {
      const res = await client.get<Tracker[]>('/trackers/');
      setDiscoveries(res.data.filter(t => t.source_intent === 'KEYWORD_DISCOVERY' || t.source_intent === 'HYBRID'));
    } catch (err) {
      console.error("Failed to fetch discoveries:", err);
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

  // Probe intensity controls SOURCE BREADTH only (how many items per source);
  // freshness is chosen independently (see freshnessDays).
  useEffect(() => {
    if (editingId) return; // Do not overwrite user custom edits during edit mode
    if (intensity === 'strict') {
      setDevMaxItems(10);
    } else if (intensity === 'balanced') {
      setDevMaxItems(20);
    } else {
      setDevMaxItems(50);
    }
  }, [intensity]);

  const handleToggle = async (id: number) => {
    try {
      const res = await client.post<Tracker>(`/trackers/${id}/toggle`);
      setDiscoveries(discoveries.map(d => d.id === id ? res.data : d));
    } catch (err) {
      alert("Failed to toggle discovery status");
    }
  };

  const handleRun = async (id: number) => {
    try {
      await client.post(`/trackers/${id}/run`);
      alert("Discovery scan triggered successfully");
    } catch (err) {
      alert("Failed to run discovery scan");
    }
  };

  // High-attention targets alert earlier (a CONFIRMED/CORROBORATED increment is
  // pushed, not just shown in the quiet Radar) — 愿景 #2.
  const handleHighAttention = async (id: number) => {
    try {
      const res = await client.post<Tracker>(`/trackers/${id}/high-attention`);
      setDiscoveries(prev => prev.map(d => d.id === id ? { ...d, is_high_attention: res.data.is_high_attention } : d));
    } catch (err) {
      alert("Failed to toggle high-attention");
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm("Are you sure you want to delete this discovery scan?")) return;
    try {
      await client.delete(`/trackers/${id}`);
      setDiscoveries(discoveries.filter(d => d.id !== id));
    } catch (err) {
      alert("Failed to delete discovery");
    }
  };

  const handleStartEdit = (d: Tracker) => {
    setEditingId(d.id);
    setName(d.name);
    setSection(d.radar_section);
    setIntervalVal(d.fetch_interval_minutes);
    setPromptOverride(d.prompt_override || '');
    setTestResult(null);
    setActiveStep(0);

    // Extract signals
    try {
      const targetData = JSON.parse(d.target);
      const kws: string[] = [];
      const accs: string[] = [];
      const webs: string[] = [];
      
      if (targetData.signals && Array.isArray(targetData.signals)) {
        targetData.signals.forEach((sig: any) => {
          if (sig.type === 'keyword') kws.push(sig.value);
          else if (sig.type === 'account') accs.push(sig.value);
          else webs.push(sig.value);
        });
      } else if (targetData.keywords) {
        kws.push(...(targetData.keywords || []));
        accs.push(...(targetData.accounts || []));
        webs.push(...(targetData.urls || []));
      } else if (Array.isArray(targetData)) {
        kws.push(...targetData);
      } else {
        webs.push(d.target);
      }
      setKeywords(kws.join('\n'));
      setAccounts(accs.join('\n'));
      setWebsites(webs.join('\n'));
    } catch {
      setWebsites(d.target);
    }

    if (d.fetch_policy) {
      try {
        const p = JSON.parse(d.fetch_policy);
        setDevRouteStrategy(p.keyword_strategy || 'default');
        setDevMaxItems(p.max_items_per_route || 20);
        setFreshnessDays(p.max_days || 7);
        if (p.keyword_strategy === 'trusted_news_only') {
          setIntensity('strict');
        } else if (p.use_default_osint === true && p.max_items_per_route > 25) {
          setIntensity('broad');
        } else {
          setIntensity('balanced');
        }
        setKeepKeywords(p.keep_keywords ? p.keep_keywords.join('\n') : '');
        setIgnoreKeywords(p.ignore_keywords ? p.ignore_keywords.join('\n') : '');
      } catch {}
    }
    open();
  };

  const handleClose = () => {
    close();
    setEditingId(null);
    setName('');
    setKeywords('');
    setAccounts('');
    setWebsites('');
    setIntensity('balanced');
    setSection('Frontier Outpost');
    setIntervalVal(30);
    setPromptOverride('');
    setDevRouteStrategy('default');
    setDevMaxItems(20);
    setFreshnessDays(7);
    setKeepKeywords('');
    setIgnoreKeywords('');
    setTestResult(null);
    setActiveStep(0);
  };

  const getTargetPayload = () => {
    const kwList = keywords.split('\n').map(x => x.trim()).filter(Boolean);
    const accList = accounts.split('\n').map(x => x.trim()).filter(Boolean);
    const webList = websites.split('\n').map(x => x.trim()).filter(Boolean);

    const signals: any[] = [];
    kwList.forEach(k => signals.push({ type: 'keyword', value: k }));
    accList.forEach(a => signals.push({ type: 'account', value: a }));
    webList.forEach(w => signals.push({ type: 'website', value: w }));

    return JSON.stringify({
      topic: name,
      signals
    });
  };

  const getFetchPolicy = () => {
    const keepList = keepKeywords.split('\n').map(x => x.trim()).filter(Boolean);
    const ignoreList = ignoreKeywords.split('\n').map(x => x.trim()).filter(Boolean);
    let policy: any = {
      keyword_strategy: devRouteStrategy,
      max_items_per_route: Number(devMaxItems),
      max_days: Number(freshnessDays),
      fallback_enabled: true,
      use_default_osint: true,
      keep_keywords: keepList,
      ignore_keywords: ignoreList
    };

    if (intensity === 'strict') {
      policy.keyword_strategy = 'trusted_news_only';
      policy.use_default_osint = false;
    } else if (intensity === 'broad') {
      policy.use_default_osint = true;
    }

    return JSON.stringify(policy);
  };

  // Connection Test
  const runLiveTest = async () => {
    setTesting(true);
    setTestResult(null);
    
    try {
      // 试运行会逐个源联网抓取，正常就要 20~40s；全局 15s 超时太短会误报"失败"。
      // 给这个慢操作单独放宽到 60s。
      const res = await client.post('/trackers/test-resolve-intent', {
        target: getTargetPayload(),
        source_intent: 'HYBRID',
        fetch_policy: getFetchPolicy()
      }, { timeout: 60000 });
      setTestResult(res.data);
    } catch (err: any) {
      const isTimeout = err.code === 'ECONNABORTED' || /timeout/i.test(err.message || '');
      setTestResult({
        error_message: isTimeout
          ? '试运行耗时较长仍未返回：所选信号解析出的源较多、逐个联网抓取偏慢。可减少关键词或降低探测强度后重试。也可以直接“保存并开启探测”——后台会按计划自动抓取，不受此预览影响。'
          : (err.response?.data?.detail || err.message)
      });
    } finally {
      setTesting(false);
    }
  };

  const handleNextStep = () => {
    // 门控按步校验：第 0 步只管"意图"，信号是第 1 步才填的，别在第 0 步就拦。
    if (activeStep === 0) {
      if (!name.trim()) {
        alert("请先填写探测主题");
        return;
      }
      if (!section.trim()) {
        alert("请先填写雷达大屏板块");
        return;
      }
    }
    if (activeStep === 1) {
      if (!keywords.trim() && !accounts.trim() && !websites.trim()) {
        alert("请至少输入一个信号：关键词、账号或网站链接");
        return;
      }
    }
    setActiveStep(prev => prev + 1);
  };

  const handlePrevStep = () => {
    setActiveStep(prev => prev - 1);
  };

  const handleSaveSubmit = async () => {
    setSubmitting(true);
    
    const payload = {
      name,
      tracker_type: 'HYBRID',
      target: getTargetPayload(),
      tier: 1,
      radar_section: section,
      fetch_interval_minutes: Number(interval),
      prompt_override: promptOverride || null,
      source_intent: 'HYBRID',
      fetch_policy: getFetchPolicy()
    };

    try {
      if (editingId) {
        await client.put(`/trackers/${editingId}`, payload);
      } else {
        await client.post('/trackers/', payload);
      }
      handleClose();
      fetchData();
    } catch (err: any) {
      alert("Failed to save discovery: " + (err.response?.data?.detail || err.message));
    } finally {
      setSubmitting(false);
    }
  };

  const getDisplayTarget = (d: Tracker) => {
    try {
      const data = JSON.parse(d.target);
      if (data.signals) {
        const parts: string[] = [];
        const kws = data.signals.filter((s: any) => s.type === 'keyword').length;
        const accs = data.signals.filter((s: any) => s.type === 'account').length;
        const webs = data.signals.filter((s: any) => s.type === 'website').length;
        if (kws > 0) parts.push(`${kws} KWs`);
        if (accs > 0) parts.push(`${accs} Accs`);
        if (webs > 0) parts.push(`${webs} Sites`);
        return parts.join(', ') || 'No signals';
      }
      return d.target;
    } catch {
      return d.target;
    }
  };

  // Tracing log actions
  const handleOpenTrace = async (tracker: Tracker) => {
    setSelectedTracker(tracker);
    setTraceRuns([]);
    setSelectedRun(null);
    openTrace();
    setLoadingTraces(true);
    try {
      const res = await client.get<PipelineRun[]>(`/trackers/${tracker.id}/traces`);
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
    if (!selectedTracker) return;
    setRunningTrace(true);
    try {
      // 完整抓取诊断更慢（可达一两分钟），单独放宽超时。
      const res = await client.post<PipelineRun>(`/trackers/${selectedTracker.id}/run-trace`, {}, { timeout: 180000 });
      // Refresh trace runs list
      const freshRuns = await client.get<PipelineRun[]>(`/trackers/${selectedTracker.id}/traces`);
      setTraceRuns(freshRuns.data);
      
      // Select the newly generated run
      const matched = freshRuns.data.find(r => r.id === res.data.id) || res.data;
      setSelectedRun(matched);
      alert("Pipeline run trace completed successfully!");
      fetchData();
    } catch (err: any) {
      alert("Pipeline trace run failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setRunningTrace(false);
    }
  };

  const handleExportTrace = async (runId: number) => {
    try {
      const res = await client.get(`/trackers/traces/${runId}/export`);
      const fileBlob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(fileBlob);
      link.download = `pipeline_run_${runId}_export.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err: any) {
      alert("Failed to export trace logs: " + err.message);
    }
  };

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Stack gap={0}>
          <Text size="xl" fw={700} className="title-text-color">{t('nav_trackers') || "主动探测"}</Text>
          <Text size="sm" c="dimmed">基于意图的主题探测：设定主题及多源信号，AI 智能引擎将自动调度管线探测资讯并提取异动 (Intent-driven Topic Discovery)</Text>
        </Stack>
        <Button 
          variant="filled" 
          color="indigo" 
          leftSection={<Plus size={16} />}
          onClick={() => { handleClose(); open(); }}
        >
          新建主题探测
        </Button>
      </Group>

      {/* Discovery List Table */}
      <Paper withBorder radius="md" style={{ background: 'rgba(255,255,255,0.01)', overflow: 'hidden' }}>
        <Table verticalSpacing="md" horizontalSpacing="lg" highlightOnHover style={{ color: 'var(--mantine-color-gray-3)' }}>
          <Table.Thead style={{ background: 'rgba(255,255,255,0.02)' }}>
            <Table.Tr>
              <Table.Th>探测主题</Table.Th>
              <Table.Th>模式</Table.Th>
              <Table.Th>活跃探测信号</Table.Th>
              <Table.Th>雷达分类</Table.Th>
              <Table.Th>抓取间隔(分)</Table.Th>
              <Table.Th>状态</Table.Th>
              <Table.Th>最近扫描</Table.Th>
              <Table.Th></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {discoveries.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={8} style={{ textAlign: 'center' }}>
                  <Text c="dimmed" py="lg">无活动探测主题</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              discoveries.map((d) => (
                <Table.Tr key={d.id}>
                  <Table.Td fw={700} className="title-text-color">{d.name}</Table.Td>
                  <Table.Td>
                    <Badge variant="light" color="indigo">主题混合探测</Badge>
                  </Table.Td>
                  <Table.Td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {getDisplayTarget(d)}
                  </Table.Td>
                  <Table.Td>{d.radar_section}</Table.Td>
                  <Table.Td>{d.fetch_interval_minutes} 分钟</Table.Td>
                  <Table.Td>
                    <Badge color={d.is_active ? 'teal' : 'red'} variant="dot">
                      {d.is_active ? '活动' : '已暂停'}
                    </Badge>
                  </Table.Td>
                  <Table.Td style={{ fontSize: 'var(--mantine-font-size-xs)' }}>
                    {d.last_scraped_at ? new Date(d.last_scraped_at).toLocaleString() : '从不'}
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <ActionIcon
                        variant={d.is_high_attention ? 'light' : 'subtle'}
                        color={d.is_high_attention ? 'yellow' : 'gray'}
                        title={d.is_high_attention ? '高关注：重要进展会主动提醒（点击取消）' : '设为高关注：重要进展主动提醒'}
                        onClick={() => handleHighAttention(d.id)}
                      >
                        <Star size={16} fill={d.is_high_attention ? 'currentColor' : 'none'} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="teal"
                        title="立即扫描"
                        onClick={() => handleRun(d.id)}
                      >
                        <Play size={16} />
                      </ActionIcon>
                      
                      {devMode && (
                        <ActionIcon
                          variant="subtle"
                          color="indigo"
                          title="管道诊断 (Pipeline Trace)"
                          onClick={() => handleOpenTrace(d)}
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
                            onClick={() => handleStartEdit(d)}
                            style={{ color: 'white' }}
                          >
                            修改配置
                          </Menu.Item>
                          {devMode && (
                            <Menu.Item
                              leftSection={<Activity size={14} />}
                              onClick={() => handleOpenTrace(d)}
                              style={{ color: 'white' }}
                            >
                              诊断 / Trace
                            </Menu.Item>
                          )}
                          <Menu.Item 
                            leftSection={<Power size={14} />} 
                            onClick={() => handleToggle(d.id)}
                            style={{ color: 'white' }}
                          >
                            {d.is_active ? '暂停' : '激活'}
                          </Menu.Item>
                          <Menu.Item 
                            leftSection={<Trash2 size={14} />} 
                            color="red"
                            onClick={() => handleDelete(d.id)}
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

      {/* Discovery Multi-step Wizard Modal */}
      <Modal 
        opened={opened} 
        onClose={handleClose} 
        title={editingId ? "修改探测配置" : "新建全网主动探测"}
        size="lg"
        centered
        styles={{
          content: { background: 'rgba(25,25,25,0.95)', border: '1px solid rgba(255,255,255,0.1)', color: 'white' },
          header: { background: 'rgba(25,25,25,0.95)', color: 'white' }
        }}
      >
        <Stepper active={activeStep} onStepClick={setActiveStep} color="indigo" size="sm">
          {/* Step 1: Target settings */}
          <Stepper.Step label="表达意图" description="定义探测主题">
            <Stack gap="md" mt="md">
              <TextInput
                label="探测项目主题 (Topic Title)"
                placeholder="例如：苹果最新设备"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                styles={modalInputStyles}
              />

              <TextInput
                label="雷达大屏板块 (Radar Section)"
                placeholder="Frontier Outpost"
                required
                value={section}
                onChange={(e) => setSection(e.target.value)}
                styles={modalInputStyles}
              />

              <Select
                label="新鲜度 (Freshness) — 只关注多新的内容"
                description="决定只看最近多久的内容：源头按此限定日期抓取（Google News），并过滤更旧的条目。与探测强度/源策略无关。"
                data={[
                  { value: '1', label: '最近 1 天（突发/快讯）' },
                  { value: '3', label: '最近 3 天' },
                  { value: '7', label: '最近 7 天（默认）' },
                  { value: '14', label: '最近 14 天' },
                  { value: '30', label: '最近 30 天（慢话题）' },
                  { value: '0', label: '不限（含旧闻，谨慎：可能拉入历史）' },
                ]}
                value={String(freshnessDays)}
                onChange={(v) => setFreshnessDays(Number(v ?? 7))}
                styles={modalInputStyles}
              />

              {/* Portfolio preview — "选源可解释": see which sources will be
                  watched and why, before creating the target. */}
              <div>
                <Button variant="light" size="xs" color="indigo" loading={planning}
                        disabled={!name.trim()} onClick={handlePreviewPlan}>
                  预览会监听哪些源
                </Button>
                {plan && (
                  <Paper withBorder p="sm" radius="md" mt="xs" style={{ background: 'rgba(99,102,241,0.04)' }}>
                    <Text size="xs" c="dimmed" mb={4}>
                      识别领域：<Text span fw={600} c="indigo">{plan.detected_domain}</Text>
                      {plan.planner_used === 'fallback' ? '（关键词匹配，未配模型）' : `（${plan.planner_used} 规划）`}
                    </Text>
                    {plan.entities?.length > 0 && (
                      <Text size="xs" mb={4}>实体：{plan.entities.slice(0, 8).join('、')}</Text>
                    )}
                    <Text size="xs" mb={4}>
                      将监听 <Text span fw={700} c="indigo">{plan.selected_collections?.length || 0}</Text> 个源集合：
                      {(plan.selected_collections || []).join('、') || '（无匹配，用通用基座）'}
                    </Text>
                    {plan.rationale && <Text size="10px" c="dimmed">{plan.rationale}</Text>}
                  </Paper>
                )}
              </div>
            </Stack>
          </Stepper.Step>

          {/* Step 2: Signals & Intensity */}
          <Stepper.Step label="添加信号" description="输入关键字与来源">
            <Stack gap="md" mt="md">
              <Select
                label="探测强度比例 (Probe Intensity)"
                data={[
                  { value: 'strict', label: '精准 (Strict): 官方主流新闻, 过滤严格' },
                  { value: 'balanced', label: '平衡 (Balanced): 主流新闻 + 优质技术社区' },
                  { value: 'broad', label: '广泛 (Broad): 包含论坛、社交搜索与 RSSHub 深度挖掘' }
                ]}
                value={intensity}
                onChange={(v) => setIntensity(v as any)}
                styles={modalInputStyles}
              />

              <Textarea
                label="监控关键字 (Keywords) — 每行一个"
                placeholder="iPhone&#10;Vision Pro"
                minRows={2}
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                styles={modalInputStyles}
              />

              <Textarea
                label="特定跟踪社交账号 (Social Accounts) — 每行一个"
                placeholder="twitter:sama&#10;bilibili:12345"
                minRows={2}
                value={accounts}
                onChange={(e) => setAccounts(e.target.value)}
                styles={modalInputStyles}
              />

              <Textarea
                label="特定跟踪网站与 RSS 信号源 (Websites & Feeds) — 每行一个"
                placeholder="https://apple.com/newsroom&#10;https://hnrss.org/newest"
                minRows={2}
                value={websites}
                onChange={(e) => setWebsites(e.target.value)}
                styles={modalInputStyles}
              />

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
                  <Accordion.Item value="developer_strategy">
                    <Accordion.Control>⚙️ 开发者工程策略设定 (Developer Settings Overrides)</Accordion.Control>
                    <Accordion.Panel>
                      <Stack gap="md" pt="xs">
                        <Select
                          label="全网管线策略 Override (Route Strategy)"
                          data={[
                            { value: 'default', label: '平衡策略 (Default OSINT)' },
                            { value: 'trusted_news_only', label: '严格新闻策略 (Google News Only)' }
                          ]}
                          value={devRouteStrategy}
                          onChange={(v) => setDevRouteStrategy(v || 'default')}
                          styles={modalInputStyles}
                        />
                        <NumberInput
                          label="单源最大抓取条数 (Max Items per Route)"
                          min={5}
                          max={100}
                          value={devMaxItems}
                          onChange={(v) => setDevMaxItems(Number(v) || 20)}
                          styles={modalInputStyles}
                        />
                        {/* 新鲜度移到第 1 步的一等设置项，不再放在开发者设置里 */}
                      </Stack>
                    </Accordion.Panel>
                  </Accordion.Item>
                </Accordion>
              )}
            </Stack>
          </Stepper.Step>

          {/* Step 3: Dry-run and connection test preview */}
          <Stepper.Step label="试运行预览" description="连接测试反馈">
            <Stack gap="md" mt="md">
              <Paper withBorder p="md" style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.05)', textAlign: 'center' }}>
                <Text size="xs" mb="md" c="dimmed">
                  通过试运行探测，系统会利用当前配置的信号与强度动态解析管线，并尝试拉取最新的资讯条目。
                </Text>
                <Button color="indigo" size="sm" onClick={runLiveTest} loading={testing}>
                  开始探测连接测试
                </Button>
              </Paper>

              {testResult && (
                <Stack gap="md">
                  {testResult.error_message ? (
                    <Card withBorder style={{ borderColor: 'var(--mantine-color-red-8)', background: 'rgba(250,82,82,0.03)' }} p="md" radius="md">
                      <Group gap="xs">
                        <AlertCircle color="red" size={16} />
                        <Text size="sm" fw={700}>测试失败</Text>
                      </Group>
                      <Text size="xs" mt="xs" c="red">{testResult.error_message}</Text>
                    </Card>
                  ) : (
                    <>
                      <Card withBorder style={{ borderColor: 'var(--mantine-color-teal-8)', background: 'rgba(9,146,104,0.03)' }} p="md" radius="md">
                        <Group justify="space-between">
                          <Group gap="xs">
                            <CheckCircle2 color="teal" size={16} />
                            <Text size="sm" fw={700} c="teal">测试成功</Text>
                          </Group>
                          <Badge color="indigo">抓取条数: {testResult.item_count}</Badge>
                        </Group>
                        <Text size="xs" mt="xs" c="dimmed">
                          最新条目时间: {testResult.latest_item_time ? new Date(testResult.latest_item_time).toLocaleString() : '无'} | 
                          综合数据质量分: {testResult.quality_score}
                        </Text>
                      </Card>

                      <Text size="xs" fw={700}>获取条目预览 (Sample Titles)</Text>
                      <ScrollArea h={120} style={{ background: 'rgba(0,0,0,0.3)', borderRadius: 6 }} p="xs">
                        <Stack gap="xs">
                          {testResult.sample_titles && testResult.sample_titles.length > 0 ? (
                            testResult.sample_titles.map((title: string, idx: number) => (
                              <Group key={idx} wrap="nowrap" align="center" gap="xs">
                                <Text size="11px" c="dimmed">[{idx + 1}]</Text>
                                <Text size="11px" fw={500} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {title}
                                </Text>
                              </Group>
                            ))
                          ) : (
                            <Text size="xs" c="dimmed" fs="italic">未抓取到有效文章标题</Text>
                          )}
                        </Stack>
                      </ScrollArea>

                      <Text size="xs" fw={700}>已解析路由管线节点 Resolved Routes ({testResult.resolved_routes?.length || 0})</Text>
                      <Stack gap="xs">
                        {testResult.resolved_routes?.map((route: any, idx: number) => (
                          <Paper key={idx} p="xs" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.03)' }}>
                            <Group justify="space-between">
                              <Stack gap={2}>
                                <Text size="xs" fw={700}>{route.route_id} ({route.adapter})</Text>
                                <Text size="10px" c="dimmed" style={{ maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {route.url_or_command}
                                </Text>
                              </Stack>
                              <Badge color={route.ok ? 'teal' : 'red'} size="xs">
                                {route.ok ? 'OK' : 'Error'}
                              </Badge>
                            </Group>
                          </Paper>
                        ))}
                      </Stack>
                    </>
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
              {editingId ? '保存探测任务' : '保存并开启探测'}
            </Button>
          )}
        </Group>
      </Modal>

      {/* Tracing Modal (Developer Diagnostics) */}
      <Modal
        opened={traceOpened}
        onClose={closeTrace}
        title={selectedTracker ? `诊断与管线分析 - ${selectedTracker.name}` : '数据管线分析'}
        size="xl"
        centered
        styles={{
          content: { background: 'rgba(25,25,25,0.98)', border: '1px solid rgba(255,255,255,0.15)', color: 'white' },
          header: { background: 'rgba(25,25,25,0.98)', color: 'white' }
        }}
      >
        <Group justify="space-between" mb="md">
          <Text size="xs" c="dimmed">
            本页展示任务运行时的路由分流、错误抓取栈及 AI 处理用量。 (Execution Trace Analysis Logs)
          </Text>
          <Group gap="xs">
            <Button 
              size="xs" 
              variant="light" 
              color="indigo" 
              leftSection={<RefreshCw size={12} />} 
              onClick={() => selectedTracker && handleOpenTrace(selectedTracker)}
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
            该探测器尚无历史管道运行记录。您可以点击上方“立即运行诊断”以触发一次新抓取测试。
          </Alert>
        ) : (
          <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
            {/* Runs Left Column */}
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
                        Routes: {run.total_routes} | Persisted: {run.accepted_items}
                      </Text>
                    </Paper>
                  ))}
                </Stack>
              </ScrollArea>
            </Stack>

            {/* Run Detail Right Column */}
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

                  {/* Summary Stats */}
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
                      <Text size="9px" c="dimmed" fw={700}>抓取/保存数量</Text>
                      <Group gap="xs" justify="center" mt={4}>
                        <FileText size={12} className="text-sky-400" />
                        <Text size="xs" fw={700}>{selectedRun.total_items} / {selectedRun.accepted_items}</Text>
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

                  {/* Pipeline Events List */}
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
