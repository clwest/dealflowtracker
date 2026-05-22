"""Tests for `brain_client.push_artifact` / `pull_artifact` (Move 2 Round 1).

Integration-style tests that mock `_http_request` at the boundary so we
never touch the network. Verifies:
- push_artifact sends a POST to /api/fleet/artifacts/ with the right
  body shape AND fleet_path arg (which triggers signing)
- pull_artifact sends a GET with the right fleet_path
- Both surface success / error response shapes cleanly to the caller
"""

from __future__ import annotations

import os
from unittest.mock import patch

# Set env defaults so the underlying ask() flow doesn't short-circuit
os.environ.setdefault("BRAIN_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_test_fleet_artifacts.db")

from app.brain_client import push_artifact, pull_artifact


class TestPushArtifact:
    def test_push_201_returns_id_and_sha256(self):
        captured = {}

        def fake_http(url, method, data=None, token=None, host_header=None,
                       fleet_path=None, fleet_query=""):
            captured["url"] = url
            captured["method"] = method
            captured["data"] = data
            captured["fleet_path"] = fleet_path
            return (
                {
                    "id": "abc-uuid",
                    "sha256": "f" * 64,
                    "size_bytes": 123,
                    "created_at": "2026-05-22T22:00:00Z",
                    "artifact_type": "contract_draft",
                },
                201,
            )

        with patch("app.brain_client._http_request", side_effect=fake_http):
            result = push_artifact(
                {"title": "NDA"},
                artifact_type="contract_draft",
                metadata={"tag": "test"},
            )

        assert result["ok"] is True
        assert result["id"] == "abc-uuid"
        assert result["sha256"] == "f" * 64
        # Sanity on the outbound shape
        assert captured["method"] == "POST"
        assert captured["url"].endswith("/api/fleet/artifacts/")
        assert captured["fleet_path"] == "/api/fleet/artifacts/"
        assert captured["data"] == {
            "artifact_type": "contract_draft",
            "payload": {"title": "NDA"},
            "metadata": {"tag": "test"},
        }

    def test_push_413_payload_too_large(self):
        def fake_http(url, method, data=None, token=None, host_header=None,
                       fleet_path=None, fleet_query=""):
            return (
                {
                    "error": {
                        "code": "payload_too_large",
                        "message": "payload 999999 bytes exceeds limit 512 KB",
                    }
                },
                413,
            )

        with patch("app.brain_client._http_request", side_effect=fake_http):
            result = push_artifact({"big": "x" * 999999}, artifact_type="huge")

        assert result["ok"] is False
        assert result["status_code"] == 413
        assert "exceeds limit" in result["error"]


class TestPullArtifact:
    def test_pull_200_returns_payload(self):
        captured = {}

        def fake_http(url, method, data=None, token=None, host_header=None,
                       fleet_path=None, fleet_query=""):
            captured["url"] = url
            captured["method"] = method
            captured["fleet_path"] = fleet_path
            return (
                {
                    "id": "abc-uuid",
                    "artifact_type": "contract_draft",
                    "payload": {"title": "NDA"},
                    "metadata": {"tag": "test"},
                    "sha256": "f" * 64,
                    "size_bytes": 123,
                    "created_at": "2026-05-22T22:00:00Z",
                    "created_by": {
                        "app_slug": "dealflowtracker",
                        "key_id": "fs_dealflowtracker_k1",
                        "request_id": "req-1",
                    },
                },
                200,
            )

        with patch("app.brain_client._http_request", side_effect=fake_http):
            result = pull_artifact("abc-uuid")

        assert result["ok"] is True
        assert result["artifact"]["payload"] == {"title": "NDA"}
        assert result["artifact"]["created_by"]["app_slug"] == "dealflowtracker"
        # Sanity on the outbound shape
        assert captured["method"] == "GET"
        assert captured["url"].endswith("/api/fleet/artifacts/abc-uuid/")
        assert captured["fleet_path"] == "/api/fleet/artifacts/abc-uuid/"

    def test_pull_404_treated_as_error(self):
        def fake_http(url, method, data=None, token=None, host_header=None,
                       fleet_path=None, fleet_query=""):
            return (
                {
                    "error": {
                        "code": "artifact_not_found",
                        "message": "no such artifact",
                    }
                },
                404,
            )

        with patch("app.brain_client._http_request", side_effect=fake_http):
            result = pull_artifact("phantom-uuid")

        assert result["ok"] is False
        assert result["status_code"] == 404
        assert "no such artifact" in result["error"]


