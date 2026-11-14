"""Tests using local XML only; does not depend on network calls."""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('collector',ROOT/'scripts'/'collect.py')
collector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

class CollectorTests(unittest.TestCase):
    def test_rss_and_dates(self):
        xml=b'<rss version="2.0"><channel><item><title>New etch tool</title><link>https://example.org/story</link><pubDate>Thu, 12 Nov 2026 16:00:00 GMT</pubDate><description>Short description</description></item></channel></rss>'
        items=collector.parse_feed(xml)
        self.assertEqual(len(items),1)
        self.assertEqual(collector.article_date(items[0]).date().isoformat(),'2026-11-13')

    def test_atom(self):
        xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Chip research</title><updated>2026-11-12T18:00:00Z</updated><summary>Summary</summary><link rel="alternate" href="https://example.org/atom" /></entry></feed>'
        items=collector.parse_feed(xml)
        self.assertEqual(items[0]['link'],'https://example.org/atom')
        self.assertEqual(collector.article_date(items[0]).date().isoformat(),'2026-11-13')

    def test_week_bounds(self):
        start,end=collector.iso_week_bounds('2026-W46')
        self.assertEqual(start.date().isoformat(),'2026-11-09')
        self.assertEqual(end.date().isoformat(),'2026-11-16')

    def test_categories(self):
        for term,cat in [('Photoresist capacity','materials'),('Wafer etch equipment','equipment'),('LLM agent framework','ai'),('HBM chip supply','semiconductor')]:
            self.assertEqual(collector.category_for(term,'','auto'),cat)

    def test_link_safety_and_dedupe(self):
        self.assertEqual(collector.normalized_url('javascript:alert(1)'),'')
        self.assertEqual(collector.normalized_url('https://example.org/foo?utm_source=x'),'https://example.org/foo')
        row={'id':'one','url':'https://example.org/one','title':'Test new chip production', 'score':50,'publishedAt':'2026-11-13','category':'semiconductor','source':'A'}
        row2={**row,'id':'two','url':'https://example.org/two','score':40}
        self.assertEqual(len(collector.dedupe([row,row2])),1)

if __name__=='__main__': unittest.main()
