# Deploying to Google Agent Engine

Deploys the WCAG audit pipeline as a live public endpoint on Vertex AI Agent
Engine, with headless Chromium installed at build time so the browser-backed
audit (Playwright + axe-core) runs in the cloud.

## What's here

| File | Purpose |
|---|---|
| `../agent_engine_app.py` | Deployable wrapper class (`set_up` / `query`) — adapts the CLI pipeline to Agent Engine's request/response contract. Lives at repo root so `agents` imports cleanly. |
| `requirements.txt` | Runtime pip deps (no test deps). |
| `installation_scripts/install.sh` | Build-time `playwright install --with-deps chromium`. |
| `deploy.py` | One-command deploy. Prints the resource name. |
| `call_endpoint.py` | Calls the deployed endpoint — produces the writeup Results data. |

## Phase 0 — one-time setup (your hands)

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <YOUR_PROJECT_ID>
gcloud services enable aiplatform.googleapis.com
gsutil mb -l us-central1 gs://<YOUR_STAGING_BUCKET>
```

Then add to `.env` (repo root):

```
GOOGLE_CLOUD_PROJECT=<YOUR_PROJECT_ID>
GOOGLE_CLOUD_LOCATION=us-central1
STAGING_BUCKET=gs://<YOUR_STAGING_BUCKET>
GOOGLE_API_KEY=<already present>
```

## Phase 1 verify — local smoke test (free, no cloud)

Confirms the exact object Agent Engine will run works end to end:

```bash
python agent_engine_app.py --url https://example.com
```

## Phase 2 — deploy (spends money)

```bash
python deploy/deploy.py
```

First build is slow — it downloads Chromium. On success it prints
`resource_name`; that's your live endpoint handle.

## Phase 3 — verify the live endpoint (produces evidence)

```bash
python deploy/call_endpoint.py <resource_name> --url https://example.com
```

Use the returned report to fill the Results section of `kaggle_writeup.md`
and to paste the endpoint into README + writeup.

## Notes / gotchas

- **Cloud IP hits bot-walls.** Cloudflare-protected sites (Gumtree) will block
  the cloud endpoint. Demo the live endpoint on static sites (example.com, the
  W3C bad demo); keep Gumtree as the local HTML-input-mode demo.
- **Memory.** Chromium needs ~1 GB headroom — ensure the instance has ≥2 GB.
- **SDK surface.** Two lines in `deploy.py` are flagged: the `build_options` /
  `installation_scripts` keyword has moved across `google-cloud-aiplatform`
  releases. If `create()` rejects a kwarg, check `help(agent_engines.create)`
  for your installed version and adjust.
- **Cost.** An always-on instance with Chromium bills continuously. Keep it up
  through grading, then tear down:
  `python -c "import vertexai; from vertexai import agent_engines; vertexai.init(project='...', location='us-central1'); agent_engines.get('<resource_name>').delete()"`
