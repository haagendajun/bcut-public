-- bcut 초기 스키마 (erd.md, ADR-0001~0006). 프로젝트 ref: fsngkxbhgtmzpjoasmvn (ap-northeast-2)
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now(),
  last_sign_in_at timestamptz
);
create table public.events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null check (length(btrim(name)) > 0),
  last_scan_folder text,
  created_at timestamptz not null default now(),
  unique (owner_id, name)
);
create table public.photos (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  event_id uuid not null references public.events(id),
  file_name text not null,
  file_size bigint not null check (file_size >= 0),
  first_seen_at timestamptz not null default now(),
  unique (event_id, file_name, file_size)
);
create table public.scans (
  id uuid primary key,
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  event_id uuid not null references public.events(id),
  folder_path text,
  tool_version text not null,
  config jsonb not null default '{}'::jsonb,
  photo_count int not null default 0 check (photo_count >= 0),
  counts jsonb not null default '{}'::jsonb,
  started_at timestamptz not null,
  finished_at timestamptz
);
create table public.verdicts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  scan_id uuid not null references public.scans(id),
  photo_id uuid not null references public.photos(id),
  tier text not null check (tier in ('candidate','review','normal','no_face','unscorable')),
  reasons text[] not null default '{}'
    check (reasons <@ array['eyes_closed','exposure','blur','out_of_focus']),
  suspicion numeric check (suspicion is null or (suspicion >= 0 and suspicion <= 1)),
  face_count int check (face_count is null or face_count >= 0),
  error text,
  details jsonb not null default '{}'::jsonb,
  unique (scan_id, photo_id)
);
create table public.keep_marks (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  photo_id uuid not null references public.photos(id),
  marked_at timestamptz not null default now(),
  cancelled_at timestamptz
);
create unique index keep_marks_one_active_per_photo
  on public.keep_marks (photo_id) where cancelled_at is null;
create table public.sorts (
  id uuid primary key,
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  scan_id uuid not null references public.scans(id),
  out_path text,
  method text not null check (method in ('clone','copy')),
  tool_version text not null,
  counts jsonb not null default '{}'::jsonb,
  missing int not null default 0,
  unlisted int not null default 0,
  aborted boolean not null default false,
  created_at timestamptz not null default now()
);
create table public.sort_items (
  sort_id uuid not null references public.sorts(id),
  photo_id uuid not null references public.photos(id),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  folders text[] not null default '{}',
  kept boolean not null default false,
  primary key (sort_id, photo_id)
);
create index scans_event_id_idx on public.scans (event_id);
create index verdicts_photo_id_idx on public.verdicts (photo_id);
create index keep_marks_photo_id_idx on public.keep_marks (photo_id);
create index sorts_scan_id_idx on public.sorts (scan_id);
create index sort_items_photo_id_idx on public.sort_items (photo_id);

create function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = ''
as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, split_part(coalesce(new.email, ''), '@', 1))
  on conflict (id) do nothing;
  return new;
end;
$$;
revoke all on function public.handle_new_user() from public, anon, authenticated;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

alter table public.profiles enable row level security;
alter table public.events enable row level security;
alter table public.photos enable row level security;
alter table public.scans enable row level security;
alter table public.verdicts enable row level security;
alter table public.keep_marks enable row level security;
alter table public.sorts enable row level security;
alter table public.sort_items enable row level security;

create policy profiles_select_own on public.profiles for select to authenticated using (id = (select auth.uid()));
create policy profiles_update_own on public.profiles for update to authenticated using (id = (select auth.uid())) with check (id = (select auth.uid()));
create policy events_select_own on public.events for select to authenticated using (owner_id = (select auth.uid()));
create policy events_insert_own on public.events for insert to authenticated with check (owner_id = (select auth.uid()));
create policy events_update_own on public.events for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy photos_select_own on public.photos for select to authenticated using (owner_id = (select auth.uid()));
create policy photos_insert_own on public.photos for insert to authenticated with check (owner_id = (select auth.uid()));
create policy scans_select_own on public.scans for select to authenticated using (owner_id = (select auth.uid()));
create policy scans_insert_own on public.scans for insert to authenticated with check (owner_id = (select auth.uid()));
create policy verdicts_select_own on public.verdicts for select to authenticated using (owner_id = (select auth.uid()));
create policy verdicts_insert_own on public.verdicts for insert to authenticated with check (owner_id = (select auth.uid()));
create policy keep_marks_select_own on public.keep_marks for select to authenticated using (owner_id = (select auth.uid()));
create policy keep_marks_insert_own on public.keep_marks for insert to authenticated with check (owner_id = (select auth.uid()));
create policy keep_marks_update_own on public.keep_marks for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy sorts_select_own on public.sorts for select to authenticated using (owner_id = (select auth.uid()));
create policy sorts_insert_own on public.sorts for insert to authenticated with check (owner_id = (select auth.uid()));
create policy sort_items_select_own on public.sort_items for select to authenticated using (owner_id = (select auth.uid()));
create policy sort_items_insert_own on public.sort_items for insert to authenticated with check (owner_id = (select auth.uid()));

revoke all on all tables in schema public from anon;
revoke delete, truncate on all tables in schema public from authenticated;
revoke update on public.profiles, public.events, public.keep_marks from authenticated;
grant update (display_name, last_sign_in_at) on public.profiles to authenticated;
grant update (last_scan_folder) on public.events to authenticated;
grant update (cancelled_at) on public.keep_marks to authenticated;
alter default privileges in schema public revoke all on tables from anon;
