-- 셀렉 훑기 모드 DB 변경 (erd.md "적용 대기 변경", ADR-0007·0008)
-- 1) keep_marks -> photo_marks (kind: pick | maybe | discard). 옛 "남기기"는 셀렉(pick)과 같은 뜻이다.
-- 2) sort_items.kept -> mark_kind
-- 3) review_sessions 신규 (훑기 한 번의 시간·장수, 추가만 가능)
-- 지금 DB는 비어 있어 이름 바꾸기가 안전하다. 행이 있어도 옛 표시는 pick으로 옮겨진다.

-- 1) 표시: keep_marks -> photo_marks
alter table public.keep_marks rename to photo_marks;
alter table public.photo_marks
  add column kind text not null default 'pick' check (kind in ('pick', 'maybe', 'discard'));
alter table public.photo_marks alter column kind drop default;

alter table public.photo_marks rename constraint keep_marks_pkey to photo_marks_pkey;
alter table public.photo_marks rename constraint keep_marks_owner_id_fkey to photo_marks_owner_id_fkey;
alter table public.photo_marks rename constraint keep_marks_photo_id_fkey to photo_marks_photo_id_fkey;
alter index public.keep_marks_one_active_per_photo rename to photo_marks_one_active_per_photo;
alter index public.keep_marks_photo_id_idx rename to photo_marks_photo_id_idx;
alter policy keep_marks_select_own on public.photo_marks rename to photo_marks_select_own;
alter policy keep_marks_insert_own on public.photo_marks rename to photo_marks_insert_own;
alter policy keep_marks_update_own on public.photo_marks rename to photo_marks_update_own;

-- 2) 나누어 담기 항목: 담을 때 적용된 표시 (없으면 null)
alter table public.sort_items
  add column mark_kind text check (mark_kind in ('pick', 'maybe', 'discard'));
update public.sort_items set mark_kind = 'pick' where kept;
alter table public.sort_items drop column kept;

-- 3) 훑기 기록: 끝날 때 한 번에 올리고, 수정·삭제는 없다
create table public.review_sessions (
  id uuid primary key,
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  event_id uuid not null references public.events(id),
  scan_id uuid references public.scans(id),
  started_at timestamptz not null,
  ended_at timestamptz not null,
  photos_seen int not null check (photos_seen >= 0),
  pick_count int not null check (pick_count >= 0),
  maybe_count int not null check (maybe_count >= 0),
  discard_count int not null check (discard_count >= 0),
  tool_version text not null,
  check (ended_at >= started_at)
);
create index review_sessions_event_id_idx on public.review_sessions (event_id);
create index review_sessions_scan_id_idx on public.review_sessions (scan_id);

alter table public.review_sessions enable row level security;
create policy review_sessions_select_own on public.review_sessions
  for select to authenticated using (owner_id = (select auth.uid()));
create policy review_sessions_insert_own on public.review_sessions
  for insert to authenticated with check (owner_id = (select auth.uid()));

revoke all on public.review_sessions from anon;
revoke update, delete, truncate on public.review_sessions from authenticated;
