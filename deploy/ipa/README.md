# IPA virtual machine deployment

Target: Ubuntu 24.04 LTS, PostgreSQL 16, Nginx and a dedicated `policyapp` system account.

The application must run with `WAVE2_ENV=production` and a PostgreSQL `DATABASE_URL`. Production startup deliberately fails when the database URL, session secret or randomisation seed is missing.

The included systemd service binds Gunicorn only to `127.0.0.1:8000`. Nginx is the only HTTP entry point. TLS and the public hostname are expected to be terminated or forwarded by the IPA-managed reverse proxy.

The local backup timer retains 30 days of encrypted-at-rest VM files only if the VM storage itself is encrypted. This is not an off-host backup. IPA IT must copy backups to a separately protected system and periodically test restoration.

Do not put `/etc/policy-reasoning.env`, SSH keys, database dumps or participant exports in Git.

## Wave 1 on the same VM

Wave 1 runs as an isolated service and database:

- system user: `albenaapp`
- checkout: `/opt/albena-experiment/app`
- database/role: `albena_experiment` / `albenaapp`
- Gunicorn: `127.0.0.1:8001`
- internal Nginx address during staging: `http://192.168.10.222:8081/`
- runtime files: `/var/lib/albena-experiment`
- completed PDF/JSON archive: `/var/lib/albena-experiment/completed`
- local backup set: `/var/backups/albena-experiment`

The Wave 1 environment file is `/etc/albena-experiment.env` and must be mode `0600`:

```text
WAVE1_ENV=production
WAVE1_DATABASE_URL=postgresql:///albena_experiment
WAVE1_RUNTIME_DIRECTORY=/var/lib/albena-experiment
WAVE1_PDF_DIRECTORY=/var/lib/albena-experiment/pdfs
RESULTS_ARCHIVE_BACKEND=local
RESULTS_LOCAL_DIRECTORY=/var/lib/albena-experiment/completed
APP_VERSION=1.5.0
SESSION_LIMIT_SECONDS=2700
WAVE1_TRUST_PROXY=true
WAVE1_SECURE_COOKIES=false
WAVE1_TRUSTED_HOSTS=192.168.10.222,albena.ipa.government.bg
SECRET_KEY=<generated secret>
```

Set `WAVE1_SECURE_COOKIES=true` only after the public HTTPS endpoint is working. The database and local result archive are independent of GitHub; GitHub contains source code only.

Install `albena-experiment.service`, `nginx-albena-experiment.conf`, and the Wave 1 backup service/timer from this directory. The local backup is operational protection, not an off-host backup. IPA IT must provide a second protected destination before production data collection.
