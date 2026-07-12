-- Add dealership tiering for alert prioritization.
alter table dealerships
  add column if not exists tier text not null default 'independent'
  check (tier in ('franchise', 'auction', 'independent'));

-- One-time backfill based on current name/brand values.
update dealerships
set tier = case
  when coalesce(brand, '') <> '' then 'franchise'
  when lower(coalesce(name, '')) similar to '%(chevrolet|chevy|ford|toyota|honda|nissan|kia|hyundai|gmc|buick|ram|dodge|jeep|chrysler|subaru|mazda|vw|volkswagen|bmw|mercedes|lexus|audi|carmax|autonation)%' then 'franchise'
  when lower(coalesce(name, '')) like '%auction%' then 'auction'
  else 'independent'
end;

create index if not exists idx_dealerships_tier on dealerships(region_id, tier, active);
