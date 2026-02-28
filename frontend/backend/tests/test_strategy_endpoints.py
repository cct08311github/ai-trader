from __future__ import annotations


def test_get_proposals(client):
    r = client.get('/api/strategy/proposals?limit=10&offset=0')
    assert r.status_code == 200
    data = r.json()
    assert data['status'] == 'ok'
    assert isinstance(data['data'], list)
    assert data['data'][0]['proposal_id'] == 'p1'


def test_get_logs(client):
    r = client.get('/api/strategy/logs?limit=10&offset=0')
    assert r.status_code == 200
    data = r.json()
    assert data['status'] == 'ok'
    assert data['data'][0]['trace_id'] == 't1'


def test_rw_endpoints_disabled(client):
    r = client.post('/api/strategy/p1/approve', json={'actor':'u','reason':'x'}, headers={'X-OPS-TOKEN':'nope'})
    # unauthorized comes before 405
    assert r.status_code in (401, 503)
