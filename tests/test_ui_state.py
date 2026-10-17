"""UI state updates must preserve unrelated keys after two clients read the same state."""


def test_stale_clients_patch_distinct_work_and_app_state(unlocked):
    url = '/api/ui-state'
    initial = {
        'future_key': {'keep': True},
        'works': {'one': {'tabs': ['old'], 'future_work_key': 7, 'sidebar': {'future': 9}}},
        'persona_by_work': {'two': 'old-persona'},
    }
    assert unlocked.put(url, json=initial).status_code == 200

    # Both clients have the same old snapshot. Whole-document PUT of either snapshot
    # after the other's write would erase the other client's changes.
    first_snapshot = unlocked.get(url).json()
    second_snapshot = unlocked.get(url).json()
    assert first_snapshot == second_snapshot
    first_snapshot['works']['one']['tabs'] = ['new']
    second_snapshot['works']['two'] = {'tabs': ['other']}
    assert unlocked.put(url, json=first_snapshot).status_code == 200
    assert unlocked.put(url, json=second_snapshot).status_code == 200
    assert unlocked.get(url).json()['works']['one']['tabs'] == ['old']
    assert unlocked.put(url, json=initial).status_code == 200

    assert (
        unlocked.patch(
            url, json={'works': {'one': {'tabs': ['new'], 'sidebar': {'collapsed': True}}}}
        ).status_code
        == 200
    )
    assert unlocked.patch(url, json={'works': {'two': {'tabs': ['other']}}}).status_code == 200
    assert unlocked.patch(url, json={'last_work': 'two'}).status_code == 200
    assert (
        unlocked.patch(url, json={'persona_by_work': {'one': 'new-persona', 'two': None}}).status_code == 200
    )

    assert unlocked.get(url).json() == {
        'future_key': {'keep': True},
        'works': {
            'one': {'tabs': ['new'], 'future_work_key': 7, 'sidebar': {'future': 9, 'collapsed': True}},
            'two': {'tabs': ['other']},
        },
        'last_work': 'two',
        'persona_by_work': {'one': 'new-persona'},
    }


def test_ui_state_patch_rejects_unrelated_or_malformed_updates(unlocked):
    url = '/api/ui-state'
    for changes in ({'works': {'one': []}}, {'works': []}, {'persona_by_work': {'one': 4}}, {'unknown': 1}):
        assert unlocked.patch(url, json=changes).status_code == 400
    assert unlocked.get(url).json() == {}
