create extension if not exists "uuid-ossp";

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text,
  organization text,
  role text not null default 'member',
  plan text not null default 'starter',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.ai_outputs (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references auth.users(id) on delete set null,
  domain text not null,
  tool text not null,
  prompt jsonb not null default '{}'::jsonb,
  output_markdown text not null,
  input_file_url text,
  tokens_used integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists public.usage_events (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references auth.users(id) on delete set null,
  domain text not null,
  tool text not null,
  provider text not null,
  tokens_used integer not null default 0,
  credits_used integer not null default 0,
  cost_cents integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists public.subscriptions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references auth.users(id) on delete cascade,
  plan text not null,
  status text not null default 'active',
  current_period_end timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.payments (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references auth.users(id) on delete set null,
  plan text not null,
  amount_paise integer not null default 0,
  provider text not null default 'razorpay',
  provider_order_id text,
  provider_payment_id text,
  status text not null default 'created',
  created_at timestamptz not null default now()
);

create table if not exists public.connected_accounts (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references auth.users(id) on delete cascade,
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

create table if not exists public.agent_action_drafts (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references auth.users(id) on delete cascade,
  source_output_id uuid references public.ai_outputs(id) on delete set null,
  action_type text not null,
  provider text not null,
  draft_payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.agent_action_runs (
  id uuid primary key default uuid_generate_v4(),
  draft_id uuid references public.agent_action_drafts(id) on delete cascade,
  user_id uuid references auth.users(id) on delete cascade,
  provider text not null,
  status text not null,
  result jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now()
);

alter table public.usage_events add column if not exists credits_used integer not null default 0;

alter table public.profiles enable row level security;
alter table public.ai_outputs enable row level security;
alter table public.usage_events enable row level security;
alter table public.subscriptions enable row level security;
alter table public.payments enable row level security;
alter table public.connected_accounts enable row level security;
alter table public.agent_action_drafts enable row level security;
alter table public.agent_action_runs enable row level security;

create policy "Users can read own profile"
on public.profiles for select
using (auth.uid() = id);

create policy "Users can update own profile"
on public.profiles for update
using (auth.uid() = id);

create policy "Users can read own outputs"
on public.ai_outputs for select
using (auth.uid() = user_id);

create policy "Users can insert own outputs"
on public.ai_outputs for insert
with check (auth.uid() = user_id);

create policy "Users can read own usage"
on public.usage_events for select
using (auth.uid() = user_id);

create policy "Users can insert own usage"
on public.usage_events for insert
with check (auth.uid() = user_id);


create policy "Users can read own subscriptions"
on public.subscriptions for select
using (auth.uid() = user_id);

create policy "Users can insert own subscriptions"
on public.subscriptions for insert
with check (auth.uid() = user_id);

create policy "Users can update own subscriptions"
on public.subscriptions for update
using (auth.uid() = user_id);

create policy "Users can read own payments"
on public.payments for select
using (auth.uid() = user_id);

create policy "Users can insert own payments"
on public.payments for insert
with check (auth.uid() = user_id);

create policy "Users can update own payments"
on public.payments for update
using (auth.uid() = user_id);

create policy "Users can read own connected accounts"
on public.connected_accounts for select
using (auth.uid() = user_id);

create policy "Users can insert own connected accounts"
on public.connected_accounts for insert
with check (auth.uid() = user_id);

create policy "Users can update own connected accounts"
on public.connected_accounts for update
using (auth.uid() = user_id);

create policy "Users can read own action drafts"
on public.agent_action_drafts for select
using (auth.uid() = user_id);

create policy "Users can insert own action drafts"
on public.agent_action_drafts for insert
with check (auth.uid() = user_id);

create policy "Users can update own action drafts"
on public.agent_action_drafts for update
using (auth.uid() = user_id);

create policy "Users can read own action runs"
on public.agent_action_runs for select
using (auth.uid() = user_id);

create policy "Users can insert own action runs"
on public.agent_action_runs for insert
with check (auth.uid() = user_id);

create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, email, full_name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'full_name', 'AgroMind User'));
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_user();
