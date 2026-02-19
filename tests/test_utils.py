import unittest

from src.utils import validate_url_not_private


class TestValidateUrlNotPrivate(unittest.TestCase):
    def test_blocks_localhost(self) -> None:
        with self.assertRaises(ValueError):
            validate_url_not_private("http://localhost/secret")

    def test_blocks_127_0_0_1(self) -> None:
        with self.assertRaises(ValueError):
            validate_url_not_private("http://127.0.0.1/secret")

    def test_blocks_ipv6_loopback(self) -> None:
        with self.assertRaises(ValueError):
            validate_url_not_private("http://[::1]/secret")

    def test_blocks_zero_address(self) -> None:
        with self.assertRaises(ValueError):
            validate_url_not_private("http://0.0.0.0/secret")

    def test_blocks_private_ip_10(self) -> None:
        with self.assertRaises(ValueError):
            validate_url_not_private("http://10.0.0.1/secret")

    def test_blocks_private_ip_192_168(self) -> None:
        with self.assertRaises(ValueError):
            validate_url_not_private("http://192.168.1.1/secret")

    def test_blocks_link_local(self) -> None:
        with self.assertRaises(ValueError):
            validate_url_not_private("http://169.254.169.254/latest/meta-data/")

    def test_allows_public_url(self) -> None:
        validate_url_not_private("https://example.com/page")

    def test_allows_public_hostname(self) -> None:
        validate_url_not_private("https://irbank.net/1234/ir")

    def test_blocks_empty_host(self) -> None:
        with self.assertRaises(ValueError):
            validate_url_not_private("file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
