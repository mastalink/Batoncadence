"""Tests for the BatonCadence Console route and loader."""

from fastapi.testclient import TestClient

from mco.cli import create_app
from mco.console import get_console_html


def test_get_console_html_reads_package_data():
    html = get_console_html()
    assert "<!DOCTYPE html>" in html or "<!doctype html>" in html.lower()
    assert "BatonCadence" in html


def test_console_route_serves_page():
    http = TestClient(create_app())
    resp = http.get("/console")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "BatonCadence" in resp.text


def test_console_route_requires_no_auth_like_dashboard():
    """The page itself is public; every API call it makes carries the bearer
    token the operator pastes (same model as /dashboard)."""
    http = TestClient(create_app())
    assert http.get("/console").status_code == 200
    assert http.get("/dashboard").status_code == 200
