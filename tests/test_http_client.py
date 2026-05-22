import unittest
from unittest.mock import Mock, patch

from app.utils.http.client import HttpClient


class TestHttpClient(unittest.TestCase):
    def test_merges_default_headers_for_qiumibao_domain(self) -> None:
        client = HttpClient()
        client._session.get = Mock()
        response = Mock()
        response.raise_for_status.return_value = None
        response.text = "ok"
        client._session.get.return_value = response

        client.get_text("https://dingshi2.qiumibao.com/demo.json")

        headers = client._session.get.call_args.kwargs["headers"]
        self.assertEqual(headers["origin"], "https://www.qiumibao.com")
        self.assertEqual(headers["referer"], "https://www.qiumibao.com/")
        self.assertIn("Mozilla/5.0", headers["user-agent"])

    def test_custom_headers_override_default_headers(self) -> None:
        client = HttpClient()
        client._session.get = Mock()
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}
        client._session.get.return_value = response

        client.get_json(
            "https://data.zhibo8.cc/manage/public/app.php",
            headers={"referer": "https://custom.example/", "x-test": "1"},
        )

        headers = client._session.get.call_args.kwargs["headers"]
        self.assertEqual(headers["origin"], "https://data.zhibo8.cc")
        self.assertEqual(headers["referer"], "https://custom.example/")
        self.assertEqual(headers["x-test"], "1")

    def test_uses_configured_proxies(self) -> None:
        with patch("app.utils.http.client.settings.CRAWLER_HTTP_PROXY", "http://127.0.0.1:8888"), patch(
            "app.utils.http.client.settings.CRAWLER_HTTPS_PROXY",
            "http://127.0.0.1:8888",
        ):
            client = HttpClient()
            client._session.get = Mock()
            response = Mock()
            response.raise_for_status.return_value = None
            response.text = "ok"
            client._session.get.return_value = response

            client.get_text("https://dingshi2.qiumibao.com/demo.json")

        proxies = client._session.get.call_args.kwargs["proxies"]
        self.assertEqual(proxies, {"http": "http://127.0.0.1:8888", "https": "http://127.0.0.1:8888"})


if __name__ == "__main__":
    unittest.main()
