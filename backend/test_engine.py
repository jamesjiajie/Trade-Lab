import unittest
from datetime import date, timedelta

from engine import Bar, replay, validate_bars


class ReplayTest(unittest.TestCase):
    def setUp(self):
        first = date(2026, 1, 1)
        self.bars = [Bar((first + timedelta(days=day)).isoformat(), 10 + day, 11 + day, 9 + day, 10 + day, 1000) for day in range(23)]

    def test_decision_executes_next_open_and_is_repeatable(self):
        validate_bars(self.bars)
        decision_day = self.bars[19].date
        early = replay(self.bars, 19, {decision_day: "BUY"}, 0, 0)
        later = replay(self.bars, 20, {decision_day: "BUY"}, 0, 0)
        self.assertEqual(early["accounts"]["manual"]["trades"], [])
        self.assertEqual(later["accounts"]["manual"]["trades"][0]["date"], self.bars[20].date)
        self.assertGreaterEqual(later["accounts"]["manual"]["cash"], 0)
        self.assertEqual(later, replay(self.bars, 20, {decision_day: "BUY"}, 0, 0))


if __name__ == "__main__":
    unittest.main()
