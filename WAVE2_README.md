# Policy Reasoning Lab - Wave 2 prototype

Status: local prototype on `wave2-preregistered`. It is not deployed and does not alter the Wave 1 Render service.

## Design

- zero-cost naturalistic ИИ arm using the participant's existing ИИ tool;
- three mandatory frozen tasks and two optional participant prompts;
- parallel no-ИИ reflection tasks for the control arm;
- server-side baseline lock, stratified allocation, state transitions and 12-minute deadline;
- exact participant-facing task text included in the integrity-checked instrument manifest.

## Run locally

```sh
WAVE2_RANDOMISATION_SEED='replace-with-a-local-secret' .venv/bin/python wave2_app.py
```

Open `http://127.0.0.1:5001/`.

The prototype writes only to its local SQLite database. That database is for development and must not be used for participant data.

## Verify

```sh
python -m unittest discover -s tests_wave2 -v
node --check static_wave2/wave2.js
```

Read `WAVE2_ARCHITECTURE.md` before any deployment. Consent text, eligibility rules, invitation controls, storage, retention and the statistical analysis plan still require scientific approval.
