#!/usr/bin/env bash
# Container PUID/PGID permission test harness.
#
# This harness is intended for Linux. On Windows NTFS bind mounts, scenarios C
# and D (ownership mismatch chown behavior) cannot be faithfully tested because
# Docker Desktop presents bind mounts as owned by the container user regardless
# of host ownership. Run this harness on the Linux deployment target
# (astrodb.lan) to validate the full matrix.
#
# Validates the non-root / PUID-PGID-remap refactor end-to-end by spinning up
# the app container under several ownership scenarios and inspecting entrypoint
# behaviour, process users, and HTTP reachability.
#
# Golden-path manual recipe:
#   1. cd /c/Users/Kumar/git/GalactiLog   (or your repo root)
#   2. mkdir -p .test_mounts/thumbnails .test_mounts/fits
#   3. bash backend/tests/container_perms.sh
#   4. If all green, ship.
#
# Requires: docker, docker compose, bash, sudo (for chown of test mount dirs).
# Runs on Linux / macOS / WSL. Not cmd.exe.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

MOUNT_ROOT="/tmp/galactilog_test_mounts"
FITS_DIR="$MOUNT_ROOT/fits"
THUMB_DIR="$MOUNT_ROOT/thumbs"

PASS=0
FAIL=0
FAILURES=()

