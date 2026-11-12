import datetime as dt
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from mhi import drops, gallery, media, news

TODAY = dt.date(2026, 11, 11)
NOW = dt.datetime(2026, 11, 11, 18, 0, tzinfo=dt.timezone.utc)
CFG = {
    'colorized_pattern': 'coloriz|colour',
    'fx_to_usd': {'AUD': 0.65},
    'drops': {'stores': [{'url': 'https://shop.example'},
                         {'url': 'https://woo.example/', 'currency': 'AUD'}]},
}


def row(pid, title='2026 Niue Dragon 1 oz Silver Colorized Coin', store='https://shop.example', **over):
    base = {'store': store, 'product_id': str(pid), 'title': title,
            'url': f'{store}/products/{pid}', 'published': '', 'published_at': '',
            'first_seen': '2026-11-01', 'first_seen_at': '', 'baseline': '0', 'colorized': '1',
            'price': '99.5', 'mintage': '500', 'stock_status': 'available'}
    base.update(over)
    return base


class Pictures(unittest.TestCase):
    def test_addresses_are_cleaned_or_dropped(self):
        self.assertEqual(media.clean('//cdn.example/a b.jpg'), 'https://cdn.example/a%20b.jpg')
        self.assertEqual(media.clean('http://x.example/a.jpg?v=1&amp;w=2'), 'https://x.example/a.jpg?v=1&w=2')
        self.assertEqual(media.clean('/img/a.jpg', 'https://x.example/p/1'), 'https://x.example/img/a.jpg')
        # "&reg" inside a query string must survive untouched
        self.assertEqual(media.clean('https://x.example/a.jpg?a=1&reg=2'), 'https://x.example/a.jpg?a=1&reg=2')
        for bad in ('', None, 5, 'data:image/png;base64,AAAA', '/relative/no-base.jpg', 'javascript:alert(1)',
                    'https://x.example/woocommerce-placeholder.png', 'ftp://x.example/a.jpg'):
            self.assertEqual(media.clean(bad), '', bad)

    def test_shopify_feed_pictures(self):
        product = {'images': [{'src': 'https://cdn.shopify.com/s/files/1/a.jpg?v=1'},
                              {'src': 'https://cdn.shopify.com/s/files/1/a.jpg?v=1'},
                              {'src': 'https://cdn.shopify.com/s/files/1/b.jpg?v=1'},
                              {'src': 'https://cdn.shopify.com/s/files/1/c.jpg?v=1'},
                              {'src': 'https://cdn.shopify.com/s/files/1/d.jpg?v=1'}]}
        got = media.from_shopify(product)
        self.assertEqual([u[-9:-4] for u in got['images']], ['a.jpg', 'b.jpg', 'c.jpg'])
        self.assertEqual(media.from_shopify({})['images'], [])
        self.assertEqual(media.from_shopify({'images': None})['images'], [])

    def test_woocommerce_feed_pictures_and_thumbnail(self):
        product = {'images': [{'src': 'https://woo.example/wp-content/uploads/2026/11/coin.jpg',
                               'thumbnail': 'https://woo.example/wp-content/uploads/2026/11/coin-300x300.jpg'},
                              {'src': 'https://woo.example/wp-content/uploads/2026/11/back.jpg'}]}
        got = media.from_woocommerce(product)
        self.assertEqual(len(got['images']), 2)
        self.assertTrue(got['thumb'].endswith('coin-300x300.jpg'))
        only_stand_in = {'images': [{'src': 'https://woo.example/woocommerce-placeholder.png',
                                     'thumbnail': 'https://woo.example/woocommerce-placeholder-300x300.png'}]}
        self.assertEqual(media.from_woocommerce(only_stand_in), {'images': [], 'thumb': ''})
        # with a srcset, the grid uses the smallest version that is still sharp
        product['images'][0]['srcset'] = ('https://woo.example/u/coin.jpg 2000w, https://woo.example/u/coin-300x300.jpg 300w, '
                                          'https://woo.example/u/coin-768x768.jpg 768w, https://woo.example/u/coin-600x600.jpg 600w')
        self.assertTrue(media.from_woocommerce(product)['thumb'].endswith('coin-600x600.jpg'))

    def test_odd_feed_shapes_mean_no_picture_not_a_failed_read(self):
        nothing = {'images': [], 'thumb': ''}
        for odd in (None, 5, 'text', [], {'images': 5}, {'images': {'src': 'x'}}, {'images': [5, None, {'src': 7}, ['x']]}):
            self.assertEqual(media.from_shopify(odd), nothing, odd)
            self.assertEqual(media.from_woocommerce(odd), nothing, odd)
        self.assertEqual(media.from_page(None, [5, {'@type': 'Product', 'image': {'url': 9}}], 3), nothing)
        html = '<script type="application/ld+json">{"@type":"Product","image":{"url":{"deep":1}},"offers":{"availability":"InStock"}}</script>'
        info = drops.parse_product_page(html, 'https://store.example/p')
        self.assertEqual((info['images'], info['available']), ([], True))     # stock still read

    def test_product_page_pictures(self):
        ld = ('<script type="application/ld+json">{"@type":"Product","name":"Coin","image":'
              '["/img/front.jpg",{"@type":"ImageObject","url":"https://cdn.example/back.jpg"}],'
              '"offers":{"availability":"https://schema.org/InStock"}}</script>'
              '<meta property="og:image" content="https://cdn.example/share.jpg">')
        info = drops.parse_product_page(ld, 'https://store.example/product/1')
        self.assertEqual(info['images'], ['https://store.example/img/front.jpg', 'https://cdn.example/back.jpg'])
        self.assertIs(info['available'], True)
        # no structured picture: fall back to the share-preview picture
        og = '<meta property="og:image" content="https://cdn.example/share.jpg"><h1>Coin</h1><button>Add to cart</button>'
        self.assertEqual(drops.parse_product_page(og, 'https://store.example/p')['images'], ['https://cdn.example/share.jpg'])
        self.assertEqual(drops.parse_product_page('<h1>Coin</h1>')['images'], [])

    def test_feed_readers_keep_pictures(self):
        shop = {'products': [{'id': 1, 'title': 'Colorized Silver Eagle', 'handle': 'eagle',
                              'published_at': '2026-11-10T08:00:00-05:00', 'tags': [],
                              'variants': [{'available': True, 'price': '99.00'}],
                              'images': [{'src': 'https://cdn.shopify.com/s/files/1/eagle.jpg?v=3'}]}]}
        woo = [{'id': 7, 'name': 'Colorized Copper Round', 'permalink': 'https://woo.example/product/round/',
                'is_in_stock': True, 'prices': {'price': '1299', 'currency_minor_unit': 2},
                'images': [{'src': 'https://woo.example/u/round.jpg', 'thumbnail': 'https://woo.example/u/round-300x300.jpg'}]}]

        class Fake:
            def __init__(self, body):
                self.body = body

            def get(self, url, **kwargs):
                return 200, json.dumps(self.body)

        cfg = {**CFG, 'drops': {'feed_max_pages': 1}}
        item = drops.read_shopify('https://shop.example', Fake(shop), cfg)[0]
        self.assertEqual(item['images'], ['https://cdn.shopify.com/s/files/1/eagle.jpg?v=3'])
        item = drops.read_woocommerce('https://woo.example', Fake(woo), cfg)[0]
        self.assertEqual(item['images'], ['https://woo.example/u/round.jpg'])
        self.assertEqual(item['thumb'], 'https://woo.example/u/round-300x300.jpg')

    def test_file_roundtrip_update_and_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'data' / 'media.csv')
            saved = media.load(path)
            self.assertEqual(saved, {})
            keep = {('s', '1'), ('s', '2')}
            items = [{'product_id': '1', 'images': ['https://c.example/1.jpg', 'https://c.example/1b.jpg'], 'thumb': 'https://c.example/1s.jpg'},
                     {'product_id': '2', 'images': []},                       # read, but no picture
                     {'product_id': '3', 'images': ['https://c.example/3.jpg']}]  # not a recent launch
            self.assertEqual(media.update(saved, 's', items, keep), 1)
            self.assertEqual(media.update(saved, 's', items, keep), 0)       # nothing changed the second time
            media.save(saved, path)
            again = media.load(path)
            self.assertEqual(again, {('s', '1'): {'thumb': 'https://c.example/1s.jpg',
                                                  'images': ['https://c.example/1.jpg', 'https://c.example/1b.jpg'],
                                                  'presale': False, 'ships': ''}})
            # a later read without pictures keeps what was saved; ageing out removes it
            media.update(again, 's', [{'product_id': '1'}], keep)
            self.assertIn(('s', '1'), again)
            self.assertEqual(media.prune(again, set()), 1)
            self.assertEqual(again, {})


