-- ============================================================
-- HAIL TRACKER PRO PHASE 1.1 SCHEMA
-- Track successful alert email delivery timestamps.
-- ============================================================

alter table hail_alerts
  add column if not exists email_sent_at timestamptz;

create index if not exists idx_hail_alerts_region_email_sent_at
  on hail_alerts(region_id, email_sent_at desc);
