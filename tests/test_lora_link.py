"""Trained LoRAs in the app, read by ComfyUI through an ``atelierx`` folder link (#160)."""

import pytest

from atelierx.image.lora import link


def _setup(paths, tmp_path):
    comfy = tmp_path / 'comfy' / 'models' / 'loras'
    comfy.mkdir(parents=True)
    return {'loras': [str(comfy), str(tmp_path / 'comfy' / 'output' / 'loras')]}, comfy


def test_the_app_folder_is_linked_into_comfyui_and_new_files_show_through_it(paths, tmp_path):
    folders, comfy = _setup(paths, tmp_path)
    values = {'lora_dir': ''}
    assert link.status(paths, values, folders)['state'] == 'missing'
    done = link.connect(paths, values, folders)
    assert done['state'] == 'linked' and done['folder'] == str(paths.output / 'loras')
    (paths.output / 'loras' / 'c001-e10.safetensors').write_bytes(b'lora')
    assert (comfy / 'atelierx' / 'c001-e10.safetensors').read_bytes() == b'lora'
    # Connecting again changes nothing.
    assert link.connect(paths, values, folders)['state'] == 'linked'


def test_a_moved_app_folder_is_linked_again_and_a_foreign_folder_is_left_alone(paths, tmp_path):
    folders, comfy = _setup(paths, tmp_path)
    old = tmp_path / 'old-app' / 'loras'
    old.mkdir(parents=True)
    (old / 'keep.safetensors').write_bytes(b'old')
    link.connect(paths, {'lora_dir': str(old)}, folders)
    assert link.status(paths, {'lora_dir': ''}, folders)['state'] == 'broken'
    assert link.connect(paths, {'lora_dir': ''}, folders)['state'] == 'linked'
    # Only the link was replaced; the folder it pointed at keeps its files.
    assert (old / 'keep.safetensors').read_bytes() == b'old'

    # Someone else's real folder under the same name.
    import os

    os.rmdir(comfy / 'atelierx') if not (comfy / 'atelierx').is_symlink() else (comfy / 'atelierx').unlink()
    (comfy / 'atelierx').mkdir()
    (comfy / 'atelierx' / 'theirs.safetensors').write_bytes(b'x')
    assert link.status(paths, {'lora_dir': ''}, folders)['state'] == 'conflict'
    with pytest.raises(ValueError) as raised:
        link.connect(paths, {'lora_dir': ''}, folders)
    assert raised.value.args[0].key == 'server.lora_link.conflict'
    assert (comfy / 'atelierx' / 'theirs.safetensors').is_file()


def test_an_older_comfyui_folder_setting_needs_no_link_and_can_move_into_the_app(paths, tmp_path):
    folders, comfy = _setup(paths, tmp_path)
    legacy = comfy / 'anima'
    legacy.mkdir()
    (legacy / 'c001-e20.safetensors').write_bytes(b'lora')
    values = {'lora_dir': str(legacy)}
    assert link.status(paths, values, folders)['state'] == 'inside'

    renamed = []
    moved = link.move_into_app(paths, values, lambda old, new: renamed.append((old, new)))
    assert moved == ['c001-e20.safetensors'] and not (legacy / 'c001-e20.safetensors').exists()
    assert (paths.output / 'loras' / 'c001-e20.safetensors').read_bytes() == b'lora'
    assert renamed == [('c001-e20.safetensors', 'atelierx\\c001-e20.safetensors')]


def test_no_comfyui_lora_folder_is_reported(paths):
    assert link.status(paths, {}, None)['state'] == 'no_comfy'
    with pytest.raises(ValueError):
        link.connect(paths, {}, {'loras': []})
