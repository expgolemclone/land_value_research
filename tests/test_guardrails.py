import unittest

from src.anomaly import should_accept_web_address


class GuardrailTests(unittest.TestCase):
    def test_aggregate_site_disables_web_address(self) -> None:
        self.assertFalse(should_accept_web_address("本社他", 100))

    def test_web_address_score_boundary(self) -> None:
        self.assertFalse(should_accept_web_address("本社", 39))
        self.assertTrue(should_accept_web_address("本社", 40))


if __name__ == "__main__":
    unittest.main()
