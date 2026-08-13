// Shared source-identity display helpers. Lived inside Dashboard.tsx until P6
// moved the raw subscription stream out of that page — both surfaces must show
// "who reported it" the same way, so the logic lives once, here.
import { useState } from 'react';
import { FileText, Link as LinkIcon } from 'lucide-react';

// Only allow http(s) hrefs from untrusted feed/LLM content — blocks a
// javascript:/data: URL in a scraped link from executing on click (stored XSS).
export const safeHref = (u?: string): string | undefined =>
  (u && /^https?:\/\//i.test(u)) ? u : undefined;

// Aggregators (Google News etc.) redirect through their own domain, so the item
// URL's hostname is the aggregator, not the real publisher. The real outlet is in
// the title suffix ("Headline - The Register"). Surface the real publisher so the
// feed shows who reported it, not "news.google.com" (愿景: 一手来源/溯源).
const AGGREGATOR_HOSTS = ['news.google.com', 'google.com', 'bing.com'];
const publisherFromTitle = (host: string, title: string): string | null => {
  const h = (host || '').replace(/^www\./, '');
  if (!AGGREGATOR_HOSTS.some(a => h === a || h.endsWith('.' + a))) return null;
  const m = (title || '').match(/[\s]+[-–—][\s]+([^-–—]{2,42})\s*$/);
  return m ? m[1].trim() : null;
};

export const displaySource = (url: string, title: string): string => {
  let host = '';
  try { host = new URL(url).hostname; } catch { return ''; }
  return publisherFromTitle(host, title) || host.replace(/^www\./, '');
};

export function SourceIcon({ domain, type }: { domain: string; type: 'evidence' | 'original' }) {
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
