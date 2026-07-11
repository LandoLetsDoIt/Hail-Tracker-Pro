-- Add timezone support for timing-aware canvass scoring.
alter table regions
  add column if not exists timezone text not null default 'America/Chicago';

-- Default plains/mountain watched regions to America/Denver.
update regions
set timezone = 'America/Denver'
where lower(coalesce(slug, '')) in ('denver-co', 'gillette-wy', 'cheyenne-wy')
   or lower(coalesce(name, '')) in ('denver, co', 'gillette, wy', 'cheyenne, wy');
