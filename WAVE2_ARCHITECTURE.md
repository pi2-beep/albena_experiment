# Albena experiment - Wave 2 architecture

Status: implementation foundation; not deployed. Wave 1 production remains on `main` and is frozen by tag `wave1-v1.4.3-final`.

## Separation guarantees

- Wave 2 development occurs only on `wave2-preregistered`.
- Wave 2 will use a separate Render service, database, URL, secrets and backup directory.
- No Wave 2 branch is connected to the Wave 1 production service.
- Wave 1 data and Wave 2 data must never share tables or export directories.

## Canonical records

PostgreSQL is the intended canonical store if a no-cost managed option is approved. Render local files and browser storage are not authoritative. FTPS is a versioned backup/export destination only. The local prototype deliberately uses an isolated SQLite file and is not production storage.

The draft relational schema is in `wave2/schema.sql`. Database changes will be applied through migrations after the database provider and retention policy are approved.

## Server-controlled state

The valid lifecycle is defined in `wave2/domain.py`:

`started -> consented -> eligible -> baseline_draft -> baseline_locked -> randomised -> intervention_active -> immediate_post_complete -> review_decided -> final_complete -> completed`

Ineligible and withdrawn are terminal states. The browser may request a transition, but only the server may validate and commit it.

## Frozen instruments

Draft Wave 2 instruments are stored in `wave2/instruments/`. `manifest_v1.json` contains SHA-256 hashes and the loader refuses changed content. The manifest remains marked as draft until the scientific text, consent and preregistration are approved.

## Randomisation

`wave2/randomisation.py` generates reproducible 1:1 schedules independently for each `session_code | baseline_preferred` stratum. Every block is randomly selected from size 4 or 6 and contains equal AI/control assignments.

The master seed is secret and must never be committed. Production allocation will consume pre-generated slots in a PostgreSQL transaction with a unique constraint on stratum, schedule version and sequence.

## Intervention records

Wave 2 uses a zero-cost, naturalistic intervention. Participants assigned to the ИИ arm use an ИИ tool to which they already have access; the site supplies the frozen case and three frozen prompts, then records the pasted responses and declared tool metadata. The two additional prompts are optional. Control participants complete three parallel structured-reflection tasks without ИИ. Assigned tasks and participant-initiated optional tasks are separate data categories.

## Open decisions before deployable implementation

- Whether the naturalistic variation in participant-selected ИИ tools is acceptable in the final preregistration and analysis plan.
- Database provider, retention period and backup encryption.
- Controlled session-code catalogue and invitation-token procedure.
- Whether early intervention completion is allowed and whether provider latency counts toward 12 minutes.
- Timeout, retry, outage and partial-completion rules.
- Final wording/version of consent, eligibility, case and participant-facing task translations.
- Access roles for the invitation registry, participant dataset and AI transcript dataset.
