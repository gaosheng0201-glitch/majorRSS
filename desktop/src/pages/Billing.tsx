import { useEffect, useState } from 'react';
import { 
  Text, Paper, SimpleGrid, Group, Stack, Table, ScrollArea, Loader, RingProgress,
  useMantineColorScheme
} from '@mantine/core';
import { Database, DollarSign, Activity } from 'lucide-react';
import client from '../api/client';
import UsageHeatmap, { type DailyUsage } from '../components/UsageHeatmap';
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

interface CostBucket {
  [key: string]: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    calls: number;
    estimated_cost_usd: number;
  };
}

export default function Billing() {
  const { t } = useLanguage();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const [loading, setLoading] = useState(true);
  const [tokenSummary, setTokenSummary] = useState<TokenUsageSummary>({});
  const [rawUsage, setRawUsage] = useState<TokenUsageRecord[]>([]);
  const [trendData, setTrendData] = useState<DailyUsage[]>([]);
  const [estCost, setEstCost] = useState(0);
  const [byCategory, setByCategory] = useState<CostBucket>({});
  const [byTarget, setByTarget] = useState<CostBucket>({});

  const fetchTokenUsage = async () => {
    try {
      const res = await client.get<{
        summary: TokenUsageSummary;
        by_category: CostBucket;
        by_target: CostBucket;
        raw_usage: TokenUsageRecord[];
        daily_trend: DailyUsage[];
        estimated_cost_usd: number;
      }>('/settings/token-usage');
      setTokenSummary(res.data.summary);
      setRawUsage(res.data.raw_usage);
      setTrendData(res.data.daily_trend || []);
      setByCategory(res.data.by_category || {});
      setByTarget(res.data.by_target || {});
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


  const catRows = Object.entries(byCategory).sort((a, b) => b[1].estimated_cost_usd - a[1].estimated_cost_usd);
  const targetRows = Object.entries(byTarget).sort((a, b) => b[1].estimated_cost_usd - a[1].estimated_cost_usd);
  const maxCatCost = Math.max(...catRows.map(([, v]) => v.estimated_cost_usd), 0.000001);

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

      {/* Daily consumption as a calendar heatmap. Was a bar chart; see
          components/UsageHeatmap.tsx for why the geometry changed. */}
      <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
        <Text size="md" fw={700} className="title-text-color" mb="xl">{t('bill_daily_trend')}</Text>
        {trendData.length === 0 ? (
          <Text size="sm" c="dimmed" ta="center" py="xl">{t('bill_daily_empty')}</Text>
        ) : (
          <UsageHeatmap data={trendData} isDark={isDark} />
        )}
      </Paper>

      {/* Cost breakdown: by category (where the money goes) + by target (P1.2) */}
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
          <Text size="md" fw={700} className="title-text-color" mb="md">{t('bill_by_category')}</Text>
          <Stack gap="sm">
            {catRows.length === 0 ? (
              <Text size="sm" c="dimmed">—</Text>
            ) : catRows.map(([k, v]) => (
              <div key={k}>
                <Group justify="space-between" mb={4}>
                  <Text size="sm" className="title-text-color">{k}</Text>
                  <Text size="sm" fw={700} c={isDark ? 'teal.4' : 'teal.7'}>${v.estimated_cost_usd.toFixed(3)}</Text>
                </Group>
                <div style={{ height: 6, background: isDark ? 'rgba(255,255,255,0.06)' : '#eee', borderRadius: 3 }}>
                  <div style={{
                    height: 6,
                    width: `${(v.estimated_cost_usd / maxCatCost) * 100}%`,
                    background: 'linear-gradient(90deg, var(--mantine-color-indigo-6), var(--mantine-color-indigo-9))',
                    borderRadius: 3,
                  }} />
                </div>
                <Text size="xs" c="dimmed" mt={2}>{v.calls} calls · {(v.total_tokens / 1000).toFixed(0)}k tok</Text>
              </div>
            ))}
          </Stack>
        </Paper>

        <Paper withBorder p="lg" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff' }}>
          <Text size="md" fw={700} className="title-text-color" mb="md">{t('bill_by_target')}</Text>
          <Table verticalSpacing="sm" style={{ color: isDark ? 'var(--mantine-color-gray-3)' : '#495057' }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('bill_col_target')}</Table.Th>
                <Table.Th>{t('bill_col_calls')}</Table.Th>
                <Table.Th>{t('bill_col_cost')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {targetRows.length === 0 ? (
                <Table.Tr><Table.Td colSpan={3}><Text c="dimmed" size="sm">—</Text></Table.Td></Table.Tr>
              ) : targetRows.map(([k, v]) => (
                <Table.Tr key={k}>
                  <Table.Td>{k}</Table.Td>
                  <Table.Td>{v.calls}</Table.Td>
                  <Table.Td fw={700} c={isDark ? 'teal.4' : 'teal.7'}>${v.estimated_cost_usd.toFixed(3)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      </SimpleGrid>

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
