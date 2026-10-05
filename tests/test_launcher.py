import json
import urllib.request

from flextri import launcher, paths


def test_self_test_passes():
    assert launcher.self_test() == 0


def test_second_launch_finds_the_running_app_and_quit_stops_it():
    desk = launcher.Desktop(launcher._any_free_port())
    desk.start()
    try:
        launcher._running_file().write_text(json.dumps({"port": desk.server.config.port}))
        assert launcher._already_running() == desk.url
        with urllib.request.urlopen(desk.url + "/", timeout=5) as r:
            assert 'action="/app/quit"' in r.read().decode()
        req = urllib.request.Request(desk.url + "/app/quit", method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            assert "flexTri has stopped" in r.read().decode()
        desk.thread.join(5)
        assert not desk.thread.is_alive()
    finally:
        desk.stop()


def test_nothing_running():
    paths.data_dir()
    assert launcher._already_running() is None
