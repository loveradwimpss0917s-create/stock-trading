/** Clips values outside the [p, 1-p] quantile range to that range's bounds. */
export function winsorize(xs: number[], p = 0.01): number[] {
  if (xs.length === 0) return [];
  const sorted = [...xs].sort((a, b) => a - b);
  const lowerBound = sorted[Math.floor(p * (sorted.length - 1))];
  const upperBound = sorted[Math.ceil((1 - p) * (sorted.length - 1))];
  return xs.map((x) => Math.min(Math.max(x, lowerBound), upperBound));
}

/** Standardizes to zero mean, unit (population) standard deviation. */
export function zscore(xs: number[]): number[] {
  const n = xs.length;
  if (n === 0) return [];
  const mean = xs.reduce((a, b) => a + b, 0) / n;
  const variance = xs.reduce((a, b) => a + (b - mean) ** 2, 0) / n;
  const sd = Math.sqrt(variance);
  if (sd === 0) return xs.map(() => 0);
  return xs.map((x) => (x - mean) / sd);
}

/** Demeans each score against the average of its own sector33 group. */
export function sectorNeutralize(
  scores: Map<string, number>,
  sector: Map<string, string>
): Map<string, number> {
  const sectorGroups = new Map<string, string[]>();
  for (const [code, sec] of sector) {
    if (!scores.has(code)) continue;
    if (!sectorGroups.has(sec)) sectorGroups.set(sec, []);
    sectorGroups.get(sec)!.push(code);
  }

  const result = new Map<string, number>();
  for (const codes of sectorGroups.values()) {
    const mean = codes.reduce((sum, code) => sum + scores.get(code)!, 0) / codes.length;
    for (const code of codes) {
      result.set(code, scores.get(code)! - mean);
    }
  }
  return result;
}
