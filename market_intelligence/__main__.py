"""Run Market Intelligence independently before connecting it to HADES."""
import argparse
import json
import os
from pathlib import Path

from .core import MarketStore, import_listener_signals, run_web


def main():
    parser = argparse.ArgumentParser(description='HADES Market Intelligence — independent experiment')
    parser.add_argument('--db', default='data/market_intelligence.db', help='SQLite database file')
    sub = parser.add_subparsers(dest='command', required=True)
    web = sub.add_parser('web', help='Search SearXNG and extract articles via Trafilatura')
    web.add_argument('--query', action='append', required=True, help='Repeat for multiple queries')
    web.add_argument('--searxng-url', default=os.environ.get('SEARXNG_URL', 'http://127.0.0.1:8080'))
    web.add_argument('--limit', type=int, default=10)
    web.add_argument('--no-extract', action='store_true', help='Use search snippets only')
    listener = sub.add_parser('listener', help='Import existing Lead Signal Listener results')
    listener.add_argument('--listener-db', default='data/signals.db')
    listener.add_argument('--min-score', type=int, default=10)
    listener.add_argument('--limit', type=int, default=500)
    report = sub.add_parser('report', help='Read evidence-backed opportunity hypotheses')
    report.add_argument('--min-score', type=int, default=30)
    args = parser.parse_args()
    db = MarketStore(args.db)
    if args.command == 'web':
        result = run_web(db, searxng_url=args.searxng_url, queries=args.query,
                         limit_per_query=args.limit, enrich=not args.no_extract)
    elif args.command == 'listener':
        result = import_listener_signals(db, Path(args.listener_db),
                                         limit=args.limit, min_score=args.min_score)
    else:
        result = db.report(min_score=args.min_score)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
