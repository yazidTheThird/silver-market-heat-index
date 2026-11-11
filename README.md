# Blackbird.png market tracker

Tracks **completed purchases**, **store-listing availability**, and **collection quality** separately. GitHub Pages serves `docs/index.html`.

## Release-readiness assessment

The first dashboard panel compares **two complete, consecutive 28-day periods** for a selected comparable coin group. Presets cover 1 oz colorized Eagles, Maples and Libertads; a custom group is available. Review the search results and keep base coin, weight, grading, finish, price range, geography, currency, and shipping treatment identical. Do not aggregate overlapping queries or compare a basic colorized coin to a premium sculpted release.

1. Open [eBay Product Research](https://www.ebay.com/sh/research) in your own account. The panel supplies a starting query and exact date ranges.
2. Copy each period's actual **units sold**, **average sold price**, and **sellers with sales**. Sell-through is optional; use the same source definition for both periods. A missing observation is never zero. With explicitly zero sales, enter 0 sellers and leave average price blank.
3. Enter the shared filters, confirm both periods are complete and comparable, then calculate. Optionally compare your planned run and price with the observed market scale.
4. Reports save in that browser's local storage. Use Download/Load saved reports to back up or move your aggregate reports. Nothing is sent to eBay or GitHub by the form. Browser storage can be cleared or unavailable, so download a backup.

There is **no live connection to eBay Product Research**. The existing Browse API collects active listings only. eBay's [Marketplace Insights API is restricted and closed to new users](https://developer.ebay.com/api-docs/buy/ref-marketplace-supported.html), checked 6 November 2026. Product Research requires an authenticated account and provides actual sold-price data, including accepted Best Offers ([official help](https://www.ebay.com/help/selling/selling-tools/product-research?id=4853)). The dashboard accepts manually copied aggregate figures; it does not claim eBay offers a native CSV export or verify user-entered numbers independently.

Rules, shared by the browser and Node in `mhi/readiness.js`:

- Gray if older than 10 days, prior volume below 30, combined volume below 60, or fewer than three selling sellers in a period. An explicitly zero-sales period is exempt from the current seller minimum.
- Green: units up at least 20%, average sold price no worse than −5%, optional sell-through no worse than −5 percentage points.
- Red: zero current sales, volume down at least 50%, or volume down at least 20% with average prices down at least 5%.
- Otherwise amber when prices are available; missing prices cannot earn green. A sharp verified volume collapse can still be red without prices.
- No percentage growth from a zero baseline. Planned price and run size do not change the market signal. They are shown separately, with a warning when the planned price exceeds the observed average by more than 20%.

These are explicit **screening heuristics**, not statistically calibrated thresholds, a forecast, or a sellout probability. Changes in product mix can move averages; seller counts do not measure concentration fully. eBay is one sales channel. Validate a design and price with your own audience and dealer orders.

To deliberately publish aggregate reports to the shared site (not private customer data or authenticated URLs):

```sh
node scripts/import_release_reports.cjs blackbird-release-reports.json
python run.py --rebuild
# Review and commit data/release_reports.json and docs/index.html to publish.
```

The importer validates all records before an atomic write. Identical profile/date/query/filter/marketplace/currency records replace prior values. The shared file starts empty; test fixtures are never published as market evidence. Published reports remain visible to every visitor; local reports remain on the current browser. The weekly series below is a separate legacy-compatible input and is not silently combined into these 28-day comparisons.

Validation: `node tests/readiness.cjs` plus the Python regression suite below.

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

## New releases gallery

`docs/releases.html` shows every new listing at the tracked stores as pictures, newest first, on one screen. Every run rebuilds it, so it follows the three-hourly check. Open it from the link under the dashboard title, or put `releases.html` at the end of the dashboard address.

* **What is on it.** Listings a store published in the last 90 days, plus, for stores that give no date, listings the tracker first saw in that time. The detail view says which one applies: "Listed" is the store's own date, "First spotted" is the tracker's. When an undated store suddenly shows 25 or more "new" products in one day, that is old catalogue being discovered, and those are left off.
* **Older-dated coins start hidden.** An 1885 Morgan listed today is a new listing, not a new release. Titles whose latest year is before last year stay hidden until you turn on "Older-dated coins too" in Filters. Titles with no year are shown.
* **Finding things.** Period, colorized only, theme, store, base coin, metal, finish, size, title search, and sorting by mintage or price. The groups reuse the tags in `mhi/tags.py`. "Photos only" turns the page into a dense wall. Tapping a coin opens it; tapping the picture turns it over when the store has more than one. A yellow dot marks listings that appeared since your last visit on that device.
* **Pictures.** The collector saves the picture addresses of recent launches in `data/media.csv`: from the Shopify and WooCommerce feeds, or from the product page's schema.org or `og:image` data on other platforms. Only addresses are saved; the page loads each picture from the store's own site. A listing shows an empty coin outline until its store has been read once with this version, or when the store refuses to serve the picture to another site.
* **Presale.** Listings the store sells ahead of shipping get a yellow "Presale" tag on the picture, with the ship date when the listing gives one, and the "Presale" chip shows only those. The collector looks for pre-order or presale wording in titles, tags, categories, stock labels, schema.org `PreOrder` data and buy buttons. A match found only in descriptions is ignored at a store that repeats it on most products (shipping boilerplate). "Backorder" does not count, because several stores use it for ordinary restocking. A blue dot marks listings new since your last visit.
* **Stores.** `config.yaml` lists every store read, plus the ones tested on 11 Nov 2026 and left out because they block automated visitors or show no readable stock. Stores read page by page from a sitemap check URLs naming this year or next first, and spend about 10 days working through old catalogue. Undated products found in that time are left off the gallery.
* **Same caution as the dashboard.** A listing is not a sale and "Unavailable" is not "sold". Mintage is read from listing text and can be wrong.

Settings are under `gallery:` in `config.yaml`. `python run.py --rebuild` rebuilds the page from saved data with no network access. The page never changes the availability evidence: pictures live in their own file, and a failure in the gallery is logged and skipped.

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
