# Market Heat Index — colorized collectibles

A daily 0–100 score for the **colorized silver coin & collectibles market**:

- **HOT:** launch now, consider a bigger mintage.
- **NORMAL:** launch with a waitlist.
- **DEAD:** hold, or take pre-orders only.

It runs by itself every morning on GitHub (free), saves the history, and publishes a dashboard you can open on your phone. It can also send you a Telegram message.

## What goes into the score

| Component | Weight | Signal |
|---|---|---|
| **Colorized drops selling out** | 35 | Watches the colorized products at the mint and dealer stores you list (any platform). It records when each one launches and the day it sells out. Scores the share of last-30-day launches already sold out, the share that sold out within 2 days, and the median days to sell out. |
| **eBay collector premium** | 30 | Median price of colorized Libertads, Eagles, half dollars and rounds on eBay, divided by the **same coins in plain form**. Silver price cancels out, so what's left is purely what collectors pay for color. Also uses weekly sold count and sell-through % if you paste them from Terapeak. |
| **Colorized chatter** | 15 | Posts and comments mentioning colorized coins in the past week on r/Silverbugs, r/Pmsforsale, r/coins and r/Coins4Sale, plus Google Trends for "colorized coin" and "colorized silver". |
| **Silver price mood** | 10 | Silver's weekly move, monthly trend and volatility. Background only: big moves bring buyers out. |
| **Calendar & competition** | 10 | Paydays (1st and 15th), season, weekday. Crowded weeks lower it: competing drops you log, plus a busy week of new colorized launches spotted by the drop tracker. |

Every signal is turned into a **percentile against its own recent past**. 80 means "hotter than 80% of the last 90 days." The index is the weighted average.

If a source fails on a given day, it's skipped and the dashboard shows the day's **coverage**. When too few sources answered, the dashboard says "Not enough data today" instead of guessing.

### How the drop tracker works (any store platform)

Every day, for each store you list, the tracker:

1. **Finds the products.** It reads the store's colorized category page(s) you give it (`listing_urls`), or its sitemap (`sitemap_url`), and collects the product links.
2. **Checks each one.** It opens each product page and reads the stock status from the structured product data that stores embed for Google Shopping (`InStock` / `OutOfStock` / `SoldOut`). If a store doesn't include that, it falls back to the buy button itself: "Add to cart" means in stock, "Sold out" means sold out.
3. **Records what changed.** New products are logged as launches, and it notes the day each one flips to sold out. A tracked product whose page disappears counts as sold out. Sold-out items are re-checked weekly in case of restocks.
4. **Remembers what to skip.** Non-colorized products are noted once and never fetched again.

Shopify and WooCommerce stores are detected automatically and need no extra setup. For a store that only shows its products after JavaScript runs, add `render: true` and it will use a headless browser.

**Setting up a store takes 1 minute:** open the store's colorized category in your browser, copy the address, and paste it under `listing_urls` in `config.yaml`. If that page only contains colorized items, also set `listing_is_colorized: true`.

**The first day is a baseline.** Products already on a store the first time it's checked don't count as new launches, because there's no way to know when they launched. Everything that appears after that is timed from launch to sell-out. Expect the drop score to fill in once a few new launches have come and gone.

**If a store can't be read**, the run log says so, with what to try. Two things can block it:
- **Anti-bot protection** (e.g. Cloudflare) can block GitHub's servers outright. For those stores, log their drops by hand in `competing_releases.csv`.
- **Store layout.** If the tracker picks up the wrong links, set `product_link_pattern` to a piece of text that appears only in product URLs, e.g. `"/product/"`.

## Broad tracking: every collectible silver release

The tracker follows **every collectible / limited release** at each store, not just
colorized ones: proofs, high relief, shaped coins, privy marks, limited bars and rounds,
world-mint series. Plain bullion (random-year coins, generic rounds and bars, tubes, junk
silver) is skipped. Each product is flagged colorized or not, and its **launch price**
and **mintage** (when the store states it) are saved.

The **heat index stays a colorized gauge**: it is computed only from colorized products,
so its meaning doesn't change. The "What's hot" card covers everything, with an
*All collectible silver / Colorized only* switch.

Stores: CoinsTV, Hero Bullion, GR Reserve, Bullion Sharks, PopCoins, MyCollectables (AU),
Direct Coins (AU), CDN Coin (CA), APMEX, SD Bullion, Bullion Exchanges, Provident,
Money Metals and Bullion By Post (UK). If a store can't be read, the run log says so
and the rest carry on. The first broad run at a store records its existing catalog as
baseline, so old products aren't counted as new launches.

To go back to colorized only, set `tracking: mode: colorized` in `config.yaml`.

## What's hot: themes, coins, sizes, finishes

