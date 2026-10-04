from tools.audit_public import contains_high_confidence_credential, path_findings


def test_public_sample_fixture_allowlist_is_narrow():
    assert path_findings('samples/demo/.atelierx/work.json') == []
    assert path_findings('samples/demo/output/model.safetensors')
    assert path_findings('data/work.json')


def test_secret_scan_reports_path_without_returning_secret():
    secret = b'ghp_' + b'A' * 40
    assert contains_high_confidence_credential(secret)
    assert not contains_high_confidence_credential(b'ghp_' + b'x' * 8)


def test_historical_sensitive_filename_is_explicit():
    findings = path_findings('notes/ROADMAP.md', historical=True)
    assert len(findings) == 1
    assert findings[0]['reason'].startswith('historical filename:')
