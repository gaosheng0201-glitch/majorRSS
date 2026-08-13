// The raw subscription stream — the FULL, unfiltered view of everything the
// radar fetched, relevance-gated items included ("低相关项留 Raw Feed" is the
// stated design; the floor excludes them from LLM fusion, never from sight).
//
// Extracted from Dashboard.tsx by P6. In pure-RSS mode this list IS the product
// (愿景 147: "纯 RSS 模式是永远的地板" — a first-class mode, not a fallback), so
// it renders as the radar page's main face there. In AI mode it stays reachable
// behind a quiet disclosure on the leads tab: hiding the gated items entirely
// would turn the relevance floor from a soft filter into an invisible one,
// which the trust loop forbids.
import { useEffect, useState } from 'react';
import DOMPurify from 'dompurify';
import {
  Text, Paper, Group, Stack, Badge, Loader, Card, ScrollArea, Collapse,
  UnstyledButton, Anchor, useMantineColorScheme,
} from '@mantine/core';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';
import { displaySource, safeHref, SourceIcon } from './sourceDisplay';

export interface RawArticleResponse {
  id: number;
  tracker_name: string;
  title: string;
  url: string;
  content: string;
  published_at?: string;
  created_at: string;
}

export function RawArticleCard({ article }: { article: RawArticleResponse }) {
  const { t } = useLanguage();
  const [opened, setOpened] = useState(false);
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  let domain = "";
  try {
    domain = new URL(article.url).hostname;
  } catch (e) {}
  // 显示真实发布方（聚合器条目从标题提取），图标仍按 host。
  const sourceLabel = displaySource(article.url, article.title) || domain;
  // 开发者模式：显示真实获取渠道（清洗前的原始来源），便于发现内容是否经聚合器
  // 二次转手——避免"美化后"的显示掩盖问题（作者要求）。
  const devMode = localStorage.getItem('developer_mode') === 'true';
  const rawChannel = domain && sourceLabel !== domain.replace(/^www\./, '');

  const displayTime = article.published_at || article.created_at;

  return (
    <Card
      withBorder
      p="md"
      radius="md"
      style={{
        background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff',
        boxShadow: isDark ? 'none' : '0 1px 3px rgba(0,0,0,0.05)'
      }}
    >
      <Group justify="space-between" align="center" mb="xs">
        <Group gap="xs">
          <div style={{
            width: 24,
            height: 24,
            borderRadius: 4,
            background: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)',
            border: isDark ? '1px solid rgba(255, 255, 255, 0.06)' : '1px solid rgba(0, 0, 0, 0.08)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0
          }}>
            <SourceIcon domain={domain} type="original" />
          </div>
          <Text size="xs" c="dimmed" style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {sourceLabel}
          </Text>
          {article.tracker_name && article.tracker_name !== "Unknown" && (
            <Badge color="pink" variant="light" size="xs">
              {t('dash_tracker_badge')}: {article.tracker_name}
            </Badge>
          )}
        </Group>
        <Text size="xs" c="dimmed">
          {new Date(displayTime).toLocaleString()}
        </Text>
      </Group>

      <Stack gap="xs">
        <Anchor
          href={safeHref(article.url)}
          target="_blank" rel="noopener noreferrer"
          size="sm"
          fw={700}
          className="title-text-color"
          underline="hover"
          style={{ lineHeight: 1.4 }}
        >
          {article.title}
          <span style={{ fontSize: '11px', color: 'var(--accent-link-color)', marginLeft: 4 }}>↗</span>
        </Anchor>

        {devMode && (
          <Text size="10px" c="dimmed" style={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
            渠道 {domain || '—'}{rawChannel ? `（显示为 ${sourceLabel}）` : ''} · {article.url}
          </Text>
        )}

        {article.content && (
          <Stack gap="xs">
            <UnstyledButton
              onClick={() => setOpened(prev => !prev)}
              style={{
                color: 'var(--mantine-color-indigo-4)',
                fontSize: 'var(--mantine-font-size-xs)',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                padding: '2px 0'
              }}
            >
              {opened ? t('dash_hide_content') : t('dash_show_content')}
            </UnstyledButton>
            <Collapse expanded={opened}>
              <Paper
                p="md"
                radius="md"
                mt="xs"
                style={{
                  background: isDark ? 'rgba(21, 23, 27, 0.6)' : '#f8f9fa',
                  border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.08)'}`,
                  fontSize: 'var(--mantine-font-size-sm)',
                  lineHeight: 1.6
                }}
              >
                <ScrollArea.Autosize mah={400} offsetScrollbars>
                  <div
                    dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(article.content) }}
                    style={{
                      lineHeight: 1.6,
                      fontSize: 'var(--mantine-font-size-sm)',
                      wordBreak: 'break-word',
                      color: isDark ? 'rgba(255, 255, 255, 0.85)' : '#212529'
                    }}
                    className="raw-article-html-content"
                  />
                </ScrollArea.Autosize>
              </Paper>
            </Collapse>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}

export default function RawFeed({ pollMs = 0 }: { pollMs?: number }) {
  const { lang } = useLanguage();
  const [articles, setArticles] = useState<RawArticleResponse[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchRaw = async () => {
    try {
      const res = await client.get<RawArticleResponse[]>('/intelligence/raw-feed');
      setArticles(res.data || []);
    } catch (e) {
      console.error('Failed to load raw feed', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRaw();
    if (pollMs > 0) {
      const t = setInterval(fetchRaw, pollMs);
      return () => clearInterval(t);
    }
  }, [pollMs]);

  if (loading && articles.length === 0) {
    return <Group justify="center" py="xl"><Loader size="sm" color="indigo" /></Group>;
  }
  if (articles.length === 0) {
    return (
      <Text c="dimmed" size="sm" ta="center" py="xl">
        {lang === 'zh' ? '还没有抓取到内容。' : 'Nothing fetched yet.'}
      </Text>
    );
  }
  return (
    <Stack gap="md">
      {articles.map(a => <RawArticleCard key={a.id} article={a} />)}
    </Stack>
  );
}
