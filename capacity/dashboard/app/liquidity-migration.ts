export type MigrationParameters = {
  aum0: number; scaleElasticity: number; tailElasticity: number;
  burrC: number; burrD: number; burrScale: number;
};

export function migrationShares(aum: number, p: MigrationParameters, buckets: { lower: number; upper: number }[]) {
  const ratio = aum / p.aum0;
  const scale = p.burrScale * Math.pow(ratio, p.scaleElasticity);
  const d = p.burrD * Math.pow(ratio, -p.tailElasticity);
  // Evaluate survival probabilities in log space, including the open upper tail.
  const survival = (x: number) => {
    if (x <= 0) return 1;
    if (!Number.isFinite(x)) return 0;
    const z = p.burrC * Math.log(x / scale);
    const logTerm = Math.max(0, z) + Math.log1p(Math.exp(-Math.abs(z)));
    return Math.exp(-d * logTerm);
  };
  return buckets.map(b => Math.max(0, survival(b.lower) - survival(b.upper)) * 100);
}