class Launches(unittest.TestCase):
    def test_launch_date_and_who_gave_it(self):
        self.assertEqual(gallery.launch_of(row(1, published_at='2026-10-29T08:56:50-04:00', published='2026-10-29')),
                         ('2026-10-29T12:56:50Z', True))
        self.assertEqual(gallery.launch_of(row(1, published='2026-10-29')), ('2026-10-29', True))
        self.assertEqual(gallery.launch_of(row(1, first_seen_at='2026-11-06T16:25:51Z')), ('2026-11-06T16:25:51Z', False))
        self.assertEqual(gallery.launch_of(row(1)), ('2026-11-01', False))
        # already in the catalogue when tracking began: launch unknown
        self.assertIsNone(gallery.launch_of(row(1, baseline='1')))
        # …unless the store itself dates it
        self.assertEqual(gallery.launch_of(row(1, baseline='1', published='2026-11-02'))[1], True)
        # blanks arrive as NaN when the state comes from pandas
        self.assertEqual(gallery.launch_of(row(1, published_at=float('nan'), published=float('nan'))), ('2026-11-01', False))

    def test_window_and_catalogue_batches(self):
        rows = [row(1, published='2026-11-10'), row(2, published='2026-07-01'),      # too old
                row(3, published='2026-12-25')]                                         # date in the future
        rows += [row(100 + i, store='https://woo.example', first_seen='2026-11-01') for i in range(25)]  # batch
        rows += [row(200 + i, store='https://woo.example', first_seen='2026-11-05') for i in range(3)]   # real launches
        items, stores = gallery.releases(rows, CFG, TODAY)
        self.assertEqual(len(items), 4)
        self.assertEqual(sorted(it['d'] for it in items), ['2026-11-05'] * 3 + ['2026-11-10'])
        self.assertEqual(items[0]['d'], '2026-11-10')                                   # newest first
        self.assertEqual([s['cur'] for s in stores], ['USD', 'AUD'])
        keys = gallery.recent_keys(pd.DataFrame(rows).to_dict('records'), CFG, TODAY)
        self.assertEqual(len(keys), 4)
        self.assertIn(('https://shop.example', '1'), keys)

    def test_issue_year(self):
        cases = {'2026 Niue Dragon 1 oz Silver Coin': 2026,
                 '1885-CC Morgan Silver Dollar - PCGS MS64': 1885,
                 '2026 Agoro DC Batman #251 The Joker’s Revenge (1973) 20g Silver Foil': 2026,
                 'USA 1776-2026 Semiquincentennial Round': 2026,
                 'Perth Mint 1997 1 oz .9999 Silver Kookaburra': 1997,
                 'King Lion 1 oz Colorized Copper Medal': None,
                 'Silver Round 2000 Mintage': None,
                 'Thor 1/2000 oz Gold $2000 Note': None,
                 '5 oz Bar 9999 Fine': None}
        for title, year in cases.items():
            self.assertEqual(gallery.issue_year(title, TODAY), year, title)
        self.assertIsNone(gallery.issue_year('2099 Future Coin', TODAY))

    def test_listing_fields(self):
        rows = [row(1, title='2026 Tuvalu  Dragon &amp; Phoenix 2 oz Silver Colorized Coin', published_at='2026-11-10T10:00:00Z',
                    first_seen_at='2026-11-10T12:00:00Z', stock_status='unavailable'),
                row(2, title='1921 Morgan Dollar', colorized='0', price='', mintage='', url='javascript:alert(1)',
                    published='2026-11-09', stock_status='unknown')]
        pictures = {('https://shop.example', '1'): {'thumb': '', 'images': ['https://c.example/1.jpg']}}
        items, _ = gallery.releases(rows, CFG, TODAY, pictures, {'https://shop.example': True})
        first, second = items
        self.assertEqual(first['t'], '2026 Tuvalu Dragon & Phoenix 2 oz Silver Colorized Coin')
        self.assertEqual((first['k'], first['c'], first['a'], first['y'], first['m'], first['p']), (1, 1, 0, 2026, 500, 99.5))
        self.assertEqual(first['n'], '2026-11-10T12:00:00Z')
        self.assertEqual(first['i'], ['https://c.example/1.jpg'])
        self.assertIn('Dragons', first['th'])
        self.assertEqual((first['z'], first['me']), ('2–3 oz', 'Silver'))
        for absent in ('u', 'c', 'p', 'm', 'a', 'i', 'h'):
            self.assertNotIn(absent, second, absent)           # unsafe link dropped, blanks left out
        self.assertEqual(second['y'], 1921)


