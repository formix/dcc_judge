"""Adventures load from a file path, a folder, an http(s) URL or a bundled id."""

import functools
import http.server
import shutil
import threading
from pathlib import Path

import pytest

from engine.adventure import AdventureError, load_adventure
from engine.game import Game
from engine.state import SaveStore

FILE = Path(__file__).resolve().parents[1] / "adventures" / "elders_secret" / "adventure.yaml"


def test_load_from_file_folder_and_id():
    assert load_adventure(str(FILE)).id == "elders_secret"
    assert load_adventure(str(FILE.parent)).id == "elders_secret"
    assert load_adventure("elders_secret").source == "elders_secret"
    assert load_adventure(str(FILE)).source == str(FILE)


def test_load_from_url(tmp_path):
    shutil.copy(FILE, tmp_path / "adventure.yaml")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/adventure.yaml"
        adventure = load_adventure(url)
        assert adventure.id == "elders_secret" and adventure.source == url
        with pytest.raises(AdventureError):
            load_adventure(f"http://127.0.0.1:{server.server_port}/missing.yaml")
    finally:
        server.shutdown()


def test_bad_sources_are_reported(tmp_path):
    with pytest.raises(AdventureError):
        load_adventure(str(tmp_path / "nope.yaml"))
    bad = tmp_path / "bad.yaml"
    bad.write_text("just: [unclosed")
    with pytest.raises(AdventureError):
        load_adventure(str(bad))


def test_new_and_resume_from_a_path(tmp_path):
    store = SaveStore(tmp_path)
    game, _ = Game.new(str(FILE), seed=4, store=store, log_dir=None)
    assert game.state.adventure_source == str(FILE)
    resumed = Game.load(str(FILE), store=store, log_dir=None)
    assert resumed.state.to_dict() == game.state.to_dict()
