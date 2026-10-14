def test_preview_response_enforces_sandbox_independent_of_parent(client, paths):
    paths.web.mkdir(exist_ok=True)
    (paths.web / 'preview.html').write_text('<html>fixture</html>')
    (paths.web / 'index.html').write_text('<html>app</html>')
    response = client.get('/preview.html')
    assert response.status_code == 200
    policy = response.headers['content-security-policy']
    assert 'sandbox allow-scripts;' in policy
    assert 'allow-same-origin' not in policy
    assert "connect-src 'none'" in policy
    assert "frame-ancestors 'self'" in policy
    assert "form-action 'none'" in policy
    assert 'content-security-policy' not in client.get('/').headers