class Page(unittest.TestCase):
    def test_page_is_built_from_saved_files_and_titles_stay_inert(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'data').mkdir()
            rows = [row(1, title='2026 Coin </script><script>alert(1)</script>', published='2026-11-10'),
                    row(2, baseline='1')]
            pd.DataFrame(rows).to_csv(tmp / 'data' / 'drops_state.csv', index=False)
            (tmp / 'data' / 'collection_health.csv').write_text('store,checked_at,ok\nhttps://shop.example,x,True\nhttps://woo.example,x,False\n')
            media.save({('https://shop.example', '1'): {'thumb': '', 'images': ['https://c.example/1.jpg']}},
                       str(tmp / 'data' / 'media.csv'))
            with patch.object(gallery, 'STATE', str(tmp / 'data' / 'drops_state.csv')), \
                 patch.object(gallery, 'HEALTH', str(tmp / 'data' / 'collection_health.csv')), \
                 patch.object(gallery, 'OUT', str(tmp / 'docs' / 'releases.html')), \
                 patch.object(media, 'PATH', str(tmp / 'data' / 'media.csv')):
                out = gallery.build(CFG, NOW)
            page = Path(out).read_text(encoding='utf-8')
        self.assertEqual(page.count('</script>'), 1)                        # only the page's own
        self.assertNotIn('__DATA__', page)
        data = json.loads(re.search(r'const D = (\{.*?\});\nconst DAY', page, re.S).group(1))
        self.assertEqual(data['meta'], {'generated': '2026-11-11T18:00:00Z', 'window': 90, 'min_year': 2025, 'fx': {'AUD': 0.65}})
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['i'], ['https://c.example/1.jpg'])
        self.assertEqual([s.get('ok') for s in data['stores']], [True, False])

    def test_page_builds_before_anything_is_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gallery, 'STATE', str(Path(tmp) / 'none.csv')), \
                 patch.object(gallery, 'HEALTH', str(Path(tmp) / 'none2.csv')), \
                 patch.object(gallery, 'OUT', str(Path(tmp) / 'docs' / 'releases.html')), \
                 patch.object(media, 'PATH', str(Path(tmp) / 'none3.csv')):
                page = Path(gallery.build({}, NOW)).read_text(encoding='utf-8')
        self.assertIn('"items":[]', page)

    def test_settings_fall_back_to_defaults(self):
        self.assertEqual(gallery.settings({})['window_days'], 90)
        self.assertEqual(gallery.settings({'gallery': {'window_days': '30', 'bulk_first_seen': 'x'}}),
                         {'window_days': 30, 'bulk_first_seen': 25, 'keep_pictures_extra_days': 30, 'catchup_days': 10})


