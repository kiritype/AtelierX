import sys

import pytest

from atelierx.desktop import unblock_bundle

MARK = '[ZoneTransfer]\nZoneId=3\n'


@pytest.mark.skipif(sys.platform != 'win32', reason='Zone.Identifier is an NTFS stream on Windows')
def test_unblock_bundle_removes_the_download_mark_from_dlls_only(tmp_path):
    (tmp_path / 'pythonnet' / 'runtime').mkdir(parents=True)
    dll = tmp_path / 'pythonnet' / 'runtime' / 'Python.Runtime.dll'
    clean = tmp_path / 'clean.dll'
    other = tmp_path / 'notes.txt'
    for file in (dll, clean, other):
        file.write_bytes(b'x')
    for file in (dll, other):
        with open(f'{file}:Zone.Identifier', 'w', encoding='ascii') as stream:
            stream.write(MARK)

    assert unblock_bundle(tmp_path) == 1
    with pytest.raises(FileNotFoundError):
        open(f'{dll}:Zone.Identifier', encoding='ascii').close()
    assert dll.read_bytes() == b'x'
    with open(f'{other}:Zone.Identifier', encoding='ascii') as stream:
        assert stream.read() == MARK
    assert unblock_bundle(tmp_path) == 0
