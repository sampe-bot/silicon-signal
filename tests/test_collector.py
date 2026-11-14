"""Tests using local XML only; does not depend on network calls."""
import importlib.util
import io
import json
import pathlib
import unittest
from unittest.mock import patch

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
            'OPENAI_API_KEY': 'test-key',
            'OPENAI_BASE_URL': 'https://openrouter.ai/api/v1/',
            'OPENAI_MODEL': 'nvidia/nemotron-3.5-super-vl:free',
        }
        with patch.dict(collector.os.environ, env, clear=True), patch.object(
            collector, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())
        ) as request, patch('sys.stdout', new_callable=io.StringIO):
            collector.enrich_with_openai([row])
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, 'https://openrouter.ai/api/v1/responses')
        self.assertEqual(sent.get_header('Authorization'), 'Bearer test-key')
        self.assertEqual(json.loads(sent.data)['model'], env['OPENAI_MODEL'])
        self.assertEqual(json.loads(sent.data)['reasoning'], {'enabled': False})
        self.assertEqual(json.loads(sent.data)['max_output_tokens'], 8000)
        self.assertTrue(row['enriched'])
        self.assertEqual(row['titleJa'], '半導体ニュース')

    def test_enrichment_batches_and_openai_compatibility(self):
        for base_url in ('https://api.openai.com/v1', 'https://openrouter.ai/api/v1'):
            with self.subTest(base_url=base_url):
                rows = [{'id': str(i), 'title': 'Chip', 'summary': 'News', 'category': 'semiconductor'} for i in range(7)]
                def respond(request, timeout):
                    body = json.loads(request.data)
                    self.assertNotIn('reasoning', body)
                    items = json.loads(body['input'])
                    translated = [{'id': item['id'], 'titleJa': '半導体'} for item in items]
                    return io.BytesIO(json.dumps({'output': [{'content': [{'type': 'output_text', 'text': json.dumps(translated)}]}]}).encode())
                env = {'OPENAI_API_KEY': 'test-key', 'OPENAI_BASE_URL': base_url, 'OPENAI_MODEL': 'other-model'}
                with patch.dict(collector.os.environ, env, clear=True), patch.object(
                    collector, 'urlopen', side_effect=respond
                ) as request, patch('sys.stdout', new_callable=io.StringIO):
                    collector.enrich_with_openai(rows)
                self.assertEqual([len(json.loads(json.loads(call.args[0].data)['input'])) for call in request.call_args_list], [5, 2])
                self.assertTrue(all(row['enriched'] for row in rows))

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
                with patch.dict(collector.os.environ, {'OPENAI_API_KEY': 'test-key'}, clear=True), patch.object(
                    collector, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())
                ), patch.object(collector.time, 'sleep'), patch('sys.stderr', new_callable=io.StringIO) as errors:
                    collector.enrich_with_openai([row])
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

if __name__=='__main__': unittest.main()
