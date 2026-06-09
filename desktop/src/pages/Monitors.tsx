import { useEffect, useState } from 'react';
import { 
  Text, Table, Group, Stack, Button, Badge, ActionIcon,
  Modal, TextInput, NumberInput, Loader, Paper, Menu, Card, ScrollArea
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Plus, Trash2, Power, MoreVertical, Eye, Play } from 'lucide-react';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';

interface Subscription {
  id: number;
  name: string;
  target_url: string;
  is_active: boolean;
  fetch_interval_minutes: number;
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

export default function Monitors() {
  const { t } = useLanguage();
  const [monitors, setMonitors] = useState<Subscription[]>([]);
  const [updates, setUpdates] = useState<SubscriptionUpdate[]>([]);
  const [loading, setLoading] = useState(true);
  const [opened, { open, close }] = useDisclosure(false);

  // Form states
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [interval, setIntervalVal] = useState<number | string>(60);
  const [submitting, setSubmitting] = useState(false);

  const fetchData = async () => {
    try {
      const [monitorsRes, updatesRes] = await Promise.all([
        client.get<Subscription[]>('/monitors/'),
        client.get<SubscriptionUpdate[]>('/monitors/updates')
      ]);
      setMonitors(monitorsRes.data);
      setUpdates(updatesRes.data);
    } catch (err) {
      console.error("Failed to fetch webpage monitors data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleToggle = async (id: number) => {
    try {
      const res = await client.post<Subscription>(`/monitors/${id}/toggle`);
      setMonitors(monitors.map(m => m.id === id ? res.data : m));
    } catch (err) {
      alert(t('monitors_alert_toggle_fail'));
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm(t('monitors_confirm_delete'))) return;
    try {
      await client.delete(`/monitors/${id}`);
      setMonitors(monitors.filter(m => m.id !== id));
    } catch (err) {
      alert(t('monitors_alert_delete_fail'));
    }
  };

  const handleRunAll = async () => {
    try {
      await client.post('/monitors/run');
      alert(t('monitors_alert_run_success'));
    } catch (err) {
      alert(t('monitors_alert_run_fail'));
    }
  };

  const handleMarkAsRead = async (updateId: number) => {
    try {
      await client.post(`/monitors/updates/${updateId}/read`);
      setUpdates(updates.map(u => u.id === updateId ? { ...u, is_read: true } : u));
    } catch (err) {
      alert(t('monitors_alert_read_fail'));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !url) return;

    setSubmitting(true);
    try {
      await client.post('/monitors/', {
        name,
        target_url: url,
        fetch_interval_minutes: Number(interval)
      });
      close();
      setName('');
      setUrl('');
      fetchData();
    } catch (err) {
      alert(t('monitors_alert_create_fail'));
    } finally {
      setSubmitting(false);
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
          <Text size="xl" fw={700} c="white">{t('monitors_title')}</Text>
          <Text size="sm" c="dimmed">{t('monitors_desc')}</Text>
        </Stack>
        <Group>
          <Button 
            variant="light" 
            color="indigo" 
            leftSection={<Play size={16} />}
            onClick={handleRunAll}
          >
            {t('monitors_btn_run_all')}
          </Button>
          <Button 
            variant="filled" 
            color="indigo" 
            leftSection={<Plus size={16} />}
            onClick={open}
          >
            {t('monitors_btn_add')}
          </Button>
        </Group>
      </Group>

      {/* Monitors Table */}
      <Paper withBorder radius="md" style={{ background: 'rgba(255,255,255,0.01)', overflow: 'hidden' }}>
        <Table verticalSpacing="md" horizontalSpacing="lg" highlightOnHover style={{ color: 'var(--mantine-color-gray-3)' }}>
          <Table.Thead style={{ background: 'rgba(255,255,255,0.02)' }}>
            <Table.Tr>
              <Table.Th style={{ color: 'white' }}>{t('monitors_col_name')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('monitors_col_url')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('monitors_col_interval')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('monitors_col_status')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('monitors_col_last_status')}</Table.Th>
              <Table.Th style={{ color: 'white' }}>{t('monitors_col_last_run')}</Table.Th>
              <Table.Th style={{ color: 'white' }}></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {monitors.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={7} style={{ textAlign: 'center' }}>
                  <Text c="dimmed" py="lg">{t('monitors_empty')}</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              monitors.map((m) => (
                <Table.Tr key={m.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <Table.Td fw={700} c="white">{m.name}</Table.Td>
                  <Table.Td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {m.target_url}
                  </Table.Td>
                  <Table.Td>{m.fetch_interval_minutes}</Table.Td>
                  <Table.Td>
                    <Badge color={m.is_active ? 'teal' : 'red'} variant="dot">
                      {m.is_active ? t('trackers_status_active') : t('trackers_status_paused')}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="light" color={m.last_status === 'Success' ? 'teal' : m.last_status === 'Idle' ? 'gray' : 'red'}>
                      {m.last_status === 'Success' ? t('monitors_status_success') : m.last_status === 'Idle' ? t('monitors_status_idle') : t('monitors_status_failed')}
                    </Badge>
                  </Table.Td>
                  <Table.Td style={{ fontSize: 'var(--mantine-font-size-xs)' }}>
                    {m.last_scraped_at ? new Date(m.last_scraped_at).toLocaleString() : t('trackers_never')}
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <Menu position="bottom-end" shadow="md">
                        <Menu.Target>
                          <ActionIcon variant="subtle" color="gray">
                            <MoreVertical size={16} />
                          </ActionIcon>
                        </Menu.Target>
                        <Menu.Dropdown style={{ background: 'rgba(20,20,20,0.95)', border: '1px solid rgba(255,255,255,0.1)' }}>
                          <Menu.Item 
                            leftSection={<Power size={14} />} 
                            onClick={() => handleToggle(m.id)}
                            style={{ color: 'white' }}
                          >
                            {m.is_active ? t('trackers_menu_pause') : t('trackers_menu_activate')}
                          </Menu.Item>
                          <Menu.Item 
                            leftSection={<Trash2 size={14} />} 
                            color="red"
                            onClick={() => handleDelete(m.id)}
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

      {/* Updates Stream */}
      <Stack gap="xs">
        <Text size="lg" fw={700} c="white">{t('monitors_stream_title')}</Text>
        <ScrollArea h="40vh" scrollbarSize={6}>
          <Stack gap="md">
            {updates.length === 0 ? (
              <Paper withBorder p="xl" radius="md" style={{ background: 'transparent', textAlign: 'center' }}>
                <Text c="dimmed">{t('monitors_stream_empty')}</Text>
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
                        <Text size="sm" fw={700} c="white">{up.subscription_name}</Text>
                        {!up.is_read && <Badge size="xs" color="indigo">{t('monitors_badge_new')}</Badge>}
                      </Group>
                      <Text size="xs" c="dimmed">{new Date(up.created_at).toLocaleString()}</Text>
                    </Stack>
                    
                    {!up.is_read && (
                      <ActionIcon 
                        variant="subtle" 
                        color="indigo" 
                        title={t('monitors_mark_read')}
                        onClick={() => handleMarkAsRead(up.id)}
                      >
                        <Eye size={16} />
                      </ActionIcon>
                    )}
                  </Group>

                  <Stack gap="xs" mt="sm">
                    {up.llm_summary ? (
                      <Text size="sm" c="gray.3" style={{ lineHeight: 1.5 }}>
                        <strong>{t('monitors_ai_summary_label')}</strong> {up.llm_summary}
                      </Text>
                    ) : (
                      <Text size="sm" c="gray.3" style={{ fontStyle: 'italic' }}>
                        {t('monitors_ai_summary_empty')}
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

      {/* Add Monitor Modal */}
      <Modal 
        opened={opened} 
        onClose={close} 
        title={t('monitors_modal_title')}
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
              label={t('monitors_form_name')}
              placeholder="e.g. NVIDIA Press Releases"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
            />

            <TextInput
              label={t('monitors_form_url')}
              placeholder="https://example.com/page"
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
            />

            <NumberInput
              label={t('monitors_form_interval')}
              min={10}
              required
              value={Number(interval)}
              onChange={(v) => setIntervalVal(v || 60)}
              styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' }, label: { color: 'white' } }}
            />

            <Group justify="flex-end" mt="md">
              <Button variant="outline" color="gray" onClick={close}>{t('monitors_btn_cancel')}</Button>
              <Button type="submit" color="indigo" loading={submitting}>{t('monitors_btn_add_confirm')}</Button>
            </Group>
          </Stack>
        </form>
      </Modal>
    </Stack>
  );
}
