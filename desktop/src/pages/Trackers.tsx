import { useEffect, useState, type FormEvent } from 'react';
import { 
  Text, Table, Group, Stack, Button, Badge, ActionIcon,
  Modal, TextInput, Select, NumberInput, Textarea, Loader, Paper, Menu, Checkbox
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Plus, Play, Trash2, Power, MoreVertical, Edit } from 'lucide-react';
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
  cookie_string?: string;
  created_at: string;
  last_scraped_at?: string;
}

export default function Trackers() {
  const { t } = useLanguage();
  const [trackers, setTrackers] = useState<Tracker[]>([]);
  const [loading, setLoading] = useState(true);
  const [opened, { open, close }] = useDisclosure(false);
  const [editingTracker, setEditingTracker] = useState<Tracker | null>(null);

  // Form states
  const [name, setName] = useState('');
  const [type, setType] = useState<string | null>('URL');
  const [target, setTarget] = useState('');
  const [tier, setTier] = useState<number | string>(1);
  const [section, setSection] = useState('Frontier Outpost');
  const [interval, setIntervalVal] = useState<number | string>(30);
  const [promptOverride, setPromptOverride] = useState('');
  const [cookieString, setCookieString] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Hybrid specific states
  const [urls, setUrls] = useState('');
  const [keywords, setKeywords] = useState('');
  const [accounts, setAccounts] = useState('');
  const [useDefaultOsint, setUseDefaultOsint] = useState(true);
  const [maxDays, setMaxDays] = useState<number | string>(7);

  const fetchTrackers = async () => {
    try {
      const res = await client.get<Tracker[]>('/trackers/');
      setTrackers(res.data);
    } catch (err) {
      console.error("Failed to fetch trackers:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTrackers();
  }, []);

  const handleToggle = async (id: number) => {
    try {
      const res = await client.post<Tracker>(`/trackers/${id}/toggle`);
      setTrackers(trackers.map(t => t.id === id ? res.data : t));
    } catch (err) {
      alert(t('trackers_alert_toggle_fail'));
    }
  };

  const handleRun = async (id: number) => {
    try {
      await client.post(`/trackers/${id}/run`);
      alert(t('trackers_alert_run_success'));
    } catch (err) {
      alert(t('trackers_alert_run_fail'));
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm(t('trackers_confirm_delete'))) return;
    try {
      await client.delete(`/trackers/${id}`);
      setTrackers(trackers.filter(t => t.id !== id));
    } catch (err) {
      alert(t('trackers_alert_delete_fail'));
    }
  };

  const handleStartEdit = (tracker: Tracker) => {
    setEditingTracker(tracker);
    setName(tracker.name);
    setType(tracker.tracker_type);
    setTier(tracker.tier);
    setSection(tracker.radar_section);
    setIntervalVal(tracker.fetch_interval_minutes);
    setPromptOverride(tracker.prompt_override || '');
    setCookieString(tracker.cookie_string || '');

    // Reset simple and hybrid states first
    setTarget('');
    setUrls('');
    setKeywords('');
    setAccounts('');
    setUseDefaultOsint(true);
    setMaxDays(7);

    if (tracker.tracker_type === 'HYBRID') {
      try {
        const data = JSON.parse(tracker.target);
        setUrls(data.urls ? data.urls.join('\n') : '');
        setKeywords(data.keywords ? data.keywords.join('\n') : '');
        setAccounts(data.accounts ? data.accounts.join('\n') : '');
        setUseDefaultOsint(data.use_default_osint !== false);
        setMaxDays(data.max_days !== undefined ? data.max_days : 7);
      } catch (err) {
        // Fallback: if JSON fails to parse, treat target as raw string
        setUrls(tracker.target);
      }
    } else {
      // Simple Mode (URL, KEYWORD, ACCOUNT)
      try {
        const data = JSON.parse(tracker.target);
        if (Array.isArray(data)) {
          setTarget(data.join('\n'));
        } else {
          setTarget(tracker.target);
        }
      } catch (err) {
        // If not JSON, use raw target string
        setTarget(tracker.target);
      }
    }
    open();
  };

  const handleClose = () => {
    close();
    setEditingTracker(null);
    setName('');
    setType('URL');
    setTarget('');
    setUrls('');
    setKeywords('');
    setAccounts('');
    setUseDefaultOsint(true);
    setMaxDays(7);
    setTier(1);
    setSection('Frontier Outpost');
    setIntervalVal(30);
    setPromptOverride('');
    setCookieString('');
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name) {
      alert(t('trackers_alert_fill_fields'));
      return;
    }

    let targetPayload = '';

    if (type === 'HYBRID') {
      const urlsList = urls.split('\n').map(u => u.trim()).filter(Boolean);
      const keywordsList = keywords.split('\n').map(k => k.trim()).filter(Boolean);
      const accountsList = accounts.split('\n').map(a => a.trim().replace('@', '')).filter(Boolean);

      if (urlsList.length === 0 && keywordsList.length === 0 && accountsList.length === 0) {
        alert(t('trackers_alert_fill_fields'));
        return;
      }

      targetPayload = JSON.stringify({
        urls: urlsList,
        keywords: keywordsList,
        accounts: accountsList,
        use_default_osint: useDefaultOsint,
        max_days: Number(maxDays) || 0
      });
    } else {
      // Simple Mode (URL, KEYWORD, ACCOUNT)
      const items = target.split('\n').map(x => x.trim()).filter(Boolean);
      if (items.length === 0) {
        alert(t('trackers_alert_fill_fields'));
        return;
      }
      targetPayload = JSON.stringify(items);
    }

    setSubmitting(true);
    try {
      const payload = {
        name,
        tracker_type: type || 'URL',
        target: targetPayload,
        tier: Number(tier),
        radar_section: section,
        fetch_interval_minutes: Number(interval),
        prompt_override: promptOverride || null,
        cookie_string: cookieString || null
      };

      if (editingTracker) {
        await client.put(`/trackers/${editingTracker.id}`, payload);
      } else {
        await client.post('/trackers/', payload);
      }

      handleClose();
      fetchTrackers();
    } catch (err) {
      if (editingTracker) {
        alert(t('trackers_alert_edit_fail'));
      } else {
        alert(t('trackers_alert_create_fail'));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const getDisplayTarget = (tracker: Tracker) => {
    try {
      const data = JSON.parse(tracker.target);
      if (tracker.tracker_type === 'HYBRID') {
        const parts: string[] = [];
        if (data.urls && data.urls.length > 0) parts.push(`${data.urls.length} URLs`);
        if (data.keywords && data.keywords.length > 0) parts.push(`${data.keywords.length} KWs`);
        if (data.accounts && data.accounts.length > 0) parts.push(`${data.accounts.length} Accs`);
        return parts.join(', ') || 'Empty';
      } else {
        if (Array.isArray(data)) {
          const count = data.length;
          const label = tracker.tracker_type === 'URL' ? 'URLs' : tracker.tracker_type === 'KEYWORD' ? 'KWs' : 'Accs';
          return `${count} ${label}`;
        }
        return tracker.target.length > 48 ? `${tracker.target.substring(0, 45)}...` : tracker.target;
      }
    } catch (err) {
      return tracker.target.length > 48 ? `${tracker.target.substring(0, 45)}...` : tracker.target;
    }
  };

  if (loading) {
    return (
      <Group justify="center" h="80vh">
        <Loader size="xl" type="dots" color="indigo" />
      </Group>
    );
  }

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Stack gap={0}>
          <Text size="xl" fw={700} c="white">{t('trackers_title')}</Text>
          <Text size="sm" c="dimmed">{t('trackers_desc')}</Text>
        </Stack>
        <Button 
          variant="filled" 
          color="indigo" 
          leftSection={<Plus size={16} />}
          onClick={() => { handleClose(); open(); }}
        >
          {t('trackers_add')}
        </Button>
      </Group>

      {/* Trackers Table */}
      <Paper withBorder radius="md" style={{ background: 'rgba(255,255,255,0.01)', overflow: 'hidden' }}>
        <Table verticalSpacing="md" horizontalSpacing="lg" highlightOnHover style={{ color: 'var(--mantine-color-gray-3)' }}>
          <Table.Thead style={{ background: 'rgba(255,255,255,0.02)' }}>
            <Table.Tr>
              <Table.Th style={{ color: 'white' }}>{t('trackers_col_name')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('trackers_col_type')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('trackers_col_target')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('trackers_col_section')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('trackers_col_tier')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('trackers_col_interval')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('trackers_col_status')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('trackers_col_last_run')}</Table.Th>
              <Table.Th style={{ color: 'white' }}></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {trackers.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={9} style={{ textAlign: 'center' }}>
                  <Text c="dimmed" py="lg">{t('trackers_empty')}</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              trackers.map((tItem) => (
                <Table.Tr key={tItem.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <Table.Td fw={700} c="white">{tItem.name}</Table.Td>
                  <Table.Td>
                    <Badge variant="light" color="indigo">{tItem.tracker_type}</Badge>
                  </Table.Td>
                  <Table.Td style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={tItem.tracker_type === 'HYBRID' ? tItem.target : undefined}>
                    {getDisplayTarget(tItem)}
                  </Table.Td>
                  <Table.Td>{tItem.radar_section}</Table.Td>
                  <Table.Td>
                    <Badge color="gray" variant="outline">Tier {tItem.tier}</Badge>
                  </Table.Td>
                  <Table.Td>{tItem.fetch_interval_minutes}</Table.Td>
                  <Table.Td>
                    <Badge color={tItem.is_active ? 'teal' : 'red'} variant="dot">
                      {tItem.is_active ? t('trackers_status_active') : t('trackers_status_paused')}
                    </Badge>
                  </Table.Td>
                  <Table.Td style={{ fontSize: 'var(--mantine-font-size-xs)' }}>
                    {tItem.last_scraped_at ? new Date(tItem.last_scraped_at).toLocaleString() : t('trackers_never')}
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <ActionIcon 
                        variant="subtle" 
                        color="teal" 
                        title={t('trackers_run_tooltip')}
                        onClick={() => handleRun(tItem.id)}
                      >
                        <Play size={16} />
                      </ActionIcon>
                      
                      <Menu position="bottom-end" shadow="md">
                        <Menu.Target>
                          <ActionIcon variant="subtle" color="gray">
                            <MoreVertical size={16} />
                          </ActionIcon>
                        </Menu.Target>
                        <Menu.Dropdown style={{ background: 'rgba(20,20,20,0.95)', border: '1px solid rgba(255,255,255,0.1)' }}>
                          <Menu.Item 
                            leftSection={<Edit size={14} />} 
                            onClick={() => handleStartEdit(tItem)}
                            style={{ color: 'white' }}
                          >
                            {t('trackers_menu_edit')}
                          </Menu.Item>
                          <Menu.Item 
                            leftSection={<Power size={14} />} 
                            onClick={() => handleToggle(tItem.id)}
                            style={{ color: 'white' }}
                          >
                            {tItem.is_active ? t('trackers_menu_pause') : t('trackers_menu_activate')}
                          </Menu.Item>
                          <Menu.Item 
                            leftSection={<Trash2 size={14} />} 
                            color="red"
                            onClick={() => handleDelete(tItem.id)}
                          >
                            {t('trackers_menu_delete')}
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

      {/* Add Tracker Modal */}
      <Modal 
        opened={opened} 
        onClose={handleClose} 
        title={editingTracker ? t('trackers_modal_title_edit') : t('trackers_modal_title')}
        size="md"
        centered
        styles={{
          content: { background: 'rgba(25,25,25,0.95)', border: '1px solid rgba(255,255,255,0.1)' },
          header: { background: 'rgba(25,25,25,0.95)', color: 'white' }
        }}
      >
        <form onSubmit={handleSubmit}>
          <Stack gap="md">
            <TextInput
              label={t('trackers_form_name')}
              placeholder="e.g. HuggingFace Daily"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
            />
            
            <Select
              label={t('trackers_form_type')}
              data={['URL', 'KEYWORD', 'ACCOUNT', 'HYBRID']}
              required
              value={type}
              onChange={setType}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
            />

            {type !== 'HYBRID' ? (
              <Textarea
                label={
                  type === 'URL' 
                    ? t('trackers_form_urls') 
                    : type === 'KEYWORD' 
                    ? t('trackers_form_keywords') 
                    : t('trackers_form_accounts')
                }
                placeholder={
                  type === 'URL' 
                    ? t('trackers_form_target_urls_ph') 
                    : type === 'KEYWORD' 
                    ? t('trackers_form_target_keywords_ph') 
                    : t('trackers_form_target_accounts_ph')
                }
                required
                minRows={3}
                maxRows={6}
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
              />
            ) : (
              <Stack gap="xs">
                <Textarea
                  label={t('trackers_form_urls')}
                  placeholder={t('trackers_form_target_urls_ph')}
                  minRows={2}
                  maxRows={4}
                  value={urls}
                  onChange={(e) => setUrls(e.target.value)}
                  styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
                />
                
                <Textarea
                  label={t('trackers_form_keywords')}
                  placeholder={t('trackers_form_target_keywords_ph')}
                  minRows={2}
                  maxRows={4}
                  value={keywords}
                  onChange={(e) => setKeywords(e.target.value)}
                  styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
                />

                <Textarea
                  label={t('trackers_form_accounts')}
                  placeholder={t('trackers_form_target_accounts_ph')}
                  minRows={2}
                  maxRows={4}
                  value={accounts}
                  onChange={(e) => setAccounts(e.target.value)}
                  styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
                />

                <Checkbox
                  label={t('trackers_form_use_osint')}
                  checked={useDefaultOsint}
                  onChange={(e) => setUseDefaultOsint(e.currentTarget.checked)}
                  styles={{ label: { color: 'white' } }}
                  mt="xs"
                />

                <NumberInput
                  label={t('trackers_form_max_days')}
                  min={0}
                  value={Number(maxDays)}
                  onChange={(v) => setMaxDays(v || 0)}
                  styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
                  mt="xs"
                />
              </Stack>
            )}

            <Select
              label={t('trackers_form_tier')}
              data={[
                { value: '1', label: t('trackers_tier_1') },
                { value: '2', label: t('trackers_tier_2') },
                { value: '3', label: t('trackers_tier_3') }
              ]}
              required
              value={String(tier)}
              onChange={(v) => setTier(v || 1)}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
            />

            <TextInput
              label={t('trackers_form_section')}
              placeholder="e.g. Frontier Outpost"
              required
              value={section}
              onChange={(e) => setSection(e.target.value)}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
            />

            <NumberInput
              label={t('trackers_form_interval')}
              min={5}
              required
              value={Number(interval)}
              onChange={(v) => setIntervalVal(v || 30)}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
            />

            <Textarea
              label={t('trackers_form_prompt')}
              placeholder="Custom instructions for LLM extraction/filtering..."
              value={promptOverride}
              onChange={(e) => setPromptOverride(e.target.value)}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
            />

            <Textarea
              label={t('trackers_form_cookie')}
              placeholder="Cookie string for bypassing loginwalls..."
              value={cookieString}
              onChange={(e) => setCookieString(e.target.value)}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
            />

            <Group justify="flex-end" mt="md">
              <Button variant="outline" color="gray" onClick={handleClose}>{t('trackers_btn_cancel')}</Button>
              <Button type="submit" color="indigo" loading={submitting}>
                {editingTracker ? t('trackers_btn_save') : t('trackers_btn_create')}
              </Button>
            </Group>
          </Stack>
        </form>
      </Modal>
    </Stack>
  );
}
