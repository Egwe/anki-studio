"""Tests for the request size limits (AS-033)."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from anki_studio.limits import UPLOAD_LIMIT, BodyLimitMiddleware


async def echo(request: Request) -> PlainTextResponse:
    """Return the size of the received body.

    Args:
        request: Incoming request.

    Returns:
        The number of body bytes as text.
    """
    return PlainTextResponse(str(len(await request.body())))


def make_client() -> TestClient:
    """Build a tiny app with a 10-byte limit on ``/upload`` and 5 elsewhere.

    Returns:
        A test client for the app.
    """
    app = Starlette(
        routes=[
            Route("/upload", echo, methods=["POST", "GET"]),
            Route("/other", echo, methods=["POST"]),
        ]
    )
    return TestClient(BodyLimitMiddleware(app, limits={"/upload": 10}, default=5))


def test_requests_within_limit_pass() -> None:
    """Bodies up to the limit of their path reach the app."""
    client = make_client()

    assert client.post("/upload", content=b"x" * 10).text == "10"
    assert client.post("/other", content=b"x" * 5).text == "5"
    assert client.get("/upload").status_code == 200


def test_oversized_requests_get_413() -> None:
    """Bodies above the limit are refused before the app reads them."""
    client = make_client()

    assert client.post("/upload", content=b"x" * 11).status_code == 413
    assert client.post("/other", content=b"x" * 6).status_code == 413


def test_missing_length_gets_411() -> None:
    """A POST without ``Content-Length`` is refused."""
    client = make_client()

    def chunks():
        """Yield the body in pieces, which makes httpx send it chunked.

        Yields:
            Two small byte strings.
        """
        yield b"ab"
        yield b"cd"

    assert client.post("/upload", content=chunks()).status_code == 411


def test_upload_limit_covers_ten_documents_and_a_package() -> None:
    """The generate form may carry ten documents plus one APKG."""
    assert UPLOAD_LIMIT > 10 * 100 * 2**20 + 512 * 2**20
