import { useEffect, useState } from 'react';
import {
  Text, Paper, Badge, Group, Stack, SimpleGrid, ScrollArea, Loader, Anchor, UnstyledButton,
  useMantineColorScheme,
} from '@mantine/core';
import { Radar as RadarIcon, RefreshCw, ChevronDown, ChevronRight, Zap, ShieldCheck, Link as LinkIcon } from 'lucide-react';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';

interface ThreadSource { title: string; url: string; }
interface StoryThread {
  id: number;
  tracker_id: number | null;
  title: string | null;
  lifecycle: 'LEAD' | 'CORROBORATED' | 'CONFIRMED';
  distinct_source_count: number;
  member_count: number;
  is_resonant: boolean;
  resonance_score: number;
  last_update_at: string | null;
  first_seen_at: string | null;
  alert_reasons: string[];
  sources: ThreadSource[];
}

// Lifecycle groups in importance order — CONFIRMED first.
const LIFECYCLE_ORDER: StoryThread['lifecycle'][] = ['CONFIRMED', 'CORROBORATED', 'LEAD'];

const LIFECYCLE_META: Record<string, { color: string; en: string; zh: string; hint_en: string; hint_zh: string }> = {
  CONFIRMED: { color: 'green', en: 'Confirmed', zh: '已证实', hint_en: 'A first-party / official source is present', hint_zh: '已有一手 / 官方来源' },
  CORROBORATED: { color: 'blue', en: 'Corroborated', zh: '多源佐证', hint_en: '2+ independent sources agree', hint_zh: '2+ 个独立来源印证' },
  LEAD: { color: 'gray', en: 'Lead', zh: '线报', hint_en: 'Single, unverified source', hint_zh: '单一来源，尚未证实' },
};

const REASON_LABEL: Record<string, { en: string; zh: string }> = {
  RESONANCE: { en: 'Cross-source resonance', zh: '跨源共振' },
  CONFIRMED_HIGH_ATTENTION: { en: 'Confirmed on a high-attention target', zh: '高关注目标已证实' },
  CORROBORATED_HIGH_ATTENTION: { en: 'Corroborated on a high-attention target', zh: '高关注目标多源佐证' },
};