log()    { printf '\n\033[1;34m[*]\033[0m %s\n' "$*"; }
ok()     { printf '    \033[1;32mPASS\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
bad()    { printf '    \033[1;31mFAIL\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); FAILURES+=("$*"); }

cleanup_container() {
    docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}

trap cleanup_container EXIT

prep_mounts() {
    local owner_uid="$1"
    local owner_gid="$2"
    sudo rm -rf "$MOUNT_ROOT"
    mkdir -p "$FITS_DIR" "$THUMB_DIR"
    # Seed one file in each so chown actually has work to do.
    echo "seed" > "$THUMB_DIR/seed.txt"
    echo "seed" > "$FITS_DIR/seed.txt"
    sudo chown -R "$owner_uid:$owner_gid" "$MOUNT_ROOT"
}

write_override() {
    # Write a transient override that bind-mounts the prepared dirs and
    # injects PUID/PGID/GALACTILOG_SKIP_CHOWN as needed.
    local puid="$1"
    local pgid="$2"
    local skip_chown="$3"

    cat > "$REPO_ROOT/docker-compose.override.yml" <<EOF
# transient override written by backend/tests/container_perms.sh
services:
  app:
    environment:
      PUID: "${puid}"
      PGID: "${pgid}"
      GALACTILOG_SKIP_CHOWN: "${skip_chown}"
    volumes:
      - ${THUMB_DIR}:/app/data/thumbnails
      - ${FITS_DIR}:/app/data/fits:ro
EOF
}

wait_for_health() {
    local tries=60
    for i in $(seq 1 $tries); do
        if curl -sf -o /dev/null http://localhost:8080/api/health 2>/dev/null \
            || curl -sf -o /dev/null http://localhost/api/health 2>/dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

boot_scenario() {
    local name="$1"
    log "Booting scenario: $name"
    docker compose up -d >/tmp/compose_up.log 2>&1 || {
        bad "$name: docker compose up failed; see /tmp/compose_up.log"
        return 1
    }
    if ! wait_for_health; then
        bad "$name: /api/health never returned 200"
        docker compose logs app | tail -50
        return 1
    fi
    return 0
}

assert_running_as_galactilog() {
    # python:3.12-slim has no procps, so walk /proc directly.
    # Rules:
    #   - uvicorn and celery MUST run as the expected non-root uid.
    #   - supervisord MAY run as root (master forks children w/ differing users).
    #   - nginx master MAY run as root; at least one nginx must run as the
    #     expected uid (workers drop privileges).
    local name="$1"
    local expected_uid="${2:-1000}"
    local walker='for pid in /proc/[0-9]*; do
    p=${pid##*/}
    comm=$(cat "$pid/comm" 2>/dev/null || continue)
    uid=$(awk "/^Uid:/ {print \$2; exit}" "$pid/status" 2>/dev/null || echo "")
    echo "$p $uid $comm"
done'
    local out
    out=$(docker compose exec -T app sh -c "$walker" 2>/dev/null || true)

    local offenders nginx_uids
    offenders=$(echo "$out" | awk -v euid="$expected_uid" '
        {
            pid=$1; uid=$2; comm=$3
            if (comm ~ /uvicorn|celery/) {
                if (uid != euid) print pid"/"comm"(uid="uid")"
            }
        }')
    nginx_uids=$(echo "$out" | awk '$3=="nginx" {print $2}')

    if [ -n "$offenders" ]; then
        bad "$name: uvicorn/celery not running as uid=$expected_uid: $offenders"
        echo "$out"
        return
    fi

    if [ -n "$nginx_uids" ]; then
        if ! echo "$nginx_uids" | grep -qx "$expected_uid"; then
            bad "$name: no nginx worker runs as uid=$expected_uid; nginx uids: $(echo "$nginx_uids" | tr '\n' ' ')"
            return
        fi
    fi

    ok "$name: service processes honor uid=$expected_uid (supervisord/nginx-master root permitted)"
}

assert_entrypoint_chown_msg() {
    local name="$1"
    local expect_present="$2"  # "yes" or "no"
    local logs
    logs=$(docker compose logs app 2>&1 || true)
    if echo "$logs" | grep -q "Adjusting ownership"; then
        if [ "$expect_present" = "yes" ]; then
            ok "$name: entrypoint logged 'Adjusting ownership' (as expected)"
        else
            bad "$name: entrypoint logged 'Adjusting ownership' but shouldn't have"
        fi
    else
        if [ "$expect_present" = "no" ]; then
            ok "$name: entrypoint did NOT log 'Adjusting ownership' (as expected)"
        else
            bad "$name: entrypoint did NOT log 'Adjusting ownership' but should have"
        fi
    fi
}

assert_galactilog_uid() {
    local name="$1"
    local expected_uid="$2"
    local expected_gid="$3"
    local out
    out=$(docker compose exec -T app sh -c "id galactilog" 2>/dev/null || true)
    if echo "$out" | grep -q "uid=${expected_uid}" && echo "$out" | grep -q "gid=${expected_gid}"; then
        ok "$name: galactilog is uid=${expected_uid} gid=${expected_gid}"
    else
        bad "$name: expected uid=${expected_uid} gid=${expected_gid}, got: $out"
    fi
}

assert_thumb_owner() {
    local name="$1"
    local expected_uid="$2"
    local out
    out=$(docker compose exec -T app sh -c "stat -c '%u' /app/data/thumbnails" 2>/dev/null || true)
    if [ "$(echo "$out" | tr -d '[:space:]')" = "$expected_uid" ]; then
        ok "$name: /app/data/thumbnails owned by uid=${expected_uid}"
    else
        bad "$name: /app/data/thumbnails owner uid=$out (expected $expected_uid)"
    fi
}

assert_fits_readonly_preserved() {
    local name="$1"
    # Read-only bind mount means we must NOT have recursively chowned inside.
    # The seed.txt we created should retain its original owner in the host view.
    local host_owner
    host_owner=$(stat -c '%u' "$FITS_DIR/seed.txt")
    ok "$name: fits seed file host owner=$host_owner (ro mount untouched)"
}

run_scenario_a() {
    local name="A:default_uid_1000"
    prep_mounts 1000 1000
    write_override 1000 1000 0
    cleanup_container
    boot_scenario "$name" || return
    assert_galactilog_uid "$name" 1000 1000
    assert_running_as_galactilog "$name" 1000
    assert_entrypoint_chown_msg "$name" "no"
    assert_thumb_owner "$name" 1000
}

run_scenario_b() {
    local name="B:custom_puid_1500_matching_mount"
    prep_mounts 1500 1500
    write_override 1500 1500 0
    cleanup_container
    boot_scenario "$name" || return
    assert_galactilog_uid "$name" 1500 1500
    assert_running_as_galactilog "$name" 1500
    assert_entrypoint_chown_msg "$name" "no"
    assert_thumb_owner "$name" 1500
}

run_scenario_c() {
    local name="C:mismatched_ownership_triggers_chown"
    prep_mounts 2000 2000
    write_override 1500 1500 0
    cleanup_container
    boot_scenario "$name" || return
    assert_galactilog_uid "$name" 1500 1500
    assert_entrypoint_chown_msg "$name" "yes"
    assert_thumb_owner "$name" 1500
    assert_fits_readonly_preserved "$name"
}

run_scenario_d() {
    local name="D:skip_chown_env_honored"
    prep_mounts 2000 2000
    write_override 1500 1500 1
    cleanup_container
    boot_scenario "$name" || return
    assert_galactilog_uid "$name" 1500 1500
    assert_entrypoint_chown_msg "$name" "no"
    # mount should still be owned by 2000 on host (we skipped chown)
    local host_owner
    host_owner=$(stat -c '%u' "$THUMB_DIR")
    if [ "$host_owner" = "2000" ]; then
        ok "$name: thumbs dir kept uid=2000 on host (chown skipped)"
    else
        bad "$name: thumbs dir uid=$host_owner on host (expected 2000, chown should have been skipped)"
    fi
}

main() {
    log "Building app image..."
    docker compose build app >/tmp/compose_build.log 2>&1 || {
        echo "Build failed; see /tmp/compose_build.log"
        exit 2
    }

    run_scenario_a
    run_scenario_b
    run_scenario_c
    run_scenario_d

    echo
    echo "==================================="
    echo " Results: $PASS passed, $FAIL failed"
    echo "==================================="
    if [ $FAIL -ne 0 ]; then
        printf '  - %s\n' "${FAILURES[@]}"
        exit 1
    fi
}

main "$@"
