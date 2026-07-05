import { useEffect, useState, useRef } from 'react';
import DOMPurify from 'dompurify';
import { 
  Text, Paper, SimpleGrid, Group, Stack, Badge, 
  Button, RingProgress, Loader, Card, ScrollArea, Divider, Collapse, UnstyledButton, Modal, Tabs, Anchor,
  useMantineColorScheme
} from '@mantine/core';
import { 
  Activity, AlertTriangle, CheckCircle, RefreshCw, Sparkles, Link as LinkIcon, FileText
} from 'lucide-react';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';

// Only allow http(s) hrefs from untrusted feed/LLM content — blocks a
// javascript:/data: URL in a scraped link from executing on click (stored XSS).
const safeHref = (u?: string): string | undefined =>
  (u && /^https?:\/\//i.test(u)) ? u : undefined;

interface AlertSource {
  title: string;
  url: string;
  description?: string;
}

interface Alert {
  id: number;
  entity_name: string;
  alert_summary: string;
  created_at: string;
  sources?: AlertSource[];
}

interface Report {
  id: number;
  title: string;
  source_url: string;
  validity_category: string;
  radar_section: string;
  tracker_name: string;
  llm_summary: string;
  importance_score: number;
  created_at: string;
  key_entities: string[];
}

interface RawArticleResponse {
  id: number;
  tracker_name: string;
  title: string;
  url: string;
  content: string;
  published_at?: string;
  created_at: string;
}

interface Stats {
  pending_count: number;
  active_trackers_count: number;
  active_monitors_count: number;
  latest_alerts: Alert[];
}

const getDisplayTitleForUrl = (url: string) => {
  try {
    const parsed = new URL(url);
    let display = parsed.hostname;
    // Remove "www." prefix for cleaner look
    display = display.replace(/^www\./, '');
    if (parsed.pathname && parsed.pathname !== '/') {
      display += parsed.pathname;
    }
    // Remove trailing slash if present
    display = display.replace(/\/$/, '');
    if (display.length > 40) {
      return display.substring(0, 37) + '...';
    }
    return display;
  } catch (e) {
    return url.length > 40 ? url.substring(0, 37) + '...' : url;
  }
};

interface SourceLink {
  title: string;
  url: string;
  description?: string;
}

const parseSourceLinks = (text: string): SourceLink[] => {
  if (!text) return [];
  
  const links: SourceLink[] = [];
  const matchedUrls = new Set<string>();
  
  // Regex to find all markdown links globally, supporting multi-line anchor text
  const mdLinkRegex = /\[([\s\S]+?)\]\((https?:\/\/[^\s)]+)\)/g;
  let match;
  
  while ((match = mdLinkRegex.exec(text)) !== null) {
    const rawAnchor = match[1].trim();
    const url = match[2].trim();
    matchedUrls.add(url);
    
    let title = "";
    let description = "";
    
    // Split by newlines to see if it's multi-line
    const lines = rawAnchor.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    if (lines.length > 0) {
      title = lines[0];
      if (lines.length > 1) {
        description = lines.slice(1).join(" ");
      } else {
        // Single line, let's see if it's very long and can be split by sentence
        if (title.length > 120) {
          const firstPeriodIndex = title.indexOf('. ');
          if (firstPeriodIndex !== -1) {
            description = title.substring(firstPeriodIndex + 2);
            title = title.substring(0, firstPeriodIndex + 1);
          }
        }
      }
    }
    
    // Clean up title (remove starting numbering/bullets like "1. ", "- ", "• ")
    title = title.replace(/^[-*•\s\d.]+\s*/, '').trim();
    if (description) {
      description = description.replace(/^[-*•\s\d.]+\s*/, '').trim();
    }
    
    links.push({ title, url, description });
  }
  
  // Also scan for plain URLs that weren't matched as markdown links (useful for original/raw list)
  const urlRegex = /(https?:\/\/[^\s)]+)/g;
  const plainLines = text.split(/\r?\n/);
  for (let line of plainLines) {
    line = line.trim();
    if (!line) continue;
    
    // Ignore tracker lines
    if (
      line.includes('material/radar') || 
      line.includes('探测任务来源') || 
      line.includes('Tracker:') || 
      line.includes('任务来源') || 
      line === '<br>' || 
      line === '<br />'
    ) {
      continue;
    }
    
    const urlMatch = line.match(urlRegex);
    if (urlMatch) {
      for (const rawUrl of urlMatch) {
        const cleanUrl = rawUrl.replace(/[)]$/, '').trim();
        if (matchedUrls.has(cleanUrl)) continue;
        
        links.push({
          title: getDisplayTitleForUrl(cleanUrl),
          url: cleanUrl,
          description: cleanUrl
        });
      }
    }
  }
  
  return links;
};