function ThreadCard({ th, isDark, lang }: { th: StoryThread; isDark: boolean; lang: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Paper withBorder p="md" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.02)' : '#ffffff' }}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          <Text size="sm" fw={700} className="title-text-color" lineClamp={2}>
            {th.title || (lang === 'zh' ? '未命名线索' : 'Untitled thread')}
          </Text>
          {/* Lifecycle is conveyed by the group header — don't repeat it per card.
              Keep only the per-card signal (resonance) + a quiet source count. */}
          <Group gap="xs">
            {th.is_resonant && (
              <Badge size="xs" color="orange" variant="filled" leftSection={<Zap size={10} />}>
                {lang === 'zh' ? `共振 ×${th.distinct_source_count}` : `Resonant ×${th.distinct_source_count}`}
              </Badge>
            )}
            <Text size="10px" c="dimmed">
              {th.distinct_source_count} {lang === 'zh' ? '个来源' : 'sources'} · {th.member_count} {lang === 'zh' ? '条' : 'items'}
            </Text>
          </Group>
        </Stack>
      </Group>

      {/* Why am I being interrupted? — alert reasons. */}
      {th.alert_reasons.length > 0 && (
        <Group gap="xs" mt="xs">
          <ShieldCheck size={13} className="text-indigo-400" />
          <Text size="10px" fw={600} c="dimmed">{lang === 'zh' ? '为什么提醒你：' : 'Why flagged: '}</Text>
          {th.alert_reasons.map(r => (
            <Badge key={r} size="9px" color="indigo" variant="dot">
              {(REASON_LABEL[r] ? (lang === 'zh' ? REASON_LABEL[r].zh : REASON_LABEL[r].en) : r)}
            </Badge>
          ))}
        </Group>
      )}

      {/* Source citations — traceable to origin (溯源). */}
      {th.sources.length > 0 && (
        <>
          <UnstyledButton onClick={() => setOpen(o => !o)} mt="sm">
            <Group gap={4}>
              {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              <LinkIcon size={12} className="text-indigo-400" />
              <Text size="11px" fw={600} c="dimmed">
                {lang === 'zh' ? `来源溯源 (${th.sources.length})` : `Sources (${th.sources.length})`}
              </Text>
            </Group>
          </UnstyledButton>
          {open && (
            <Stack gap={4} mt={6} pl="md">
              {th.sources.map((s, i) => (
                <Anchor key={i} href={/^https?:\/\//i.test(s.url) ? s.url : undefined} target="_blank" rel="noopener noreferrer" size="11px" lineClamp={1} c="indigo">
                  {s.title || s.url}
                </Anchor>
              ))}
            </Stack>
          )}
        </>
      )}
    </Paper>
  );
}

interface CatchUp {
  since: string;
  updated_threads: number;
  resonant: number;
  confirmed: number;
}

const LAST_SEEN_KEY = 'radar_last_seen_at';

export default function Radar() {
  const { lang } = useLanguage();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const [threads, setThreads] = useState<StoryThread[]>([]);
  const [loading, setLoading] = useState(true);
  const [catchup, setCatchup] = useState<CatchUp | null>(null);
  // Snapshot the previous "last seen" once on mount, before we overwrite it —
  // this is the anchor for "since you last looked".
  const [sinceAnchor] = useState<string | null>(() => localStorage.getItem(LAST_SEEN_KEY));

  const fetchThreads = async () => {
    setLoading(true);
    try {
      const res = await client.get<StoryThread[]>('/intelligence/threads?limit=60');
      setThreads(res.data || []);
    } catch (e) {
      console.error('Failed to load threads', e);
    } finally {
      setLoading(false);
    }
  };

  const fetchCatchup = async () => {
    // Only meaningful if the user has looked before.
    if (!sinceAnchor) return;
    try {
      const res = await client.get<CatchUp>(`/intelligence/catchup?since=${encodeURIComponent(sinceAnchor)}`);
      setCatchup(res.data);
    } catch (e) {
      console.error('Failed to load catch-up', e);
    }
  };

  useEffect(() => {
    fetchThreads();
    fetchCatchup();
    // Mark "seen now" so the next visit measures increments since this one.
    localStorage.setItem(LAST_SEEN_KEY, new Date().toISOString());
    const t = setInterval(fetchThreads, 30000);
    return () => clearInterval(t);
  }, []);

  const grouped = LIFECYCLE_ORDER.map(lc => ({
    lifecycle: lc,
    meta: LIFECYCLE_META[lc],
    items: threads.filter(t => t.lifecycle === lc),
  })).filter(g => g.items.length > 0);

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Stack gap={0}>
          <Group gap="xs">
            <RadarIcon size={22} className="text-indigo-400" />
            <Text size="xl" fw={700} className="title-text-color">{lang === 'zh' ? '雷达 (Radar)' : 'Radar'}</Text>
          </Group>
          <Text size="sm" c="dimmed">
            {lang === 'zh' ? '事件线索 · 按生命周期与跨源共振组织，而非一条条未读' : 'Event threads — organized by lifecycle & cross-source resonance, not a pile of unread items'}
          </Text>
        </Stack>
        <UnstyledButton onClick={fetchThreads} className="nav-btn-hover" style={{ padding: '8px 14px', borderRadius: 8, border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)'}` }}>
          <Group gap={6}><RefreshCw size={14} /><Text size="sm">{lang === 'zh' ? '刷新' : 'Refresh'}</Text></Group>
        </UnstyledButton>
      </Group>

      {/* Catch-up: one quiet line, not a banner card (info-design: don't add chrome). 盲区 #7 */}
      {catchup && catchup.updated_threads > 0 && (
        <Text size="sm" c="dimmed">
          {lang === 'zh'
            ? <>自你上次查看，<Text span fw={700} c="indigo">{catchup.updated_threads}</Text> 条线索有新进展{catchup.resonant > 0 ? <>，<Text span c="orange">{catchup.resonant}</Text> 条共振</> : null}{catchup.confirmed > 0 ? <>，<Text span c="teal">{catchup.confirmed}</Text> 条已证实</> : null}。</>
            : <>Since you last looked, <Text span fw={700} c="indigo">{catchup.updated_threads}</Text> threads advanced{catchup.resonant > 0 ? <>, <Text span c="orange">{catchup.resonant}</Text> resonating</> : null}{catchup.confirmed > 0 ? <>, <Text span c="teal">{catchup.confirmed}</Text> confirmed</> : null}.</>}
        </Text>
      )}

      {loading && threads.length === 0 ? (
        <Group justify="center" p="xl"><Loader size="sm" /></Group>
      ) : threads.length === 0 ? (
        <Paper withBorder p="xl" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.02)' : '#ffffff', textAlign: 'center' }}>
          <Text c="dimmed" size="sm">{lang === 'zh' ? '尚无事件线索。雷达抓取并聚类后，事件会出现在这里。' : 'No event threads yet. As the radar fetches and clusters, events appear here.'}</Text>
        </Paper>
      ) : (
        <ScrollArea.Autosize mah="calc(100vh - 180px)">
          <Stack gap="xl">
            {grouped.map(g => (
              <Stack gap="sm" key={g.lifecycle}>
                <Group gap="xs">
                  <Badge color={g.meta.color} variant="light" size="md">{lang === 'zh' ? g.meta.zh : g.meta.en}</Badge>
                  <Text size="xs" c="dimmed">{lang === 'zh' ? g.meta.hint_zh : g.meta.hint_en} · {g.items.length}</Text>
                </Group>
                <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
                  {g.items.map(th => <ThreadCard key={th.id} th={th} isDark={isDark} lang={lang} />)}
                </SimpleGrid>
              </Stack>
            ))}
          </Stack>
        </ScrollArea.Autosize>
      )}
    </Stack>
  );
}
