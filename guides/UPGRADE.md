# Upgrading GalactiLog

## [version] Per-rig PHD2 timezone and site

This release gives each PHD2 equipment profile its own timezone, latitude and longitude, so a rig at a remote site is no longer read under the one global observer timezone. See the [Configuration Guide](CONFIGURATION.md#per-rig-phd2-profile-settings) for the fields themselves.

### What happens on first start

Two things run automatically. Neither needs an action.

1. The stored PHD2 profile map is rewritten from the old profile-to-telescope form into the richer per-profile form that holds a telescope, a timezone and a pair of coordinates. This is a settings rewrite only. Every upgraded profile keeps its telescope and starts with an empty timezone and empty coordinates, which mean "inherit the global values", which is exactly what the install already did. No stored instant moves and no guiding value changes as a result of the rewrite.

2. A one-time forced re-parse of every catalogued guide log is queued. The guide-log parser changed in the same release: it now reads the ASIAIR banner, the mount pointing fields and the `Calibration step = ` line prefix. Logs already stored under the old parser are stale by construction, and the worst affected are held with an empty parse result and an unchanged size and modification time, so an ordinary scan would short-circuit past them. The forced pass is what recovers them. It takes one to three minutes in the background on a typical library and needs no interaction. Guide logs an earlier release could not parse, ASIAIR logs in particular, appear after it finishes.

This release carries a data version bump to 17 and no new alembic revision.

### After the upgrade

Set a timezone. An empty Observer Timezone now means "not configured" rather than "use the server's zone", and guiding from a profile with no timezone is catalogued but never matched to frames. Set **Settings > Library > Observer Location > Timezone** to the zone of the PC that runs PHD2, and set a per-profile timezone for any rig that runs on a clock of its own. The activity feed reports profiles it had to skip as `phd2_correlation_timezone_unset`.

Each timezone change queues its own full re-parse, and those passes write no scan state, so the job monitor shows nothing while they run. Configuring several rigs one field at a time queues one pass per change. The passes are idempotent and run in sequence; the numbers settle a few minutes after the last save.

### Rollback

Rolling back to a pre-upgrade image after this release requires restoring the database. "No schema change means rollback is safe" does not hold here.

The rewritten `general.phd2_profile_map` value is a format the older releases cannot read. Running an older image against a database that has been through this upgrade fails on every settings read, which takes the settings screen, library scanning, session grouping and all PHD2 processing with it.

To downgrade:

1. Restore the database from a backup taken before the upgrade, then start the older image.
2. Or, with no backup, edit `general.phd2_profile_map` in the `user_settings` row by hand back to the flat profile-name-to-telescope-name form the older release expects, dropping the per-profile timezone and coordinates.

Reverting the value by hand is not durable. Any later settings save on the new build writes the per-profile form again, so an install that has run this release is one settings save away from the same state whether or not the migration is undone. Take a database backup before upgrading if a rollback needs to stay available.

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