class TrackerRun(unittest.TestCase):
    def test_run_saves_pictures_of_recent_launches_only(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        recent = (today - dt.timedelta(days=3)).isoformat()
        old = (today - dt.timedelta(days=400)).isoformat()
        feed = [{'product_id': '1', 'title': 'New Colorized Coin', 'url': 'https://shop.example/products/1',
                 'published': recent, 'published_at': recent + 'T10:00:00Z', 'available': True, 'colorized': True,
                 'price': 50.0, 'mintage': None, 'images': ['https://cdn.example/new.jpg'], 'thumb': ''},
                {'product_id': '2', 'title': 'Old Colorized Coin', 'url': 'https://shop.example/products/2',
                 'published': old, 'published_at': old + 'T10:00:00Z', 'available': True, 'colorized': True,
                 'price': 50.0, 'mintage': None, 'images': ['https://cdn.example/old.jpg'], 'thumb': ''}]
        cfg = {**CFG, 'drops': {'stores': [{'url': 'https://shop.example', 'platform': 'shopify'}]}}
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            data.mkdir()
            with patch.object(drops, 'ROOT', tmp), patch.object(drops, 'STATE', str(data / 'drops_state.csv')), \
                 patch.object(drops, 'BROAD', str(data / 'broad_stores.txt')), \
                 patch.object(media, 'PATH', str(data / 'media.csv')), \
                 patch.object(drops, 'read_shopify', return_value=feed):
                state, ok, _ = drops.run_tracker(cfg, today)
                saved = media.load()
                # a failing picture step never stops the tracker
                with patch.object(media, 'save', side_effect=OSError('disk full')):
                    _, ok_again, _ = drops.run_tracker(cfg, today)
            self.assertEqual((ok, ok_again, len(state)), (1, 1, 2))
            self.assertEqual(list(saved), [('https://shop.example', '1')])
            self.assertEqual(list(state.columns), drops.STATE_COLS)            # tracker state is unchanged


if __name__ == '__main__':
    unittest.main()


class Presale(unittest.TestCase):
    def test_wording(self):
        yes = ['PREORDER: 2022 Silver Eagle', '2027 Goat 1 oz (Presale)', 'Pre-Sale', 'Available for pre-ordering',
               'Presale &#8211; 2027 Kangaroo', 'Silver Presale',
               'Expected to ship on or around December 15, 2026', 'Ships around Jan 20']
        no = ['2026 Silver Eagle Veteran Edition', 'In stock', 'Pressed copper round', 'Shipping is free over $99',
              'Order now while supplies last', 'In Stock / On Backorder', 'Available on backorder']
        for t in yes:
            self.assertTrue(media.presale_in(t)[0], t)
        for t in no:
            self.assertFalse(media.presale_in(t)[0], t)
        self.assertEqual(media.presale_in('Pre-order. Expected to ship on or around December 15, 2026.')[1], 'December 15, 2026')
        self.assertEqual(media.presale_in('<p>Presale</p><p>Ships after: Jan 20</p>')[1], 'Jan 20')
        self.assertEqual(media.presale_in('No presale here', None, 5), (True, ''))

    def test_feeds(self):
        p = media.presale_shopify({'title': 'Dragon Coin', 'tags': ['Pre-Order', 'Silver'], 'body_html': ''})
        self.assertTrue(p['presale'])
        p = media.presale_shopify({'title': 'Dragon Coin', 'tags': [], 'body_html': '<p>Pre-sale. Ships around Feb 2027</p>'})
        self.assertEqual((p['presale'], p['presale_text'], p['ships']), (False, True, 'Feb 2027'))
        w = media.presale_woocommerce({'name': 'Round', 'is_on_backorder': True,
                                       'stock_availability': {'text': 'In Stock / On Backorder'}})
        self.assertFalse(w['presale'])
        w = media.presale_woocommerce({'name': 'Round', 'categories': [{'name': 'Pre-Sale Silver'}]})
        self.assertTrue(w['presale'])
        w = media.presale_woocommerce({'name': 'Round', 'stock_availability': {'text': 'In stock'}})
        self.assertFalse(w['presale'])
        self.assertEqual(media.presale_shopify(None)['presale'], False)

    def test_product_page(self):
        html = ('<script type="application/ld+json">{"@type":"Product","name":"Goat",'
                '"offers":{"availability":"https://schema.org/PreOrder"}}</script>'
                '<div class="ship-date">Expected to ship on or around Dec 15, 2026</div>')
        info = drops.parse_product_page(html, 'https://s.example/p')
        self.assertEqual((info['available'], info['presale'], info['ships']), (True, True, 'Dec 15, 2026'))
        plain = '<script type="application/ld+json">{"@type":"Product","offers":{"availability":"InStock"}}</script>'
        self.assertFalse(drops.parse_product_page(plain)['presale'])
        button = '<h1>Lion</h1><button>Pre-order now</button>'
        self.assertTrue(drops.parse_product_page(button)['presale'])

    def test_boilerplate_ignored_and_status_kept(self):
        saved = {}
        items = [{'product_id': str(i), 'images': [f'https://c.example/{i}.jpg'], 'presale': False,
                  'presale_text': True, 'ships': ''} for i in range(10)]           # every description says it
        media.update(saved, 's', items)
        self.assertFalse(any(m['presale'] for m in saved.values()))
        items[0].update(presale=True, ships='Dec 1')
        media.update(saved, 's', items)
        self.assertEqual((saved[('s', '0')]['presale'], saved[('s', '0')]['ships']), (True, 'Dec 1'))
        # a page that failed this time keeps the earlier answer
        media.update(saved, 's', [{'product_id': '0', 'checked': True}])
        self.assertTrue(saved[('s', '0')]['presale'])
        # presale without a picture is still recorded; turning off clears the ship date
        media.update(saved, 's', [{'product_id': '99', 'presale': True, 'ships': 'Jan 5'}])
        self.assertEqual(saved[('s', '99')], {'thumb': '', 'images': [], 'presale': True, 'ships': 'Jan 5'})
        media.update(saved, 's', [{'product_id': '99', 'presale': False}])
        self.assertNotIn(('s', '99'), saved)
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'm.csv')
            media.save(saved, path)
            self.assertEqual(media.load(path), saved)

    def test_old_file_without_presale_columns_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'm.csv'
            path.write_text('store,product_id,thumb,images\ns,1,,https://c.example/1.jpg\n')
            self.assertEqual(media.load(str(path))[('s', '1')]['presale'], False)

    def test_page_item_carries_presale(self):
        rows = [row(1, published='2026-11-10')]
        items, _ = gallery.releases(rows, CFG, TODAY, {('https://shop.example', '1'): {
            'thumb': '', 'images': [], 'presale': True, 'ships': 'Dec 15'}})
        self.assertEqual((items[0]['ps'], items[0]['sh']), (1, 'Dec 15'))
        items, _ = gallery.releases(rows, CFG, TODAY, {})
        self.assertNotIn('ps', items[0])


