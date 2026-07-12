-- Add separate dealership hail threshold per region.
alter table regions
  add column if not exists dealer_threshold_mm numeric not null default 12.7;
