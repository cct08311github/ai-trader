from __future__ import annotations

_TEST_TOKEN = "test-bearer-token"
_AUTH_HEADERS = {"Authorization": f"Bearer {_TEST_TOKEN}"}


def test_get_proposals(client):
    r = client.get('/api/strategy/proposals?limit=10&offset=0', headers=_AUTH_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data['status'] == 'ok'
    assert isinstance(data['data'], list)
    assert data['data'][0]['proposal_id'] == 'p1'


def test_get_logs(client):
    r = client.get('/api/strategy/logs?limit=10&offset=0', headers=_AUTH_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data['status'] == 'ok'
    assert data['data'][0]['trace_id'] == 't1'


def test_rw_endpoints_disabled(client):
    # No Bearer token → 401 from auth middleware (before route is reached)
    r = client.post('/api/strategy/p1/approve', json={'actor': 'u', 'reason': 'x'})
    assert r.status_code in (401, 503)
