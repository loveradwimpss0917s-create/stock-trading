// Shared adapter contracts for price/financials/margin-short data sources.
//
// The actual ingestion batch that runs in production lives in
// pipeline_py/ingest/*.py (executed by GitHub Actions — see design
// blueprint section A: heavy/scheduled data work runs in Python on
// Actions, not in the Worker). These TypeScript interfaces exist so
// packages/core and any future Worker-side code share one type contract
// with that Python pipeline's output shape, and so a plan upgrade (Free ->
// Standard for margin/short-sale data) only requires swapping which
// adapter implements MarginShortAdapter — not touching call sites.

export interface DailyQuote {
  code: string;
  date: string; // YYYY-MM-DD
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  turnoverValue: number | null;
  knownFrom: string; // ISO timestamp
}

export interface FinancialStatement {
  code: string;
  disclosureDate: string; // YYYY-MM-DD
  fiscalPeriod: string; // 1Q/2Q/3Q/FY
  netSales: number | null;
  operatingProfit: number | null;
  ordinaryProfit: number | null;
  netIncome: number | null;
  eps: number | null;
  bps: number | null;
  knownFrom: string; // ISO timestamp — must equal the disclosure time, not ingestion time
}

export interface MarginShort {
  code: string;
  date: string; // YYYY-MM-DD
  marginLong: number | null;
  marginShort: number | null;
  shortBalanceRatio: number | null;
  dataFreq: 'weekly' | 'daily';
}

export interface PriceAdapter {
  fetchDailyQuotes(code: string, from: string, to: string): Promise<DailyQuote[]>;
}

export interface FinancialsAdapter {
  fetchStatements(code: string): Promise<FinancialStatement[]>;
}

export interface MarginShortAdapter {
  fetchMarginShort(code: string, from: string, to: string): Promise<MarginShort[]>;
}
