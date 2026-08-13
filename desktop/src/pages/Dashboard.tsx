import { useEffect, useState, useRef } from 'react';
import DOMPurify from 'dompurify';
import {
  Text, Paper, SimpleGrid, Group, Stack, Badge,
  Button, RingProgress, Loader, ScrollArea, UnstyledButton, Modal, Anchor,
  useMantineColorScheme
} from '@mantine/core';
import {
  Activity, AlertTriangle, CheckCircle, RefreshCw, Sparkles
} from 'lucide-react';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';
import { safeHref, SourceIcon } from '../components/sourceDisplay';


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



interface Stats {
  pending_count: number;
  active_trackers_count: number;
  active_monitors_count: number;
  latest_alerts: Alert[];
}

const parseMarkdown = (text: string) => {
  let formatted = text
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color: var(--accent-link-color); text-decoration: underline; font-weight: 500;">$1</a>');
  return formatted.replace(/\n/g, '<br />');
};


export default function Dashboard({ appMode }: { appMode: 'ai_fusion' | 'pure_rss' }) {
  const { t, lang } = useLanguage();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const [stats, setStats] = useState<Stats | null>(null);
  const [radarStats, setRadarStats] = useState<{ingested:number;noise_filtered:number;duplicates_merged:number;noise_removed_total:number;events_tracked:number;resonant_events:number;alerts:number}|null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const [currentAlertIndex, setCurrentAlertIndex] = useState(0);
  const seenAlertIds = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!stats?.latest_alerts || stats.latest_alerts.length <= 1) return;
    const carouselTimer = setInterval(() => {
      setCurrentAlertIndex((prev) => (prev + 1) % stats.latest_alerts.length);
    }, 5000); // Auto-rotate every 5 seconds
    return () => clearInterval(carouselTimer);
  }, [stats?.latest_alerts]);

  const fetchData = async () => {
    try {
      // P6: the reading feeds (refined threads + raw stream) live on the radar
      // page now — this page is the stats board only.
      const statsRes = await client.get<Stats>('/intelligence/stats');

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
    } catch (err) {
      console.error("Failed to fetch dashboard data:", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [appMode]);

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


  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Stack gap={0}>
          <Text size="xl" fw={700} className="title-text-color">{t('dash_title')}</Text>
          <Text size="sm" c="dimmed">{t('dash_desc')}</Text>
        </Stack>
        <Group>
          {(
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
      {stats?.latest_alerts && stats.latest_alerts.length > 0 && (() => {
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

    </Stack>
  );
}
