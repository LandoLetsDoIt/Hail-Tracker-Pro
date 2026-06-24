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