const parseMarkdown = (text: string) => {
  let formatted = text
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color: var(--accent-link-color); text-decoration: underline; font-weight: 500;">$1</a>');
  return formatted.replace(/\n/g, '<br />');
};

function SourceIcon({ domain, type }: { domain: string; type: 'evidence' | 'original' }) {
  const [error, setError] = useState(false);
  const iconColor = type === 'evidence' ? 'var(--mantine-color-indigo-4)' : 'var(--mantine-color-gray-5)';
  
  if (error || !domain) {
    return type === 'evidence' ? <FileText size={16} color={iconColor} /> : <LinkIcon size={16} color={iconColor} />;
  }
  
  return (
    <img 
      src={`https://www.google.com/s2/favicons?domain=${domain}&sz=32`} 
      alt="" 
      style={{ width: 16, height: 16, borderRadius: 2, display: 'block' }}
      onError={() => setError(true)}
    />
  );
}

function IntelReportCard({ report }: { report: Report }) {
  const { t } = useLanguage();
  const [opened, setOpened] = useState(false);
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  
  // Split summary at the markdown divider (making sure to support both LF and CRLF line endings)
  const parts = report.llm_summary.split(/\r?\n\r?\n---\r?\n|\r?\n---\r?\n/);
  const summaryText = parts[0];
  const detailsText = parts.slice(1).join('\n---\n');

  // Parse detailsText to split "Source Evidence" and "Original URLs" lists
  const parseDetails = (text: string) => {
    let evidence = "";
    let original = "";
    
    const evidenceMarker = "**:material/menu_book: Source Evidence:**";
    const originalMarker = "**:material/link: 本次融合的所有原始 URL (含被过滤的噪音):**";
    
    const evIndex = text.indexOf(evidenceMarker);
    const origIndex = text.indexOf(originalMarker);
    
    if (evIndex !== -1 && origIndex !== -1) {
      if (evIndex < origIndex) {
        evidence = text.substring(evIndex + evidenceMarker.length, origIndex).trim();
        original = text.substring(origIndex + originalMarker.length).trim();
      } else {
        original = text.substring(origIndex + originalMarker.length, evIndex).trim();
        evidence = text.substring(evIndex + evidenceMarker.length).trim();
      }
    } else if (evIndex !== -1) {
      evidence = text.substring(evIndex + evidenceMarker.length).trim();
    } else if (origIndex !== -1) {
      original = text.substring(origIndex + originalMarker.length).trim();
    } else {
      evidence = text;
    }
    
    return { evidence, original };
  };

  const { evidence, original } = parseDetails(detailsText);
  const evidenceLinks = parseSourceLinks(evidence);
  const originalLinks = parseSourceLinks(original);
  
  return (
    <Card 
      withBorder 
      p="lg" 
      radius="md" 
      style={{ 
        background: isDark ? 'rgba(255,255,255,0.015)' : '#ffffff',
        boxShadow: isDark ? 'none' : '0 1px 3px rgba(0,0,0,0.05)'
      }}
    >
      <Card.Section 
        inheritPadding 
        py="xs" 
        style={{ 
          background: isDark ? 'rgba(255,255,255,0.02)' : '#f8f9fa',
          borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.06)'}`
        }}
      >
        <Group justify="space-between">
          <Group gap="xs">
            <Badge color="indigo" variant="light">{report.radar_section}</Badge>
            <Badge color="teal" variant="outline">{report.validity_category}</Badge>
          </Group>
          <Text size="xs" c="dimmed">{new Date(report.created_at).toLocaleString()}</Text>
        </Group>
      </Card.Section>

      <Stack gap="xs" mt="md">
        {/* Title and Tracker Tag */}
        <Group gap="xs" align="center" style={{ display: 'inline-flex', flexWrap: 'wrap' }}>
          <Text size="md" fw={700} className="title-text-color" style={{ display: 'inline' }}>
            {report.title}
          </Text>
          {report.tracker_name && report.tracker_name !== "Unknown" && (
            <Badge color="pink" variant="light" size="xs" style={{ verticalAlign: 'middle' }}>
              {t('dash_tracker_badge')}: {report.tracker_name}
            </Badge>
          )}
        </Group>

        <Text 
          size="sm" 
          c="dimmed" 
          style={{ lineHeight: 1.6 }} 
          dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(parseMarkdown(summaryText)) }}
        />
        
        {detailsText && (
          <Stack gap="xs" mt="sm">
            <UnstyledButton 
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                setOpened(prev => !prev);
              }}
              style={{ 
                color: 'var(--mantine-color-indigo-4)', 
                fontSize: 'var(--mantine-font-size-xs)',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                padding: '4px 8px 4px 0',
                position: 'relative',
                zIndex: 10
              }}
            >
              {opened ? t('dash_hide_sources') : t('dash_show_sources')}
            </UnstyledButton>
            <Collapse expanded={opened}>
              <Tabs 
                defaultValue={evidenceLinks.length > 0 ? "evidence" : "original"} 
                variant="default" 
                styles={{
                  root: { 
                    background: isDark ? 'rgba(21, 23, 27, 0.6)' : 'rgba(248, 249, 250, 0.8)', 
                    border: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.08)', 
                    borderRadius: '12px', 
                    padding: '16px',
                    marginTop: '12px',
                    boxShadow: isDark ? '0 4px 24px rgba(0, 0, 0, 0.3)' : '0 4px 16px rgba(0, 0, 0, 0.05)',
                    backdropFilter: 'blur(10px)'
                  },
                  list: { 
                    borderBottom: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.06)', 
                    marginBottom: '12px',
                    display: 'flex',
                    gap: '16px'
                  },
                  tab: { 
                    fontWeight: 600, 
                    fontSize: '13px', 
                    padding: '8px 4px',
                    color: isDark ? 'var(--mantine-color-gray-5)' : '#495057',
                    borderBottom: '2px solid transparent',
                    backgroundColor: 'transparent',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                  },
                  tabLabel: { 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: '8px' 
                  }
                }}
              >
                <Tabs.List>
                  {evidenceLinks.length > 0 && (
                    <Tabs.Tab value="evidence" leftSection={<FileText size={14} />}>
                      <Group gap="xs" wrap="nowrap">
                        <span>{t('dash_adopted_sources')}</span>
                        <Badge 
                          size="sm" 
                          variant="filled"
                          style={{ 
                            borderRadius: '9999px',
                            backgroundColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.05)',
                            color: isDark ? '#a5d8ff' : 'var(--mantine-color-indigo-6)',
                            fontWeight: 700
                          }}
                        >
                          {evidenceLinks.length}
                        </Badge>
                      </Group>
                    </Tabs.Tab>
                  )}
                  {originalLinks.length > 0 && (
                    <Tabs.Tab value="original" leftSection={<LinkIcon size={14} />}>
                      <Group gap="xs" wrap="nowrap">
                        <span>{t('dash_raw_urls')}</span>
                        <Badge 
                          size="sm" 
                          variant="filled"
                          style={{ 
                            borderRadius: '9999px',
                            backgroundColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.05)',
                            color: isDark ? '#e9ecef' : '#495057',
                            fontWeight: 700
                          }}
                        >
                          {originalLinks.length}
                        </Badge>
                      </Group>
                    </Tabs.Tab>
                  )}
                </Tabs.List>

                {evidenceLinks.length > 0 && (
                  <Tabs.Panel value="evidence" pt="xs">
                    <ScrollArea.Autosize mah={350} offsetScrollbars>
                      <Stack gap={0}>
                        {evidenceLinks.map((src, index) => {
                          let domain = "";
                          try {
                            domain = new URL(src.url).hostname;
                          } catch (e) {}
                          
                          return (
                            <Group 
                              key={index} 
                              gap="md" 
                              wrap="nowrap" 
                              align="flex-start" 
                              py="md" 
                              style={{ borderBottom: isDark ? '1px solid rgba(255,255,255,0.04)' : '1px solid rgba(0,0,0,0.06)' }}
                            >
                              <div style={{
                                width: 32,
                                height: 32,
                                borderRadius: 6,
                                background: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)',
                                border: isDark ? '1px solid rgba(255, 255, 255, 0.06)' : '1px solid rgba(0, 0, 0, 0.08)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                flexShrink: 0,
                                marginTop: 2
                              }}>
                                <SourceIcon domain={domain} type="evidence" />
                              </div>
                              <Stack gap={4} style={{ flex: 1 }}>
                                <Anchor 
                                  href={safeHref(src.url)} 
                                  target="_blank" rel="noopener noreferrer"
                                  size="sm" 
                                  fw={600} 
                                  className="title-text-color" 
                                  underline="hover"
                                  style={{ 
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '6px',
                                    lineHeight: 1.4
                                  }}
                                >
                                  {src.title}
                                  <span style={{ fontSize: '11px', color: 'var(--accent-link-color)' }}>↗</span>
                                </Anchor>
                                {src.description && (
                                  <Text size="xs" c="dimmed" style={{ lineHeight: 1.5 }}>
                                    {src.description}
                                  </Text>
                                )}
                              </Stack>
                            </Group>
                          );
                        })}
                      </Stack>
                    </ScrollArea.Autosize>
                  </Tabs.Panel>
                )}

                {originalLinks.length > 0 && (
                  <Tabs.Panel value="original" pt="xs">
                    <ScrollArea.Autosize mah={350} offsetScrollbars>
                      <Stack gap={0}>
                        {originalLinks.map((src, index) => {
                          let domain = "";
                          try {
                            domain = new URL(src.url).hostname;
                          } catch (e) {}
                          
                          return (
                            <Group 
                              key={index} 
                              gap="md" 
                              wrap="nowrap" 
                              align="flex-start" 
                              py="md" 
                              style={{ borderBottom: isDark ? '1px solid rgba(255,255,255,0.04)' : '1px solid rgba(0,0,0,0.06)' }}
                            >
                              <div style={{
                                width: 32,
                                height: 32,
                                borderRadius: 6,
                                background: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)',
                                border: isDark ? '1px solid rgba(255, 255, 255, 0.06)' : '1px solid rgba(0, 0, 0, 0.08)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                flexShrink: 0,
                                marginTop: 2
                              }}>
                                <SourceIcon domain={domain} type="original" />
                              </div>
                              <Stack gap={4} style={{ flex: 1 }}>
                                <Anchor 
                                  href={safeHref(src.url)} 
                                  target="_blank" rel="noopener noreferrer"
                                  size="sm" 
                                  fw={600} 
                                  className="title-text-color" 
                                  underline="hover"
                                  style={{ 
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '6px',
                                    lineHeight: 1.4
                                  }}
                                >
                                  {src.title}
                                  <span style={{ fontSize: '11px', color: 'var(--accent-link-color)' }}>↗</span>
                                </Anchor>
                                {src.description && src.description !== src.title && (
                                  <Text size="xs" c="dimmed" style={{ lineHeight: 1.5, wordBreak: 'break-all' }}>
                                    {src.description}
                                  </Text>
                                )}
                              </Stack>
                            </Group>
                          );
                        })}
                      </Stack>
                    </ScrollArea.Autosize>
                  </Tabs.Panel>
                )}

                <Group justify="center" mt="md">
                  <UnstyledButton 
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      setOpened(false);
                    }}
                    style={{
                      color: isDark ? 'var(--mantine-color-gray-5)' : '#495057',
                      fontSize: 'var(--mantine-font-size-xs)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                      padding: '6px 12px',
                      borderRadius: '6px',
                      backgroundColor: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)',
                      border: isDark ? '1px solid rgba(255, 255, 255, 0.05)' : '1px solid rgba(0, 0, 0, 0.08)',
                      transition: 'all 0.2s ease',
                    }}
                  >
                    {t('dash_hide_sources')} ∧
                  </UnstyledButton>
                </Group>
              </Tabs>
            </Collapse>
          </Stack>
        )}
        
        <Divider my="xs" style={{ borderColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.08)' }} />
        
        <Group justify="space-between">
          <Group gap="xs">
            {report.key_entities.map((ent, idx) => (
              <Badge key={idx} size="xs" color="gray" variant="dot">{ent}</Badge>
            ))}
          </Group>
          <Text size="xs" fw={700} c="indigo">
            ★ {t('dash_importance')}: {report.importance_score}/5
          </Text>
        </Group>
      </Stack>
    </Card>
  );
}

