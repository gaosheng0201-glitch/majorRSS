import { useEffect, useState } from 'react';
import { 
  Text, Paper, SimpleGrid, Group, Stack, Table, ScrollArea, Loader, RingProgress,
  useMantineColorScheme
} from '@mantine/core';
import { Database, DollarSign, Activity } from 'lucide-react';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';

interface TokenUsageRecord {
  id: number;
  model_name: string;
  action_type: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  created_at: string;
}

interface TokenUsageSummary {
  [model_name: string]: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    calls: number;
  };
}

export default function Billing() {
  const { t } = useLanguage();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const [loading, setLoading] = useState(true);
  const [tokenSummary, setTokenSummary] = useState<TokenUsageSummary>({});
  const [rawUsage, setRawUsage] = useState<TokenUsageRecord[]>([]);
  const [trendData, setTrendData] = useState<{ date: string; tokens: number }[]>([]);
  const [estCost, setEstCost] = useState(0);

  const fetchTokenUsage = async () => {
    try {
      const res = await client.get<{
        summary: TokenUsageSummary;
        raw_usage: TokenUsageRecord[];
        daily_trend: { date: string; tokens: number }[];
        estimated_cost_usd: number;
      }>('/settings/token-usage');
      setTokenSummary(res.data.summary);
      setRawUsage(res.data.raw_usage);
      setTrendData(res.data.daily_trend || []);
      // Cost is computed backend-side per model (input/output priced separately,
      // embeddings included) — see services/pricing.py.
      setEstCost(res.data.estimated_cost_usd || 0);
    } catch (err) {
      console.error("Failed to fetch token usage:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTokenUsage();
  }, []);

  // Split flash/pro token counts for the two headline tiles (display only).
  let flashTokens = 0;
  let proTokens = 0;
  Object.entries(tokenSummary).forEach(([model, data]) => {
    if (model.toLowerCase().includes('flash')) {
      flashTokens += data.total_tokens;
    } else if (model.toLowerCase().includes('pro')) {
      proTokens += data.total_tokens;
    }
  });

  const maxTokens = Math.max(...trendData.map(d => d.tokens), 1);

  if (loading) {
    return (
      <Group justify="center" h="80vh">
        <Loader size="xl" type="dots" color="indigo" />
      </Group>
    );
  }

  return (
    <Stack gap="lg">
      <Stack gap={0}>
        <Text size="xl" fw={700} className="title-text-color">{t('bill_title')}</Text>
        <Text size="sm" c="dimmed">{t('bill_desc')}</Text>
      </Stack>

      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
        {/* Gemini 3 Flash Metric */}
        <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
          <Group justify="space-between">
            <Stack gap={2}>
              <Text size="xs" c="dimmed" fw={700} tt="uppercase">{t('bill_flash_tokens')}</Text>
              <Text size="xl" fw={700} className="title-text-color">{flashTokens.toLocaleString()}</Text>
              <Text size="xs" c={isDark ? "indigo.4" : "indigo.7"}>{t('bill_flash_desc')}</Text>
            </Stack>
            <RingProgress
              size={60}
              thickness={6}
              sections={[{ value: 100, color: 'indigo' }]}
              label={
                <Group justify="center">
                  <Database size={16} className="text-gray-400" />
                </Group>
              }
            />
          </Group>
        </Paper>

        {/* Gemini 3.1 Pro Metric */}
        <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
          <Group justify="space-between">
            <Stack gap={2}>
              <Text size="xs" c="dimmed" fw={700} tt="uppercase">{t('bill_pro_tokens')}</Text>
              <Text size="xl" fw={700} className="title-text-color">{proTokens.toLocaleString()}</Text>
              <Text size="xs" c={isDark ? "teal.4" : "teal.7"}>{t('bill_pro_desc')}</Text>
            </Stack>
            <RingProgress
              size={60}
              thickness={6}
              sections={[{ value: 100, color: 'teal' }]}
              label={
                <Group justify="center">
                  <Activity size={16} className="text-gray-400" />
                </Group>
              }
            />
          </Group>
        </Paper>

        {/* Total Cost Metric */}
        <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
          <Group justify="space-between">
            <Stack gap={2}>
              <Text size="xs" c="dimmed" fw={700} tt="uppercase">{t('bill_est_cost')}</Text>
              <Text size="xl" fw={700} className="title-text-color">${estCost.toFixed(4)}</Text>
              <Text size="xs" c="dimmed">{t('bill_cost_desc')}</Text>
            </Stack>
            <RingProgress
              size={60}
              thickness={6}
              sections={[{ value: 100, color: 'emerald' }]}
              label={
                <Group justify="center">
                  <DollarSign size={16} className="text-gray-400" />
                </Group>
              }
            />
          </Group>
        </Paper>
      </SimpleGrid>

      {/* Daily Consumption Bar Chart */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <Text size="md" fw={700} className="title-text-color" mb="xl">{t('bill_daily_trend')}</Text>
        {trendData.length === 0 ? (
          <Text size="sm" c="dimmed" ta="center" py="xl">{t('bill_daily_empty')}</Text>
        ) : (
          <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-around', height: 160, paddingBottom: 20 }}>
            {trendData.map((d, index) => {
              const barHeight = Math.max((d.tokens / maxTokens) * 100, 6); // Max height of 100px
              return (
                <div key={index} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '8%' }}>
                  <Text size="xs" className="title-text-color" fw={700} mb={4}>
                    {d.tokens > 1000 ? `${(d.tokens / 1000).toFixed(1)}k` : d.tokens}
                  </Text>
                  <div style={{ 
                    height: `${barHeight}px`, 
                    width: 20, 
                    background: 'linear-gradient(180deg, var(--mantine-color-indigo-6) 0%, var(--mantine-color-indigo-9) 100%)', 
                    borderRadius: '4px 4px 0 0',
                    boxShadow: '0 0 10px rgba(92, 124, 250, 0.3)',
                    transition: 'height 0.3s ease'
                  }} />
                  <Text size="xs" c="dimmed" mt="xs" style={{ whiteSpace: 'nowrap' }}>
                    {d.date}
                  </Text>
                </div>
              );
            })}
          </div>
        )}
      </Paper>

      {/* Recent Usage table */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <Text size="md" fw={700} className="title-text-color" mb="md">{t('bill_recent')}</Text>
        <ScrollArea h="35vh" scrollbarSize={6}>
          <Table verticalSpacing="md" horizontalSpacing="lg" style={{ color: isDark ? 'var(--mantine-color-gray-3)' : '#495057' }}>
            <Table.Thead style={{ background: isDark ? 'rgba(255,255,255,0.02)' : '#f8f9fa' }}>
              <Table.Tr>
                <Table.Th>{t('bill_col_time')}</Table.Th>
                <Table.Th>{t('bill_col_action')}</Table.Th>
                <Table.Th>{t('bill_col_model')}</Table.Th>
                <Table.Th>{t('bill_col_prompt')}</Table.Th>
                <Table.Th>{t('bill_col_comp')}</Table.Th>
                <Table.Th>{t('bill_col_total')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rawUsage.length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={6} align="center">
                    <Text c="dimmed">{t('bill_no_logs')}</Text>
                  </Table.Td>
                </Table.Tr>
              ) : (
                rawUsage.slice(0, 20).map((u) => (
                  <Table.Tr key={u.id} style={{ borderBottom: isDark ? '1px solid rgba(255,255,255,0.05)' : '1px solid rgba(0,0,0,0.08)' }}>
                    <Table.Td>{new Date(u.created_at).toLocaleString()}</Table.Td>
                    <Table.Td>{u.action_type}</Table.Td>
                    <Table.Td>{u.model_name}</Table.Td>
                    <Table.Td>{u.prompt_tokens.toLocaleString()}</Table.Td>
                    <Table.Td>{u.completion_tokens.toLocaleString()}</Table.Td>
                    <Table.Td fw={700} c="indigo">{u.total_tokens.toLocaleString()}</Table.Td>
                  </Table.Tr>
                ))
              )}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Paper>
    </Stack>
  );
}
