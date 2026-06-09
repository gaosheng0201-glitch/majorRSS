import { useEffect, useState, type FormEvent } from 'react';
import { 
  Text, Paper, Stack, Button, Textarea, Grid, ScrollArea, Accordion, Group, ActionIcon, Divider
} from '@mantine/core';
import { Send, RefreshCw } from 'lucide-react';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';

interface Investigation {
  id: number;
  query: string;
  native_result?: string;
  funnel_result?: string;
  created_at: string;
}

export default function FactChecker() {
  const { t } = useLanguage();
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [query, setQuery] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const fetchInvestigations = async () => {
    setLoadingHistory(true);
    try {
      const res = await client.get<Investigation[]>('/settings/investigations');
      setInvestigations(res.data);
    } catch (err) {
      console.error("Failed to fetch investigations:", err);
    } finally {
      setLoadingHistory(false);
    }
  };

  useEffect(() => {
    fetchInvestigations();
  }, []);

  const handleInvestigateSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!query || !query.trim()) return;

    setSubmitting(true);
    try {
      await client.post('/settings/investigate', { query });
      alert(t('factcheck_alert_success'));
      setQuery('');
      // Wait a moment then refresh history
      setTimeout(fetchInvestigations, 3000);
    } catch (err) {
      alert(t('factcheck_alert_fail'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Stack gap="lg">
      <Stack gap={0}>
        <Text size="xl" fw={700} c="white">{t('factcheck_title')}</Text>
        <Text size="sm" c="dimmed">{t('factcheck_desc')}</Text>
      </Stack>

      <Grid>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
            <form onSubmit={handleInvestigateSubmit}>
              <Stack gap="md">
                <Text size="md" fw={700} c="white">{t('factcheck_active_pipeline')}</Text>
                <Text size="xs" c="dimmed">
                  {t('factcheck_pipeline_desc')}
                </Text>

                <Textarea
                  required
                  placeholder={t('factcheck_input')}
                  minRows={4}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  styles={{ input: { background: 'rgba(255,255,255,0.05)', color: 'white' } }}
                />

                <Button 
                  type="submit" 
                  color="indigo" 
                  loading={submitting}
                  leftSection={<Send size={14} />}
                >
                  {t('factcheck_btn')}
                </Button>
              </Stack>
            </form>
          </Paper>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 7 }}>
          <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
            <Group justify="space-between" mb="md">
              <Text size="md" fw={700} c="white">{t('factcheck_history')}</Text>
              <ActionIcon variant="subtle" color="gray" onClick={fetchInvestigations} loading={loadingHistory}>
                <RefreshCw size={16} />
              </ActionIcon>
            </Group>

            <ScrollArea h="55vh" scrollbarSize={6}>
              {investigations.length === 0 ? (
                <Text size="sm" c="dimmed" ta="center" py="xl">{t('factcheck_empty')}</Text>
              ) : (
                <Accordion variant="separated" styles={{
                  item: { background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.05)' },
                  control: { color: 'white' },
                  content: { color: 'var(--mantine-color-gray-3)' }
                }}>
                  {investigations.map((inv) => (
                    <Accordion.Item key={inv.id} value={String(inv.id)}>
                      <Accordion.Control>
                        <Group justify="space-between">
                          <Text size="sm" fw={700} style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {inv.query}
                          </Text>
                          <Text size="xs" c="dimmed" mr="md">
                            {new Date(inv.created_at).toLocaleDateString()}
                          </Text>
                        </Group>
                      </Accordion.Control>
                      <Accordion.Panel>
                        <Stack gap="md">
                          <Text size="sm" style={{ borderLeft: '3px solid var(--mantine-color-indigo-6)', paddingLeft: 8 }}>
                            <strong>{t('factcheck_query_label')}:</strong> {inv.query}
                          </Text>
                          <Divider style={{ borderColor: 'rgba(255,255,255,0.05)' }} />
                          <Grid>
                            <Grid.Col span={{ base: 12, md: 6 }}>
                              <Text size="xs" fw={700} c="indigo" mb="xs">{t('factcheck_native_title')}</Text>
                              <ScrollArea h={200} p="xs" style={{ background: 'rgba(255,255,255,0.02)', borderRadius: 4 }}>
                                <Text size="xs" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                                  {inv.native_result || t('factcheck_processing')}
                                </Text>
                              </ScrollArea>
                            </Grid.Col>
                            <Grid.Col span={{ base: 12, md: 6 }}>
                              <Text size="xs" fw={700} c="teal" mb="xs">{t('factcheck_funnel_title')}</Text>
                              <ScrollArea h={200} p="xs" style={{ background: 'rgba(255,255,255,0.02)', borderRadius: 4 }}>
                                <Text size="xs" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                                  {inv.funnel_result || t('factcheck_processing')}
                                </Text>
                              </ScrollArea>
                            </Grid.Col>
                          </Grid>
                        </Stack>
                      </Accordion.Panel>
                    </Accordion.Item>
                  ))}
                </Accordion>
              )}
            </ScrollArea>
          </Paper>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
