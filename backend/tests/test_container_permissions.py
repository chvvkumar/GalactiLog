"""
Container permissions / PUID-PGID integration tests.

These tests shell out to `docker compose exec` to introspect a running
container. They are gated behind GALACTILOG_TEST_LIVE_CONTAINER=1 so the
normal pytest run (which has no app container) skips them cleanly.

Run with:
    GALACTILOG_TEST_LIVE_CONTAINER=1 pytest backend/tests/test_container_permissions.py -v

For scenarios that require container rebuild/restart (PUID/PGID remap),
see backend/tests/container_perms.sh instead.
"""
import json
import os
import subprocess
import time

import pytest

LIVE = os.environ.get("GALACTILOG_TEST_LIVE_CONTAINER") == "1"

pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="Set GALACTILOG_TEST_LIVE_CONTAINER=1 to run live-container tests",
)


def _exec(cmd: str, check: bool = False, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a shell command inside the running app container."""
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "app", "sh", "-c", cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def _host(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="session")
def live_container():
    """Ensure the app container is up; skip the module if not."""
    result = _host(["docker", "compose", "ps", "--format", "json", "app"])
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip("app container is not running (docker compose up first)")

    # `docker compose ps --format json` emits either one JSON object or
    # newline-delimited objects depending on version. Parse defensively.
    raw = result.stdout.strip()
    try:
        if raw.startswith("["):
            entries = json.loads(raw)
        else:
            entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except json.JSONDecodeError:
        pytest.skip(f"could not parse docker compose ps output: {raw[:200]}")

    state = (entries[0].get("State") or "").lower() if entries else ""
    if "running" not in state:
        pytest.skip(f"app container state is {state!r}, not running")

    # Wait briefly for supervisord to fully spawn children.
    # python:3.12-slim doesn't ship procps, so use /proc walker instead of ps.
    proc_walk = r'''for pid in /proc/[0-9]*; do
    comm=$(cat "$pid/comm" 2>/dev/null || continue)
    echo "$comm"
done'''
    for _ in range(10):
        ps = _exec(proc_walk)
        if "supervisord" in ps.stdout and ("uvicorn" in ps.stdout or "nginx" in ps.stdout):
            break
        time.sleep(1)
    return True


def _proc_walk():
    """Walk /proc inside the container. Returns list of (pid, ppid, uid, comm)."""
    cmd = r'''for pid in /proc/[0-9]*; do
    p=${pid##*/}
    comm=$(cat "$pid/comm" 2>/dev/null || continue)
    uid=$(awk "/^Uid:/ {print \$2; exit}" "$pid/status" 2>/dev/null || echo "")
    ppid=$(awk "/^PPid:/ {print \$2; exit}" "$pid/status" 2>/dev/null || echo "")
    echo "$p $ppid $uid $comm"
done'''
    result = _exec(cmd)
    assert result.returncode == 0, result.stderr
    entries = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        pid, ppid, uid, comm = parts
        try:
            entries.append((int(pid), int(ppid), int(uid), comm.strip()))
        except ValueError:
            continue
    return entries


def test_galactilog_user_exists_with_expected_default_uid(live_container):
    """Default image should expose galactilog with uid/gid 1000 when PUID/PGID unset."""
    if os.environ.get("PUID") or os.environ.get("PGID"):
        pytest.skip("PUID/PGID overridden in environment; default-UID test not meaningful")

    result = _exec("id galactilog")
    assert result.returncode == 0, result.stderr
    assert "uid=1000" in result.stdout
    assert "gid=1000" in result.stdout


def test_processes_run_as_galactilog_user(live_container):
    """Service processes should run as galactilog (uid 1000 or PUID).

    Exceptions permitted:
      - supervisord master runs as root (needs to fork children with differing
        `user=` directives, open log fds, bind privileged ports).
      - nginx master runs as root per nginx.conf `user galactilog galactilog;`
        (workers drop to galactilog). The assertion requires that at least one
        nginx worker runs as galactilog.
    """
    expected_uid = int(os.environ.get("PUID") or "1000")

    entries = _proc_walk()
    assert entries, "no processes discovered via /proc walk"

    offenders = []
    nginx_uids: list[int] = []
    saw_supervisord = False

    for pid, ppid, uid, comm in entries:
        c = comm
        if c == "supervisord":
            saw_supervisord = True
            # supervisord may be root; that's fine.
            continue
        if c == "nginx":
            nginx_uids.append(uid)
            continue
        if any(k in c for k in ("uvicorn", "celery")):
            if uid != expected_uid:
                offenders.append((pid, uid, comm))

    assert not offenders, (
        f"processes not running as uid={expected_uid}: {offenders}"
    )

    if nginx_uids:
        assert any(u == expected_uid for u in nginx_uids), (
            f"no nginx process runs as uid={expected_uid}; all nginx uids: {nginx_uids}"
        )


def test_nginx_binds_port_80(live_container):
    """Nginx bound to :80 via setcap (no root). Hit it via the host."""
    # Use the host-side port mapping. docker-compose.yml exposes app on 8080
    # by default; try both.
    for url in ("http://localhost:8080/api/health", "http://localhost/api/health"):
        r = _host(["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}", url])
        if r.stdout.strip() == "200":
            return
    pytest.fail("neither :8080 nor :80 returned 200 for /api/health")


@pytest.mark.xfail(
    reason="PUID/PGID remap requires container restart; see backend/tests/container_perms.sh",
    strict=False,
)
def test_puid_pgid_remapping(live_container):
    pytest.xfail("Tested by backend/tests/container_perms.sh (restart-based)")


def test_run_dir_owned_by_galactilog(live_container):
    """/app/run and its contents must be owned by galactilog.

    Exception: artifacts owned by the supervisord master (which runs as root
    by design) will be root-owned: supervisor.sock, supervisord.pid. Skip
    any *.sock entries and the supervisord pidfile.
    """
    result = _exec(
        "stat -c '%n %U:%G' /app/run /app/run/* 2>/dev/null || stat -c '%n %U:%G' /app/run"
    )
    assert result.returncode == 0, result.stderr
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        name_part = line.rsplit(" ", 1)[0]
        basename = name_part.rsplit("/", 1)[-1]
        if basename.endswith(".sock") or basename == "supervisord.pid":
            continue
        owner = line.rsplit(" ", 1)[-1]
        user = owner.split(":")[0]
        assert user in ("galactilog", "galacti"), f"{line!r} not owned by galactilog"


def test_thumbnail_write_readable_by_nginx(live_container):
    """Regression test for issue #162: nginx must be able to serve thumbnails
    written by the backend. Write a tiny JPEG via docker exec, then fetch it
    through nginx from the host."""
    fname = "test_perms.jpg"
    # Smallest valid JPEG (1x1 pixel, ~125 bytes). Base64 decode in-container.
    b64 = (
        "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/"
        "2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDyyigUtf/Z"
    )
    _exec(f"rm -f /app/data/thumbnails/{fname}")
    write = _exec(
        f"echo '{b64}' | base64 -d > /app/data/thumbnails/{fname} && "
        f"stat -c '%U:%G %a' /app/data/thumbnails/{fname}"
    )
    assert write.returncode == 0, write.stderr

    try:
        # nginx config maps /thumbnails/ -> /app/data/thumbnails/
        for base in ("http://localhost:8080", "http://localhost"):
            r = _host(
                ["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}",
                 f"{base}/thumbnails/{fname}"]
            )
            if r.stdout.strip() == "200":
                return
        pytest.fail("nginx returned non-200 for newly-written thumbnail")
    finally:
        _exec(f"rm -f /app/data/thumbnails/{fname}")


def test_skip_chown_env_var_honored(live_container):
    """Documentation test: marker. Full validation is in container_perms.sh
    (scenario D) because it requires a restart with custom env.
    """
    pytest.skip("Requires container restart; covered by container_perms.sh scenario D")


def test_celerybeat_schedule_writable(live_container):
    """After startup, celery beat writes its schedule under /app/run.
    File must exist and be owned by galactilog."""
    # Give beat a moment to flush its schedule on fresh containers.
    for _ in range(10):
        r = _exec("ls /app/run/celerybeat-schedule* 2>/dev/null")
        if r.stdout.strip():
            break
        time.sleep(1)

    ls = _exec("ls /app/run/celerybeat-schedule* 2>/dev/null")
    assert ls.stdout.strip(), "celerybeat schedule file not created under /app/run/"

    stat = _exec("stat -c '%U:%G' /app/run/celerybeat-schedule* | head -1")
    assert stat.returncode == 0, stat.stderr
    owner = stat.stdout.strip().split(":")[0]
    assert owner in ("galactilog", "galacti"), f"celerybeat schedule owned by {owner}"