class TestListArtifacts:
    """Move 2 Round 2 — list_artifacts() helper."""

    def test_list_200_returns_results(self):
        from app.brain_client import list_artifacts
        captured = {}

        def fake_http(url, method, data=None, token=None, host_header=None,
                       fleet_path=None, fleet_query=""):
            captured["url"] = url
            captured["method"] = method
            captured["fleet_path"] = fleet_path
            captured["fleet_query"] = fleet_query
            return (
                {
                    "count": 3,
                    "limit": 25,
                    "offset": 0,
                    "next_offset": None,
                    "results": [
                        {"id": "a", "artifact_type": "json", "sha256": "f"*64,
                         "size_bytes": 10, "created_at": "2026-05-22T00:00:00Z",
                         "expires_at": "2026-06-21T00:00:00Z",
                         "is_expired": False, "deleted_at": None, "metadata": {}},
                    ],
                },
                200,
            )

        with patch("app.brain_client._http_request", side_effect=fake_http):
            result = list_artifacts()

        assert result["ok"] is True
        assert result["count"] == 3
        assert len(result["results"]) == 1
        assert captured["method"] == "GET"
        assert captured["fleet_path"] == "/api/fleet/artifacts/"
        # No query params when defaults — limit/offset still go through
        assert "limit=25" in captured["fleet_query"]
        assert "offset=0" in captured["fleet_query"]

    def test_list_with_filters_passes_query(self):
        from app.brain_client import list_artifacts
        captured = {}

        def fake_http(url, method, data=None, token=None, host_header=None,
                       fleet_path=None, fleet_query=""):
            captured["fleet_query"] = fleet_query
            captured["url"] = url
            return ({"count": 0, "limit": 10, "offset": 0, "next_offset": None, "results": []}, 200)

        with patch("app.brain_client._http_request", side_effect=fake_http):
            list_artifacts(
                limit=10,
                offset=20,
                artifact_type="contract_draft",
                include_expired=True,
            )

        # All filters present in querystring
        q = captured["fleet_query"]
        assert "limit=10" in q
        assert "offset=20" in q
        assert "artifact_type=contract_draft" in q
        assert "include_expired=true" in q
        # URL also carries the query for the actual HTTP call
        assert "?" in captured["url"]

    def test_list_404_error_surfaced(self):
        from app.brain_client import list_artifacts

        def fake_http(url, method, data=None, token=None, host_header=None,
                       fleet_path=None, fleet_query=""):
            return ({"error": {"code": "x", "message": "boom"}}, 401)

        with patch("app.brain_client._http_request", side_effect=fake_http):
            result = list_artifacts()

        assert result["ok"] is False
        assert result["status_code"] == 401


class TestRoundTrip:
    """Mock both calls in sequence — pushes then pulls the same payload,
    asserts the round trip preserves the structure."""

    def test_round_trip_same_payload(self):
        original = {"title": "NDA", "parties": ["A", "B"]}
        artifact_id = "rt-uuid-1"
        # Storage for the fake server-side artifact
        store = {}

        def fake_http(url, method, data=None, token=None, host_header=None,
                       fleet_path=None, fleet_query=""):
            if method == "POST":
                store[artifact_id] = data["payload"]
                return (
                    {
                        "id": artifact_id,
                        "sha256": "f" * 64,
                        "size_bytes": 100,
                        "created_at": "2026-05-22T22:00:00Z",
                        "artifact_type": data["artifact_type"],
                    },
                    201,
                )
            # GET
            return (
                {
                    "id": artifact_id,
                    "payload": store[artifact_id],
                    "artifact_type": "test",
                    "metadata": {},
                    "sha256": "f" * 64,
                    "size_bytes": 100,
                    "created_at": "2026-05-22T22:00:00Z",
                    "created_by": {"app_slug": "dealflowtracker"},
                },
                200,
            )

        with patch("app.brain_client._http_request", side_effect=fake_http):
            push_result = push_artifact(original, artifact_type="test")
            assert push_result["ok"]
            pull_result = pull_artifact(push_result["id"])
            assert pull_result["ok"]
            assert pull_result["artifact"]["payload"] == original