function RawArticleCard({ article }: { article: RawArticleResponse }) {
  const { t } = useLanguage();
  const [opened, setOpened] = useState(false);
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  let domain = "";
  try {
    domain = new URL(article.url).hostname;
  } catch (e) {}

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
            {domain}
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

export default function Dashboard({ appMode }: { appMode: 'ai_fusion' | 'pure_rss' }) {
  const { t, lang } = useLanguage();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const [stats, setStats] = useState<Stats | null>(null);
  const [radarStats, setRadarStats] = useState<{ingested:number;noise_filtered:number;duplicates_merged:number;noise_removed_total:number;events_tracked:number;resonant_events:number;alerts:number}|null>(null);
  const [feed, setFeed] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const [currentAlertIndex, setCurrentAlertIndex] = useState(0);
  const seenAlertIds = useRef<Set<number>>(new Set());

  // Raw Articles states
  const [rawFeed, setRawFeed] = useState<RawArticleResponse[]>([]);
  const [rawLoading, setRawLoading] = useState(false);
  const [showRaw, setShowRaw] = useState(appMode === 'pure_rss');

  useEffect(() => {
    setShowRaw(appMode === 'pure_rss');
  }, [appMode]);

  useEffect(() => {
    if (!stats?.latest_alerts || stats.latest_alerts.length <= 1) return;
    const carouselTimer = setInterval(() => {
      setCurrentAlertIndex((prev) => (prev + 1) % stats.latest_alerts.length);
    }, 5000); // Auto-rotate every 5 seconds
    return () => clearInterval(carouselTimer);
  }, [stats?.latest_alerts]);

  const fetchData = async () => {
    if (showRaw || appMode === 'pure_rss') {
      setRawLoading(true);
    }
    try {
      const promises: Promise<any>[] = [
        client.get<Stats>('/intelligence/stats'),
        client.get<Report[]>('/intelligence/feed')
      ];

      if (showRaw || appMode === 'pure_rss') {
        promises.push(client.get<RawArticleResponse[]>('/intelligence/raw-feed'));
      }

      const results = await Promise.all(promises);
      const statsRes = results[0];
      const feedRes = results[1];
      const rawRes = results[2];

      // Radar KPIs (time saved / noise reduction) — non-blocking.
      client.get('/intelligence/radar-stats').then(r => setRadarStats(r.data)).catch(() => {});

      const newStats = statsRes.data;
      const incomingAlerts: Alert[] = newStats?.latest_alerts || [];
      const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

      // If we already have some seen alerts, and we see new ones, trigger notification
      if (seenAlertIds.current.size > 0 && incomingAlerts.length > 0) {
        const newAlerts = incomingAlerts.filter((a: Alert) => !seenAlertIds.current.has(a.id));
        if (newAlerts.length > 0) {
          // Add them to seen
          newAlerts.forEach((a: Alert) => seenAlertIds.current.add(a.id));
          
          if (isTauri) {
            import('@tauri-apps/plugin-notification').then(({ sendNotification, isPermissionGranted }) => {
              isPermissionGranted().then((granted) => {
                if (granted) {
                  newAlerts.forEach((alert: Alert) => {
                    sendNotification({
                      title: `Trend Alert: ${alert.entity_name}`,
                      body: alert.alert_summary.substring(0, 120) + (alert.alert_summary.length > 120 ? '...' : ''),
                    });
                  });
                }
              });
            }).catch(err => {
              console.error('[Tauri Notification] Failed to send notification:', err);
            });
          }
        }
      } else {
        // First load or no alerts, just populate the seen list
        incomingAlerts.forEach((a: Alert) => seenAlertIds.current.add(a.id));
      }

      setStats(newStats);
      setFeed(feedRes.data);
      if (rawRes) {
        setRawFeed(rawRes.data);
      }
    } catch (err) {
      console.error("Failed to fetch dashboard data:", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
      setRawLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [showRaw, appMode]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  const handleScanTrends = async () => {
    try {
      await client.post('/intelligence/scan-trends');
      alert(t('dash_scan_queued'));
    } catch (err) {
      alert(t('dash_scan_failed'));
    }
  };

  if (loading) {
    return (
      <Group justify="center" h="80vh">
        <Loader size="xl" type="dots" color="indigo" />
      </Group>
    );
  }

  const handleTabChange = (val: string | null) => {
    setShowRaw(val === 'raw');
  };

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Stack gap={0}>
          <Text size="xl" fw={700} className="title-text-color">{t('dash_title')}</Text>
          <Text size="sm" c="dimmed">{t('dash_desc')}</Text>
        </Stack>
        <Group>
          {!showRaw && (
            <Button 
              variant="light" 
              color="indigo" 
              leftSection={<Sparkles size={16} />}
              onClick={handleScanTrends}
            >
              {t('dash_force_scan')}
            </Button>
          )}
          <Button 
            variant="subtle" 
            color="gray" 
            leftSection={<RefreshCw size={16} className={refreshing ? "spin-animation" : ""} />}
            onClick={handleRefresh}
          >
            {t('dash_refresh')}
          </Button>
        </Group>
      </Group>

      {/* Stats Cards */}
      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
        <Paper withBorder p="md" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.02)' : '#ffffff' }}>
          <Group justify="space-between">
            <Stack gap={2}>
              <Text size="xs" c="dimmed" fw={700} tt="uppercase">{t('dash_pending_ai')}</Text>
              <Text size="xl" fw={700} className="title-text-color">{stats?.pending_count ?? 0}</Text>
            </Stack>
            <RingProgress
              size={60}
              thickness={6}
              sections={[{ value: stats?.pending_count ? 40 : 100, color: stats?.pending_count ? 'orange' : 'teal' }]}
              label={
                <Group justify="center">
                  <Activity size={16} className="text-gray-400" />
                </Group>
              }
            />
          </Group>
        </Paper>

        <Paper withBorder p="md" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.02)' : '#ffffff' }}>
          <Group justify="space-between">
            <Stack gap={2}>
              <Text size="xs" c="dimmed" fw={700} tt="uppercase">{t('dash_active_scrapers')}</Text>
              <Text size="xl" fw={700} className="title-text-color">{stats?.active_trackers_count ?? 0}</Text>
            </Stack>
            <RingProgress
              size={60}
              thickness={6}
              sections={[{ value: 100, color: 'indigo' }]}
              label={
                <Group justify="center">
                  <CheckCircle size={16} className="text-gray-400" />
                </Group>
              }
            />
          </Group>
        </Paper>

        <Paper withBorder p="md" radius="md" style={{ background: isDark ? 'rgba(255,255,255,0.02)' : '#ffffff' }}>
          <Group justify="space-between">
            <Stack gap={2}>
              <Text size="xs" c="dimmed" fw={700} tt="uppercase">{t('dash_monitored_pages')}</Text>
              <Text size="xl" fw={700} className="title-text-color">{stats?.active_monitors_count ?? 0}</Text>
            </Stack>
            <RingProgress
              size={60}
              thickness={6}
              sections={[{ value: 100, color: 'teal' }]}
              label={
                <Group justify="center">
                  <CheckCircle size={16} className="text-gray-400" />
                </Group>
              }
            />
          </Group>
        </Paper>
      </SimpleGrid>

      {/* Radar KPIs — one quiet line, not a card grid (info-design: meta is
          secondary; content is the hero). "time saved" proof, 盲区 #8. */}
      {radarStats && radarStats.ingested > 0 && (
        <Text size="xs" c="dimmed" mt="xs">
          {lang === 'zh'
            ? <>本周雷达为你过滤了 <Text span fw={700} c="indigo">{radarStats.noise_removed_total}</Text> 条噪音与重复，从 {radarStats.ingested} 条中提炼出 <Text span fw={700} c="indigo">{radarStats.events_tracked}</Text> 个事件{radarStats.resonant_events > 0 ? <>（<Text span c="orange">{radarStats.resonant_events}</Text> 个共振）</> : null}。</>
            : <>This week the radar filtered <Text span fw={700} c="indigo">{radarStats.noise_removed_total}</Text> noise/dupes from {radarStats.ingested} items into <Text span fw={700} c="indigo">{radarStats.events_tracked}</Text> events{radarStats.resonant_events > 0 ? <> (<Text span c="orange">{radarStats.resonant_events}</Text> resonant)</> : null}.</>}
        </Text>
      )}

      {/* Trend Alerts Carousel Card */}
      {!showRaw && stats?.latest_alerts && stats.latest_alerts.length > 0 && (() => {
        const alert = stats.latest_alerts[currentAlertIndex];
        if (!alert) return null;
        
        return (
          <Stack gap="xs">
            <Group justify="space-between" align="center">
              <Text size="lg" fw={700} className="title-text-color">{t('dash_alert')}</Text>
              {stats.latest_alerts.length > 1 && (
                <Group gap="xs">
                  {stats.latest_alerts.map((_, idx) => (
                    <UnstyledButton
                      key={idx}
                      onClick={() => setCurrentAlertIndex(idx)}
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: idx === currentAlertIndex ? 'var(--mantine-color-red-6)' : (isDark ? 'rgba(255, 255, 255, 0.2)' : 'rgba(0, 0, 0, 0.15)'),
                        transition: 'background-color 0.2s ease',
                        cursor: 'pointer'
                      }}
                    />
                  ))}
                </Group>
              )}
            </Group>
            
            <Paper 
              withBorder 
              p="md" 
              radius="md" 
              style={{ 
                borderLeft: '4px solid var(--mantine-color-red-6)',
                background: 'rgba(250, 82, 82, 0.04)',
                borderColor: 'rgba(250, 82, 82, 0.2)',
                position: 'relative'
              }}
            >
              <Group align="flex-start" gap="md" wrap="nowrap">
                <AlertTriangle color="var(--mantine-color-red-6)" size={24} style={{ marginTop: 2, flexShrink: 0 }} />
                <Stack gap="xs" style={{ flex: 1 }}>
                  <Group justify="space-between" align="center">
                    <Text size="sm" fw={700} className="title-text-color">
                      {t('dash_trend_trigger')}: {alert.entity_name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {new Date(alert.created_at).toLocaleString()}
                    </Text>
                  </Group>
                  <Text size="xs" c="dimmed" style={{ 
                    lineHeight: 1.6,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    display: '-webkit-box',
                    WebkitLineClamp: 3,
                    WebkitBoxOrient: 'vertical',
                    wordBreak: 'break-word'
                  }}>
                    {alert.alert_summary}
                  </Text>
                  
                  {/* Click to view details and sources */}
                  <Group justify="flex-end" align="center" mt="xs">
                    <Button 
                      variant="subtle" 
                      color="red" 
                      size="xs"
                      onClick={() => setSelectedAlert(alert)}
                      styles={{ root: { padding: '4px 8px', height: 'auto' } }}
                    >
                      {t('dash_view_details')} →
                    </Button>
                  </Group>
                </Stack>
              </Group>
            </Paper>
          </Stack>
        );
      })()}

      <Modal 
        opened={!!selectedAlert} 
        onClose={() => setSelectedAlert(null)} 
        title={
          <Group gap="xs">
            <AlertTriangle color="var(--mantine-color-red-6)" size={20} />
            <Text fw={700} size="md" className="title-text-color">
              {t('dash_trend_trigger')}: {selectedAlert?.entity_name}
            </Text>
          </Group>
        }
        centered
        size="lg"
        styles={{
          content: { background: isDark ? '#1a1b1e' : '#ffffff', border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.1)' },
          header: { background: isDark ? '#1a1b1e' : '#ffffff' }
        }}
      >
        {selectedAlert && (
          <Stack gap="md">
            <Text size="xs" c="dimmed">
              {new Date(selectedAlert.created_at).toLocaleString()}
            </Text>
            <Paper p="md" radius="md" style={{ background: 'rgba(250, 82, 82, 0.03)', border: '1px solid rgba(250, 82, 82, 0.1)' }}>
              <Text 
                size="sm" 
                c="dimmed" 
                style={{ lineHeight: 1.6 }}
                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(parseMarkdown(selectedAlert.alert_summary)) }}
              />
            </Paper>
            
            {selectedAlert.sources && selectedAlert.sources.length > 0 && (() => {
              const sources = selectedAlert.sources;
              return (
                <Stack gap="xs" mt="md">
                  <Group gap="xs" align="center">
                    <Text size="sm" fw={700} className="title-text-color">
                      {t('dash_adopted_sources')}
                    </Text>
                    <Badge 
                      size="sm" 
                      variant="filled"
                      style={{ 
                        borderRadius: '9999px',
                        backgroundColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.05)',
                        color: isDark ? '#a5d8ff' : 'var(--mantine-color-indigo-6)',
                        fontWeight: 700
                      }}
                    >
                      {sources.length}
                    </Badge>
                  </Group>
                  <Paper 
                    p="md" 
                    radius="md" 
                    style={{ 
                      background: isDark ? 'rgba(21, 23, 27, 0.6)' : '#f8f9fa', 
                      border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.08)'}`,
                      boxShadow: isDark ? 'inset 0 2px 4px rgba(0,0,0,0.2)' : 'inset 0 1px 2px rgba(0,0,0,0.05)'
                    }}
                  >
                    <ScrollArea.Autosize mah={220} offsetScrollbars>
                      <Stack gap={0}>
                        {sources.map((src, index) => {
                          let domain = "";
                          try {
                            domain = new URL(src.url).hostname;
                          } catch (e) {}
                          
                          return (
                            <Group 
                              key={index} 
                              gap="md" 
                              wrap="nowrap" 
                              align="flex-start" 
                              py="sm" 
                              style={{ 
                                borderBottom: index === sources.length - 1 
                                  ? 'none' 
                                  : `1px solid ${isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)'}` 
                              }}
                            >
                            <div style={{
                              width: 32,
                              height: 32,
                              borderRadius: 6,
                              background: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)',
                              border: isDark ? '1px solid rgba(255, 255, 255, 0.06)' : '1px solid rgba(0, 0, 0, 0.08)',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              flexShrink: 0,
                              marginTop: 2
                            }}>
                              <SourceIcon domain={domain} type="evidence" />
                            </div>
                            <Stack gap={4} style={{ flex: 1 }}>
                              <Anchor 
                                href={safeHref(src.url)} 
                                target="_blank" rel="noopener noreferrer"
                                size="sm" 
                                fw={600} 
                               className="title-text-color" 
                                underline="hover"
                                style={{ 
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '6px',
                                  lineHeight: 1.4
                                }}
                              >
                                {src.title}
                                <span style={{ fontSize: '11px', color: 'var(--accent-link-color)' }}>↗</span>
                              </Anchor>
                              {src.description && (
                                <Text size="xs" c="dimmed" style={{ lineHeight: 1.5 }}>
                                  {src.description}
                                </Text>
                              )}
                            </Stack>
                            </Group>
                          );
                        })}
                      </Stack>
                    </ScrollArea.Autosize>
                  </Paper>
                </Stack>
              );
            })()}

            <Group justify="flex-end" mt="xs">
              <Button color="indigo" onClick={() => setSelectedAlert(null)}>
                {t('dash_close')}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>

      {/* Intelligence Feed vs Raw Articles Tabs */}
      <Stack gap="xs">
        {appMode === 'ai_fusion' && (
          <Tabs value={showRaw ? 'raw' : 'ai'} onChange={handleTabChange} variant="outline" mb="sm">
            <Tabs.List>
              <Tabs.Tab value="ai" leftSection={<Sparkles size={14} />}>
                {t('dashboard_ai_feed')}
              </Tabs.Tab>
              <Tabs.Tab value="raw" leftSection={<FileText size={14} />}>
                {t('dashboard_raw_feed')}
              </Tabs.Tab>
            </Tabs.List>
          </Tabs>
        )}

        {showRaw ? (
          <Stack gap="xs">
            <Text size="lg" fw={700} className="title-text-color">{t('dashboard_raw_feed')}</Text>
            <ScrollArea h="55vh" scrollbarSize={6}>
              <Stack gap="md">
                {rawLoading ? (
                  <Group justify="center" py="xl">
                    <Loader size="md" color="indigo" />
                  </Group>
                ) : rawFeed.length === 0 ? (
                  <Paper withBorder p="xl" radius="md" style={{ background: 'transparent', textAlign: 'center' }}>
                    <Text c="dimmed">{t('dash_no_intel')}</Text>
                  </Paper>
                ) : (
                  rawFeed.map((article) => (
                    <RawArticleCard key={article.id} article={article} />
                  ))
                )}
              </Stack>
            </ScrollArea>
          </Stack>
        ) : (
          <Stack gap="xs">
            <Text size="lg" fw={700} className="title-text-color">{t('dash_latest_intel')}</Text>
            <ScrollArea h="55vh" scrollbarSize={6}>
              <Stack gap="md">
                {feed.length === 0 ? (
                  <Paper withBorder p="xl" radius="md" style={{ background: 'transparent', textAlign: 'center' }}>
                    <Text c="dimmed">{t('dash_no_intel')}</Text>
                  </Paper>
                ) : (
                  feed.map((report) => (
                    <IntelReportCard key={report.id} report={report} />
                  ))
                )}
              </Stack>
            </ScrollArea>
          </Stack>
        )}
      </Stack>
    </Stack>
  );
}
