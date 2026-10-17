-- WOD Tracker database. Mirrors the desktop tool's SQLite schema (wod/db.py), plus who owns each row.
-- Every user table has Row Level Security: a signed-in user reads and writes only their own rows.

-- ---------- people ----------
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  name text,
  units text not null default 'lb' check (units in ('lb', 'kg')),
  gym text,
  created_at timestamptz not null default now()
);

-- ---------- movement catalogue (shared, read-only to users) ----------
create table public.movements (
  key text primary key,                       -- e.g. 'power_snatch'
  name text not null,
  class text not null,                        -- rope, hang, overhead, floor_to_shoulder, machine, carry
  unit text not null default 'reps'           -- reps, cal, ft, m
);

-- ---------- workouts ----------
create table public.workouts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade default auth.uid(),
  date date not null default current_date,
  name text,
  workout_text text not null,
  spec jsonb,                                 -- parsed workout
  spec_hash text,                             -- same workout done again
  format text,                                -- amrap, rounds, for_time
  mode text,                                  -- standard, sequence
  score text,
  rounds_complete numeric,
  total_reps integer,
  elapsed_s numeric, moving_s numeric, between_s numeric, between_pct numeric, rest_s numeric,
  notes text,
  status text not null default 'uploaded' check (status in ('uploaded', 'analyzing', 'done', 'failed')),
  engine_version text,
  source text not null default 'live' check (source in ('live', 'import', 'desktop')),
  pose_path text,                             -- storage: poses/<user>/<workout>/pose.json.gz
  audio_path text,
  result jsonb,                               -- the full analysis, for the report screen
  created_at timestamptz not null default now()
);
create index on public.workouts (user_id, date desc);
create index on public.workouts (user_id, spec_hash);

create table public.blocks (                  -- one movement in one round
  id bigint generated always as identity primary key,
  workout_id uuid not null references public.workouts(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  round integer not null,
  pos_in_round integer not null,
  movement text not null,
  label text,
  start_s numeric, end_s numeric, duration_s numeric,
  reps numeric, expected numeric,
  unit text not null default 'reps',
  counted boolean not null default true,      -- false = taken from the whiteboard (bike calories, carry distance)
  sets text,                                  -- "12+8"
  sec_per_rep numeric, reps_per_sec numeric,
  transition_after_s numeric, next_movement text,
  flagged boolean not null default false,
  corrected boolean not null default false,
  load text
);
create index on public.blocks (user_id, movement);
create index on public.blocks (workout_id);

create table public.sets (
  id bigint generated always as identity primary key,
  block_id bigint not null references public.blocks(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  idx integer not null,
  reps integer, start_s numeric, end_s numeric, rest_after_s numeric
);

create table public.reps (
  id bigint generated always as identity primary key,
  block_id bigint not null references public.blocks(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  idx integer not null,
  t_s numeric not null
);
create index on public.reps (block_id);

create table public.fresh_benchmarks (        -- time for 10 fresh reps, per user and movement
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  workout_id uuid not null references public.workouts(id) on delete cascade,
  movement text not null,
  time_for_10_s numeric, estimated boolean, reps_per_sec numeric, unit text,
  first_time_seen boolean not null default false
);
create index on public.fresh_benchmarks (user_id, movement);

create table public.corrections (             -- a user's fix = labeled data
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade default auth.uid(),
  workout_id uuid not null references public.workouts(id) on delete cascade,
  round integer, movement text, field text not null default 'reps',
  old_value numeric, new_value numeric not null, note text,
  created_at timestamptz not null default now()
);

create table public.analysis_jobs (
  id bigint generated always as identity primary key,
  workout_id uuid not null references public.workouts(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  status text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed')),
  engine_version text, error text, took_s numeric, ai_cost_usd numeric,
  created_at timestamptz not null default now(), finished_at timestamptz
);
create index on public.analysis_jobs (status, created_at);

create table public.coach_messages (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade default auth.uid(),
  question text not null, answer text, cost_usd numeric,
  created_at timestamptz not null default now()
);

-- ---------- security: own rows only ----------
alter table public.profiles enable row level security;
alter table public.movements enable row level security;
alter table public.workouts enable row level security;
alter table public.blocks enable row level security;
alter table public.sets enable row level security;
alter table public.reps enable row level security;
alter table public.fresh_benchmarks enable row level security;
alter table public.corrections enable row level security;
alter table public.analysis_jobs enable row level security;
alter table public.coach_messages enable row level security;

create policy "movements are readable" on public.movements for select to authenticated using (true);
create policy "own profile" on public.profiles for all to authenticated using (id = (select auth.uid())) with check (id = (select auth.uid()));
create policy "own workouts" on public.workouts for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy "read own blocks" on public.blocks for select to authenticated using (user_id = (select auth.uid()));
create policy "read own sets" on public.sets for select to authenticated using (user_id = (select auth.uid()));
create policy "read own reps" on public.reps for select to authenticated using (user_id = (select auth.uid()));
create policy "read own benchmarks" on public.fresh_benchmarks for select to authenticated using (user_id = (select auth.uid()));
create policy "own corrections" on public.corrections for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy "read own jobs" on public.analysis_jobs for select to authenticated using (user_id = (select auth.uid()));
create policy "own coach messages" on public.coach_messages for select to authenticated using (user_id = (select auth.uid()));
create policy "ask the coach" on public.coach_messages for insert to authenticated with check (user_id = (select auth.uid()));
-- blocks, sets, reps, benchmarks and jobs are written only by the analysis server (service role bypasses RLS).

-- ---------- week-1 test results (anyone with the link can add one, nobody can read them back) ----------
create table public.test_runs (
  id bigint generated always as identity primary key,
  code text not null unique check (code ~ '^[A-Z0-9]{4,8}$'),
  kind text not null check (kind in ('live', 'video')),
  summary jsonb not null check (pg_column_size(summary) < 20000),
  created_at timestamptz not null default now()
);
alter table public.test_runs enable row level security;
create policy "send a test result" on public.test_runs for insert to anon, authenticated with check (true);

-- ---------- file storage ----------
insert into storage.buckets (id, name, public, file_size_limit)
values ('poses', 'poses', false, 52428800),          -- <user id>/<workout id>/pose.json.gz, audio, review frames
       ('test-runs', 'test-runs', false, 104857600)   -- <code>/pose.json.gz, audio
on conflict (id) do nothing;

create policy "own pose files" on storage.objects for all to authenticated
  using (bucket_id = 'poses' and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'poses' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "upload a test run" on storage.objects for insert to anon, authenticated
  with check (bucket_id = 'test-runs');
