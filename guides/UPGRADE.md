# Upgrading GalactiLog

## [version] Non-root container execution

Starting with this release, the container runs as a non-root `galactilog` user (UID/GID 1000 by default) instead of root. The in-container user is remapped at entrypoint time to match `PUID` and `PGID` environment variables, following the LinuxServer.io convention. This resolves cases where nginx, previously running as `www-data`, could not read bind-mounted thumbnail directories owned by a different host user (see issue #162).

Port 80 binding inside the container continues to work via file capabilities; no port change is required.

### What to expect on first boot

- The entrypoint checks ownership of `/app/data/thumbnails`. If it does not match the effective `PUID:PGID`, the entrypoint runs a recursive `chown` once.
- For large thumbnail directories, this one-time chown may add a noticeable delay to the first startup after upgrade.
- Subsequent restarts skip the chown when ownership already matches.
- The FITS mount at `/app/data/fits` is read-only and is never chowned.

### Action required

Most users: none. The default `PUID=1000` and `PGID=1000` match a typical Docker host where the directory was previously created by the root-owned container and is now accessible to UID 1000, or where the host user running Docker is UID 1000.

Verify after upgrade:

```bash
docker compose up -d
docker compose logs app | head -n 40
```

Confirm the web UI loads and thumbnails display. A 403 on `/thumbnails/...` or `/preview/...` indicates the container user cannot read the files; see the [Install Guide](INSTALL.md#running-as-non-root) and the [Configuration Guide](CONFIGURATION.md#permissions-and-ownership) for remediation.

### If you run on TrueNAS, Unraid, Synology, or Kubernetes

Set `PUID` and `PGID` in the app service's `environment:` block to match the existing host owner of the thumbnails bind mount:

- TrueNAS SCALE: `PUID=568`, `PGID=568` (the `apps` user).
- Unraid: `PUID=99`, `PGID=100` (the `nobody` user).
- Synology DSM: use `id <username>` via SSH to find the owner of the shared folder, then set `PUID` and `PGID` accordingly.
- Kubernetes: set `securityContext.runAsUser` and `runAsGroup` on the pod, or pass `PUID`/`PGID` via `env`. Ensure the `PersistentVolume` permissions allow that UID to write to the thumbnails path.

Alternative: pre-chown the thumbnails directory on the host to the desired UID/GID and set `GALACTILOG_SKIP_CHOWN=1` to opt out of the entrypoint chown:

```bash
sudo chown -R 568:568 /mnt/tank/apps/galactilog/thumbnails
```

```yaml
environment:
  - PUID=568
  - PGID=568
  - GALACTILOG_SKIP_CHOWN=1
```

### Rollback

To revert to a previous image, pin the older tag in `docker-compose.yml`:

```yaml
image: chvvkumar/galactilog:<previous-version>
```

The older image runs as root and writes thumbnails as UID/GID 0. If the entrypoint chowned your host directory to 1000 (or to `PUID:PGID`) during the upgrade, the previous image will still function because root can read and write any ownership. However, if you later return to the non-root image or access the files from another host account, you may want to chown the directory back to its prior owner:

```bash
sudo chown -R <prior-uid>:<prior-gid> /path/to/thumbnails
```

Named Docker volumes are unaffected; ownership inside a Docker-managed volume is preserved across image changes.
