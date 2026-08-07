import { useMemo } from 'react';
import { Group, Text, Tooltip } from '@mantine/core';

/**
 * Daily token consumption as a calendar heatmap.
 *
 * Replaces a bar chart that was hard to read for two reasons, only one of which
 * was the geometry:
 *
 *  1. The series dropped days with no usage entirely, so a six-day stretch where
 *     the app was not running rendered as continuous consumption. A calendar
 *     fixes this by construction — a cell is a DATE, not a data point, so a gap
 *     has to draw itself.
 *  2. One day (5.9M tokens, the semantic-layer backfill) was 5x the next
 *     highest, so a linear scale flattened every other day to a stub. A heatmap
 *     on a LINEAR colour ramp would have inherited this exactly — one dark cell
 *     and a wash of pale ones. Hence quantile bucketing below.
 *
 * Encoding follows the sequential rule: one hue, light→dark, magnitude only.
 * Colour is a coarse channel (~5 distinguishable steps), so the exact tokens,
 * cost and call count live in the per-cell tooltip.
 */

export interface DailyUsage {
  iso: string;        // YYYY-MM-DD
  tokens: number;
  cost_usd?: number;
  calls?: number;
}

const LEVELS = 4;                     // non-zero buckets; ≤7 classes stays legible
const CELL = 16;
const GAP = 4;                         // surface shows between cells, never touching

// One hue (Mantine indigo), lightest = least. Both ramps are VALIDATED, not
// eyeballed: monotone lightness, ≥0.06 ΔL between steps, single hue, and — the
// check that failed the first hand-picked attempt — the step nearest the surface
// still clears 2:1 against it. Without that last one the lowest bucket is
// indistinguishable from an empty cell, so "a little usage" and "none at all"
// would render identically, which is the one distinction this chart exists for.
// Dark ramp on #17181a: 2.62:1 at the light end. Light ramp on #ffffff: 2.29:1.
// Re-run scripts/validate_palette.js --ordinal if either is ever retuned.
const RAMP_DARK  = ['#364fc7', '#4263eb', '#5c7cfa', '#91a7ff'];
const RAMP_LIGHT = ['#91a7ff', '#5c7cfa', '#4263eb', '#364fc7'];

const WEEKDAYS_ZH = ['一', '二', '三', '四', '五', '六', '日'];

function isoOf(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * Quantile thresholds over the NON-ZERO days.
 *
 * Equal-width bins are wrong for this data: with a 5x outlier, 9 of 11 days land
 * in bin 1 and the chart says nothing. Equal-COUNT bins spread those days across
 * the ramp, which is what makes "which days were heavy" readable. The trade is
 * that colour distance no longer equals token distance — acceptable only because
 * every cell carries its exact numbers on hover.
 */
function quantileThresholds(values: number[]): number[] {
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length === 0) return [];
  return Array.from({ length: LEVELS - 1 }, (_, i) => {
    const q = (i + 1) / LEVELS;
    return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
  });
}

export default function UsageHeatmap({ data, isDark }: { data: DailyUsage[]; isDark: boolean }) {
  const ramp = isDark ? RAMP_DARK : RAMP_LIGHT;
  const emptyCell = isDark ? 'rgba(255,255,255,0.045)' : 'rgba(0,0,0,0.05)';

  const { weeks, thresholds, monthLabels } = useMemo(() => {
    const byIso = new Map(data.map(d => [d.iso, d]));
    const th = quantileThresholds(data.filter(d => d.tokens > 0).map(d => d.tokens));

    // Window: from the first day we have through today, padded to whole weeks and
    // to a 4-week minimum so the grid has a stable shape from the very first run.
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const first = data.length ? new Date(`${data[0].iso}T00:00:00`) : new Date(today);
    const minStart = new Date(today); minStart.setDate(minStart.getDate() - 27);
    const start = first < minStart ? first : minStart;
    // Back up to Monday (getDay: 0=Sun) so every column is one calendar week.
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7));

    const cols: (DailyUsage | null)[][] = [];
    const labels: { col: number; text: string }[] = [];
    const cur = new Date(start);
    let lastMonth = -1;
    while (cur <= today) {
      const col: (DailyUsage | null)[] = [];
      for (let i = 0; i < 7; i++) {
        if (cur > today) { col.push(null); continue; }
        const iso = isoOf(cur);
        col.push(byIso.get(iso) ?? { iso, tokens: 0 });
        if (cur.getMonth() !== lastMonth && cur.getDate() <= 7) {
          lastMonth = cur.getMonth();
          labels.push({ col: cols.length, text: `${cur.getMonth() + 1}月` });
        }
        cur.setDate(cur.getDate() + 1);
      }
      cols.push(col);
    }
    return { weeks: cols, thresholds: th, monthLabels: labels };
  }, [data]);

  const levelOf = (tokens: number) => {
    if (tokens <= 0) return -1;
    let lvl = 0;
    while (lvl < thresholds.length && tokens > thresholds[lvl]) lvl++;
    return lvl;
  };

  const cellStyle = (tokens: number): React.CSSProperties => {
    const lvl = levelOf(tokens);
    return {
      width: CELL, height: CELL, borderRadius: 3,
      background: lvl < 0 ? emptyCell : ramp[lvl],
      cursor: tokens > 0 ? 'default' : undefined,
    };
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: GAP, overflowX: 'auto', paddingBottom: 4 }}>
        {/* Weekday gutter: only alternate rows are labelled, so the axis stays recessive. */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: GAP, marginRight: 2 }}>
          <div style={{ height: 14 }} />
          {WEEKDAYS_ZH.map((w, i) => (
            <div key={w} style={{ height: CELL, display: 'flex', alignItems: 'center' }}>
              <Text size="9px" c="dimmed" style={{ lineHeight: 1, width: 12 }}>
                {i % 2 === 1 ? w : ''}
              </Text>
            </div>
          ))}
        </div>

        {weeks.map((col, ci) => (
          <div key={ci} style={{ display: 'flex', flexDirection: 'column', gap: GAP }}>
            <Text size="9px" c="dimmed" style={{ height: 14, lineHeight: '14px', whiteSpace: 'nowrap' }}>
              {monthLabels.find(m => m.col === ci)?.text ?? ''}
            </Text>
            {col.map((d, ri) =>
              d === null ? (
                <div key={ri} style={{ width: CELL, height: CELL }} />
              ) : (
                <Tooltip
                  key={ri}
                  withArrow
                  openDelay={80}
                  label={
                    d.tokens > 0
                      ? `${d.iso} · ${d.tokens.toLocaleString()} tok · $${(d.cost_usd ?? 0).toFixed(4)}${d.calls ? ` · ${d.calls} calls` : ''}`
                      : `${d.iso} · 无消耗`
                  }
                >
                  <div style={cellStyle(d.tokens)} />
                </Tooltip>
              )
            )}
          </div>
        ))}
      </div>

      {/* Scale legend. A sequential ramp always ships one — without it the reader
          cannot tell whether darker means more or simply different. */}
      <Group gap={6} mt="lg" justify="flex-start">
        <Text size="xs" c="dimmed">少</Text>
        <div style={{ width: CELL, height: CELL, borderRadius: 3, background: emptyCell }} />
        {ramp.map(c => (
          <div key={c} style={{ width: CELL, height: CELL, borderRadius: 3, background: c }} />
        ))}
        <Text size="xs" c="dimmed">多</Text>
      </Group>
    </div>
  );
}
