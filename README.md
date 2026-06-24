This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Hail Lead Engine Phase 0

This repository now includes a Phase 0 Python worker for the Hail Lead Engine.

- `worker/hail_engine.py` downloads a NOAA MRMS MESH GRIB2 file
- It extracts hail size at Springfield, MO by default (`37.21, -93.29`)
- It prints hail size in mm and inches for the Phase 0 test point
- `.github/workflows/hail_engine.yml` runs the worker on a schedule and via manual dispatch

### Run locally

```bash
python -m pip install -r worker/requirements.txt
python worker/hail_engine.py <grib2-url-or-path> --lat 37.21 --lon -93.29
```

### Phase 1 integration

The worker now supports scanning watched regions and writing alert history to Supabase.
To enable this, set the following env vars in your runtime environment:

```bash
SUPABASE_URL=https://<your-project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>
```

Then run:

```bash
python worker/hail_engine.py latest --scan-regions --dry-run
```

Use `--dry-run` to verify region scanning without creating alerts.

### Phase 1 manual runbook (local)

Use these commands from the repository root on Windows.

Before using the integration script below, apply the migration in `supabase/migrations/03_hail_alerts_email_sent_at.sql` to your Supabase database so `hail_alerts.email_sent_at` exists.

1. Quick email smoke test (no NOAA fetch, no Supabase writes):

```powershell
C:/Users/Lando/miniconda3/envs/hail-env/python.exe worker/hail_engine.py --email-smoke-test --email-region "Manual Test" --email-hail-in 1.25
```

2. Force one end-to-end trigger by lowering threshold to `0.0` mm:

```powershell
C:/Users/Lando/miniconda3/envs/hail-env/python.exe -c "import os, requests; from worker.verify_supabase import get_supabase_headers; b=os.getenv('SUPABASE_URL').rstrip('/'); h={**get_supabase_headers(),'Prefer':'return=representation'}; u=f'{b}/rest/v1/regions?id=eq.1'; r=requests.patch(u,headers=h,json={'threshold_mm':0.0},timeout=30); print('PATCH_STATUS', r.status_code); print('PATCH_BODY', r.text)"
```

3. Run a real region scan (writes alert, sends email if eligible):

```powershell
C:/Users/Lando/miniconda3/envs/hail-env/python.exe worker/hail_engine.py latest --scan-regions
```

4. Restore threshold to normal (`25.4` mm = `1.0` inch):

```powershell
C:/Users/Lando/miniconda3/envs/hail-env/python.exe -c "import os, requests; from worker.verify_supabase import get_supabase_headers; b=os.getenv('SUPABASE_URL').rstrip('/'); h={**get_supabase_headers(),'Prefer':'return=representation'}; u=f'{b}/rest/v1/regions?id=eq.1'; r=requests.patch(u,headers=h,json={'threshold_mm':25.4},timeout=30); print('RESTORE_STATUS', r.status_code); print('RESTORE_BODY', r.text)"
```

5. Optional cleanup: clear active test alert row for region `1`:

```powershell
C:/Users/Lando/miniconda3/envs/hail-env/python.exe -c "import os, requests; from worker.verify_supabase import get_supabase_headers; b=os.getenv('SUPABASE_URL').rstrip('/'); h=get_supabase_headers(); q=f'{b}/rest/v1/hail_alerts?select=id,is_active,triggered_at,region_id&region_id=eq.1&is_active=eq.true&order=triggered_at.desc&limit=1'; r=requests.get(q,headers=h,timeout=30); print('ACTIVE_QUERY_STATUS', r.status_code); print('ACTIVE_QUERY_BODY', r.text); rows=r.json();\nif rows:\n rid=rows[0]['id']; hd={**h,'Prefer':'return=representation'}; d=requests.patch(f'{b}/rest/v1/hail_alerts?id=eq.{rid}',headers=hd,json={'is_active':False},timeout=30); print('CLEAR_STATUS', d.status_code); print('CLEAR_BODY', d.text)\nelse:\n print('CLEAR_STATUS skipped'); print('CLEAR_BODY []')"
```

6. One-command integration flow (insert -> email logic -> verify -> cleanup):

```powershell
C:/Users/Lando/miniconda3/envs/hail-env/python.exe worker/integration_email_alert_flow.py
```

### GitHub Actions Supabase verification

A manual workflow dispatch now verifies Supabase only when secrets are configured.

1. Add these repository secrets in GitHub:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

2. Open the Actions tab and run the `Hail Lead Engine` workflow manually.

3. If secrets are present, the `supabase-verify` job will execute:

```bash
cd worker
python verify_supabase.py --dry-run
```

This validates read-only Supabase access without writing alerts.

### Notes

- The worker reads `regions` and writes `hail_alerts` when Supabase is configured.
- Thresholds are expressed in millimeters and converted to inches for display.
- If Supabase is not configured, the worker still falls back to a default Springfield region.

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
