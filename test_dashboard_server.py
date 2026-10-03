import errno
import socket
import threading
import time
import urllib.request

from dashboard_server import serve_with_reuse


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_it_serves_state_on_a_free_port(tmp_path):
    import json
    (tmp_path / "s.json").write_text(json.dumps({"status": "running", "equity": 1005.0}))
    port = free_port()
    # Daemon thread: serve() never returns, so the test must not join it.
    threading.Thread(
        target=serve_with_reuse,
        args=(tmp_path / "s.json", "127.0.0.1", port),
        daemon=True,
    ).start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
                body = json.loads(r.read())
            break
        except OSError:
            time.sleep(0.2)
    else:
        raise AssertionError("server never came up")
    assert body["equity"] == 1005.0


def test_it_waits_out_a_busy_port(tmp_path):
    """A dying listener can still hold the socket for a moment on restart."""
    import json
    (tmp_path / "s.json").write_text(json.dumps({"status": "ok"}))
    port = free_port()

    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)

    def release():
        time.sleep(1.5)
        blocker.close()

    threading.Thread(target=release, daemon=True).start()

    # serve() blocks forever once bound, so it has to run off the main thread
    # and success is detected by the port answering, not by a return value.
    errors: list[Exception] = []

    def run():
        try:
            serve_with_reuse(tmp_path / "s.json", "127.0.0.1", port, attempts=10, delay=0.5)
        except Exception as exc:
            errors.append(exc)

    threading.Thread(target=run, daemon=True).start()

    deadline = time.time() + 20
    body = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
                body = json.loads(r.read())
            break
        except OSError:
            time.sleep(0.3)

    assert not errors, f"serve_with_reuse raised: {errors[0]}"
    assert body is not None, "never bound after the blocker released the port"
    assert body["status"] == "ok"


def test_it_gives_up_with_a_clear_error(tmp_path):
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    try:
        try:
            serve_with_reuse(tmp_path / "s.json", "127.0.0.1", port, attempts=2, delay=0.1)
        except RuntimeError as exc:
            assert str(port) in str(exc)
        else:
            raise AssertionError("expected RuntimeError on a permanently busy port")
    finally:
        blocker.close()


def test_a_permission_error_is_not_retried(tmp_path):
    # Port 1 is privileged, so binding must fail with EACCES, not EADDRINUSE.
    # Retrying that forever would just look like a hang.
    try:
        serve_with_reuse(tmp_path / "s.json", "127.0.0.1", 1, attempts=3, delay=0.1)
    except OSError as exc:
        assert exc.errno != errno.EADDRINUSE
    except RuntimeError:
        raise AssertionError("a privilege error must not be retried")