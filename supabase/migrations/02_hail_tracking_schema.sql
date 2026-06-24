-- ============================================================
-- HAIL TRACKER PRO PHASE 1 SCHEMA
-- Add watched regions and hail alert history for the ingestion worker.
-- ============================================================

create table regions (
  id bigserial primary key,
  slug text not null unique,
  name text not null,
  min_lat numeric not null,
  min_lon numeric not null,
  max_lat numeric not null,
  max_lon numeric not null,
  threshold_mm numeric not null default 25.4,
  is_active boolean not null default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index idx_regions_slug on regions(slug);
create index idx_regions_active on regions(is_active);

create table hail_alerts (
  id bigserial primary key,
  region_id bigint not null references regions(id) on delete cascade,
  mesh_url text not null,
  mesh_source text not null,
  hail_mm numeric not null,
  hail_in numeric not null,
  threshold_mm numeric not null,
  triggered_at timestamptz not null default now(),
  cleared_at timestamptz,
  is_active boolean not null default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index idx_hail_alerts_region on hail_alerts(region_id);
create index idx_hail_alerts_active on hail_alerts(region_id, is_active);

-- Ensure updated_at is maintained if the original schema's trigger exists.
create trigger regions_updated_at before update on regions
  for each row execute function set_updated_at();

create trigger hail_alerts_updated_at before update on hail_alerts
  for each row execute function set_updated_at();

-- Seed a starting watched region around Springfield, MO.
insert into regions (
  slug,
  name,
  min_lat,
  min_lon,
  max_lat,
  max_lon,
  threshold_mm,
  is_active
)
values (
  'springfield-mo',
  'Springfield, MO',
  37.10,
  -93.45,
  37.32,
  -93.10,
  25.4,
  true
);
