import { useEffect, useState, type FormEvent } from 'react';
import { 
  Text, Group, Stack, Button, TextInput, Paper, ScrollArea, Divider, Select,
  SimpleGrid, Badge, Loader, useMantineColorScheme, Tabs, Table, Alert
} from '@mantine/core';
import { 
  Key, Database, Satellite, Compass, Lock, ShieldAlert, Trash2, 
  RefreshCw, Rss, Layers
} from 'lucide-react';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';

interface AuthProfile {
  id: number;
  platform: string;
  display_name: string;
  storage_ref: string;
  status: string;
  last_checked_at?: string;
  created_at: string;
}

export interface AuthStatus {
  key: string;
  name: string;
  has_cookie: boolean;
  is_healthy: boolean;
  mtime: number | null;
}

interface Subscription {
  id: number;
  name: string;
  target_url: string;
  is_active: boolean;
  fetch_interval_minutes: number;
  last_scraped_at?: string;
  last_status: string;
}

interface Tracker {
  id: number;
  name: string;
  tracker_type: string;
  target: string;
  source_intent: string;
  fetch_policy?: string;
  is_active: boolean;
  normalized_intent?: string;
}

interface SignalItem {
  id: string;
  type: string;
  value: string;
  parentTopic: string;
  isActive: boolean;
  intensity: string;
}

interface SourcePresetCollection {
  collection_id: string;
  title: string;
  description?: string;
  categories: string[];
  owner_type: string;
  default_keywords: string[];
  source_count: number;
}

interface SourcePreset {
  preset_id: string;
  title: string;
  description?: string;
  source_type: string;
  url: string;
  canonical_site?: string;
  categories: string[];
  tags: string[];
  language?: string;
  region?: string;
  importance?: string;
  noise_level?: string;
  update_frequency?: string;
  requires_auth: boolean;
  owner_type: string;
  verification_status: string;
}

