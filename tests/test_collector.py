"""Tests using local XML only; does not depend on network calls."""
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPSHandler
from urllib.response import addinfourl

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('collector',ROOT/'scripts'/'collect.py')
collector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

class CollectorTests(unittest.TestCase):
    def test_enrichment_uses_configured_endpoint(self):
        row = {'id': 'test', 'title': 'Chip news', 'summary': 'New chip', 'category': 'semiconductor'}
        translated = [{'id': 'test', 'titleJa': '半導体ニュース', 'summaryJa': '新しい半導体。', 'whyJa': ''}]
        response = {'output': [{'content': [{'type': 'output_text', 'text': json.dumps(translated)}]}]}
        env = {
            'OPENAI_API_KEY': 'openai-key',
            'OPENAI_MODEL': 'openai-model',
            'OPENROUTER_API_KEY': 'openrouter-key',
            'OPENROUTER_MODEL': 'nvidia/nemotron-3.5-super-vl:free',
        }
        for provider, endpoint in (
            ('openai', 'https://api.openai.com/v1/responses'),
            ('openrouter', 'https://openrouter.ai/api/v1/responses'),
        ):
            with self.subTest(provider=provider):
                article = row.copy()
                with patch.dict(collector.os.environ, {**env, 'LLM_PROVIDER': provider}, clear=True), patch.object(
                    collector.LLM_OPENER, 'open', return_value=io.BytesIO(json.dumps(response).encode())
                ) as request, patch('sys.stdout', new_callable=io.StringIO):
                    translate_batch = collector.select_llm_provider()
                    collector.enrich_articles([article], translate_batch)
                sent = request.call_args.args[0]
                body = json.loads(sent.data)
                self.assertEqual(sent.full_url, endpoint)
                self.assertEqual(sent.get_header('Authorization'), f'Bearer {env[provider.upper() + "_API_KEY"]}')
                self.assertEqual(body['model'], env[provider.upper() + '_MODEL'])
                self.assertEqual(body['max_output_tokens'], 8000)
                if provider == 'openrouter':
                    self.assertEqual(body['reasoning'], {'enabled': False})
                else:
                    self.assertNotIn('reasoning', body)
                self.assertTrue(article['enriched'])
                self.assertEqual(article['titleJa'], '半導体ニュース')

    def test_enrichment_batches(self):
        rows = [{'id': str(i), 'title': 'Chip', 'summary': 'News', 'category': 'semiconductor'} for i in range(7)]
        batch_sizes = []

        def translate_batch(instruction, payload):
            batch_sizes.append(len(payload))
            return [{'id': item['id'], 'titleJa': '半導体'} for item in payload]

        with patch('sys.stdout', new_callable=io.StringIO):
            collector.enrich_articles(rows, translate_batch)
        self.assertEqual(batch_sizes, [5, 2])
        self.assertTrue(all(row['enriched'] for row in rows))

    def test_enrichment_rejects_redirects(self):
        endpoint = 'https://api.openai.com/v1/responses'
        headers = Message()
        headers['Location'] = 'https://redirect.example/collect'
        response = addinfourl(io.BytesIO(), headers, endpoint, 302)
        response.msg = 'Found'
        request = collector.Request(endpoint, data=b'{}', headers={'Authorization': 'Bearer test-key'})
        with patch.object(HTTPSHandler, 'https_open', return_value=response) as send:
            with self.assertRaises(HTTPError) as error:
                collector.LLM_OPENER.open(request)
            self.assertEqual(error.exception.code, 302)
            error.exception.close()
        send.assert_called_once_with(request)

    def test_enrichment_diagnoses_missing_or_truncated_answers(self):
        cases = [
            ({'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}, 'output': []}, 'incomplete: max_output_tokens'),
            ({'output': [], 'usage': {'output_tokens_details': {'reasoning_tokens': 3500}}}, 'no answer text'),
            ({'output': [{'content': [{'type': 'output_text', 'text': '[{"id": "unfinished'}]}]}, 'not complete, valid JSON'),
        ]
        for response, message in cases:
            with self.subTest(message=message):
                row = {'id': 'one', 'title': 'Chip', 'summary': 'News', 'category': 'semiconductor'}
                original = row.copy()
                env = {'LLM_PROVIDER': 'openai', 'OPENAI_API_KEY': 'test-key', 'OPENAI_MODEL': 'test-model'}
                with patch.dict(collector.os.environ, env, clear=True), patch.object(
                    collector.LLM_OPENER, 'open', return_value=io.BytesIO(json.dumps(response).encode())
                ), patch.object(collector.time, 'sleep'), patch('sys.stderr', new_callable=io.StringIO) as errors:
                    collector.enrich_articles([row], collector.select_llm_provider())
                self.assertEqual(row, original)
                self.assertIn(message, errors.getvalue())

    def test_enrichment_reads_fenced_json_ignoring_reasoning(self):
        response = {'output': [
            {'type': 'reasoning', 'content': [{'type': 'reasoning_text', 'text': 'not JSON'}]},
            {'content': [{'type': 'output_text', 'text': '```json\n[{"id":"one"}]\n```'}]},
        ]}
        self.assertEqual(collector.enrichment_records(response), [{'id': 'one'}])

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

class CollectionRerunTests(unittest.TestCase):
    llm_env = {'LLM_PROVIDER': 'openai', 'OPENAI_API_KEY': 'test-key', 'OPENAI_MODEL': 'test-model'}

    def setUp(self):
        self.root = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.data = self.root / 'data'
        self.edition_path = self.data / 'editions' / '2026-W46.json'
        self.index_path = self.data / 'index.json'
        self.feeds = [
            {'name': 'Working feed', 'url': 'https://example.org/rss', 'category': 'semiconductor'},
            {'name': 'Unavailable feed', 'url': 'https://unavailable.example/rss'},
        ]
        collector.write_json(self.root / 'config' / 'feeds.json', self.feeds)
        self.enterContext(patch.object(collector, 'ROOT', self.root))
        self.enterContext(patch.object(collector, 'DATA', self.data))
        self.enterContext(patch.dict(collector.os.environ, self.llm_env, clear=True))
        self.enterContext(patch('sys.argv', ['collect.py', '--week', '2026-W46']))
        self.enterContext(patch('sys.stdout', new_callable=io.StringIO))
        self.enterContext(patch('sys.stderr', new_callable=io.StringIO))
        self.enterContext(patch.object(collector.time, 'sleep'))

    def article(self, number, enriched=True, **overrides):
        url = f'https://example.org/article/{number}'
        return {
            'id': collector.hashlib.sha256(url.encode()).hexdigest()[:16],
            'category': 'semiconductor', 'title': f'Chip production announcement number {number}',
            'summary': f'Chip production details {number}',
            'titleJa': f'半導体ニュース{number}' if enriched else '',
            'summaryJa': f'半導体の概要{number}' if enriched else '',
            'whyJa': '技術への影響' if enriched else '', 'enriched': enriched,
            'source': f'Source {number % 8}', 'publishedAt': '2026-11-12T12:00:00+09:00',
            'url': url, 'score': 50, 'tags': [], **overrides,
        }

    def save_existing(self, articles):
        collector.write_json(self.edition_path, {'week': '2026-W46', 'articles': articles})
        collector.write_json(self.index_path, {'latest': '2026-W46', 'editions': [{'week': '2026-W46', 'count': len(articles)}]})

    def run_with_rows(self, rows):
        with patch.object(collector, 'collect', return_value=(rows, 1)):
            collector.main()
        return json.loads(self.edition_path.read_text())['articles']

    def api_response(self, records):
        return io.BytesIO(json.dumps({'output': [{'content': [
            {'type': 'output_text', 'text': json.dumps(records)}
        ]}]}).encode())

    def test_partial_feed_failure_preserves_all_44_articles_and_translations(self):
        existing = [self.article(i) for i in range(44)]
        self.save_existing(existing)
        article = existing[0]
        xml = f'''<rss><channel><item><title>{article['title']}</title>
            <link>{article['url']}</link><description>{article['summary']}</description>
            <pubDate>Thu, 12 Nov 2026 03:00:00 GMT</pubDate></item></channel></rss>'''.encode()
        with patch.object(collector, 'urlopen', side_effect=[io.BytesIO(xml), OSError('RSS unavailable')]) as request, patch.object(
            collector.LLM_OPENER, 'open'
        ) as translate:
            collector.main()
        saved = json.loads(self.edition_path.read_text())
        self.assertEqual(len(saved['articles']), 44)
        self.assertEqual({row['id'] for row in saved['articles']}, {row['id'] for row in existing})
        for row in saved['articles']:
            old = next(item for item in existing if item['id'] == row['id'])
            for field in ('titleJa', 'summaryJa', 'whyJa', 'enriched'):
                self.assertEqual(row[field], old[field])
        self.assertEqual(request.call_count, 2)
        translate.assert_not_called()
        index = json.loads(self.index_path.read_text())
        self.assertEqual(index['editions'][0]['count'], 44)
        self.assertIn('44件', saved['overview'])

    def test_merge_updates_by_id_and_retains_missing_articles(self):
        old = self.article(1)
        missing = self.article(2)
        fresh = self.article(1, enriched=False, score=99, source='Updated source')
        merged = collector.merge_articles([old, missing], [fresh, self.article(3, enriched=False)])
        by_id = {row['id']: row for row in merged}
        self.assertEqual(len(merged), 3)
        self.assertEqual(by_id[old['id']]['score'], 99)
        self.assertEqual(by_id[old['id']]['source'], 'Updated source')
        self.assertEqual(by_id[old['id']]['summaryJa'], old['summaryJa'])
        self.assertEqual(by_id[missing['id']], missing)
        self.assertEqual(old['score'], 50)  # Merging does not mutate saved input.

    def test_limit_and_source_cap_do_not_remove_existing_articles(self):
        existing = [self.article(i, source='Same source') for i in range(8)]
        for limit in (1, 8, 9):
            with self.subTest(limit=limit):
                rows = collector.merge_articles(existing, [
                    self.article(100, enriched=False, score=100, source='Same source'),
                    self.article(101, enriched=False, score=99, source='Other source'),
                ], limit)
                self.assertTrue({row['id'] for row in existing} <= {row['id'] for row in rows})
                self.assertEqual(len(rows), max(len(existing), limit))
                self.assertNotIn(self.article(100)['id'], {row['id'] for row in rows})

    def test_empty_collection_retains_existing_edition_without_api_key(self):
        old = self.article(1)
        self.save_existing([old])
        with patch.dict(collector.os.environ, {}, clear=True), patch.object(collector.LLM_OPENER, 'open') as request:
            self.assertEqual(self.run_with_rows([]), [old])
        request.assert_not_called()

    def test_all_feed_failures_leave_edition_and_index_untouched(self):
        self.save_existing([self.article(1)])
        before = (self.edition_path.read_bytes(), self.index_path.read_bytes())
        with patch.object(collector, 'urlopen', side_effect=OSError('RSS unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'All RSS feeds failed'):
                collector.main()
        self.assertEqual((self.edition_path.read_bytes(), self.index_path.read_bytes()), before)

    def test_first_collection_with_no_articles_does_not_publish(self):
        with self.assertRaisesRegex(RuntimeError, 'No articles found'):
            self.run_with_rows([])
        self.assertFalse(self.edition_path.exists())
        self.assertFalse(self.index_path.exists())

    def test_translation_failures_keep_previous_original_and_japanese_together(self):
        old = self.article(1)
        changed = self.article(1, enriched=False, title='Revised chip announcement', summary='Revised details')
        new = self.article(2, enriched=False)
        for failure in ('exception', 'missing record', 'empty title', 'no key'):
            with self.subTest(failure=failure):
                self.save_existing([old])
                records = [] if failure == 'missing record' else [{'id': old['id'], 'titleJa': ''}]
                with patch.object(collector.LLM_OPENER, 'open') as request:
                    if failure == 'exception':
                        request.side_effect = OSError('Translation unavailable')
                    else:
                        request.return_value = self.api_response(records)
                    env = self.llm_env.copy()
                    if failure == 'no key':
                        env.pop('OPENAI_API_KEY')
                        env['OPENROUTER_API_KEY'] = 'other-provider-key'
                    with patch.dict(collector.os.environ, env, clear=True):
                        rows = self.run_with_rows([changed.copy(), new.copy()])
                    if failure == 'no key':
                        request.assert_not_called()
                self.assertEqual({row['id']: row for row in rows}, {old['id']: old, new['id']: new})

    def test_changed_translation_inputs_are_retranslated_and_untranslated_articles_retried(self):
        old = self.article(1)
        for field, value in (('title', 'Revised headline'), ('summary', 'Revised summary'), ('category', 'equipment')):
            with self.subTest(field=field):
                unchanged = self.article(2)
                retry = self.article(3, enriched=False)
                self.save_existing([old, unchanged, retry])
                changed = self.article(1, enriched=False, **{field: value})
                translated = [
                    {'id': old['id'], 'titleJa': '更新された見出し', 'summaryJa': '更新された概要', 'whyJa': ''},
                    {'id': retry['id'], 'titleJa': '再試行した見出し', 'summaryJa': '再試行した概要', 'whyJa': ''},
                ]
                with patch.object(collector.LLM_OPENER, 'open', return_value=self.api_response(translated)) as request:
                    rows = self.run_with_rows([changed, self.article(2, enriched=False)])
                payload = json.loads(json.loads(request.call_args.args[0].data)['input'])
                self.assertEqual({row['id'] for row in payload}, {old['id'], retry['id']})
                by_id = {row['id']: row for row in rows}
                self.assertEqual(by_id[old['id']][field], value)
                self.assertEqual(by_id[old['id']]['summaryJa'], '更新された概要')
                self.assertTrue(by_id[old['id']]['enriched'])
                self.assertEqual(by_id[unchanged['id']], unchanged)
                self.assertTrue(by_id[retry['id']]['enriched'])

    def test_duplicate_collected_ids_prefer_higher_score(self):
        fresh = self.article(1, enriched=False)
        higher = {**fresh, 'source': 'Higher priority', 'score': 99}
        self.assertEqual(collector.merge_articles([], [fresh, higher]), [higher])

    def test_new_duplicate_title_does_not_replace_published_id(self):
        old = self.article(1)
        duplicate = self.article(2, enriched=False, title=old['title'], score=100)
        self.assertEqual(collector.merge_articles([old], [duplicate]), [old])

    def test_failed_translation_batch_does_not_block_other_batches(self):
        old = self.article(0)
        self.save_existing([old])
        changed = self.article(0, enriched=False, summary='Updated details')
        fresh = [self.article(i, enriched=False) for i in range(1, 7)]
        translated = [
            {'id': row['id'], 'titleJa': '翻訳済みの見出し', 'summaryJa': '翻訳済みの概要'}
            for row in fresh[-2:]
        ]
        with patch.object(collector.LLM_OPENER, 'open', side_effect=[
            OSError('First batch failed'), self.api_response(translated)
        ]) as request:
            saved = self.run_with_rows([changed, *fresh])
        by_id = {row['id']: row for row in saved}
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(saved), 7)
        self.assertEqual(by_id[old['id']], old)
        for row in fresh[:4]:
            self.assertEqual(by_id[row['id']], row)
        for row in fresh[-2:]:
            self.assertTrue(by_id[row['id']]['enriched'])
            self.assertEqual(by_id[row['id']]['summaryJa'], '翻訳済みの概要')

    def test_first_collection_still_deduplicates_and_selects(self):
        rows = [self.article(i, enriched=False) for i in range(60)]
        rows.append({**rows[0], 'id': 'duplicate-title', 'score': 1})
        with patch.dict(collector.os.environ, {}, clear=True):
            saved = self.run_with_rows(rows)
        self.assertEqual(len(saved), 44)
        self.assertEqual(len({row['id'] for row in saved}), 44)
        self.assertNotIn('duplicate-title', {row['id'] for row in saved})
        self.assertTrue(all(sum(row['source'] == source['source'] for row in saved) <= 7 for source in saved))


if __name__=='__main__': unittest.main()
