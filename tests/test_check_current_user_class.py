import pytest
from app import create_app
from app.repositories import UserRepository
from app.database import get_cursor

@pytest.fixture()
def test_app():
    return create_app("testing")

@pytest.fixture()
def test_client(test_app):
    return test_app.test_client()

@pytest.fixture()
def test_auth_client(test_client):
    # Check user before login
    with test_client.session_transaction() as sess:
        print('Session before login:', dict(sess))
    
    resp = test_client.post(
        "/auth/login",
        data={"username": "admin", "password": "Admin@123", "remember": "on"},
        follow_redirects=False,
    )
    print('Login response status:', resp.status_code)
    print('Login response headers:', dict(resp.headers))
    
    with test_client.session_transaction() as sess:
        print('Session after login:', dict(sess))
    
    return test_client

@pytest.fixture(autouse=True)
def _reset_admin_user(test_app):
    with test_app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("UPDATE users SET role = 'admin', is_active = TRUE WHERE username = 'admin'")
    yield

class TestCheckCurrentUser:
    def test_check_current_user(self, test_auth_client, test_app):
        with test_auth_client.session_transaction() as sess:
            print('Session at test start:', dict(sess))
        
        resp = test_auth_client.get('/admin/users/')
        print('GET /admin/users/ status:', resp.status_code)
        
        with test_auth_client.session_transaction() as sess:
            print('Session after GET:', dict(sess))
        
        resp = test_auth_client.post('/admin/users/change-role/1', data={'role': 'viewer', 'csrf_token': 'test'}, follow_redirects=True)
        print('POST change-role status:', resp.status_code)
        print('Flash found:', b'you cannot change your own role' in resp.data.lower())
        
        with test_auth_client.session_transaction() as sess:
            print('Session after POST:', dict(sess))
        
        with test_app.app_context():
            admin_user = UserRepository.find_by_username("admin")
            print('Final admin role:', admin_user.role)
            assert admin_user.role == "admin"