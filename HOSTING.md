# Host a TechNeighbor hackathon demo

This configuration creates a public hackathon demonstration URL that runs without the developer’s Mac. It uses a free Render Python web service and an external persistent Neon PostgreSQL database. The website is **not deployed merely by adding these files**: sign-in, environment settings, and a successful deployment are still required.

## What is prepared

- `render.yaml` describes the free web service. No paid Render database or disk is created.
- `.python-version` selects the latest Python 3.13 patch supported by Render.
- `build.sh` installs `requirements-hosted.txt` and collects static assets for WhiteNoise.
- `start.sh` runs migrations, creates the database cache table, initializes fictional demo content, and starts Gunicorn.
- `techneighbor.settings_hosted` requires PostgreSQL, a stable secret key, exact hosts, HTTPS, and secure cookies. It contains no local phone database alias.
- Photo bytes, profiles, bookings, moderation, and cached guide audio live in PostgreSQL and survive Render restarts. The demonstration permits at most 100 uploaded photos.
- Public Arc Testnet verification works with public sample proof metadata. Issuer wallet setup, signing, revocation, and provider-key management stay in the local app; those hosted routes are disabled.
- Hosted voice playback uses pre-generated clips only; visitors cannot initiate new ElevenLabs generation requests. No ElevenLabs API key is needed on Render after those clips are imported.

## Create the free accounts

1. Sign in to Render and Neon, reviewing each provider’s sign-in permissions and terms yourself.
2. In Neon, choose Free, create a project such as `techneighbor`, choose AWS Oregon if available, and keep the PostgreSQL connection string private. Use the pooled connection string for the application.
3. Do not use Render’s free Postgres for a lasting demo: Render documents that it expires after 30 days. Neon’s pricing currently lists no time limit for its Free plan. Free-plan capacity and provider policies still apply.

Official information: [Render free service limits](https://render.com/docs/free), [Neon pricing](https://neon.com/pricing), [Render Django deployment](https://render.com/docs/deploy-django).

## Configure Render

Deploy this repository through a Blueprint, or create a **Python Web Service** from the public repository URL `https://github.com/alwayscheery/techneighbor`. A repository installation with access to all GitHub repositories is unnecessary for a manual public-repository deploy.

Choose **Free**, Oregon, branch `main`, build `./build.sh`, start `./start.sh`, and health path `/healthz/`. Set automatic deployments off initially so a code push alone does not publish changes.

Private environment variables:

| Variable | Value |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | `techneighbor.settings_hosted` |
| `DJANGO_SECRET_KEY` | Random, stable secret with at least 50 characters; preserve it across restarts |
| `DATABASE_URL` | Private Neon PostgreSQL connection string; SSL is required |
| `DJANGO_SUPERUSER_USERNAME` | `coordinator` |
| `DJANGO_SUPERUSER_PASSWORD` | Unique, privately saved password of at least 16 characters |

Render supplies `RENDER_EXTERNAL_HOSTNAME` automatically. For an additional custom domain, set `TECHNEIGHBOR_HOSTS` to the comma-separated exact hostnames, without schemes or wildcards. The bootstrap account is staff-only, not a Django superuser. Re-running startup preserves its password; changing the initial-password environment variable does not reset an existing account.

The app refuses to start if its persistent database, secret, or allowed hostname is missing. Health checks return no credential or connection details. Sign-in attempts are throttled. HSTS covers the exact site hostname; subdomain-wide HSTS and browser preload are deliberately not enabled, so Django’s deployment check reports those two advisory warnings.

## Import the existing spoken guide clips once

After the hosted database exists, an authorized operator can connect locally with the hosted environment settings and run:

```sh
python manage.py migrate --settings=techneighbor.settings_hosted
python manage.py import_hosted_audio --directory /absolute/path/to/private/audio-cache --settings=techneighbor.settings_hosted
```

Supply the private database URL and stable hosted secret through environment variables, never command text, chat, public files, or Git. This copies only the 15 fixed instruction/lesson clips into `HostedGuideAudio`. It does not copy API keys, signing keys, resident records, or private recordings. The local cache and databases remain excluded from Git and source archives.

## Verify after deployment

- The HTTPS home page, static CSS/JS, `/learn/`, `/neighbors/`, and `/community/albums/` load.
- A fictional booking can be created and cancelled.
- A fictional photo stays pending until a coordinator approves it; moderation requires the coordinator login.
- The spoken lesson actually plays and slower playback works.
- The seeded service credential reads its status from Arc Testnet.
- After a restart, a fictional saved booking/photo and the coordinator login still work.

Render’s free service sleeps after 15 idle minutes, so the first visit can take about a minute to wake. This is a stable hosted demo address, not an uptime guarantee or production care service. Keep the provider accounts active and maintain private database backups before collecting real community data.

The intended lifetime is submission and judging. No custom domain or paid plan is required. The owner can suspend the web service or remove the demo resources after judging; this setup does not promise indefinite hosting.
