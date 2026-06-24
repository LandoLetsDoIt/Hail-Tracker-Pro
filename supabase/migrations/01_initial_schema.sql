-- ============================================================
-- LEAD MANAGEMENT SYSTEM - INITIAL SCHEMA
-- Multi-client architecture: same DB serves moving, PDR, party bus, etc.
-- ============================================================

-- ------------------------------------------------------------
-- ENUMS
-- ------------------------------------------------------------

create type lead_status as enum (
  'new',                  -- just came in, nothing done yet
  'pending_review',       -- waiting for Lando to approve before hitting owner calendar
  'appointment_booked',   -- approved, on owner's calendar
  'appointment_completed',-- the in-person/video estimate happened
  'won',                  -- move actually completed - this triggers your pay
  'lost',                 -- they went with someone else / didn't book
  'dead'                  -- no response, bad lead, spam, etc.
);

create type lead_source as enum (
  'landing_page_form',    -- they booked through the website
  'tracking_phone_call',  -- they called the Twilio number
  'tracking_phone_text',  -- they texted the Twilio number
  'manual_entry',         -- owner or Lando entered it manually
  'other'
);

create type move_size as enum (
  'studio',
  'one_bedroom',
  'two_bedroom',
  'three_bedroom',
  'four_bedroom_plus',
  'commercial',
  'unknown'
);

create type move_distance as enum (
  'local',                -- within service radius
  'long_distance'         -- out of area
);

create type appointment_type as enum (
  'in_person',
  'video'                 -- the FaceTime overflow valve
);

create type appointment_status as enum (
  'pending_review',       -- waiting on Lando to approve
  'scheduled',            -- approved, on calendar, confirmed
  'completed',
  'no_show',
  'cancelled',
  'rescheduled'
);

create type message_direction as enum ('inbound', 'outbound');

create type message_channel as enum ('sms', 'email', 'voice');

-- ------------------------------------------------------------
-- TABLE: clients
-- One row per business using the system (moving co, PDR shop, etc.)
-- ------------------------------------------------------------

