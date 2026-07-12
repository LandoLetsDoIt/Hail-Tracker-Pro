-- Dealership inventory for hail-impact targeting.
create table if not exists dealerships (
  id bigserial primary key,
  region_id bigint not null references regions(id) on delete cascade,
  name text not null,
  brand text,
  lat double precision not null,
  lon double precision not null,
  osm_id text not null unique,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create index if not exists idx_dealerships_region_active on dealerships(region_id, active);
create index if not exists idx_dealerships_osm_id on dealerships(osm_id);

alter table dealerships enable row level security;
