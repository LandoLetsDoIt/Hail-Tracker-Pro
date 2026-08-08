-- ============================================================
-- HEARTBEAT DEDUP
-- Records the Central-time calendar date the nightly heartbeat
-- email was sent, so multiple scheduled runs landing inside the
-- send window don't each fire their own email.
-- ============================================================

create table if not exists heartbeat_log (
  sent_date date primary key,
  sent_at timestamptz not null default now()
);