create table clients (
  id            bigserial primary key,
  name          text not null,                    -- "Springfield Moving Co"
  slug          text not null unique,             -- "springfield-moving" - used in URLs
  vertical      text not null,                    -- "moving", "pdr", "party_bus", "mowing"
  owner_name    text not null,
  owner_phone   text not null,                    -- where alerts get texted
  owner_email   text not null,
  tracking_phone text,                            -- Twilio number assigned to this client
  service_radius_minutes int default 45,          -- drive time radius from owner's location
  business_hours jsonb default '{"mon":["09:00","18:00"],"tue":["09:00","18:00"],"wed":["09:00","18:00"],"thu":["09:00","18:00"],"fri":["09:00","18:00"],"sat":["09:00","18:00"],"sun":["09:00","18:00"]}'::jsonb,
  min_lead_time_hours int default 4,              -- earliest bookable slot = now + this
  appointment_duration_minutes int default 45,    -- 15 min onsite + buffer
  facetime_enabled boolean default false,         -- the overflow valve toggle
  facetime_threshold_hours int default 48,        -- if next in-person slot > this far out, offer video
  manual_approval_required boolean default true,  -- Lando reviews appointments before they hit owner's calendar
  google_calendar_id text,                        -- owner's calendar to write events to
  google_oauth_token jsonb,                       -- encrypted OAuth credentials
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

create index idx_clients_slug on clients(slug);

-- ------------------------------------------------------------
-- TABLE: leads
-- One row per prospect that enters the system
-- ------------------------------------------------------------

create table leads (
  id                bigserial primary key,
  client_id         bigint not null references clients(id) on delete cascade,
  status            lead_status not null default 'new',
  source            lead_source not null,

  -- contact info
  full_name         text,
  phone             text,
  email             text,

  -- move-specific fields (nullable so we can reuse this table for other verticals later)
  origin_address    text,
  destination_address text,                       -- only for long-distance
  destination_city_state text,                    -- "Dallas, TX"
  target_move_date  date,
  move_size         move_size,
  move_distance     move_distance,

  -- estimate / job tracking
  estimate_amount   numeric(10,2),                -- what owner quoted them
  job_completed_amount numeric(10,2),             -- what the move actually billed for
  job_completed_at  timestamptz,

  -- attribution
  utm_source        text,
  utm_medium        text,
  utm_campaign      text,
  landing_url       text,                         -- which page they landed on
  referrer_url      text,

  -- internal
  notes             text,                         -- free-text for owner/Lando
  created_at        timestamptz default now(),
  updated_at        timestamptz default now()
);

create index idx_leads_client_id on leads(client_id);
create index idx_leads_status on leads(client_id, status);
create index idx_leads_created_at on leads(client_id, created_at desc);

-- ------------------------------------------------------------
-- TABLE: appointments
-- One row per scheduled estimate (in-person or video)
-- ------------------------------------------------------------

create table appointments (
  id                bigserial primary key,
  client_id         bigint not null references clients(id) on delete cascade,
  lead_id           bigint not null references leads(id) on delete cascade,
  type              appointment_type not null default 'in_person',
  status            appointment_status not null default 'pending_review',
  scheduled_start   timestamptz not null,
  scheduled_end     timestamptz not null,
  google_event_id   text,                         -- populated after approval + calendar push
  approved_by       text,                         -- who clicked approve (Lando's email)
  approved_at       timestamptz,
  completed_at      timestamptz,
  cancellation_reason text,
  notes             text,
  created_at        timestamptz default now(),
  updated_at        timestamptz default now()
);

create index idx_appointments_client_id on appointments(client_id);
create index idx_appointments_lead_id on appointments(lead_id);
create index idx_appointments_scheduled_start on appointments(client_id, scheduled_start);
create index idx_appointments_status on appointments(client_id, status);

-- ------------------------------------------------------------
-- TABLE: messages
-- Log of all SMS / email / call interactions with a lead
-- ------------------------------------------------------------

create table messages (
  id                bigserial primary key,
  client_id         bigint not null references clients(id) on delete cascade,
  lead_id           bigint references leads(id) on delete cascade,
  direction         message_direction not null,
  channel           message_channel not null,
  from_address      text,                         -- phone or email
  to_address        text,
  body              text,
  media_urls        jsonb,                        -- array of attachment URLs (photos, etc.)
  twilio_sid        text,                         -- for SMS/voice, for debugging
  created_at        timestamptz default now()
);

create index idx_messages_lead_id on messages(lead_id, created_at desc);
create index idx_messages_client_id on messages(client_id, created_at desc);

-- ------------------------------------------------------------
-- TABLE: events
-- Generic event log - timeline of everything that happened to a lead
-- ------------------------------------------------------------

create table events (
  id                bigserial primary key,
  client_id         bigint not null references clients(id) on delete cascade,
  lead_id           bigint references leads(id) on delete cascade,
  event_type        text not null,                -- 'lead_created', 'appointment_booked', 'status_changed', etc.
  payload           jsonb,                        -- arbitrary structured data about the event
  created_at        timestamptz default now()
);

create index idx_events_lead_id on events(lead_id, created_at desc);
create index idx_events_client_id_type on events(client_id, event_type, created_at desc);

-- ------------------------------------------------------------
-- TABLE: app_users
-- Internal users (Lando = admin, his friend = client owner)
-- Separate from Supabase auth.users so we can have a role layer
-- ------------------------------------------------------------

create table app_users (
  id                uuid primary key references auth.users(id) on delete cascade,
  email             text not null unique,
  full_name         text,
  role              text not null check (role in ('admin', 'owner')),
  client_id         bigint references clients(id) on delete set null,  -- which client they belong to (null for admins)
  created_at        timestamptz default now()
);

create index idx_app_users_client_id on app_users(client_id);

-- ------------------------------------------------------------
-- TABLE: payouts
-- Tracks what Lando is owed and what's been paid
-- Generated from won leads + completed appointments
-- ------------------------------------------------------------

create table payouts (
  id                bigserial primary key,
  client_id         bigint not null references clients(id) on delete cascade,
  lead_id           bigint references leads(id) on delete cascade,
  appointment_id    bigint references appointments(id) on delete cascade,
  payout_type       text not null check (payout_type in ('per_appointment', 'per_completed_move', 'flat_retainer', 'other')),
  amount            numeric(10,2) not null,
  earned_at         timestamptz default now(),
  paid_at           timestamptz,                  -- null = unpaid
  payment_method    text,
  notes             text
);

create index idx_payouts_client_id on payouts(client_id, earned_at desc);
create index idx_payouts_unpaid on payouts(client_id) where paid_at is null;

-- ============================================================
-- ROW LEVEL SECURITY
-- Each client only sees their own data. Admins (Lando) see everything.
-- ============================================================

alter table clients enable row level security;
alter table leads enable row level security;
alter table appointments enable row level security;
alter table messages enable row level security;
alter table events enable row level security;
alter table app_users enable row level security;
alter table payouts enable row level security;

-- helper function: is current user an admin?
create or replace function is_admin() returns boolean as $$
  select exists (
    select 1 from app_users
    where id = auth.uid() and role = 'admin'
  );
$$ language sql security definer stable;

-- helper function: what client does the current user belong to?
create or replace function current_user_client_id() returns bigint as $$
  select client_id from app_users where id = auth.uid();
$$ language sql security definer stable;

-- clients table: admins see all, owners see only their own
create policy clients_admin_all on clients for all
  using (is_admin());

create policy clients_owner_select on clients for select
  using (id = current_user_client_id());

-- leads table: same pattern
create policy leads_admin_all on leads for all
  using (is_admin());

create policy leads_owner_select on leads for select
  using (client_id = current_user_client_id());

create policy leads_owner_update on leads for update
  using (client_id = current_user_client_id());

-- appointments table
create policy appointments_admin_all on appointments for all
  using (is_admin());

create policy appointments_owner_select on appointments for select
  using (client_id = current_user_client_id());

create policy appointments_owner_update on appointments for update
  using (client_id = current_user_client_id());

-- messages table
create policy messages_admin_all on messages for all
  using (is_admin());

create policy messages_owner_select on messages for select
  using (client_id = current_user_client_id());

-- events table
create policy events_admin_all on events for all
  using (is_admin());

create policy events_owner_select on events for select
  using (client_id = current_user_client_id());

-- app_users table
create policy app_users_admin_all on app_users for all
  using (is_admin());

create policy app_users_self_select on app_users for select
  using (id = auth.uid());

-- payouts table: ONLY admins see this. Owners never see what you're being paid.
create policy payouts_admin_all on payouts for all
  using (is_admin());

-- ============================================================
-- TRIGGERS - keep updated_at fresh
-- ============================================================

create or replace function set_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger clients_updated_at before update on clients
  for each row execute function set_updated_at();

create trigger leads_updated_at before update on leads
  for each row execute function set_updated_at();

create trigger appointments_updated_at before update on appointments
  for each row execute function set_updated_at();

-- ============================================================
-- SEED: insert the moving company as client #1
-- Update these values once you have real info from your friend
-- ============================================================

insert into clients (name, slug, vertical, owner_name, owner_phone, owner_email, service_radius_minutes, appointment_duration_minutes, facetime_enabled, facetime_threshold_hours, manual_approval_required)
values (
  'Springfield Moving Co',          -- replace with actual name
  'springfield-moving',
  'moving',
  'Friend Name',                    -- replace
  '+14175550000',                   -- replace with his actual cell
  'friend@example.com',             -- replace
  45,
  45,
  false,                            -- FaceTime off by default
  48,
  true                              -- you approve appointments for first 3 months
);
