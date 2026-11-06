import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from mhi import drops, evidence, index
from import_sales import ingest

TODAY = dt.date(2026, 11, 20)
CFG = {'drops': {'stores': [{'url': 's1'}, {'url': 's2'}, {'url': 's3'}]},
       'evidence': {'min_cohort': 30, 'min_stores': 3, 'min_sales_units': 30}}


def product(i=0, launch='2026-11-10T00:00:00Z', store='s1', title='Colorized Silver Eagle'):
    return {'store': store, 'product_id': str(i), 'title': title, 'colorized': '1',
            'published_at': launch, 'observed_available_at': launch,
            'evidence_version': '2', 'last_available_at': '2026-11-20T00:00:00Z',
            'stock_status': 'available', 'status_checked_at': '2026-11-20T00:00:00Z'}


class Observations(unittest.TestCase):
    def test_legacy_cannot_become_verified_sale(self):
        row = {'sold_out_at': '2026-11-01', 'sold_out_date': '2026-11-01'}
        evidence.observe(row, False, '2026-11-06T00:00:00Z')
        evidence.observe(row, False, '2026-11-06T02:00:00Z')
        self.assertEqual(row['confirmed_unavailable_at'], '')

    def test_confirm_then_restock_preserves_event(self):
        row = {}
        evidence.observe(row, True, '2026-11-06T00:00:00Z')
        evidence.observe(row, False, '2026-11-06T01:00:00Z')
        evidence.observe(row, False, '2026-11-06T01:30:00Z')
        self.assertEqual(row['confirmed_unavailable_at'], '')
        evidence.observe(row, False, '2026-11-06T02:00:00Z')
        self.assertEqual(row['confirmed_unavailable_at'], '2026-11-06T02:00:00Z')
        evidence.observe(row, True, '2026-11-07T00:00:00Z')
        self.assertEqual(row['confirmed_unavailable_at'], '2026-11-06T02:00:00Z')
        self.assertEqual(row['unavailable_lower_bound'], '2026-11-06T00:00:00Z')

    def test_missing_feed_item_is_unknown(self):
        state = pd.DataFrame([product()])
        merged = drops._merge(state, 's1', [], TODAY, False)
        self.assertEqual(merged.iloc[0].stock_status, 'unknown')
        self.assertNotEqual(merged.iloc[0].available, '0')

    def test_unknown_breaks_confirmation(self):
        row = {}
        for val, hour in [(True, 0), (False, 1), (None, 2), (False, 3)]:
            evidence.observe(row, val, f'2026-11-06T0{hour}:00:00Z')
        self.assertEqual(row['confirmed_unavailable_at'], '')

    def test_schema_unknown_not_stockout(self):
        for status, expected in [('Discontinued', None), ('PreOrder', True), ('OutOfStock', False)]:
            html = '<script type="application/ld+json">{"@type":"Product","offers":{"availability":"https://schema.org/'+status+'"}}</script>'
            self.assertIs(drops.parse_product_page(html)['available'], expected)

    def test_boolean_shadow_regression_and_404(self):
        urls = ['https://s1/products/a', 'https://s1/products/b']
        state = pd.DataFrame([{**product(i), 'url': u, 'published': '', 'available': '1',
                               'baseline': '0', 'last_checked': '2026-11-10'} for i,u in enumerate(urls)])
        class Fake:
            def get(self, url, **kwargs):
                return (200, '<h1>Colorized Silver Eagle</h1><button>Add to cart</button>') if url == urls[0] else (404, '')
        cfg = {'drops': {'max_product_checks_per_store': 5}, 'colorized_pattern': 'Colorized'}
        with patch.object(drops, 'discover_links', return_value=urls), patch.object(drops, '_load_ignore', return_value=set()), patch.object(drops, '_save_ignore'), patch.object(drops.time, 'sleep'):
            result = drops.read_generic({'url': 'https://s1'}, Fake(), cfg, state, TODAY)
        self.assertEqual(len(result), 2)
        self.assertIsNone(result[1]['available'])


