import { useEffect, useState } from 'react';
import { 
  Text, Paper, SimpleGrid, Group, Stack, Table, ScrollArea, Loader, RingProgress
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
  const [loading, setLoading] = useState(true);
  const [tokenSummary, setTokenSummary] = useState<TokenUsageSummary>({});
  const [rawUsage, setRawUsage] = useState<TokenUsageRecord[]>([]);
  const [trendData, setTrendData] = useState<{ date: string; tokens: number }[]>([]);

  const fetchTokenUsage = async () => {
    try {
      const res = await client.get<{ 
        summary: TokenUsageSummary; 
        raw_usage: TokenUsageRecord[];
        daily_trend: { date: string; tokens: number }[]
      }>('/settings/token-usage');
      setTokenSummary(res.data.summary);
      setRawUsage(res.data.raw_usage);
      setTrendData(res.data.daily_trend || []);
    } catch (err) {
      console.error("Failed to fetch token usage:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTokenUsage();
  }, []);

  // Compute total tokens and estimated costs
  let flashTokens = 0;
  let proTokens = 0;
  Object.entries(tokenSummary).forEach(([model, data]) => {
    if (model.toLowerCase().includes('flash')) {
      flashTokens += data.total_tokens;
    } else if (model.toLowerCase().includes('pro')) {
      proTokens += data.total_tokens;
    }
  });

  const estCost = (flashTokens / 1000000) * 0.15 + (proTokens / 1000000) * 2.5;

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
        <Text size="xl" fw={700} c="white">{t('bill_title')}</Text>
        <Text size="sm" c="dimmed">{t('bill_desc')}</Text>
      </Stack>

      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
        {/* Gemini 3 Flash Metric */}
        <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
          <Group justify="space-between">
            <Stack gap={2}>
              <Text size="xs" c="dimmed" fw={700} tt="uppercase">{t('bill_flash_tokens')}</Text>
              <Text size="xl" fw={700} c="white">{flashTokens.toLocaleString()}</Text>
              <Text size="xs" c="indigo.4">{t('bill_flash_desc')}</Text>
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
        <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
          <Group justify="space-between">
            <Stack gap={2}>
              <Text size="xs" c="dimmed" fw={700} tt="uppercase">{t('bill_pro_tokens')}</Text>
              <Text size="xl" fw={700} c="white">{proTokens.toLocaleString()}</Text>
              <Text size="xs" c="teal.4">{t('bill_pro_desc')}</Text>
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
        <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
          <Group justify="space-between">
            <Stack gap={2}>
              <Text size="xs" c="dimmed" fw={700} tt="uppercase">{t('bill_est_cost')}</Text>
              <Text size="xl" fw={700} c="white">${estCost.toFixed(4)}</Text>
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
      <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
        <Text size="md" fw={700} c="white" mb="xl">{t('bill_daily_trend')}</Text>
        {trendData.length === 0 ? (
          <Text size="sm" c="dimmed" ta="center" py="xl">{t('bill_daily_empty')}</Text>
        ) : (
          <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-around', height: 160, paddingBottom: 20 }}>
            {trendData.map((d, index) => {
              const barHeight = Math.max((d.tokens / maxTokens) * 100, 6); // Max height of 100px
              return (
                <div key={index} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '8%' }}>
                  <Text size="xs" c="white" fw={700} mb={4}>
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
      <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
        <Text size="md" fw={700} c="white" mb="md">{t('bill_recent')}</Text>
        <ScrollArea h="35vh" scrollbarSize={6}>
          <Table verticalSpacing="md" horizontalSpacing="lg" style={{ color: 'var(--mantine-color-gray-3)' }}>
            <Table.Thead style={{ background: 'rgba(255,255,255,0.02)' }}>
              <Table.Tr>
                <Table.Th style={{ color: 'white' }}>{t('bill_col_time')}</Table.Th>
                <Table.Th style={{ color: 'white' }}>{t('bill_col_action')}</Table.Th>
                <Table.Th style={{ color: 'white' }}>{t('bill_col_model')}</Table.Th>
                <Table.Th style={{ color: 'white' }}>{t('bill_col_prompt')}</Table.Th>
                <Table.Th style={{ color: 'white' }}>{t('bill_col_comp')}</Table.Th>
                <Table.Th style={{ color: 'white' }}>{t('bill_col_total')}</Table.Th>
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
                  <Table.Tr key={u.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
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
