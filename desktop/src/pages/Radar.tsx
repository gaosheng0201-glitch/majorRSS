import { useEffect, useState } from 'react';
import {
  Text, Group, Stack, Loader, Anchor, UnstyledButton, Box, Tabs,
  useMantineColorScheme,
} from '@mantine/core';
import { RefreshCw, ChevronDown, ChevronRight, Zap, Sparkles, Rss } from 'lucide-react';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';
import RawFeed from '../components/RawFeed';
import { safeHref } from '../components/sourceDisplay';

// P6 雷达视图收口 — the ONE main reading surface (愿景 41: "日用界面只有一个，
// 雷达/线索视图就是'仪表盘'"). Before this, three surfaces showed similar
// content (Dashboard's AI feed, Dashboard's raw feed, this page) and the author
// couldn't tell how radar and feed related — because they were meant to be the
// same thing. The page now has two faces per mode (author's 2026-07-29 ruling):
//
//   AI mode:   提炼 (threads that EARNED a summary — the card IS the summary)
//            | 线报 (clustered, unsummarised; stratified by intake stamps:
//              named-account tip-offs visible and labelled 未证实线报,
//              aggregator singletons collapsed — "默认安静，打扰需要证明自己")
//   Pure RSS:  the raw subscription stream itself — it IS the product in this
//              mode (愿景 147: 永远的地板), not a downgraded debug view.
//
// The raw stream stays reachable in AI mode behind a quiet disclosure on the
// leads tab: relevance-gated items exist ONLY there, and hiding them entirely
// would turn the floor from a soft filter into an invisible one (trust loop).

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
  summary: string | null;
  importance_score: number;
  validity_category: string | null;
  from_account: boolean;
  aggregated_only: boolean;
}

interface CatchUp {
  since: string;
  updated_threads: number;
  resonant: number;
  confirmed: number;
}

const LAST_SEEN_KEY = 'radar_last_seen_at';

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

