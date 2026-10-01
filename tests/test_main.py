from fastapi.testclient import TestClient

import app.main as main
from app.main import create_app


def test_index_is_a_vietnamese_html_page(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<html lang="vi">' in response.text
    assert "AI Văn Phòng · Video Agent" in response.text


def test_startup_creates_the_sqlite_database(settings):
    with TestClient(create_app(settings)):
        assert (settings.data_dir / "app.db").exists()


def test_static_css_is_served(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "#F4F2EC" in response.text


def test_missing_ffmpeg_shows_a_banner_but_the_app_still_starts(settings):
    settings.config.assembler.ffmpeg_path = "no-such-ffmpeg-binary-xyz"

    with TestClient(create_app(settings)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'class="banner-warn"' in response.text
    assert "Không chạy được ffmpeg" in response.text


def test_no_banner_when_ffmpeg_is_available(settings, monkeypatch):
    monkeypatch.setattr(main, "check_binaries", lambda cfg: {"ffmpeg": "x", "ffprobe": "x"})

    with TestClient(create_app(settings)) as client:
        response = client.get("/")

    assert 'class="banner-warn"' not in response.text
