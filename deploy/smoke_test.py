#!/usr/bin/env python3
"""Verify the deployed HTTP boundary with public, synthetic test questions."""
import argparse
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8088")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    def request(path, body=None, follow_redirects=True):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = Request(base + path, data=data, headers=headers)
        try:
            opener = urlopen if follow_redirects else build_opener(NoRedirect()).open
            response = opener(req, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    html = b""
    for path in ("/", "/ask", "/professional", "/topics"):
        code, headers, body = request(path)
        assert code == 200 and "text/html" in headers.get("Content-Type", ""), (path, code)
        assert headers.get("Cache-Control") == "no-store", path
        assert headers.get("X-Content-Type-Options") == "nosniff", path
        html = body
    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html.decode())
    assert assets, "No production assets found"
    for path in assets:
        code, headers, body = request(path)
        assert code == 200 and body, (path, code)
        assert "immutable" in headers.get("Cache-Control", ""), path

    code, _, body = request("/health/ready")
    assert code == 200 and json.loads(body)["status"] == "ready"
    code, headers, body = request("/api/v1/topics")
    assert code == 200 and len(json.loads(body)["topics"]) == 5
    assert headers.get("Cache-Control") == "no-store"
    code, headers, body = request("/api/v1/queries", {
        "question": "降压药应早上服用还是睡前服用？", "audience": "public",
    })
    answer = json.loads(body)
    assert code == 200 and answer["status"] == "answered"
    assert answer["online_search"] is False and answer["generation_method"] == "extractive"
    sources = {source["id"] for source in answer["sources"]}
    assert sources and answer["answer"]["claims"]
    assert all(claim["citations"] and set(claim["citations"]) <= sources for claim in answer["answer"]["claims"])
    assert headers.get("Cache-Control") == "no-store"

    code, _, body = request("/api/v1/queries", {
        "question": "病历号 PRIVATE1234，成人高血压用药证据", "audience": "public",
    })
    assert code == 200 and json.loads(body)["status"] == "refused"
    assert b"PRIVATE1234" not in body
    code, _, _ = request("/api/v1/queries", {"question": "x" * 65537, "audience": "public"})
    assert code == 413, code

    for path, payload, expected in (
        ("/api/not-a-real-endpoint", None, 404),
        ("/assets/not-a-real-asset.js", None, 404),
        ("/", {}, 405),
    ):
        code, headers, body = request(path, payload)
        assert code == expected, (path, code)
        assert headers.get("Cache-Control") == "no-store", path
        if path.startswith("/api/"):
            assert "application/json" in headers.get("Content-Type", ""), path

    if urlsplit(base).scheme == "https":
        for path, payload in (
            ("/health/ready/", None),
            ("/api/v1/topics/", None),
            ("/api/v1/queries/", {"question": "成人高血压证据", "audience": "public"}),
        ):
            code, headers, _ = request(path, payload, follow_redirects=False)
            target = urlsplit(headers.get("Location", ""))
            assert code == 307 and target.scheme == "https", (path, code, target.scheme)
            assert target.netloc == urlsplit(base).netloc, (path, target.netloc)

    print("PASS: SPA routes, assets/cache, API/health, real cited answer, privacy refusal, body limit and unknown routes")


if __name__ == "__main__":
    main()