class Cohorts(unittest.TestCase):
    def test_unsold_launches_in_denominator(self):
        rows = [product(i) for i in range(100)]
        for row in rows[:6]:
            row.update(confirmed_unavailable_at='2026-11-12T00:00:00Z', unavailable_lower_bound='2026-11-11T00:00:00Z')
        report = evidence.availability(pd.DataFrame(rows), CFG, TODAY)['segments'][0]
        self.assertEqual(report['current']['eligible'], 100)
        self.assertEqual(report['current']['unavailable'], 6)
        self.assertIsNone(report['change_pp'])

    def test_uncertain_boundary_and_legacy_excluded(self):
        row = product()
        row.update(confirmed_unavailable_at='2026-11-18T00:00:00Z', unavailable_lower_bound='2026-11-16T00:00:00Z')
        legacy = {**product(1), 'evidence_version': ''}
        report = evidence.availability(pd.DataFrame([row, legacy]), CFG, TODAY)['segments'][0]
        self.assertEqual(report['current'], {'eligible': 0, 'unavailable': 0, 'unknown': 1})

    def test_matched_stores_and_segments(self):
        rows = []
        for i in range(30):
            store = 's'+str(i%3+1)
            rows += [product(i, store=store), product(i+30, launch='2026-11-03T00:00:00Z', store=store)]
        report = evidence.availability(pd.DataFrame(rows), CFG, TODAY)['segments'][0]
        self.assertEqual(report['matched_stores'], 3)
        self.assertEqual(report['change_pp'], 0)
        for row in rows[1::2]:
            row['store'] = 'different'
        self.assertIsNone(evidence.availability(pd.DataFrame(rows), CFG, TODAY)['segments'][0]['change_pp'])
        self.assertEqual(evidence.segment('1oz silver plated copper Goat'), 'Plated / base metal')

    def test_stale_future_and_old_catalog_excluded(self):
        rows = [product(0), product(1, launch='2026-12-01T00:00:00Z'), product(2)]
        rows[0]['stock_status'] = 'unknown'
        rows[2]['observed_available_at'] = '2026-11-16T00:00:00Z'
        report = evidence.availability(pd.DataFrame(rows), CFG, TODAY)['segments'][0]
        self.assertEqual(report['current']['eligible'], 0)


class Sales(unittest.TestCase):
    def row(self, start, end, n=40, query='fixed'):
        return dict(period_start=start, period_end=end, source='eBay Product Research', query_id=query,
                    segment='Colorized silver Eagles', currency='USD', sold_count=n,
                    median_sold_price=100, source_url='https://www.ebay.com/sh/research')

    def test_valid_import_and_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, target = str(Path(tmp)/'input.csv'), str(Path(tmp)/'out.csv')
            pd.DataFrame([self.row('2026-11-02','2026-11-08'), self.row('2026-11-09','2026-11-15',60)]).to_csv(path,index=False)
            ingest(path,target)
            ingest(path,target)
            self.assertEqual(len(pd.read_csv(target)), 2)
            report = evidence.completed_sales(TODAY, CFG, target)[0]
            self.assertEqual(report['change_pct'], 50)
            self.assertEqual(report['label'], 'Buying up')
            self.assertTrue(evidence.completed_sales(dt.date(2026,12,1), CFG, target)[0]['stale'])

    def test_reject_missing_units_and_short_period(self):
        for row in [self.row('2026-11-02','2026-11-08',None), self.row('2026-11-02','2026-11-05')]:
            with self.assertRaises(ValueError):
                evidence.validate_sales(pd.DataFrame([row]))

    def test_never_mix_queries_or_partial_periods(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'sales.csv')
            pd.DataFrame([self.row('2026-11-02','2026-11-08'), self.row('2026-11-09','2026-11-15',100,'changed'), self.row('2026-11-16','2026-11-22',200)]).to_csv(path,index=False)
            report = evidence.completed_sales(TODAY, CFG, path)
            self.assertTrue(all(r['label'] == 'Insufficient evidence' for r in report))
            self.assertTrue(all(r['period_end'] != '2026-11-22' for r in report))

    def test_context_cannot_create_market_verdict(self):
        self.assertEqual(index.combine({c: {'score':100} for c in index.COMPONENTS}, {'weights':{c:20 for c in index.COMPONENTS}}), (None,0.0))

if __name__ == '__main__':
    unittest.main()
