import { useEffect, useState } from 'react';
import { 
  Text, Paper, Group, Stack, Button, MultiSelect, Accordion, Loader, ScrollArea
} from '@mantine/core';
import { RefreshCw, Sparkles, Calendar } from 'lucide-react';
import client from '../api/client';
import { useLanguage } from '../i18n/translations';

interface Briefing {
  id: number;
  date_str: string;
  section_name: string;
  content: string;
  created_at: string;
}

interface Tracker {
  id: number;
  radar_section: string;
}

export default function Briefing() {
  const { t } = useLanguage();
  const [briefings, setBriefings] = useState<Briefing[]>([]);
  const [sections, setSections] = useState<string[]>([]);
  const [selectedSections, setSelectedSections] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const fetchBriefings = async () => {
    try {
      const res = await client.get<Briefing[]>('/briefing/');
      setBriefings(res.data);
    } catch (err) {
      console.error("Failed to fetch briefings:", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const fetchSections = async () => {
    try {
      const res = await client.get<Tracker[]>('/trackers/');
      const uniqueSections = Array.from(new Set(res.data.map(t => t.radar_section).filter(Boolean)));
      setSections(uniqueSections);
    } catch (err) {
      console.error("Failed to fetch sections:", err);
    }
  };

  useEffect(() => {
    fetchBriefings();
    fetchSections();
  }, []);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const sectionStr = selectedSections.length > 0 ? selectedSections.join(",") : "ALL";
      await client.post('/briefing/generate', { section_name: sectionStr });
      alert(t('brief_generating'));
      // Wait a bit then refresh
      setTimeout(fetchBriefings, 3000);
    } catch (err) {
      alert(t('brief_fail') + " " + err);
    } finally {
      setGenerating(false);
    }
  };

  const parseMarkdown = (text: string) => {
    let formatted = text
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color: #748ffc; text-decoration: underline; font-weight: 500;">$1</a>');
    return formatted.replace(/\n/g, '<br />');
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
          <Text size="xl" fw={700} c="white">{t('brief_title')}</Text>
          <Text size="sm" c="dimmed">{t('brief_desc')}</Text>
        </Stack>
        <Button 
          variant="subtle" 
          color="gray" 
          leftSection={<RefreshCw size={16} className={refreshing ? "spin-animation" : ""} />}
          onClick={() => { setRefreshing(true); fetchBriefings(); }}
        >
          {t('dash_refresh')}
        </Button>
      </Group>

      <Paper withBorder p="lg" radius="md" style={{ background: 'rgba(255,255,255,0.015)' }}>
        <Stack gap="md">
          <MultiSelect
            label={t('brief_select_sections')}
            placeholder={t('brief_select_placeholder')}
            data={sections}
            value={selectedSections}
            onChange={setSelectedSections}
            clearable
            searchable
            styles={{ 
              input: { background: 'rgba(255,255,255,0.05)', color: 'white' },
              dropdown: { background: '#1a1b1e', border: '1px solid rgba(255,255,255,0.08)' }
            }}
          />
          <Button 
            color="indigo" 
            loading={generating}
            onClick={handleGenerate}
            leftSection={<Sparkles size={16} />}
            style={{ alignSelf: 'flex-start' }}
          >
            {t('brief_generate')}
          </Button>
        </Stack>
      </Paper>

      <Stack gap="xs">
        <Text size="md" fw={700} c="white">{t('brief_archives')}</Text>
        <ScrollArea h="50vh" scrollbarSize={6}>
          {briefings.length === 0 ? (
            <Paper withBorder p="xl" radius="md" style={{ background: 'transparent', textAlign: 'center' }}>
              <Text c="dimmed">{t('brief_empty')}</Text>
            </Paper>
          ) : (
            <Accordion variant="separated" styles={{
              item: { background: 'rgba(255,255,255,0.01)', border: '1px solid rgba(255,255,255,0.05)', borderRadius: 'var(--mantine-radius-md)' },
              control: { color: 'white', fontWeight: 600 },
              content: { color: 'var(--mantine-color-gray-3)', lineHeight: 1.6 }
            }} defaultValue={String(briefings[0].id)}>
              {briefings.map((b) => (
                <Accordion.Item key={b.id} value={String(b.id)}>
                  <Accordion.Control icon={<Calendar size={16} />}>
                    {t('brief_date')}: {b.date_str} [{b.section_name}]
                  </Accordion.Control>
                  <Accordion.Panel>
                    <Text 
                      size="sm" 
                      dangerouslySetInnerHTML={{ __html: parseMarkdown(b.content) }} 
                    />
                  </Accordion.Panel>
                </Accordion.Item>
              ))}
            </Accordion>
          )}
        </ScrollArea>
      </Stack>
    </Stack>
  );
}
