# Blackbird.png market tracker

Tracks **completed purchases**, **store-listing availability**, and **collection quality** separately. GitHub Pages serves `docs/index.html`.

## Methodology 2 — 6 November 2026

The previous blended 0–100 index is suspended. Silver price movements, asking prices, Google searches and calendar assumptions cannot establish purchases or predict a release sellout. Old scores remain in `data/history.csv` and appear only in the dashboard's legacy chart. They are not comparable with the corrected measurements.

### Buying

`data/completed_sales.csv` contains verified, normalized weekly completed-sale records. The automatic eBay Browse feed supplies **asking prices and active listings**, never completed transactions. Fourteen days of that feed does not change this distinction.

Import a CSV using:

```sh
python import_sales.py weekly_sales.csv
python run.py --rebuild
```

Required columns (header also provided by the empty destination CSV):

| Column | Meaning |
|---|---|
| period_start, period_end | YYYY-MM-DD, exactly seven days inclusive; open periods are not displayed |
| source | e.g. eBay Product Research, or a named client's sales export |
| query_id | Stable identifier for the exact query, geography, category, exclusions, currency, shipping/returns treatment, and unit-count definition. Change it whenever filters change. |
| segment | e.g. Colorized silver Eagles, Other colorized silver, Plated / base metal |
| currency | Currency of the realized price |
| sold_count | Actual nonnegative integer units sold, not listings, watchers or stock changes |
| median_sold_price | Positive median realized unit price; blank if unavailable. Keep shipping/tax treatment consistent. |
| source_url | HTTPS source/report reference for audit; do not commit credentials or private customer details |

Do not combine overlapping searches or repeat the same sales in multiple rows. The importer replaces a record with the same period/source/query/segment/currency, rejects malformed records, and writes atomically. It does not fetch eBay Product Research or invent transactions. Obtain a verified export or manually transcribe the consistently filtered report first. Client imports should contain aggregate counts only.

Each series is compared only with the immediately preceding seven-day period with identical metadata. A period ending more than ten days ago is stale. Provisional labels require at least 30 units in **each** period: a change of +20% or more is “Buying up,” -20% or less “Buying down,” otherwise “Buying steady.” These are transparent operational thresholds, not statistical significance or a sellout prediction. Low-volume and zero-sale periods remain visible with an insufficient-evidence label; percentage change from zero is undefined.

The old `data/ebay_sold.csv` is retained for audit but not promoted into the new series: it lacks required provenance and a completed-unit count.

### Launch movement

The measurement is **store listings becoming explicitly unavailable within seven days**, not a global mint sellout or unit-sales count.

* First observed availability must be within 24 hours after a documented publication timestamp. Unknown publication dates and old catalog discoveries are excluded.
* Two explicit unavailable observations at least one hour apart, following observed availability, confirm an availability event. Missing pages, unknown schema status, failed requests and feed omissions are unknown, never inferred sellouts.
* The event timestamp is an upper bound. If the observation interval straddles the seven-day deadline, the outcome is unknown.
* Still-available eligible listings stay in the denominator. Listings too young to complete seven days are excluded. Unknown outcomes are counted separately.
* Current cohort: publication age 7–<14 days; previous cohort: 14–<21 days, measured at midnight UTC on the report date. Cohort dates appear on the dashboard.
* Comparisons use the same segment and stores appearing in both cohorts, with at least 30 observed outcomes per period and three common stores. Below this, raw counts are shown but no directional verdict.
* Colorized silver Eagles, other colorized silver, and plated/base-metal products are separate. Classification is title-based and may need review. Each store listing is one observation; duplicates across dealers are not unique global releases.
* Historical inferred sellout dates are never upgraded to verified events. New evidence starts with fresh checks after this change. First confirmed events survive restocks for cohort accounting.

The catalog explorer keeps theme/finish/base-coin drilldowns, but no longer ranks demand from old unavailable stock or the speed of only the products that disappeared. Catalog prices are asking prices, with approximate configured FX conversions.

### Confidence and collectors

The dashboard shows fresh readable stores, fresh listing counts and cohort denominators. These are **coverage measures**, not confidence percentages. Failed reads make availability unknown; they do not turn into zero sales. `data/collection_health.csv` and `data/last_run_log.txt` identify collector failures. `data/evidence_report.json` contains the current dashboard evidence.

The generic collector's boolean/function name collision is fixed. This does not remove a website's 401/403 access restrictions. Those failures remain visible. A successful workflow can still contain partial collection failures.

## Running

Python 3.12 is used in GitHub Actions:

```sh
pip install -r requirements.txt
python -m playwright install chromium  # if config.yaml uses render: true
python -m unittest discover -s tests -v
python run.py               # daily collection + optional existing Telegram notification
python run.py --fast        # refresh availability and dashboard, no notification
python run.py --rebuild     # rebuild from saved data, no network collection or notification
```

`config.yaml` defines stores, platforms, category/sitemap URLs, currencies, title filters and sample minimums. Public Shopify/WooCommerce feeds are used where available; generic stores use product-page stock data. Collection handles unreadable availability as unknown. Do not bypass access blocks.

Optional existing secrets: `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. `DASHBOARD_URL` is an optional environment variable. No secrets are needed for offline tests/rebuild. Telegram remains part of the existing daily workflow; the repair/rebuild itself sends no message.

The scheduled daily and fast workflows share a concurrency group. They commit generated `data/` and `docs/` updates. Workflow schedules remain unchanged.
