# IPA virtual machine deployment

Target: Ubuntu 24.04 LTS, PostgreSQL 16, Nginx and a dedicated `policyapp` system account.

The application must run with `WAVE2_ENV=production` and a PostgreSQL `DATABASE_URL`. Production startup deliberately fails when the database URL, session secret or randomisation seed is missing.

The included systemd service binds Gunicorn only to `127.0.0.1:8000`. Nginx is the only HTTP entry point. TLS and the public hostname are expected to be terminated or forwarded by the IPA-managed reverse proxy.

The local backup timer retains 30 days of encrypted-at-rest VM files only if the VM storage itself is encrypted. This is not an off-host backup. IPA IT must copy backups to a separately protected system and periodically test restoration.

Do not put `/etc/policy-reasoning.env`, SSH keys, database dumps or participant exports in Git.
