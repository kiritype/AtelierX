# Backend recovery regression checks

`tests/test_backend_recovery.py` covers Generation persistence boundaries that
must not cause a second ComfyUI submission: unknown/path-like image IDs,
missing saved Anima context, completion-versus-cancel output discard, and
restart restoration of an idempotency key.

Independent postprocess intentionally keeps completed idempotency-key lookup
available even if a stored file later disappears or changes. The Generation
worker separately recomputes the stored source SHA-256 immediately before
ComfyUI upload and rejects changed bytes with `GEN_IMAGE_INTEGRITY`.

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_backend_recovery -v
```

No GPU, ComfyUI process, dependency installation, or live provider is used.
