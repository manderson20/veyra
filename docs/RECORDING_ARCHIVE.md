# Recording archive

A copy of each call recording on a backup destination, for losing the server.
Owner decision 2026-10-30: **a copy lives exactly as long as its recording.**
Retention stays true everywhere, so the archive is not a way to keep recordings
longer. An installation that must keep them for years sets a long retention.

## 1. How it works

* System -> Backups -> **Recording archive** chooses the destination
  (`GET`/`PUT /backups/recording-archive`). Folder, SFTP and S3 all work.
* The worker starts `veyra-backup@recordings` (root, through polkit) when there
  is work, at most hourly. Up to 500 copies and 500 removals a run; the first
  run after turning it on works through older recordings over several hours.
* Each recording goes to `<destination>/recordings/veyra-recording-<id>/`: the
  file as stored (encrypted recordings stay encrypted) and `manifest.json` last,
  with the sizes checked. The backup keep policy never sees this folder.
* `call_recordings` keeps `archive_destination`, `archived_at` and
  `archive_removed_at` (migration 0072).

## 2. Deleting

Deleting a recording, by hand or at its retention date, marks it deleted as
before. The next run removes its copy and only then records `archive_removed_at`,
**after checking the copy is really gone**, because the SFTP client ignores
failed removals. A copy that cannot be removed stays on the list, is retried each
run, and raises the backup copies alert. Removals run before new copies.

So the copy outlives the recording by up to about an hour, or longer while the
destination is unreachable. Held recordings are not deleted, so their copies stay.

A destination cannot be removed while it is the archive's or holds copies: Veyra
must be able to delete them. Choosing another destination leaves old copies where
they are, and they are deleted from there.

## 3. Limits

* **There is no restore from the archive in the interface.** The database row
  keeps the wrapped key; the manifest has a copy from the time of the copy. After
  rotating the installation key, a manifest's wrapped key is out of date, so
  decrypting a copy needs a database backup from before the rotation or the row.
* Turning the archive off stops new copies; removals carry on.
* Copies made by hand or restored on the destination are not tracked.