The index says *when* the market is hot. This part says *what* is hot. Every tracked
product is tagged from its title by **theme** (dragons, wildlife, mythology, patriotic,
lunar…), **base coin** (Libertad, Silver Eagle, Maple…), **size** and **finish**
(diamond dust, gilded, black proof, antiqued…), then each group is ranked by how fast
it sells out. Silver only for now (`hot_groups.metals` in `config.yaml`).

Dimensions: **Theme** (16 broad) and **Sub-theme** (about 50: big cats, wolves, Norse
myth, Egyptian, Star Wars, Marvel & DC, anime & games, USA 250, Day of the Dead…),
**Base coin**, **Size**, **Finish**, **Type** (colorized or not), **Price**, **Premium**
over silver spot, **Mintage** and **Store**. Tap any row to see its products, with links,
price and mintage.

- **Dashboard:** the "What's hot" card, with a tab per dimension.
- **`data/hot_groups.csv`:** the full table, updated on every run.
- **Telegram:** a weekly digest every Monday with the hottest and coldest groups.

**Confidence:** *high* = enough launches and timed sell-outs; *medium* = enough launches
that had at least 7 days to sell; *low (snapshot)* = only "share sold out right now",
the early read until launches pile up. Expect real rankings after 2–4 weeks.

Tagging rules are regexes in `mhi/tags.py`. To change one, copy that block into a
`tags:` section in `config.yaml` and edit it there.

## Fast launch checks (hour-level sell-out timing)

A second workflow, **Fast launch check**, runs every 3 hours. It reads the Shopify and
WooCommerce feeds in full and, for other stores, only re-checks products launched in
the last 7 days. It records the time (UTC) each product appears and sells out, so a
2-hour sell-out is told apart from a 2-day one. It doesn't compute the index or send
Telegram messages. Both workflows share a lock, so they never write data at the same
time. To change the frequency, edit the `cron` line in `.github/workflows/fast.yml`.

## One-time setup (about 20 minutes)

1. **Create a GitHub account** (free) and a **new repository**, e.g. `market-heat-index`.
2. **Upload these files:** Add file → Upload files → drag in the folder contents, including the hidden `.github` folder. If it doesn't upload, create `.github/workflows/daily.yml` in GitHub's web editor and paste its contents in.
3. **Turn on the dashboard:** Settings → Pages → *Deploy from a branch* → `main`, folder `/docs` → Save.
   - Free accounts need a **public** repo for Pages. If you want to keep it private, use the Telegram message instead.
4. **Run it once by hand:** Actions → *Daily Market Heat Index* → *Run workflow*. Open the run's log to see which stores and sources worked.
5. From then on it runs daily at **06:47 Morocco time**. To change the time, edit the `cron` line in `.github/workflows/daily.yml`.

## Optional keys (each one makes the index stronger)

Add these under Settings → Secrets and variables → Actions → *New repository secret*.

| Secret | Where | Adds |
|---|---|---|
| `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` | developer.ebay.com → create app → **Production** keys (free) | The eBay collector premium, automatically |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | reddit.com/prefs/apps → create app → type **script** | Reliable Reddit access (Reddit often blocks anonymous server requests) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | @BotFather → /newbot for the token; message your bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` for your chat id | A morning message with the score |

To put the dashboard link in the Telegram message, add a **variable** called `DASHBOARD_URL`.

## Files you keep up to date

- **`data/releases.csv`:** after each release (yours, or a competitor's when you know), add one line: launch date, name, seller, mintage, price, waitlist size, and hours until it sold out. This is what tunes the index to *your* buyers.
- **`data/competing_releases.csv`:** upcoming colorized drops you know about from other mints.
- **`data/ebay_sold.csv`** *(optional, weekly, 2 minutes)*: in eBay Seller Hub → Research (Terapeak), search "colorized silver" for the last 7 days. Paste the sold count, median sold price and **sell-through %**. This is the strongest eBay signal, and the official API doesn't provide it.

You can edit the CSVs on GitHub directly (click the file → pencil icon).

## Tuning it to your sales (after 15–20 releases)

```bash
pip install -r requirements.txt
python calibrate.py
```

It shows which components lined up with how fast releases actually sold out, and suggests new weights for `config.yaml`. It also tells you if your **waitlist ÷ mintage** ratio predicts better than the market index. If it does, use the index to **time** a launch and the waitlist to **size** it.

## Things to know

- **Colorized matching:** what counts as colorized is set by `colorized_pattern` in `config.yaml` (colorized, colourised, colored, full color, enamel…). Edit it if a store names things differently.
- **Google Trends:** niche terms like "colorized coin" can have very low search volume, so Trends counts for a third of the chatter score and Reddit for two thirds.
- **What it reads:** only public product feeds, official APIs and public posts, once a day.
- **Running locally:** `python run.py`.
