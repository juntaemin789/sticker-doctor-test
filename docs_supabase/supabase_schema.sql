-- Supabase 대시보드 > SQL Editor 에 통째로 붙여넣고 Run 하세요. (최초 1회)
-- 기존 SQLite(user_store.py)와 같은 4개 테이블입니다.

create table if not exists public.users (
    id             bigint generated always as identity primary key,
    username       text not null unique check (char_length(username) between 2 and 30),
    password_hash  text not null,
    password_salt  text not null,
    birth_date     date,
    created_at     timestamptz not null default now()
);

-- 이미 테이블을 만들어 둔 경우를 위한 한 줄 (처음이면 없어도 됨)
alter table public.users add column if not exists birth_date date;

create table if not exists public.auth_sessions (
    id           bigint generated always as identity primary key,
    user_id      bigint not null references public.users(id) on delete cascade,
    token_hash   text not null unique,
    created_at   timestamptz not null default now(),
    last_seen_at timestamptz not null default now()
);

create table if not exists public.diagnosis_records (
    id               bigint generated always as identity primary key,
    user_id          bigint not null references public.users(id) on delete cascade,
    created_at       timestamptz not null default now(),
    score            real,
    pass_count       integer not null default 0,
    warn_count       integer not null default 0,
    fail_count       integer not null default 0,
    checklist_done   integer not null default 0,
    checklist_total  integer not null default 0,
    file_count       integer not null default 0,
    market_keywords  jsonb not null default '[]'::jsonb,
    diagnosis_json   jsonb not null default '{}'::jsonb
);

create table if not exists public.reviews (
    id                   bigint generated always as identity primary key,
    diagnosis_record_id  bigint not null references public.diagnosis_records(id) on delete cascade,
    user_id              bigint not null references public.users(id) on delete cascade,
    created_at           timestamptz not null default now(),
    overall_rating       smallint not null check (overall_rating between 1 and 5),
    usefulness_rating    smallint not null check (usefulness_rating between 1 and 5),
    accuracy_rating      smallint not null check (accuracy_rating between 1 and 5),
    issue_tags           jsonb not null default '[]'::jsonb,
    comment              text not null default '',
    visibility           text not null default 'public' check (visibility in ('public', 'developer')),
    unique (diagnosis_record_id, user_id)
);

create index if not exists idx_auth_sessions_user  on public.auth_sessions(user_id);
create index if not exists idx_diagnosis_user      on public.diagnosis_records(user_id, id desc);
create index if not exists idx_reviews_record      on public.reviews(diagnosis_record_id, id desc);
create index if not exists idx_reviews_visibility  on public.reviews(visibility, id desc);

-- ── 보안 (중요) ─────────────────────────────────────────────
-- RLS를 켜고 정책을 하나도 만들지 않으면, anon/authenticated 키로는
-- 어떤 행도 읽거나 쓸 수 없습니다. 앱 서버(Streamlit)는 service_role 키로만 접근합니다.
alter table public.users             enable row level security;
alter table public.auth_sessions     enable row level security;
alter table public.diagnosis_records enable row level security;
alter table public.reviews           enable row level security;

revoke all on public.users, public.auth_sessions, public.diagnosis_records, public.reviews
    from anon, authenticated;
