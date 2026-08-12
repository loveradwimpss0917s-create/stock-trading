export function assertNoLookahead(knownFrom: Date, signalDate: Date): void {
  if (knownFrom > signalDate)
    throw new Error(`Look-ahead: known_from ${knownFrom.toISOString()} > signal ${signalDate.toISOString()}`);
}
