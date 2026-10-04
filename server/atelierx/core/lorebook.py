"""Per-entry lorebook activation options (data-model: 로어북 활성화 옵션).

Reserved structure only. The editor keeps an ``activation`` map as-is and nothing reads it yet; the chat test
still follows the platform preset. When an option is applied, its reader starts from ``activation_of``.
"""

SCAN_DEPTH_MAX = 5

# Value used when the entry does not set the option. ``None`` means "follow the platform preset".
ACTIVATION_DEFAULTS = {
    'in_start': True,  # also match keywords in the start situation (the bot's first message)
    'scan_depth': None,  # 0-5 recent turns (0 = current input only) or 'all'
    'mode': 'on_match',  # on_match: keyword turns it on / off_match: keyword turns an always entry off
    'group': None,  # among active entries with the same group, only the highest priority stays
    'requires': [],  # entry IDs that must be active for this one to activate
}

MODES = ('on_match', 'off_match')


def activation_of(meta):
    """The entry's activation options with defaults filled in. Unknown or invalid values fall back to defaults."""
    raw = meta.get('activation') if isinstance(meta, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    result = dict(ACTIVATION_DEFAULTS, requires=[])
    if isinstance(raw.get('in_start'), bool):
        result['in_start'] = raw['in_start']
    depth = raw.get('scan_depth')
    if depth == 'all' or (
        isinstance(depth, int) and not isinstance(depth, bool) and 0 <= depth <= SCAN_DEPTH_MAX
    ):
        result['scan_depth'] = depth
    if raw.get('mode') in MODES:
        result['mode'] = raw['mode']
    if isinstance(raw.get('group'), str) and raw['group'].strip():
        result['group'] = raw['group'].strip()
    if isinstance(raw.get('requires'), list):
        result['requires'] = [str(r) for r in raw['requires'] if str(r).strip()]
    return result
