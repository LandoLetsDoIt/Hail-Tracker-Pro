-- ============================================================
-- HAIL TRACKER PRO PHASE 1.2 SCHEMA
-- Static canvass scoring by census tract.
-- ============================================================

create table if not exists tract_scores (
  id bigserial primary key,
  region_id bigint not null references regions(id) on delete cascade,
  tract_geoid text not null,
  centroid_lat double precision not null,
  centroid_lon double precision not null,
  min_lat double precision not null,
  min_lon double precision not null,
  max_lat double precision not null,
  max_lon double precision not null,
  vehicle_density_pts integer not null check (vehicle_density_pts between 0 and 30),
  claim_likelihood_pts integer not null check (claim_likelihood_pts between 0 and 20),
  raw jsonb not null,
  computed_at timestamptz not null default now(),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(region_id, tract_geoid)
);

create index if not exists idx_tract_scores_region on tract_scores(region_id);
create index if not exists idx_tract_scores_region_points on tract_scores(region_id, vehicle_density_pts desc, claim_likelihood_pts desc);

create trigger tract_scores_updated_at before update on tract_scores
  for each row execute function set_updated_at();