// One event, laid out for reading — headline is the hero; the fused summary (if
// earned) is the body (P2.1 endgame: the feed card IS the thread's summary);
// time + signals are a quiet meta line; sources expand on demand.
function EventRow({ th, isDark, lang, tipoff }: { th: StoryThread; isDark: boolean; lang: string; tipoff?: boolean }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const confirmed = th.lifecycle === 'CONFIRMED';
  const corroborated = th.lifecycle === 'CORROBORATED';
  const summary = (th.summary || '').trim();
  const longSummary = summary.length > 220;
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

      {summary && (
        <Text size="sm" c={isDark ? 'gray.4' : 'gray.7'} mt={6} style={{ lineHeight: 1.6 }}
              lineClamp={expanded ? undefined : 3}>
          {summary}
        </Text>
      )}
      {summary && longSummary && (
        <UnstyledButton onClick={() => setExpanded(e => !e)}>
          <Text size="xs" c="indigo" fw={600} mt={2}>
            {expanded ? (lang === 'zh' ? '收起' : 'Less') : (lang === 'zh' ? '展开全文' : 'More')}
          </Text>
        </UnstyledButton>
      )}

      <Group gap={8} mt={5} style={{ fontSize: 12 }}>
        <Text size="xs" c="dimmed">{relativeTime(th.last_update_at, lang)}</Text>
        <Text size="xs" c="dimmed">·</Text>
        <Text size="xs" c="dimmed">{th.distinct_source_count} {lang === 'zh' ? '个来源' : 'sources'}</Text>
        {tipoff && (
          // The fast channel: single-source, from an account the user NAMED.
          // Visible on purpose, and honestly labelled — speed without
          // masquerading as verified news (愿景 95-102).
          <Text size="xs" c="grape" fw={600}>· {lang === 'zh' ? '未证实线报' : 'unverified tip'}</Text>
        )}
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

function TimeBucketedList({ threads, isDark, lang, tipoffIds }: {
  threads: StoryThread[]; isDark: boolean; lang: string; tipoffIds?: Set<number>;
}) {
  const sorted = [...threads].sort((a, b) => {
    const ta = a.last_update_at ? new Date(a.last_update_at).getTime() : 0;
    const tb = b.last_update_at ? new Date(b.last_update_at).getTime() : 0;
    return tb - ta;
  });
  const buckets = (['today', 'week', 'older'] as const)
    .map(key => ({ key, items: sorted.filter(t => bucketOf(t.last_update_at) === key) }))
    .filter(b => b.items.length > 0);
  return (
    <Stack gap="lg">
      {buckets.map(b => (
        <Box key={b.key}>
          <Text size="xs" fw={700} c="dimmed" tt="uppercase" style={{ letterSpacing: 0.6 }} mb={2}>
            {lang === 'zh' ? BUCKET_LABEL[b.key].zh : BUCKET_LABEL[b.key].en}
          </Text>
          {b.items.map(th => (
            <EventRow key={th.id} th={th} isDark={isDark} lang={lang} tipoff={tipoffIds?.has(th.id)} />
          ))}
        </Box>
      ))}
    </Stack>
  );
}

// The leads face: clustered threads that have not earned a summary, stratified
// by what the intake stamps say they are. Collapse criterion = aggregator-only
// AND single-source AND not from a named account — measured 90% of the lead
// backlog, and the stratum that buried the genuine tip-offs.
function LeadsView({ leads, isDark, lang }: { leads: StoryThread[]; isDark: boolean; lang: string }) {
  const [showCollapsed, setShowCollapsed] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  const isCollapsible = (t: StoryThread) =>
    !t.from_account && t.aggregated_only && (t.distinct_source_count || 0) <= 1;
  const tipoffs = leads.filter(t => t.from_account);
  const regular = leads.filter(t => !t.from_account && !isCollapsible(t));
  const collapsed = leads.filter(isCollapsible);
  const tipoffIds = new Set(tipoffs.map(t => t.id));
  const visible = [...tipoffs, ...regular];

  return (
    <Stack gap="md">
      {visible.length === 0 && collapsed.length === 0 ? (
        <Text c="dimmed" size="sm" ta="center" py="xl">
          {lang === 'zh' ? '暂无线报。' : 'No leads yet.'}
        </Text>
      ) : (
        <>
          {visible.length > 0 && (
            <TimeBucketedList threads={visible} isDark={isDark} lang={lang} tipoffIds={tipoffIds} />
          )}
          {collapsed.length > 0 && (
            <Box>
              <UnstyledButton onClick={() => setShowCollapsed(s => !s)}>
                <Group gap={4}>
                  {showCollapsed ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  <Text size="sm" c="dimmed">
                    {lang === 'zh'
                      ? `聚合器单源线索 ${collapsed.length} 条（默认折叠）`
                      : `${collapsed.length} aggregator singletons (collapsed)`}
                  </Text>
                </Group>
              </UnstyledButton>
              {showCollapsed && (
                <Box mt="xs">
                  <TimeBucketedList threads={collapsed} isDark={isDark} lang={lang} />
                </Box>
              )}
            </Box>
          )}
        </>
      )}

      {/* Trust loop: relevance-gated items exist only in the raw stream, so AI
          mode keeps a way in — quiet, but never invisible. */}
      <Box pt="sm" style={{ borderTop: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}` }}>
        <UnstyledButton onClick={() => setShowRaw(s => !s)}>
          <Group gap={4}>
            <Rss size={13} color="var(--mantine-color-gray-5)" />
            <Text size="sm" c="dimmed">
              {lang === 'zh' ? (showRaw ? '收起原始订阅数据流' : '查看原始订阅数据流（含已过滤条目）')
                             : (showRaw ? 'Hide raw stream' : 'View raw stream (incl. filtered items)')}
            </Text>
          </Group>
        </UnstyledButton>
        {showRaw && <Box mt="md"><RawFeed /></Box>}
      </Box>
    </Stack>
  );
}

export default function Radar({ appMode }: { appMode: 'ai_fusion' | 'pure_rss' }) {
  const { lang } = useLanguage();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const [refined, setRefined] = useState<StoryThread[]>([]);
  const [leads, setLeads] = useState<StoryThread[]>([]);
  const [loading, setLoading] = useState(true);
  const [catchup, setCatchup] = useState<CatchUp | null>(null);
  const [focusOnly, setFocusOnly] = useState(false);
  const [tab, setTab] = useState<string | null>('refined');
  const [sinceAnchor] = useState<string | null>(() => localStorage.getItem(LAST_SEEN_KEY));

  const fetchThreads = async () => {
    setLoading(true);
    try {
      const [r, l] = await Promise.all([
        client.get<StoryThread[]>('/intelligence/threads?view=refined&limit=100'),
        client.get<StoryThread[]>('/intelligence/threads?view=leads&limit=200'),
      ]);
      setRefined(r.data || []);
      setLeads(l.data || []);
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
    if (appMode === 'pure_rss') { setLoading(false); return; }
    fetchThreads();
    fetchCatchup();
    localStorage.setItem(LAST_SEEN_KEY, new Date().toISOString());
    const t = setInterval(fetchThreads, 30000);
    return () => clearInterval(t);
  }, [appMode]);

  // ---- Pure RSS mode: the raw stream IS the main face. ----
  if (appMode === 'pure_rss') {
    return (
      <Box style={{ maxWidth: 760, margin: '0 auto' }}>
        <Stack gap={2} mb="md">
          <Text size="xl" fw={700} className="title-text-color">
            {lang === 'zh' ? '订阅流' : 'Subscriptions'}
          </Text>
          <Text size="sm" c="dimmed">
            {lang === 'zh' ? '你订阅的一切，未过滤、按抓取时间读下来' : 'Everything you subscribe to, unfiltered, by fetch time'}
          </Text>
        </Stack>
        <RawFeed pollMs={30000} />
      </Box>
    );
  }

  // ---- AI mode: 提炼 | 线报 ----
  const isFocus = (t: StoryThread) => t.lifecycle === 'CONFIRMED' || t.is_resonant || t.alert_reasons.length > 0;
  const focusCount = refined.filter(isFocus).length;
  const shownRefined = refined.filter(t => !focusOnly || isFocus(t));
  const tipoffCount = leads.filter(t => t.from_account).length;
  // The people-radar bypass summarises named-account threads fast, so most
  // tip-offs live in REFINED — and a summarised single-source account thread is
  // still an unverified tip. Label it there too: visible first, never dressed
  // up as news (愿景 95-102).
  const refinedTipoffIds = new Set(refined.filter(t => t.from_account && t.lifecycle === 'LEAD').map(t => t.id));

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
          {tab === 'refined' && focusCount > 0 && (
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

      <Tabs value={tab} onChange={setTab} variant="default" mb="sm">
        <Tabs.List>
          <Tabs.Tab value="refined" leftSection={<Sparkles size={13} />}>
            {lang === 'zh' ? '提炼' : 'Refined'}
          </Tabs.Tab>
          <Tabs.Tab value="leads" leftSection={<Zap size={13} />}>
            {lang === 'zh' ? '线报' : 'Leads'}{tipoffCount > 0 ? ` (${tipoffCount})` : ''}
          </Tabs.Tab>
        </Tabs.List>
      </Tabs>

      {loading && refined.length === 0 && leads.length === 0 ? (
        <Group justify="center" p="xl"><Loader size="sm" /></Group>
      ) : tab === 'leads' ? (
        <LeadsView leads={leads} isDark={isDark} lang={lang} />
      ) : shownRefined.length === 0 ? (
        <Text c="dimmed" size="sm" ta="center" py="xl">
          {lang === 'zh' ? '还没有提炼出的事件。雷达抓取、聚类并挣得摘要后，会按时间出现在这里。' : 'No refined events yet. As threads earn summaries, they appear here by time.'}
        </Text>
      ) : (
        <TimeBucketedList threads={shownRefined} isDark={isDark} lang={lang} tipoffIds={refinedTipoffIds} />
      )}
    </Box>
  );
}
