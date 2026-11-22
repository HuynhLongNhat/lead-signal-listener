"""In-process market research controller. Never calls paid APIs.

All status is transient; evidence/report is persisted in its own SQLite DB.
Runs on a worker thread so the web UI stays responsive.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from .core import MarketStore, import_listener_signals, run_web


class ResearchController:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "market_intelligence.db"
        self.listener_db = self.data_dir / "signals.db"
        self._lock = threading.Lock()
        self._state = {
            "running": False, "stage": "idle", "message": "Chưa chạy nghiên cứu",
            "started_at": None, "finished_at": None,
            "found": 0, "new_evidence": 0, "pain_matches": 0, "errors": []
        }

    def status(self):
        with self._lock:
            return dict(self._state, errors=list(self._state["errors"]))

    def report(self):
        store = MarketStore(self.db_path)
        try:
            return store.report(limit=200)
        finally:
            store.db.close()

    @staticmethod
    def validate(payload):
        if not isinstance(payload, dict):
            raise ValueError("Yêu cầu không hợp lệ")
        values = {}
        for field in ("industry", "region", "pain"):
            value = payload.get(field, "")
            if not isinstance(value, str) or len(value) > 120:
                raise ValueError(f"Trường {field} không hợp lệ (tối đa 120 ký tự)")
            values[field] = value.strip()
        if not values["industry"] or not values["region"]:
            raise ValueError("Cần nhập ngành và khu vực")
        for field in ("web", "listener", "extract"):
            if field in payload and not isinstance(payload[field], bool):
                raise ValueError(f"Trường {field} phải là true/false")
        values.update(
            web=payload.get("web", True),
            listener=payload.get("listener", True),
            extract=payload.get("extract", True)
        )
        if not values["web"] and not values["listener"]:
            raise ValueError("Phải chọn ít nhất một nguồn")
        return values

    @staticmethod
    def queries(config):
        scope = f'{config["industry"]} {config["region"]}'
        pain = config["pain"]
        if pain:
            return [f'{scope} "{pain}"', f'{scope} {pain} khó khăn']
        return [f'{scope} "khó khăn" OR "phàn nàn"',
                f'{scope} "không hài lòng" OR "vấn đề"']

    def _update(self, **fields):
        with self._lock:
            self._state.update(fields)

    def start(self, payload):
        cfg = self.validate(payload)
        with self._lock:
            if self._state["running"]:
                raise RuntimeError("Đang có nghiên cứu khác chạy")
            self._state = {
                "running": True, "stage": "queued", "message": "Đã tiếp nhận yêu cầu",
                "started_at": int(time.time()), "finished_at": None,
                "found": 0, "new_evidence": 0, "pain_matches": 0,
                "errors": [], "request": cfg
            }
            thread = threading.Thread(target=self._execute, args=(cfg,), daemon=True)
            thread.start()
        return self.status()

    def _execute(self, cfg):
        store = None
        counts = {"found": 0, "new_evidence": 0, "pain_matches": 0}
        errors = []
        try:
            store = MarketStore(self.db_path)
            if cfg["web"]:
                self._update(stage="web", message="Đang tìm web và trích xuất bài viết…")
                result = run_web(store,
                    searxng_url=os.environ.get("SEARXNG_URL", "http://127.0.0.1:8080"),
                    queries=self.queries(cfg), limit_per_query=8, enrich=cfg["extract"])
                for k in counts:
                    counts[k] += result.get(k, 0)
                errors.extend(result.get("errors") or [])
                self._update(**counts, errors=errors[:30])
            if cfg["listener"]:
                self._update(stage="listener", message="Đang đọc tín hiệu Lead Signal Listener…")
                if self.listener_db.is_file():
                    result = import_listener_signals(store, self.listener_db, limit=300)
                    for k in counts:
                        counts[k] += result.get(k, 0)
                    errors.extend(result.get("errors") or [])
                else:
                    errors.append("Chưa có signals.db; hãy chạy thu thập Lead Signal Listener trước")
                self._update(**counts, errors=errors[:30])
            self._update(stage="analysis", message="Đang tổng hợp nhóm nỗi đau và bằng chứng…")
            report = store.report()
            has_signal = bool(report.get("opportunities"))
            stage = "done" if not errors else ("partial" if has_signal else "failed")
            self._update(stage=stage,
                message=("Hoàn tất — xem báo cáo bên dưới" if stage == "done" else
                         "Có kết quả nhưng một số nguồn lỗi" if stage == "partial" else
                         "Chưa thu được dữ liệu phù hợp; xem lỗi cấu hình"),
                errors=errors[:30], **counts)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            self._update(stage="failed", message="Nghiên cứu thất bại", errors=errors[:30], **counts)
        finally:
            if store is not None:
                store.db.close()
            self._update(running=False, finished_at=int(time.time()))
