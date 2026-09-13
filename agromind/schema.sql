create schema if not exists agromind;
create table if not exists agromind.users (
 id uuid primary key, email text unique not null, password_hash text not null,
 created_at timestamptz not null default now()
);
create table if not exists agromind.sessions (
 token_hash text primary key, user_id uuid not null references agromind.users(id) on delete cascade,
 expires_at timestamptz not null
);

create table if not exists agromind.profiles (
  id uuid primary key references agromind.users(id) on delete cascade,
  email text,
  full_name text,
  organization text,
  role text not null default 'member',
  plan text not null default 'starter',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists agromind.ai_outputs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references agromind.users(id) on delete set null,
  domain text not null,
  tool text not null,
  prompt jsonb not null default '{}'::jsonb,
  output_markdown text not null,
  input_file_url text,
  tokens_used integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists agromind.usage_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references agromind.users(id) on delete set null,
  domain text not null,
  tool text not null,
  provider text not null,
  tokens_used integer not null default 0,
  credits_used integer not null default 0,
  cost_cents integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists agromind.subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references agromind.users(id) on delete cascade,
  plan text not null,
  status text not null default 'active',
  current_period_end timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists agromind.payments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references agromind.users(id) on delete set null,
  plan text not null,
  amount_paise integer not null default 0,
  provider text not null default 'razorpay',
  provider_order_id text,
  provider_payment_id text,
  status text not null default 'created',
  created_at timestamptz not null default now()
);

create table if not exists agromind.connected_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references agromind.users(id) on delete cascade,
  provider text not null,
  provider_account_id text,
  provider_email text,
  encrypted_refresh_token text,
  scopes text[] not null default '{}',
  status text not null default 'connected',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, provider)
);

create table if not exists agromind.agent_action_drafts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references agromind.users(id) on delete cascade,
  source_output_id uuid references agromind.ai_outputs(id) on delete set null,
  action_type text not null,
  provider text not null,
  draft_payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists agromind.agent_action_runs (
  id uuid primary key default gen_random_uuid(),
  draft_id uuid references agromind.agent_action_drafts(id) on delete cascade,
  user_id uuid references agromind.users(id) on delete cascade,
  provider text not null,
  status text not null,
  result jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now()
);

create table if not exists agromind.agent_memory (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references agromind.users(id) on delete cascade,
  agent text not null,
  session_id text not null,
  role text not null,
  content text not null,
  created_at timestamptz not null default now()
);


create index if not exists outputs_user_created on agromind.ai_outputs(user_id, created_at desc);
create index if not exists usage_user_created on agromind.usage_events(user_id, created_at desc);
create index if not exists memory_session_created on agromind.agent_memory(user_id, agent, session_id, created_at desc);