class MoreStores(unittest.TestCase):
    def test_sitemap_newest_first_with_age_limit(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        recent, older, old = (today - dt.timedelta(days=d) for d in (2, 20, 400))
        index = ('<sitemapindex><sitemap><loc>https://s.example/sm-1.xml</loc></sitemap>'
                 '<sitemap><loc>https://s.example/blog.xml</loc></sitemap></sitemapindex>')
        child = (f'<urlset><url><loc>https://s.example/p/old-coin</loc><lastmod>{old}</lastmod></url>'
                 f'<url><loc>https://s.example/p/mid-coin</loc><lastmod>{older}T10:00:00+00:00</lastmod></url>'
                 f'<url><loc>https://s.example/p/new-coin</loc><lastmod>{recent}</lastmod></url>'
                 '<url><loc>https://s.example/p/undated-coin</loc></url>'
                 '<url><loc>https://s.example/about-us</loc></url></urlset>')
        pages = {'https://s.example/index.xml': index, 'https://s.example/sm-1.xml': child}

        class Fake:
            def get(self, url, **kw):
                return (200, pages[url]) if url in pages else (404, '')

        pat = re.compile('^/p/')
        self.assertEqual(drops.read_sitemap('https://s.example/index.xml', Fake(), pat, child='sm-'),
                         ['https://s.example/p/old-coin', 'https://s.example/p/mid-coin',
                          'https://s.example/p/new-coin', 'https://s.example/p/undated-coin'])
        self.assertEqual(drops.read_sitemap('https://s.example/index.xml', Fake(), pat, child='sm-', max_age_days=90),
                         ['https://s.example/p/new-coin', 'https://s.example/p/mid-coin', 'https://s.example/p/undated-coin'])
        # default child filter (product|items|shop) still applies without a pattern
        self.assertEqual(drops.read_sitemap('https://s.example/index.xml', Fake(), pat), [])

    def test_catchup_period_hidden_for_page_by_page_stores(self):
        cfg = {**CFG, 'drops': {'stores': [{'url': 'https://shop.example'},
                                           {'url': 'https://slow.example', 'platform': 'generic'}]}}
        rows = [row(1, store='https://slow.example', first_seen='2026-10-20', baseline='1'),   # tracking began
                row(2, store='https://slow.example', first_seen='2026-10-25'),                 # catch-up: hidden
                row(3, store='https://slow.example', first_seen='2026-11-05'),                 # real launch
                row(4, store='https://slow.example', first_seen='2026-10-26', published='2026-10-26'),  # dated: shown
                row(5, store='https://shop.example', first_seen='2026-10-25')]                 # feed store: shown
        got = sorted(it['t'] + str(it['s']) for it in gallery.releases(rows, cfg, TODAY)[0])
        self.assertEqual(len(got), 3)
        items, stores = gallery.releases(rows, cfg, TODAY)
        self.assertEqual(sorted((stores[it['s']]['n'], it['d']) for it in items),
                         [('shop.example', '2026-10-25'), ('slow.example', '2026-10-26'), ('slow.example', '2026-11-05')])


class SitemapOrder(unittest.TestCase):
    def test_current_years_first_and_fragments_merged(self):
        y = dt.date.today().year
        xml = ('<urlset>' + ''.join(f'<url><loc>https://s.example/p/{slug}</loc></url>' for slug in
               ['1872-sovereign/5934#child=1', '1872-sovereign/5934#child=2', f'{y}-dragon-1oz/9001',
                'kangaroo-proof/12', f'{y + 1}-goat/9002', f'1oz-{y}0101-bar/7']) + '</urlset>')

        class Fake:
            def get(self, url, **kw):
                return 200, xml

        got = drops.read_sitemap('https://s.example/sm.xml', Fake(), re.compile('^/p/'))
        self.assertEqual(got, [f'https://s.example/p/{y}-dragon-1oz/9001', f'https://s.example/p/{y + 1}-goat/9002',
                               'https://s.example/p/1872-sovereign/5934', 'https://s.example/p/kangaroo-proof/12',
                               f'https://s.example/p/1oz-{y}0101-bar/7'])


class News(unittest.TestCase):
    POSTS = [{"id": 83210, "date_gmt": "2026-11-12T13:21:21",
              "link": "https://agaunews.com/one-eyed-monster-are-nothing-mate-check-out-snakey-here/",
              "title": {"rendered": "Fantasy comes to the fore with the tale of Perseus &#038; Medusa, plus Sinbad as the latest &#8216;Fabulous Stories&#8217; coin"},
              "yoast_head_json": {"og_image": [{"width": 2000, "url": "https://agaunews.com/wp-content/uploads/2026/11/2026-TS-Perseus-FEAT.jpg"}]}},
             {"id": 1, "date_gmt": "2026-06-01T10:00:00", "link": "https://agaunews.com/old/", "title": {"rendered": "Old post"}},
             {"id": 2, "date_gmt": "", "link": "https://agaunews.com/x/", "title": {"rendered": "No date"}},
             "junk"]
    CFG = {**CFG, 'news': {'window_days': 90, 'sources': [{'url': 'https://agaunews.com', 'name': 'AgAuNEWS'}]}}

    def test_wordpress_posts(self):
        got = news.from_wp_posts(self.POSTS)
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0], {'id': '83210', 'date': '2026-11-12T13:21:21Z',
                                  'title': 'Fantasy comes to the fore with the tale of Perseus & Medusa, plus Sinbad as the latest ‘Fabulous Stories’ coin',
                                  'link': 'https://agaunews.com/one-eyed-monster-are-nothing-mate-check-out-snakey-here/',
                                  'image': 'https://agaunews.com/wp-content/uploads/2026/11/2026-TS-Perseus-FEAT.jpg'})
        self.assertEqual(news.from_wp_posts(None), [])

    def test_rss_fallback(self):
        xml = ('<rss><channel><item><title><![CDATA[Royal Mint Frankenstein]]></title>'
               '<link>https://agaunews.com/who-stitched-me-up/</link><pubDate>Tue, 10 Nov 2026 22:54:13 +0000</pubDate>'
               '<content:encoded><![CDATA[<p><img src="https://agaunews.com/wp-content/uploads/f.jpg" /></p>]]></content:encoded>'
               '</item></channel></rss>')
        self.assertEqual(news.from_rss(xml), [{'id': 'https://agaunews.com/who-stitched-me-up/', 'date': '2026-11-10T22:54:13Z',
                                               'title': 'Royal Mint Frankenstein', 'link': 'https://agaunews.com/who-stitched-me-up/',
                                               'image': 'https://agaunews.com/wp-content/uploads/f.jpg'}])

    def test_collect_keeps_window_and_survives_a_dead_site(self):
        calls = []

        def get(url, params=None):
            calls.append(url)
            return (200, json.dumps(self.POSTS)) if url.endswith('/posts') else (404, '')

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'news.csv')
            self.assertEqual(news.collect(self.CFG, get, NOW, path), 1)          # the June post is outside 90 days
            self.assertEqual(news.collect(self.CFG, lambda u, params=None: (503, ''), NOW, path), 1)  # site down: kept
            self.assertEqual(news.load(path)[0]['source'], 'https://agaunews.com')
        self.assertEqual(news.collect({}, get, NOW), 0)

    def test_posts_on_the_wall(self):
        items, stores = [], []
        posts = [{'source': 'https://agaunews.com', 'id': '1', 'date': '2026-11-12T13:21:21Z',
                  'title': '2026 Niue Colorized Dragon 1 oz silver coin', 'link': 'https://agaunews.com/a/', 'image': ''},
                 {'source': 'https://agaunews.com', 'id': '2', 'date': '2026-11-11T10:00:00Z',
                  'title': 'Bad link', 'link': 'javascript:x', 'image': ''}]
        gallery.add_news(items, stores, posts, self.CFG, TODAY, 90)
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]['nw'], items[0]['k'], items[0]['c'], items[0]['y']), (1, 1, 1, 2026))
        self.assertEqual(stores, [{'n': 'AgAuNEWS', 'u': 'https://agaunews.com', 'cur': 'USD', 'news': 1}])
