import { useEffect, useState } from 'react';
import {
  Text, Group, Stack, Loader, Anchor, UnstyledButton, Box,
  useMantineColorScheme,
} from '@mantine/core';
import { RefreshCw, ChevronDown, ChevronRight, Zap } from 'lucide-react';
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

interface CatchUp {
  since: string;
  updated_threads: number;
  resonant: number;
  confirmed: number;
}

const LAST_SEEN_KEY = 'radar_last_seen_at';
const safeHref = (u?: string) => (u && /^https?:\/\//i.test(u)) ? u : undefined;

// ---- time helpers: "什么时间" for a reading feed ----
function relativeTime(iso: string | null, lang: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const min = Math.floor(diffMs / 60000);
  const hr = Math.floor(min / 60);
  const hhmm = d.toLocaleTimeString(lang === 'zh' ? 'zh-CN' : 'en-US', { hour: '2-digit', minute: '2-digit' });
  const sameDay = d.toDateString() === now.toDateString();
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();
  if (min < 1) return lang === 'zh' ? '刚刚' : 'just now';
  if (min < 60) return lang === 'zh' ? `${min} 分钟前` : `${min}m ago`;
  if (sameDay) return lang === 'zh' ? `今天 ${hhmm}` : `today ${hhmm}`;
  if (isYesterday) return lang === 'zh' ? `昨天 ${hhmm}` : `yesterday ${hhmm}`;
  if (hr < 24 * 7) return lang === 'zh' ? `${Math.floor(hr / 24)} 天前` : `${Math.floor(hr / 24)}d ago`;
  return d.toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric' });
}

function bucketOf(iso: string | null): 'today' | 'week' | 'older' {
  if (!iso) return 'older';
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return 'today';
  if (now.getTime() - d.getTime() < 7 * 86400000) return 'week';
  return 'older';
}

const BUCKET_LABEL: Record<string, { zh: string; en: string }> = {
  today: { zh: '今天', en: 'Today' },
  week: { zh: '本周', en: 'This week' },
  older: { zh: '更早', en: 'Earlier' },
};

// One event, laid out for reading — headline is the hero; time + signals are a
// quiet meta line; sources expand on demand. No boxes, no filled badges.
function EventRow({ th, isDark, lang }: { th: StoryThread; isDark: boolean; lang: string }) {
  const [open, setOpen] = useState(false);
  const confirmed = th.lifecycle === 'CONFIRMED';
  const corroborated = th.lifecycle === 'CORROBORATED';
  return (
    <Box style={{ padding: '14px 0', borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}` }}>
      <Text
        component="a"
        href={safeHref(th.sources[0]?.url)}
        target="_blank"
        rel="noopener noreferrer"
        style={{ fontSize: 15.5, fontWeight: 600, lineHeight: 1.45, textDecoration: 'none', display: 'block', cursor: th.sources[0] ? 'pointer' : 'default' }}
        className="title-text-color"
      >
        {th.title || (lang === 'zh' ? '未命名线索' : 'Untitled')}
      </Text>

      <Group gap={8} mt={5} style={{ fontSize: 12 }}>
        <Text size="xs" c="dimmed">{relativeTime(th.last_update_at, lang)}</Text>
        <Text size="xs" c="dimmed">·</Text>
        <Text size="xs" c="dimmed">{th.distinct_source_count} {lang === 'zh' ? '个来源' : 'sources'}</Text>
        {confirmed && <Text size="xs" c="teal" fw={600}>· {lang === 'zh' ? '已证实' : 'confirmed'}</Text>}
        {corroborated && !confirmed && <Text size="xs" c="blue" fw={600}>· {lang === 'zh' ? '多源佐证' : 'corroborated'}</Text>}
        {th.is_resonant && (
          <Group gap={2}><Zap size={11} color="var(--mantine-color-orange-5)" />
            <Text size="xs" c="orange" fw={600}>{lang === 'zh' ? '共振' : 'resonant'}</Text></Group>
        )}
        {th.sources.length > 1 && (
          <UnstyledButton onClick={() => setOpen(o => !o)}>
            <Group gap={2}>
              {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              <Text size="xs" c="dimmed">{lang === 'zh' ? `${th.sources.length} 处溯源` : `${th.sources.length} sources`}</Text>
            </Group>
          </UnstyledButton>
        )}
      </Group>

      {open && th.sources.length > 0 && (
        <Stack gap={3} mt={8} pl="sm">
          {th.sources.map((s, i) => (
            <Anchor key={i} href={safeHref(s.url)} target="_blank" rel="noopener noreferrer" size="xs" lineClamp={1} c="dimmed">
              {s.title || s.url}
            </Anchor>
          ))}
        </Stack>
      )}
    </Box>
  );
}

export default function Radar() {
  const { lang } = useLanguage();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const [threads, setThreads] = useState<StoryThread[]>([]);
  const [loading, setLoading] = useState(true);
  const [catchup, setCatchup] = useState<CatchUp | null>(null);
  const [focusOnly, setFocusOnly] = useState(false);
  const [sinceAnchor] = useState<string | null>(() => localStorage.getItem(LAST_SEEN_KEY));

  const fetchThreads = async () => {
    setLoading(true);
    try {
      const res = await client.get<StoryThread[]>('/intelligence/threads?limit=100');
      setThreads(res.data || []);
    } catch (e) {
      console.error('Failed to load threads', e);
    } finally {
      setLoading(false);
    }
  };

  const fetchCatchup = async () => {
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
    localStorage.setItem(LAST_SEEN_KEY, new Date().toISOString());
    const t = setInterval(fetchThreads, 30000);
    return () => clearInterval(t);
  }, []);

  // A reading feed: most-recent first, but surface confirmed/resonant within
  // each time bucket. Grouped by time so it reads as "what happened, when".
  const isFocus = (t: StoryThread) => t.lifecycle === 'CONFIRMED' || t.is_resonant || t.alert_reasons.length > 0;
  const focusCount = threads.filter(isFocus).length;
  const sorted = [...threads]
    .filter(t => !focusOnly || isFocus(t))
    .sort((a, b) => {
      const ta = a.last_update_at ? new Date(a.last_update_at).getTime() : 0;
      const tb = b.last_update_at ? new Date(b.last_update_at).getTime() : 0;
      return tb - ta;
    });
  const buckets = (['today', 'week', 'older'] as const)
    .map(key => ({ key, items: sorted.filter(t => bucketOf(t.last_update_at) === key) }))
    .filter(b => b.items.length > 0);

  return (
    <Box style={{ maxWidth: 760, margin: '0 auto' }}>
      <Group justify="space-between" align="flex-end" mb="md">
        <Stack gap={2}>
          <Text size="xl" fw={700} className="title-text-color">{lang === 'zh' ? '雷达' : 'Radar'}</Text>
          {catchup && catchup.updated_threads > 0 ? (
            <Text size="sm" c="dimmed">
              {lang === 'zh'
                ? <>自你上次查看，<Text span fw={700} c="indigo">{catchup.updated_threads}</Text> 条有新进展{catchup.resonant > 0 ? <>，<Text span c="orange">{catchup.resonant}</Text> 条共振</> : null}{catchup.confirmed > 0 ? <>，<Text span c="teal">{catchup.confirmed}</Text> 条已证实</> : null}</>
                : <>Since you last looked, <Text span fw={700} c="indigo">{catchup.updated_threads}</Text> advanced{catchup.resonant > 0 ? <>, <Text span c="orange">{catchup.resonant}</Text> resonating</> : null}{catchup.confirmed > 0 ? <>, <Text span c="teal">{catchup.confirmed}</Text> confirmed</> : null}</>}
            </Text>
          ) : (
            <Text size="sm" c="dimmed">{lang === 'zh' ? '你关注的事，按时间读下来' : 'What you follow, read down by time'}</Text>
          )}
        </Stack>
        <Group gap="md">
          {/* Quiet focus filter — surface just the signal when noise is high. */}
          {focusCount > 0 && (
            <Group gap={4}>
              <UnstyledButton onClick={() => setFocusOnly(false)}>
                <Text size="sm" c={focusOnly ? 'dimmed' : undefined} fw={focusOnly ? 400 : 700}>
                  {lang === 'zh' ? '全部' : 'All'}
                </Text>
              </UnstyledButton>
              <Text size="sm" c="dimmed">/</Text>
              <UnstyledButton onClick={() => setFocusOnly(true)}>
                <Text size="sm" c={focusOnly ? undefined : 'dimmed'} fw={focusOnly ? 700 : 400}>
                  {lang === 'zh' ? `重点 ${focusCount}` : `Focus ${focusCount}`}
                </Text>
              </UnstyledButton>
            </Group>
          )}
          <UnstyledButton onClick={fetchThreads} title={lang === 'zh' ? '刷新' : 'Refresh'}>
            <RefreshCw size={16} className="text-indigo-400" />
          </UnstyledButton>
        </Group>
      </Group>

      {loading && threads.length === 0 ? (
        <Group justify="center" p="xl"><Loader size="sm" /></Group>
      ) : threads.length === 0 ? (
        <Text c="dimmed" size="sm" ta="center" py="xl">
          {lang === 'zh' ? '暂时没有动态。雷达抓取并聚类后，事件会按时间出现在这里。' : 'Nothing yet. As the radar fetches and clusters, events appear here by time.'}
        </Text>
      ) : (
        <Stack gap="lg">
          {buckets.map(b => (
            <Box key={b.key}>
              <Text size="xs" fw={700} c="dimmed" tt="uppercase" style={{ letterSpacing: 0.6 }} mb={2}>
                {lang === 'zh' ? BUCKET_LABEL[b.key].zh : BUCKET_LABEL[b.key].en}
              </Text>
              {b.items.map(th => <EventRow key={th.id} th={th} isDark={isDark} lang={lang} />)}
            </Box>
          ))}
        </Stack>
      )}
    </Box>
  );
}
