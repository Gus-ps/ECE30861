from .conftest import TARGET, auth


def test_swagger_declares_bearer_auth_for_all_tester_routes(make_client):
    client = make_client()
    spec = client.get('/openapi.json').json()
    scheme = spec['components']['securitySchemes']['HTTPBearer']
    assert scheme['type'] == 'http'
    assert scheme['scheme'] == 'bearer'
    for path, method in (('/test/setup', 'post'), ('/test/run', 'post'), ('/test/report', 'get')):
        operation = spec['paths'][path][method]
        assert operation['security'] == [{'HTTPBearer': []}]
        assert not any(p['name'].lower() == 'authorization'
                       for p in operation.get('parameters', []))


def test_bearer_validation_preserves_tester_errors_and_operator_access(make_client):
    client = make_client()
    for headers in ({}, {'Authorization': 'Basic abc'}, {'Authorization': 'Bearer wrong'}):
        response = client.post('/test/setup', json={'target_url': TARGET}, headers=headers)
        assert response.status_code == 401
        assert set(response.json()) == {'message', 'source'}
        assert response.json()['source'] == 'tester'
    response = client.post('/test/setup', json={'target_url': TARGET}, headers=auth())
    assert response.status_code == 201
