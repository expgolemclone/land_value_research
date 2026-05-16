/**
 * land_value_research – app.ts
 *
 * Flat-mode configuration for StockTable with detail modal.
 * Fetches ranking data from /api/ranking and renders land value
 * ranking alongside formula_screening metrics.
 */
function getStockTable() {
    const runtime = globalThis.StockTable;
    if (!runtime) {
        throw new Error("Shared StockTable runtime is not loaded.");
    }
    return runtime;
}
function getStockColumns() {
    const cols = globalThis.StockColumns;
    if (!cols) {
        throw new Error("Shared StockColumns module is not loaded.");
    }
    return cols;
}
const StockTable = getStockTable();
const C = getStockColumns();
const IS_GITHUB_PAGES = location.hostname === "expgolemclone.github.io";
/* ------------------------------------------------------------------ */
/*  Metric accessors (nested under row.metrics)                        */
/* ------------------------------------------------------------------ */
function metricsAccessor(key) {
    return (row) => {
        const metrics = row.metrics;
        return metrics?.[key] ?? null;
    };
}
function renderPreferredShares(row) {
    const metrics = row.metrics;
    if (metrics?.has_preferred_shares === true) {
        return "yes";
    }
    if (metrics?.has_preferred_shares === false) {
        return "no";
    }
    return "-";
}
function preferredSharesSortValue(row) {
    const metrics = row.metrics;
    if (metrics?.has_preferred_shares === true) {
        return 1;
    }
    if (metrics?.has_preferred_shares === false) {
        return 0;
    }
    return null;
}
function numField(key) {
    return (row) => {
        const v = row[key];
        return typeof v === "number" && Number.isFinite(v) ? v : null;
    };
}
function toOku(value) {
    if (value === null)
        return "-";
    return (value / 100_000_000).toLocaleString("ja-JP", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}
/* ------------------------------------------------------------------ */
/*  Column definitions                                                 */
/* ------------------------------------------------------------------ */
const COLUMNS = [
    C.codeCol,
    C.nameCol,
    C.priceCol,
    {
        key: "ratio",
        header: "ratio",
        type: "num",
        title: "推定土地時価 / 時価総額",
        render: (row) => {
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
        render: () => "memo",
        detailContent: (row) => {
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
        render: (row) => toOku(numField("estimated_value")(row)),
        sortValue: numField("estimated_value"),
    },
    {
        key: "market_cap_oku",
        header: "mcap",
        type: "num",
        title: "時価総額(億円)",
        toggleable: true,
        render: (row) => toOku(numField("market_cap")(row)),
        sortValue: numField("market_cap"),
    },
    {
        key: "book_value_oku",
        header: "bv",
        type: "num",
        title: "土地簿価(億円)",
        toggleable: true,
        render: (row) => toOku(numField("book_value")(row)),
        sortValue: numField("book_value"),
    },
    {
        key: "unrealized_gain_oku",
        header: "gain",
        type: "num",
        title: "含み益(億円)",
        toggleable: true,
        render: (row) => toOku(numField("unrealized_gain")(row)),
        sortValue: numField("unrealized_gain"),
    },
    {
        key: "geocode_tag",
        header: "geo",
        type: "text",
        title: "住所解決タグ",
        toggleable: true,
        render: (row) => String(row.geocode_tag ?? ""),
    },
    {
        key: "confidence",
        header: "conf",
        type: "text",
        title: "地価推定信頼度",
        toggleable: true,
        render: (row) => String(row.confidence ?? ""),
    },
    {
        key: "anomaly",
        header: "warn",
        type: "text",
        title: "異常値警告",
        toggleable: true,
        render: (row) => String(row.anomaly ?? ""),
    },
];
const METRIC_THRESHOLDS = {
    ...C.COMMON_THRESHOLDS,
    ratio: { good: (v) => v >= 0.5 },
};
/* ------------------------------------------------------------------ */
/*  Bootstrap                                                          */
/* ------------------------------------------------------------------ */
function bootstrap() {
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
}
else {
    bootstrap();
}
export {};
