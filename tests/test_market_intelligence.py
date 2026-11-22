"""Offline functional tests — no network, tokens, or paid services."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from market_intelligence.core import (Evidence, MarketStore, canonical_url,
    detect, import_listener_signals, normalize_result, run_web, search_searxng)


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MarketStore(Path(self.temp.name) / 'market.db')

    def test_vietnamese_pain_evidence(self):
        result = detect('Chủ quán bị quá tải tin nhắn, cần thuê người hỗ trợ')
        self.assertEqual(result[0]['category'], 'customer_support')
        self.assertIn('quá tải tin nhắn', result[0]['matched'])
        self.assertIn('cần thuê', result[0]['intent_terms'])

    def test_promotion_is_penalized(self):
        result = detect('Chúng tôi cung cấp giải pháp cho cửa hàng ít khách')
        self.assertLess(result[0]['signal_score'], 40)

    def test_evidence_is_deduplicated(self):
        evidence = Evidence('https://example.org/post', 'web', 'Khó tìm khách',
                            'Không có khách', 'quán cafe')
        self.assertTrue(self.store.put(evidence))
        self.assertFalse(self.store.put(evidence))
        self.store.analyze(evidence)
        report = self.store.report()
        self.assertEqual(report['total_evidence'], 1)
        self.assertEqual(report['status'], 'hypotheses_not_verified_buyers')
        self.assertEqual(report['opportunities'][0]['evidence'][0]['url'], evidence.url)

    def test_web_pipeline_with_fake_searxng(self):
        def mock_fetch(url, *, check_host=True):
            self.assertFalse(check_host)  # local SearXNG endpoint
            return json.dumps({'results': [
                {'url': 'https://example.org/1?utm_source=test',
                 'title': 'Cửa hàng khó tìm khách', 'content': 'Không ra đơn'},
                {'url': 'https://example.org/1',
                 'title': 'Cửa hàng khó tìm khách', 'content': 'Không ra đơn'},
            ]}).encode()
        result = run_web(self.store, searxng_url='http://127.0.0.1:8080',
                         queries=['doanh nghiệp khó tìm khách'], enrich=False, fetch=mock_fetch)
        self.assertEqual(result['found'], 2)
        self.assertEqual(result['new_evidence'], 1)
        self.assertGreaterEqual(result['pain_matches'], 1)
        self.assertEqual(result['report']['total_evidence'], 1)

    def test_listener_import_reads_real_schema_without_modifying_it(self):
        listener_path = Path(self.temp.name) / 'signals.db'
        conn = sqlite3.connect(listener_path)
        conn.execute('''CREATE TABLE signals (source TEXT, title TEXT, text TEXT,
            url TEXT, query TEXT, first_seen INTEGER, score INTEGER)''')
        conn.execute('INSERT INTO signals VALUES(?,?,?,?,?,?,?)',
                     ('facebook', 'Khách phản ánh', 'Quá tải tin nhắn, bỏ sót tin nhắn',
                      'https://example.org/feedback', 'chăm sóc khách', 100, 85))
        conn.commit()
        conn.close()
        result = import_listener_signals(self.store, listener_path)
        self.assertEqual(result['new_evidence'], 1)
        self.assertGreater(result['pain_matches'], 0)
        result2 = import_listener_signals(self.store, listener_path)
        self.assertEqual(result2['new_evidence'], 0)

    def test_private_host_rejected(self):
        with self.assertRaises(ValueError):
            canonical_url('file:///etc/passwd')
        with self.assertRaises(ValueError):
            canonical_url('http://localhost/secrets')

    def test_no_nonlocal_searxng(self):
        with self.assertRaises(ValueError):
            search_searxng('https://example.org', 'test')


if __name__ == '__main__':
    unittest.main()
