"""Real PostgreSQL tests, each rolled back; opt in with AGROMIND_TEST_DATABASE_URL."""
import os
from contextlib import contextmanager
import re
import uuid
import psycopg
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient
from agromind import postgres_store as store
from agromind import main
from pathlib import Path


@pytest.fixture
def database(monkeypatch):
    url = os.getenv('AGROMIND_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set AGROMIND_TEST_DATABASE_URL for PostgreSQL integration tests')
    conn = psycopg.connect(url, row_factory=dict_row)
    conn.execute(Path('agromind/schema.sql').read_text())
    @contextmanager
    def isolated_connection():
        # Savepoints allow expected constraint failures without aborting the test transaction.
        with conn.transaction():
            yield conn
    monkeypatch.setattr(store, 'connection', isolated_connection)
    monkeypatch.setattr(store, 'database_url', lambda: url)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def account():
    email = f'test-{uuid.uuid4().hex}@example.com'
    user = store.create_confirmed_user_with_password(email, 'password123', 'Test User')
    return store.sign_in_with_password(email.upper(), 'password123')


def test_password_login_sessions_and_duplicate_signup(database):
    user = account()
    row = database.execute('SELECT password_hash FROM agromind.users WHERE id=%s', (user['id'],)).fetchone()
    assert 'password123' not in row['password_hash']
    assert store.session_user(user['access_token'])['id'] == user['id']
    with pytest.raises(ValueError, match='Invalid'):
        store.sign_in_with_password(user['email'], 'wrong-password')
    with pytest.raises(ValueError, match='already exists'):
        store.create_confirmed_user_with_password(user['email'].upper(), 'password123')
    assert store.session_user('invalid-token') is None
    store.update_user_password(user['access_token'], 'changed-password')
    assert store.session_user(user['access_token']) is None
    assert store.sign_in_with_password(user['email'], 'changed-password')['id'] == user['id']


def test_outputs_usage_memory_billing_and_profile(database):
    user, other = account(), account()
    uid, token = user['id'], user['access_token']
    oid = store.save_output(uid, 'agriculture', 'crop', {'question':'test'}, 'answer', 'test', 10, 2, 3, token)
    assert store.fetch_output_by_id(oid, token)['prompt'] == {'question':'test'}
    assert store.fetch_output_by_id(oid, other['access_token']) is None
    assert store.fetch_output_by_id('invalid', token) is None
    assert store.usage_summary(uid)['credits_this_month'] == 2
    store.save_agent_memory(uid, 'chatbot', 's1', 'user', 'hello', token)
    assert store.fetch_agent_memory(uid, 'chatbot', 's1')[0]['content'] == 'hello'
    assert store.fetch_agent_memory(other['id'], 'chatbot', 's1') == []
    store.save_payment(uid, 'pro', 100, 'sandbox-test')
    store.save_subscription(uid, 'pro')
    store.update_profile_plan(uid, 'pro')
    store.update_profile(uid, {'full_name':'Updated', 'role':'Farmer'})
    assert store.fetch_profile(uid)['role'] == 'Farmer'
    with pytest.raises(ValueError, match='Administrator'):
        store.update_profile(uid, {'role':'admin'})
    assert store.fetch_profile(uid)['plan'] == 'pro'
    draft = store.create_agent_action_draft(uid, oid, 'test', 'test', {})
    assert store.update_agent_action_draft(draft['id'], {'status':'completed'}, token)['status'] == 'completed'
    store.save_agent_action_run(draft['id'], uid, 'test', 'completed')


def test_browser_signup_login_logout_and_expiration(database):
    email = f'browser-{uuid.uuid4().hex}@example.com'
    def csrf(response):
        return re.search(r'name="csrf_token" value="([^"]+)"', response.text)[1]
    with TestClient(main.app) as client:
        token = csrf(client.get('/signup'))
        response = client.post('/signup', data=dict(email=email, full_name='Browser', password='password123', csrf_token=token), follow_redirects=False)
        assert response.status_code == 303
        assert client.get('/dashboard').status_code == 200
        assert client.get('/profile').status_code == 200
        cookie = client.cookies.get('session')
        client.get('/logout')
        client.cookies.set('session', cookie)
        assert client.get('/dashboard', follow_redirects=False).status_code == 303
        client.cookies.clear()
        token = csrf(client.get('/login'))
        response = client.post('/login', data=dict(email=email, password='password123', csrf_token=token), follow_redirects=False)
        assert response.status_code == 303
        database.execute('UPDATE agromind.sessions SET expires_at=now() - interval \'1 second\' WHERE user_id=(SELECT id FROM agromind.users WHERE email=%s)', (email,))
        assert client.get('/dashboard', follow_redirects=False).status_code == 303