export default function Sources() {
  const { t } = useLanguage();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  // Auth Profiles and legacy statuses
  const [profiles, setProfiles] = useState<AuthProfile[]>([]);
  const [authStatuses, setAuthStatuses] = useState<AuthStatus[]>([]);
  const [loggingInPlatform, setLoggingInPlatform] = useState<string | null>(null);
  const [newProfilePlatform, setNewProfilePlatform] = useState<string | null>('twitter');
  const [newProfileName, setNewProfileName] = useState('');
  const [creatingProfile, setCreatingProfile] = useState(false);

  // Local & Discovery Sources
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [trackers, setTrackers] = useState<Tracker[]>([]);
  const [loadingLocal, setLoadingLocal] = useState(false);
  const [loadingSignals, setLoadingSignals] = useState(false);
  const [presetCollections, setPresetCollections] = useState<SourcePresetCollection[]>([]);
  const [sourcePresets, setSourcePresets] = useState<SourcePreset[]>([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null);
  const [loadingPresets, setLoadingPresets] = useState(false);
  const [seedingPresets, setSeedingPresets] = useState(false);

  const fetchProfiles = async () => {
    try {
      const res = await client.get<AuthProfile[]>('/auth/profiles/');
      setProfiles(res.data);
    } catch (err) {
      console.error("Failed to fetch profiles:", err);
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

  const fetchLocalSources = async () => {
    setLoadingLocal(true);
    try {
      const res = await client.get<Subscription[]>('/monitors/');
      setSubscriptions(res.data);
    } catch (err) {
      console.error("Failed to fetch subscriptions:", err);
    } finally {
      setLoadingLocal(false);
    }
  };

  const fetchDiscoveryTrackers = async () => {
    setLoadingSignals(true);
    try {
      const res = await client.get<Tracker[]>('/trackers/');
      setTrackers(res.data);
    } catch (err) {
      console.error("Failed to fetch trackers:", err);
    } finally {
      setLoadingSignals(false);
    }
  };

  const fetchPresetCollections = async () => {
    try {
      const res = await client.get<SourcePresetCollection[]>('/source-presets/collections');
      setPresetCollections(res.data);
    } catch (err) {
      console.error("Failed to fetch source preset collections:", err);
    }
  };

  const fetchSourcePresets = async (collectionId: string | null = selectedCollectionId) => {
    setLoadingPresets(true);
    try {
      const res = await client.get<SourcePreset[]>('/source-presets/sources', {
        params: collectionId ? { collection_id: collectionId } : {}
      });
      setSourcePresets(res.data);
    } catch (err) {
      console.error("Failed to fetch source presets:", err);
    } finally {
      setLoadingPresets(false);
    }
  };

  const seedAndRefreshPresets = async () => {
    setSeedingPresets(true);
    try {
      await client.post('/source-presets/seed');
      await fetchPresetCollections();
      await fetchSourcePresets(selectedCollectionId);
    } catch (err: any) {
      alert("Failed to seed source presets: " + (err.response?.data?.detail || err.message));
    } finally {
      setSeedingPresets(false);
    }
  };

  useEffect(() => {
    fetchProfiles();
    fetchAuthStatuses();
    fetchLocalSources();
    fetchDiscoveryTrackers();
    fetchPresetCollections();
    fetchSourcePresets(null);

    const interval = setInterval(() => {
      fetchProfiles();
      fetchAuthStatuses();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    fetchSourcePresets(selectedCollectionId);
  }, [selectedCollectionId]);

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

  const handleCreateProfile = async (e: FormEvent) => {
    e.preventDefault();
    if (!newProfileName.trim() || !newProfilePlatform) {
      alert("Please fill in a display name and choose a platform");
      return;
    }
    setCreatingProfile(true);
    try {
      await client.post('/auth/profiles/', {
        platform: newProfilePlatform,
        display_name: newProfileName
      }, { timeout: 300000 });
      alert("Profile created successfully");
      setNewProfileName('');
      fetchProfiles();
    } catch (err: any) {
      alert("Failed to create profile: " + (err.response?.data?.detail || err.message));
    } finally {
      setCreatingProfile(false);
    }
  };

  const handleDeleteProfile = async (profileId: number) => {
    if (!window.confirm("Are you sure you want to delete this auth profile? This will delete the session file too.")) return;
    try {
      await client.delete(`/auth/profiles/${profileId}`);
      fetchProfiles();
    } catch (err: any) {
      alert("Failed to delete profile: " + (err.response?.data?.detail || err.message));
    }
  };

  const handleTestProfile = async (profileId: number) => {
    try {
      const res = await client.post<{ is_healthy: boolean; status: string }>(`/auth/profiles/${profileId}/test`);
      alert(`Profile status checked. Healthy: ${res.data.is_healthy ? "YES" : "NO"} (${res.data.status})`);
      fetchProfiles();
    } catch (err: any) {
      alert("Failed to test profile: " + (err.response?.data?.detail || err.message));
    }
  };

  // Compile Active Signals from HYBRID topic discovery tasks
  const compileSignals = (): SignalItem[] => {
    const list: SignalItem[] = [];
    trackers
      .filter(t => t.source_intent === 'HYBRID' || t.tracker_type === 'HYBRID')
      .forEach(t => {
        let signalsArray: any[] = [];
        let intensity = "Balanced";
        
        // Try parsing normalized_intent or target JSON
        try {
          if (t.normalized_intent) {
            const parsed = JSON.parse(t.normalized_intent);
            signalsArray = parsed.signals || [];
            intensity = parsed.policy_profile || "Balanced";
          } else {
            const parsedTarget = JSON.parse(t.target);
            signalsArray = parsedTarget.signals || [];
          }
        } catch {
          // Fallback if target is not a JSON
          if (t.tracker_type === 'KEYWORD') {
            signalsArray = [{ type: 'keyword', value: t.target }];
          } else if (t.tracker_type === 'ACCOUNT') {
            signalsArray = [{ type: 'account', value: t.target }];
          } else {
            signalsArray = [{ type: 'website', value: t.target }];
          }
        }

        if (t.fetch_policy) {
          try {
            const pol = JSON.parse(t.fetch_policy);
            if (pol.keyword_strategy === 'trusted_news_only') {
              intensity = "Strict";
            } else if (pol.use_default_osint === true && pol.max_items_per_route > 20) {
              intensity = "Broad";
            }
          } catch {}
        }

        signalsArray.forEach((sig: any, index: number) => {
          list.push({
            id: `${t.id}-${index}`,
            type: sig.type || 'keyword',
            value: sig.value || sig.toString(),
            parentTopic: t.name,
            isActive: t.is_active,
            intensity: intensity === 'balanced' ? 'Balanced' : intensity === 'strict' ? 'Strict' : intensity === 'broad' ? 'Broad' : intensity
          });
        });
      });
    return list;
  };

  const signals = compileSignals();
  const selectedCollection = presetCollections.find(c => c.collection_id === selectedCollectionId);
  const collectionOptions = [
    { value: '__all__', label: `All official presets (${sourcePresets.length})` },
    ...presetCollections.map(collection => ({
      value: collection.collection_id,
      label: `${collection.title} (${collection.source_count})`
    }))
  ];

  return (
    <Stack gap="lg">
      <Stack gap={0}>
        <Text size="xl" fw={700} className="title-text-color">{t('nav_sources')}</Text>
        <Text size="sm" c="dimmed">整合管理本地被动抓取源、交互式登录凭据及主动探测关键词信号 (Index & Control Ingestion Sources)</Text>
      </Stack>

      <Tabs defaultValue="auth_profiles" variant="outline" radius="md">
        <Tabs.List>
          <Tabs.Tab value="auth_profiles" leftSection={<Key size={14} />}>
            {t('sources_auth_profiles')}
          </Tabs.Tab>
          <Tabs.Tab value="local_sources" leftSection={<Rss size={14} />}>
            {t('sources_local_sources')}
          </Tabs.Tab>
          <Tabs.Tab value="discovery_signals" leftSection={<Satellite size={14} />}>
            {t('sources_discovery_signals')}
          </Tabs.Tab>
          <Tabs.Tab value="presets" leftSection={<Layers size={14} />}>
            {t('sources_presets')}
          </Tabs.Tab>
        </Tabs.List>

        {/* Tab 1: Auth Profiles */}
        <Tabs.Panel value="auth_profiles" pt="md">
          <Stack gap="md">
            <Paper withBorder p="md" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
              <Stack gap="sm">
                <Group gap="xs">
                  <Lock size={16} className="text-indigo-400" />
                  <Text size="sm" fw={700} className="title-text-color">{t('set_auth_title')}</Text>
                </Group>
                <Text size="xs" c="dimmed">{t('set_auth_desc')}</Text>
                
                <Alert color="yellow" variant="light" icon={<ShieldAlert size={14} />} styles={{ label: { fontSize: '11px', lineHeight: 1.5 } }}>
                  {t('set_auth_architecture_tip')}
                </Alert>

                {loggingInPlatform && (
                  <Alert color="red" variant="light" icon={<Loader size="xs" color="red" />}>
                    {t('set_auth_waiting')} ({loggingInPlatform})
                  </Alert>
                )}

                {creatingProfile && (
                  <Alert color="red" variant="light" icon={<Loader size="xs" color="red" />}>
                    Waiting for user to complete login in Playwright browser for the new profile...
                  </Alert>
                )}

                <Divider my="xs" label="Legacy Global Accounts (Fact-Checker only)" labelPosition="left" />

                <SimpleGrid cols={{ base: 1, sm: 2, md: 3, lg: 4 }} spacing="md">
                  {authStatuses.map((p) => {
                    let statusColor = "gray";
                    let statusText = t('set_auth_status_none');
                    
                    if (p.has_cookie && p.is_healthy) {
                      statusColor = "green";
                      statusText = t('set_auth_status_ok');
                    } else if (p.has_cookie && !p.is_healthy) {
                      statusColor = "yellow";
                      statusText = t('set_auth_status_expired');
                    }

                    const formattedTime = p.mtime 
                      ? new Date(p.mtime * 1000).toLocaleString()
                      : null;

                    return (
                      <Paper 
                        key={p.key} 
                        withBorder 
                        p="sm" 
                        radius="md" 
                        style={{ 
                          background: isDark ? 'rgba(255,255,255,0.01)' : '#f8f9fa', 
                          display: 'flex', 
                          flexDirection: 'column', 
                          justifyContent: 'space-between',
                          minHeight: 120
                        }}
                      >
                        <Stack gap="xs">
                          <Group justify="space-between" align="center">
                            <Text size="xs" fw={700}>{p.name}</Text>
                            <Badge size="xs" color={statusColor} variant="light">
                              {statusText}
                            </Badge>
                          </Group>
                          {formattedTime && (
                            <Text size="10px" c="dimmed">
                              Updated: {formattedTime}
                            </Text>
                          )}
                        </Stack>
                        <Button
                          size="xs"
                          variant="light"
                          color="indigo"
                          onClick={() => handleLogin(p.key)}
                          loading={loggingInPlatform === p.key}
                          disabled={loggingInPlatform !== null}
                          mt="sm"
                        >
                          {p.has_cookie ? t('set_auth_relogin') : t('set_auth_login')}
                        </Button>
                      </Paper>
                    );
                  })}
                </SimpleGrid>

                <Divider my="xs" label="Reusable Auth Profiles (UUID-scoped, for Trackers)" labelPosition="left" />

                {/* Create Auth Profile Form */}
                <Paper withBorder p="md" radius="sm" style={{ background: isDark ? 'rgba(0,0,0,0.1)' : '#f8f9fa' }}>
                  <form onSubmit={handleCreateProfile}>
                    <Stack gap="sm">
                      <Text size="xs" fw={700}>Create New Auth Profile</Text>
                      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm" style={{ alignItems: 'flex-end' }}>
                        <Select
                          size="xs"
                          label="Platform"
                          data={[
                            { value: 'twitter', label: 'Twitter / X' },
                            { value: 'bilibili', label: 'Bilibili (B站)' },
                            { value: 'weibo', label: 'Weibo (微博)' },
                            { value: 'xiaohongshu', label: 'Xiaohongshu (小红书)' },
                            { value: 'instagram', label: 'Instagram' },
                            { value: 'reddit', label: 'Reddit' },
                            { value: 'linkedin', label: 'LinkedIn' }
                          ]}
                          value={newProfilePlatform}
                          onChange={setNewProfilePlatform}
                        />
                        <TextInput
                          size="xs"
                          label="Display Name"
                          placeholder="e.g. Personal Acc"
                          required
                          value={newProfileName}
                          onChange={(e) => setNewProfileName(e.target.value)}
                        />
                        <Button
                          size="xs"
                          type="submit"
                          color="indigo"
                          loading={creatingProfile}
                          disabled={loggingInPlatform !== null || creatingProfile}
                        >
                          Create & Authorize
                        </Button>
                      </SimpleGrid>
                    </Stack>
                  </form>
                </Paper>

                {/* List Saved Auth Profiles */}
                <Stack gap="xs" mt="xs">
                  <Text size="xs" fw={700}>Saved Profiles</Text>
                  {profiles.length === 0 ? (
                    <Text size="xs" c="dimmed">No auth profiles created yet. Create one above to allow Trackers to scrape gated routes.</Text>
                  ) : (
                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                      {profiles.map((prof) => {
                        const isProfActive = prof.status === 'Active';
                        return (
                          <Paper
                            key={prof.id}
                            withBorder
                            p="sm"
                            radius="md"
                            style={{
                              background: isDark ? 'rgba(255,255,255,0.01)' : '#ffffff',
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center'
                            }}
                          >
                            <Stack gap={4}>
                              <Group gap="xs">
                                <Text size="xs" fw={700}>{prof.display_name}</Text>
                                <Badge size="xs" color={prof.platform === 'twitter' ? 'blue' : prof.platform === 'bilibili' ? 'pink' : 'cyan'}>
                                  {prof.platform}
                                </Badge>
                              </Group>
                              <Text size="10px" c="dimmed" style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                Ref: {prof.storage_ref}
                              </Text>
                              <Group gap="xs">
                                <Badge size="xs" color={isProfActive ? 'green' : 'red'}>
                                  {prof.status}
                                </Badge>
                                {prof.last_checked_at && (
                                  <Text size="10px" c="dimmed">
                                    Checked: {new Date(prof.last_checked_at).toLocaleTimeString()}
                                  </Text>
                                )}
                              </Group>
                            </Stack>
                            <Group gap="xs">
                              <Button
                                size="xs"
                                variant="light"
                                color="indigo"
                                onClick={() => handleTestProfile(prof.id)}
                                title="Test Health"
                              >
                                <RefreshCw size={12} />
                              </Button>
                              <Button
                                size="xs"
                                variant="light"
                                color="red"
                                onClick={() => handleDeleteProfile(prof.id)}
                                title="Delete Profile"
                              >
                                <Trash2 size={12} />
                              </Button>
                            </Group>
                          </Paper>
                        );
                      })}
                    </SimpleGrid>
                  )}
                </Stack>
              </Stack>
            </Paper>
          </Stack>
        </Tabs.Panel>

        {/* Tab 2: Local Subscribed Sources */}
        <Tabs.Panel value="local_sources" pt="md">
          <Paper withBorder p="md" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
            <Stack gap="md">
              <Group justify="space-between">
                <Group gap="xs">
                  <Database size={16} className="text-indigo-400" />
                  <Text size="sm" fw={700}>确定性订阅目标 (Local Subscribed Targets)</Text>
                </Group>
                <Button size="xs" variant="light" color="indigo" onClick={fetchLocalSources} leftSection={<RefreshCw size={12} />}>
                  {t('dash_refresh')}
                </Button>
              </Group>
              <Text size="xs" c="dimmed">网页变动监测与确定性的 RSS/社交账号直链抓取，只在数据源发生实质差异时推送。 (Deterministic RSS/HTML Diff targets)</Text>

              {loadingLocal ? (
                <Group justify="center" py="lg">
                  <Loader size="sm" />
                </Group>
              ) : subscriptions.length === 0 ? (
                <Text size="xs" c="dimmed" ta="center" py="xl">暂无本地订阅。请前往 [订阅管理] 创建。</Text>
              ) : (
                <ScrollArea>
                  <Table striped highlightOnHover>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>订阅名称</Table.Th>
                        <Table.Th>目标链接</Table.Th>
                        <Table.Th>状态</Table.Th>
                        <Table.Th>监控频率</Table.Th>
                        <Table.Th>最近抓取</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {subscriptions.map(sub => (
                        <Table.Tr key={sub.id}>
                          <Table.Tr>
                            <Table.Td><Text size="xs" fw={600}>{sub.name}</Text></Table.Td>
                            <Table.Td>
                              <Text size="xs" c="dimmed" style={{ wordBreak: 'break-all', maxWidth: 350 }}>{sub.target_url}</Text>
                            </Table.Td>
                            <Table.Td>
                              <Badge size="xs" color={sub.last_status.startsWith('Error') ? 'red' : 'green'}>
                                {sub.last_status}
                              </Badge>
                            </Table.Td>
                            <Table.Td><Text size="xs">{sub.fetch_interval_minutes} mins</Text></Table.Td>
                            <Table.Td>
                              <Text size="xs" c="dimmed">
                                {sub.last_scraped_at ? new Date(sub.last_scraped_at).toLocaleString() : 'Never'}
                              </Text>
                            </Table.Td>
                          </Table.Tr>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
              )}
            </Stack>
          </Paper>
        </Tabs.Panel>

        {/* Tab 3: Discovery Signals */}
        <Tabs.Panel value="discovery_signals" pt="md">
          <Paper withBorder p="md" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
            <Stack gap="md">
              <Group justify="space-between">
                <Group gap="xs">
                  <Satellite size={16} className="text-indigo-400" />
                  <Text size="sm" fw={700}>信号源库 (Discovery Keywords & Target Indexes)</Text>
                </Group>
                <Button size="xs" variant="light" color="indigo" onClick={fetchDiscoveryTrackers} leftSection={<RefreshCw size={12} />}>
                  {t('dash_refresh')}
                </Button>
              </Group>
              <Text size="xs" c="dimmed">聚合当前所有在轨探测主题底下的关键词与信号，系统将把它们自动解析为 Nitter、HN、Reddit 等多通道数据管线。 (Aggregated signals derived from discovery themes)</Text>

              {loadingSignals ? (
                <Group justify="center" py="lg">
                  <Loader size="sm" />
                </Group>
              ) : signals.length === 0 ? (
                <Text size="xs" c="dimmed" ta="center" py="xl">暂无在轨探测信号。请前往 [主题探测] 创建任务并加入信号源。</Text>
              ) : (
                <ScrollArea>
                  <Table striped highlightOnHover>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>信号类型</Table.Th>
                        <Table.Th>信号内容</Table.Th>
                        <Table.Th>关联主题 (Topic)</Table.Th>
                        <Table.Th>探测强度</Table.Th>
                        <Table.Th>状态</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {signals.map(sig => (
                        <Table.Tr key={sig.id}>
                          <Table.Td>
                            <Badge size="xs" color={sig.type === 'keyword' ? 'teal' : sig.type === 'account' ? 'blue' : 'purple'}>
                              {sig.type.toUpperCase()}
                            </Badge>
                          </Table.Td>
                          <Table.Td><Text size="xs" fw={600}>{sig.value}</Text></Table.Td>
                          <Table.Td><Text size="xs" c="dimmed">{sig.parentTopic}</Text></Table.Td>
                          <Table.Td><Text size="xs">{sig.intensity}</Text></Table.Td>
                          <Table.Td>
                            <Badge size="xs" color={sig.isActive ? 'green' : 'gray'}>
                              {sig.isActive ? 'Active' : 'Paused'}
                            </Badge>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
              )}
            </Stack>
          </Paper>
        </Tabs.Panel>

        {/* Tab 4: Presets & Collections */}
        <Tabs.Panel value="presets" pt="md">
          <Paper withBorder p="md" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
            <Stack gap="md">
              <Group justify="space-between" align="flex-start">
                <Stack gap={4}>
                  <Group gap="xs">
                    <Compass size={16} className="text-indigo-400" />
                    <Text size="sm" fw={700} className="title-text-color">Official Source Preset Library</Text>
                  </Group>
                  <Text size="xs" c="dimmed">
                    Curated RSS feeds, official blogs, changelogs, service status feeds, research sources, and vertical collections seeded into the local database.
                  </Text>
                </Stack>
                <Group gap="xs">
                  <Button size="xs" variant="light" color="indigo" onClick={() => {
                    fetchPresetCollections();
                    fetchSourcePresets(selectedCollectionId);
                  }} leftSection={<RefreshCw size={12} />} loading={loadingPresets}>
                    {t('dash_refresh')}
                  </Button>
                  <Button size="xs" variant="light" color="teal" onClick={seedAndRefreshPresets} loading={seedingPresets}>
                    Re-seed
                  </Button>
                </Group>
              </Group>

              <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="sm">
                <Paper withBorder p="sm" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.01)' : '#f8f9fa' }}>
                  <Stack gap={2}>
                    <Text size="xs" c="dimmed">Collections</Text>
                    <Text size="lg" fw={700}>{presetCollections.length}</Text>
                  </Stack>
                </Paper>
                <Paper withBorder p="sm" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.01)' : '#f8f9fa' }}>
                  <Stack gap={2}>
                    <Text size="xs" c="dimmed">Visible sources</Text>
                    <Text size="lg" fw={700}>{sourcePresets.length}</Text>
                  </Stack>
                </Paper>
                <Paper withBorder p="sm" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.01)' : '#f8f9fa' }}>
                  <Stack gap={2}>
                    <Text size="xs" c="dimmed">Selected collection</Text>
                    <Text size="sm" fw={700} lineClamp={1}>{selectedCollection?.title || 'All presets'}</Text>
                  </Stack>
                </Paper>
                <Paper withBorder p="sm" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.01)' : '#f8f9fa' }}>
                  <Stack gap={2}>
                    <Text size="xs" c="dimmed">Owner</Text>
                    <Badge size="sm" color="indigo" variant="light">built-in</Badge>
                  </Stack>
                </Paper>
              </SimpleGrid>

              <Select
                size="xs"
                label="Collection"
                data={collectionOptions}
                value={selectedCollectionId || '__all__'}
                onChange={(value) => setSelectedCollectionId(value === '__all__' ? null : value)}
              />

              {selectedCollection && (
                <Alert color="indigo" variant="light" icon={<Layers size={14} />}>
                  <Stack gap={4}>
                    <Text size="xs" fw={700}>{selectedCollection.title}</Text>
                    {selectedCollection.description && (
                      <Text size="xs">{selectedCollection.description}</Text>
                    )}
                    <Group gap={6}>
                      {selectedCollection.categories.map(category => (
                        <Badge key={category} size="xs" variant="light">{category}</Badge>
                      ))}
                    </Group>
                  </Stack>
                </Alert>
              )}

              {loadingPresets ? (
                <Group justify="center" py="lg">
                  <Loader size="sm" />
                </Group>
              ) : sourcePresets.length === 0 ? (
                <Stack align="center" gap="sm" py="xl">
                  <Compass size={40} className="text-indigo-400" />
                  <Text size="sm" fw={700}>No preset sources found</Text>
                  <Text size="xs" c="dimmed" ta="center" style={{ maxWidth: 520 }}>
                    The backend API is available, but the local preset seed has not populated this database yet. Use Re-seed to import the bundled official library.
                  </Text>
                  <Button size="xs" variant="light" color="teal" onClick={seedAndRefreshPresets} loading={seedingPresets}>
                    Re-seed official library
                  </Button>
                </Stack>
              ) : (
                <ScrollArea>
                  <Table striped highlightOnHover>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Source</Table.Th>
                        <Table.Th>Type</Table.Th>
                        <Table.Th>Region</Table.Th>
                        <Table.Th>Trust</Table.Th>
                        <Table.Th>URL</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {sourcePresets.map(preset => (
                        <Table.Tr key={preset.preset_id}>
                          <Table.Td>
                            <Stack gap={3}>
                              <Text size="xs" fw={700}>{preset.title}</Text>
                              {preset.description && (
                                <Text size="10px" c="dimmed" lineClamp={2}>{preset.description}</Text>
                              )}
                              <Group gap={4}>
                                {preset.tags.slice(0, 3).map(tag => (
                                  <Badge key={tag} size="xs" color="gray" variant="light">{tag}</Badge>
                                ))}
                              </Group>
                            </Stack>
                          </Table.Td>
                          <Table.Td>
                            <Badge size="xs" color={preset.source_type === 'rss' ? 'teal' : 'blue'} variant="light">
                              {preset.source_type}
                            </Badge>
                          </Table.Td>
                          <Table.Td><Text size="xs">{preset.region || 'global'}</Text></Table.Td>
                          <Table.Td>
                            <Badge size="xs" color={preset.verification_status === 'official_feed' ? 'green' : 'yellow'} variant="light">
                              {preset.verification_status}
                            </Badge>
                          </Table.Td>
                          <Table.Td>
                            <Text size="xs" c="dimmed" style={{ wordBreak: 'break-all', maxWidth: 360 }}>
                              {preset.url}
                            </Text>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
              )}
            </Stack>
          </Paper>
          <Paper withBorder p="xl" radius="md" style={{ display: 'none', background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff', textAlign: 'center' }}>
            <Stack align="center" gap="md" py="xl">
              <Compass size={48} className="text-indigo-400" />
              <Text size="lg" fw={700} className="title-text-color">{t('sources_coming_soon')}</Text>
              <Text size="sm" c="dimmed" style={{ maxWidth: 450 }}>
                OnlyFourBot 行业精选订阅合集一键导入、Preset 预设常用开发板、科技新闻媒体与优质博客源。即将推出！
              </Text>
            </Stack>
          </Paper>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
