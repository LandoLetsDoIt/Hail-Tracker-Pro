-- Add dealership group metadata for alert routing and prioritization.
alter table dealerships
  add column if not exists dealer_group text;
