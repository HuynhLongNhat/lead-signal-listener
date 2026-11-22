"""Vietnamese pain and intent signals should be scored, without an LLM."""
import unittest

from listener.scoring import score_signal


class VietnameseScoringTests(unittest.TestCase):
    def test_vietnamese_pain_and_intent(self):
        score, persona, matched = score_signal({
            "title": "Chủ cửa hàng cần thuê người quản lý",
            "text": "Quá tải tin nhắn, không có đơn, cần dịch vụ hỗ trợ",
            "community": "",
            "kind": "pain",
            "engagement": 0,
        })
        self.assertGreaterEqual(score, 20)
        self.assertEqual(persona, "local_business")
        self.assertIn("quá tải tin nhắn", matched)
        self.assertIn("cần dịch vụ", matched)

    def test_self_promotion_penalized(self):
        score, _, matched = score_signal({
            "title": "Tôi nhận làm",
            "text": "Mình cung cấp dịch vụ thiết kế",
            "community": "",
            "kind": "pain",
            "engagement": 0,
        })
        self.assertEqual(score, 0)
        self.assertIn("nhận làm", matched)


if __name__ == "__main__":
    unittest.main()
