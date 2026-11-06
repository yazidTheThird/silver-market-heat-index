"""Auditable availability cohorts and completed-sales imports (methodology 2).

Availability is a listing-level proxy, never a count of buyers or units sold.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import math
from urllib.parse import urlparse
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALES = os.path.join(ROOT, 'data', 'completed_sales.csv')
SALES_COLUMNS = ['period_start', 'period_end', 'source', 'query_id', 'segment',
                 'currency', 'sold_count', 'median_sold_price', 'source_url']


def ts(value):
    return pd.to_datetime(value, errors='coerce', utc=True)


def observe(row, available, now):
    """Require two explicit unavailable checks at least an hour apart.

    Preserve the first confirmed event through restocks. Never reuse legacy dates.
    First-available timestamps begin at deployment, not at the old first_seen date.
    """
    if str(row.get('evidence_version')) != '2':
        for key in ('observed_available_at', 'last_available_at', 'pending_unavailable_at',
                    'confirmed_unavailable_at', 'unavailable_lower_bound'):
            row[key] = ''
    row['evidence_version'] = '2'
    row['status_checked_at'] = now
    if available is None:
        row.update(stock_status='unknown', available='', pending_unavailable_at='')
    elif available:
        if pd.isna(ts(row.get('observed_available_at'))):
            row['observed_available_at'] = now
        row.update(stock_status='available', available='1', last_available_at=now,
                   pending_unavailable_at='')
    else:
        row.update(stock_status='unavailable', available='0')
        if pd.isna(ts(row.get('observed_available_at'))):
            return  # Already unavailable at baseline: no witnessed transition.
        pending = ts(row.get('pending_unavailable_at'))
        if pd.isna(pending):
            row['pending_unavailable_at'] = now
        elif ts(now) - pending >= pd.Timedelta(hours=1):
            if pd.isna(ts(row.get('confirmed_unavailable_at'))):
                row['confirmed_unavailable_at'] = now
                row['unavailable_lower_bound'] = row.get('last_available_at', '')


def segment(title):
    text = str(title).lower()
    if re.search(r'copper|cupronickel|base metal|silver[ -]plated|silver plating|clad', text):
        return 'Plated / base metal'
    if re.search(r'silver.*eagle|eagle.*silver|\base\b', text):
        return 'Colorized silver Eagles'
    if 'silver' in text:
        return 'Other colorized silver'
    return 'Unclassified'


def cohort_rows(state, today, horizon=7):
    """One row per listing, including unsold eligible listings.

    A documented publication within 24h of first observed availability is needed.
    Timing uncertainty that straddles the horizon is excluded and counted unknown.
    Cohorts are consecutive seven-day publication windows, ending horizon days ago.
    """
    end = pd.Timestamp(today, tz='UTC')
    rows = []
    for row in state.to_dict('records'):
        if str(row.get('evidence_version')) != '2':
            continue
        launch = ts(row.get('published_at'))
        if pd.isna(launch):
            # A date-only release cannot support hour-level timing.
            continue
        first = ts(row.get('observed_available_at'))
        age = (end - launch).total_seconds() / 86400
        if pd.isna(first) or not 0 <= (first-launch).total_seconds() <= 86400:
            continue
        deadline = launch + pd.Timedelta(days=horizon)
        event = ts(row.get('confirmed_unavailable_at'))
        lower = ts(row.get('unavailable_lower_bound'))
        last_available = ts(row.get('last_available_at'))
        if pd.notna(event) and event <= deadline:
            outcome = 1
        elif pd.notna(event):
            outcome = 0 if pd.notna(lower) and lower >= deadline else None
        else:
            outcome = 0 if pd.notna(last_available) and last_available >= deadline else None
        fresh = (str(row.get('stock_status')) in ('available', 'unavailable') and
                 pd.notna(ts(row.get('status_checked_at'))) and
                 0 <= (end + pd.Timedelta(days=1) - ts(row.get('status_checked_at'))).total_seconds() <= 172800)
        rows.append({**row, 'segment': segment(row.get('title', '')),
                     'age': age, 'outcome': outcome, 'fresh': fresh,
                     'period': 'current' if horizon <= age < horizon+7 else
                               'previous' if horizon+7 <= age < horizon+14 else 'outside'})
    return rows


def availability(state, cfg, today):
    rows = [r for r in cohort_rows(state, today) if str(r.get('colorized')) == '1']
    min_n = cfg.get('evidence', {}).get('min_cohort', 30)
    min_stores = cfg.get('evidence', {}).get('min_stores', 3)
    results = []
    for seg in ('Colorized silver Eagles', 'Other colorized silver', 'Plated / base metal'):
        pool = [r for r in rows if r['segment'] == seg and r['fresh']]
        stores = {r['store'] for r in pool if r['period'] == 'current'} & {
            r['store'] for r in pool if r['period'] == 'previous'}
        # Individual periods can be shown before a matched comparison is possible.
        counts = {}
        for period in ('current', 'previous'):
            group = [r for r in pool if r['period'] == period]
            known = [r for r in group if r['outcome'] is not None]
            counts[period] = {'eligible': len(known), 'unavailable': sum(r['outcome'] for r in known),
                              'unknown': len(group)-len(known)}
        matched = {p: [r for r in pool if r['period'] == p and r['store'] in stores
                       and r['outcome'] is not None] for p in ('current', 'previous')}
        comparable = len(stores) >= min_stores and all(len(v) >= min_n for v in matched.values())
        delta = None
        if comparable:
            delta = 100 * (sum(r['outcome'] for r in matched['current']) / len(matched['current']) -
                           sum(r['outcome'] for r in matched['previous']) / len(matched['previous']))
        results.append({'segment': seg, **counts, 'matched_stores': len(stores),
                        'matched_current': len(matched['current']), 'matched_previous': len(matched['previous']),
                        'change_pp': round(delta, 1) if delta is not None else None,
                        'confidence': 'Limited: availability proxy' if comparable else 'Insufficient evidence'})
    checked = pd.to_datetime(state.get('status_checked_at', pd.Series(dtype=str)), errors='coerce', utc=True)
    fresh = checked.ge(pd.Timestamp(today, tz='UTC')) & checked.lt(pd.Timestamp(today, tz='UTC')+pd.Timedelta(days=1))
    statuses = state.get('stock_status', pd.Series('', index=state.index))
    fresh &= statuses.isin(['available', 'unavailable'])
    stores = int(state.loc[fresh, 'store'].nunique()) if len(fresh) else 0
    return {'segments': results, 'fresh_stores': stores,
            'configured_stores': len(cfg.get('drops', {}).get('stores', [])),
            'fresh_listings': int(fresh.sum()), 'tracked_listings': len(state),
            'horizon_days': 7, 'note': 'Store-listing availability; not unit sales. Same product at different stores counts as separate listings.'}


def validate_sales(df):
    if not set(SALES_COLUMNS) <= set(df.columns):
        raise ValueError('Completed sales require columns: ' + ', '.join(SALES_COLUMNS))
    df = df[SALES_COLUMNS].copy()
    if df.empty:
        return df
    for col in ('source', 'query_id', 'segment', 'currency', 'source_url'):
        if df[col].isna().any() or df[col].astype(str).str.strip().eq('').any():
            raise ValueError(f'{col} must be populated; use the same query_id only for identical filters')
    if not df.source_url.astype(str).map(lambda u: urlparse(u).scheme == 'https' and bool(urlparse(u).netloc)).all():
        raise ValueError('source_url must be a public HTTPS reference')
    start, end = pd.to_datetime(df.period_start, errors='coerce'), pd.to_datetime(df.period_end, errors='coerce')
    if start.isna().any() or end.isna().any() or not (end-start).eq(pd.Timedelta(days=6)).all():
        raise ValueError('Each row must cover exactly seven calendar days (inclusive)')
    n = pd.to_numeric(df.sold_count, errors='coerce')
    if n.isna().any() or not n.map(math.isfinite).all() or (n < 0).any() or (n % 1 != 0).any():
        raise ValueError('sold_count must be actual nonnegative integer units sold')
    prices = pd.to_numeric(df.median_sold_price, errors='coerce')
    if ((df.median_sold_price.notna() & prices.isna()) | prices.le(0)).any() or not prices.dropna().map(math.isfinite).all():
        raise ValueError('Median realized price must be positive or blank')
    if df.duplicated(['period_start', 'source', 'query_id', 'segment', 'currency']).any():
        raise ValueError('Duplicate period/source/query/segment/currency')
    df['sold_count'] = n.astype(int)
    df['median_sold_price'] = prices
    df['period_start'], df['period_end'] = start.dt.strftime('%Y-%m-%d'), end.dt.strftime('%Y-%m-%d')
    return df


def completed_sales(today, cfg, path=None):
    path = path or SALES
    if not os.path.exists(path):
        return []
    df = validate_sales(pd.read_csv(path))
    output = []
    for key, g in df.groupby(['source', 'query_id', 'segment', 'currency']):
        g = g[pd.to_datetime(g.period_end).dt.date < today].sort_values('period_end')
        if g.empty:
            continue
        last = g.iloc[-1]
        age = (today - dt.date.fromisoformat(last.period_end)).days
        prev = g[pd.to_datetime(g.period_start) == pd.Timestamp(last.period_start)-pd.Timedelta(days=7)]
        previous = int(prev.iloc[-1].sold_count) if len(prev) else None
        n = int(last.sold_count)
        enough = age <= 10 and previous is not None and min(n, previous) >= cfg.get('evidence', {}).get('min_sales_units', 30)
        change = (n/previous-1)*100 if previous else None
        label = 'Insufficient evidence'
        if enough:
            label = 'Buying up' if change >= 20 else 'Buying down' if change <= -20 else 'Buying steady'
        output.append({'source': key[0], 'query_id': key[1], 'segment': key[2], 'currency': key[3],
                       'period_start': last.period_start, 'period_end': last.period_end,
                       'units': n, 'previous_units': previous,
                       'change_pct': round(change, 1) if change is not None else None,
                       'median_price': None if pd.isna(last.median_sold_price) else float(last.median_sold_price),
                       'source_url': last.source_url, 'stale': age > 10, 'label': label})
    return output
