/**
 * land_value_research – app.ts
 *
 * Flat-mode configuration for StockTable with detail modal.
 * Fetches ranking data from /api/ranking and renders land value
 * ranking alongside formula_screening metrics.
 */

import type { ColumnDef, MetricThreshold, StockTableConfig } from "@stock-web-ui/runtime";
import type { MetricColSpec } from "@stock-web-ui/columns";

type StockTableApi = {
  init: (config: StockTableConfig) => void;
};

type StockColumnsApi = {
  buildMetricCol: (spec: MetricColSpec, accessor: (row: Record<string, unknown>) => number | null) => ColumnDef;
  codeCol: ColumnDef;
  nameCol: ColumnDef;
  priceCol: ColumnDef;
  peg5yCol: ColumnDef;
  peg5y2fCol: ColumnDef;
  fcfYCol: ColumnDef;
  croicCol: ColumnDef;
  NCR_SPEC: MetricColSpec;
  PER_A_SPEC: MetricColSpec;
  PER_C_SPEC: MetricColSpec;
  PER_N_SPEC: MetricColSpec;
  EQUITY_SPEC: MetricColSpec;
  COMMON_THRESHOLDS: Record<string, MetricThreshold>;
};

function getStockTable(): StockTableApi {
  const runtime: StockTableApi | undefined = (
    globalThis as typeof globalThis & { StockTable?: StockTableApi }
  ).StockTable;
  if (!runtime) {
    throw new Error("Shared StockTable runtime is not loaded.");
  }
  return runtime;
}

function getStockColumns(): StockColumnsApi {
  const cols: StockColumnsApi | undefined = (
    globalThis as typeof globalThis & { StockColumns?: StockColumnsApi }
  ).StockColumns;
  if (!cols) {
    throw new Error("Shared StockColumns module is not loaded.");
  }
  return cols;
}

const StockTable: StockTableApi = getStockTable();
const C: StockColumnsApi = getStockColumns();
const IS_GITHUB_PAGES: boolean = location.hostname === "expgolemclone.github.io";

/* ------------------------------------------------------------------ */
/*  Metric accessors (nested under row.metrics)                        */
/* ------------------------------------------------------------------ */

function metricsAccessor(key: string): (row: Record<string, unknown>) => number | null {
  return (row: Record<string, unknown>): number | null => {
    const metrics = row.metrics as Record<string, unknown> | undefined;
    return (metrics?.[key] as number) ?? null;
  };
}

function renderPreferredShares(row: Record<string, unknown>): string {
  const metrics = row.metrics as Record<string, unknown> | undefined;
  if (metrics?.has_preferred_shares === true) {
    return "yes";
  }
  if (metrics?.has_preferred_shares === false) {
    return "no";
  }
  return "-";
}

function preferredSharesSortValue(row: Record<string, unknown>): number | null {
  const metrics = row.metrics as Record<string, unknown> | undefined;
  if (metrics?.has_preferred_shares === true) {
    return 1;
  }
  if (metrics?.has_preferred_shares === false) {
    return 0;
  }
  return null;
}

function numField(key: string): (row: Record<string, unknown>) => number | null {
  return (row: Record<string, unknown>): number | null => {
    const v = row[key];
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  };
}

function toOku(value: number | null): string {
  if (value === null) return "-";
  return (value / 100_000_000).toLocaleString("ja-JP", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/* ------------------------------------------------------------------ */
/*  Column definitions                                                 */
/* ------------------------------------------------------------------ */

const COLUMNS: ColumnDef[] = [
  C.codeCol,
  C.nameCol,
  C.priceCol,
  {
    key: "ratio",
    header: "ratio",
    type: "num",
    title: "推定土地時価 / 時価総額",
    render: (row): string => {
      const v = numField("ratio")(row);
      return v !== null ? v.toFixed(4) : "-";
    },
    sortValue: numField("ratio"),
  },
  {
    key: "memo",
    header: "memo",
    type: "text",
    title: "調査メモ",
    toggleable: true,
    render: (): string => "memo",
    detailContent: (row): string | null => {
      const v = row.memo_html;
      return typeof v === "string" && v.length > 0 ? v : null;
    },
  },
  C.buildMetricCol(C.NCR_SPEC, metricsAccessor("net_cash_ratio")),
  C.buildMetricCol(C.PER_A_SPEC, metricsAccessor("per_actual")),
  C.buildMetricCol(C.PER_C_SPEC, metricsAccessor("per")),
  C.buildMetricCol(C.PER_N_SPEC, metricsAccessor("per_next")),
  {
    key: "has_preferred_shares",
    header: "pref",
    type: "text",
    title: "優先株",
    toggleable: true,
    render: renderPreferredShares,
    sortValue: preferredSharesSortValue,
  },
  C.buildMetricCol(C.EQUITY_SPEC, metricsAccessor("equity_ratio")),
  C.fcfYCol,
  C.croicCol,
  C.peg5yCol,
  C.peg5y2fCol,
  {
    key: "estimated_value_oku",
    header: "est_val",
    type: "num",
    title: "推定土地時価(億円)",
    toggleable: true,
    render: (row): string => toOku(numField("estimated_value")(row)),
    sortValue: numField("estimated_value"),
  },
  {
    key: "market_cap_oku",
    header: "mcap",
    type: "num",
    title: "時価総額(億円)",
    toggleable: true,
    render: (row): string => toOku(numField("market_cap")(row)),
    sortValue: numField("market_cap"),
  },
  {
    key: "book_value_oku",
    header: "bv",
    type: "num",
    title: "土地簿価(億円)",
    toggleable: true,
    render: (row): string => toOku(numField("book_value")(row)),
    sortValue: numField("book_value"),
  },
  {
    key: "unrealized_gain_oku",
    header: "gain",
    type: "num",
    title: "含み益(億円)",
    toggleable: true,
    render: (row): string => toOku(numField("unrealized_gain")(row)),
    sortValue: numField("unrealized_gain"),
  },
  {
    key: "geocode_tag",
    header: "geo",
    type: "text",
    title: "住所解決タグ",
    toggleable: true,
    render: (row): string => String(row.geocode_tag ?? ""),
  },
  {
    key: "confidence",
    header: "conf",
    type: "text",
    title: "地価推定信頼度",
    toggleable: true,
    render: (row): string => String(row.confidence ?? ""),
  },
  {
    key: "anomaly",
    header: "warn",
    type: "text",
    title: "異常値警告",
    toggleable: true,
    render: (row): string => String(row.anomaly ?? ""),
  },
];

const METRIC_THRESHOLDS: Record<string, MetricThreshold> = {
  ...C.COMMON_THRESHOLDS,
  ratio: { good: (v): boolean => v >= 0.5 },
};

/* ------------------------------------------------------------------ */
/*  Bootstrap                                                          */
/* ------------------------------------------------------------------ */

function bootstrap(): void {
  StockTable.init({
    defaultTitle: "Land Value Ranking",
    dataUrl: IS_GITHUB_PAGES ? "assets/ranking.json" : "/api/ranking",
    columns: COLUMNS,
    metricThresholds: METRIC_THRESHOLDS,
    defaultSortKey: "ratio",
    defaultSortDirection: "desc",
    tabMode: false,
    githubPages: IS_GITHUB_PAGES,
    detailModal: true,
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrap);
} else {
  bootstrap();
}
