import unittest

from fastapi.middleware.cors import CORSMiddleware

from app.main import app


class CorsConfigTests(unittest.TestCase):
    def test_content_disposition_is_exposed_to_browser_clients(self) -> None:
        cors_middleware = next(
            middleware
            for middleware in app.user_middleware
            if middleware.cls is CORSMiddleware
        )

        self.assertIn(
            "Content-Disposition",
            cors_middleware.kwargs.get("expose_headers", []),
        )


if __name__ == "__main__":
    unittest.main()
