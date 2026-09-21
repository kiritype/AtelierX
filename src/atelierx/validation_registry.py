"""Immutable runtime snapshots used after Core registers revisioned settings."""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

from .common import ApiError

PROFILE_FIELDS = {"profile_id", "revision", "output_conditions", "positive_prompt", "negative_prompt", "body_parts", "metadata", "consistency"}
GROUP_PROFILE_FIELDS = {"profile_id", "revision", "consistency"}
PROVIDER_FIELDS = {"provider_id", "revision", "model", "timeout_seconds"}
OPTIONAL_PROVIDER_FIELDS = {"max_tokens"}


def public_provider(value):
    return {key: value[key] for key in PROVIDER_FIELDS | OPTIONAL_PROVIDER_FIELDS if key in value}


def revision_key(value, field):
    ident, revision = value.get(field), value.get("revision")
    if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", ident) or type(revision) is not int or revision < 1:
        raise ApiError("VAL_REGISTRY_INVALID", "Invalid setting id or revision", 422)
    return ident, revision


class RevisionRegistry:
    """A revision map. Legacy JSON configuration stays live until Core registers."""
    def __init__(self, providers=None, profiles=None, path=None):
        self.providers, self.profiles, self.enabled = {}, {}, False
        # The server configuration registry uses its map key as the provider
        # identity.  Core sends that same ID in public snapshots, while the
        # configured value intentionally need not duplicate it.
        configured_providers = []
        for ident, value in (providers or {}).items():
            if isinstance(value, dict):
                configured_providers.append(dict(value, provider_id=value.get("provider_id", ident)))
        self.credential_sources = copy.deepcopy(configured_providers)
        self.path = Path(path) if path else None
        for value in (profiles or {}).values():
            if isinstance(value, dict) and "profile_id" in value and "revision" in value:
                self.profiles[(value["profile_id"], value["revision"])] = copy.deepcopy(value)
        for value in configured_providers:
            if isinstance(value, dict) and "provider_id" in value and "revision" in value:
                self.providers[(value["provider_id"], value["revision"])] = copy.deepcopy(value)
        self._restore()

    def _restore(self):
        if not self.path or not self.path.exists(): return
        try:
            snapshot=json.loads(self.path.read_text(encoding="utf-8"))
            # apply merges config-owned credentials for a matching revision.
            self.apply(snapshot, persist=False)
        except (OSError, ValueError, ApiError) as exc:
            raise RuntimeError("Invalid persisted Validation revision registry") from exc

    def snapshot(self):
        return {"profiles":[copy.deepcopy(v) for _,v in sorted(self.profiles.items())], "providers":[{k:v for k,v in item.items() if k not in {"api_key","api_key_env"}} for _,item in sorted(self.providers.items())]}

    def _save(self):
        if not self.path: return
        temporary=self.path.with_suffix(".tmp")
        with temporary.open("w",encoding="utf-8") as stream:
            json.dump(self.snapshot(),stream,ensure_ascii=False,sort_keys=True,separators=(",",":")); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(self.path)

    def apply(self, snapshot, persist=True):
        if not isinstance(snapshot, dict) or set(snapshot) != {"providers", "profiles"} or not all(isinstance(snapshot[k], list) for k in snapshot):
            raise ApiError("VAL_REGISTRY_INVALID", "Registry requires providers and profiles", 422)
        profiles, providers = {}, {}
        for profile in snapshot["profiles"]:
            fields = set(profile) if isinstance(profile, dict) else None
            if not isinstance(profile, dict) or fields not in (PROFILE_FIELDS, GROUP_PROFILE_FIELDS) or (fields == GROUP_PROFILE_FIELDS and profile["consistency"] is not True):
                raise ApiError("VAL_REGISTRY_INVALID", "Invalid profile registry entry", 422)
            key = revision_key(profile, "profile_id")
            if key in profiles and profiles[key] != profile: raise ApiError("VAL_REGISTRY_CONFLICT", "Profile revision is immutable", 409)
            profiles[key] = copy.deepcopy(profile)
        for provider in snapshot["providers"]:
            allowed = PROVIDER_FIELDS | OPTIONAL_PROVIDER_FIELDS | {"url", "response_format", "image_format", "shared_gpu"}
            if not isinstance(provider, dict) or not PROVIDER_FIELDS <= set(provider) or set(provider) - allowed:
                raise ApiError("VAL_REGISTRY_INVALID", "Invalid provider registry entry", 422)
            if not isinstance(provider.get("url"), str) or not provider["url"].startswith(("http://", "https://")):
                raise ApiError("VAL_REGISTRY_INVALID", "Provider endpoint is invalid", 422)
            key = revision_key(provider, "provider_id")
            if not isinstance(provider["model"], str) or not provider["model"] or type(provider["timeout_seconds"]) is not int or provider["timeout_seconds"] < 1:
                raise ApiError("VAL_REGISTRY_INVALID", "Invalid provider model or timeout", 422)
            if "max_tokens" in provider and (type(provider["max_tokens"]) is not int or provider["max_tokens"] < 1):
                raise ApiError("VAL_REGISTRY_INVALID", "Invalid provider max_tokens", 422)
            if key in providers and {k:v for k,v in providers[key].items() if k not in {"api_key","api_key_env"}} != provider: raise ApiError("VAL_REGISTRY_CONFLICT", "Provider revision is immutable", 409)
            runtime = copy.deepcopy(provider)
            runtime["api_key"] = next((source.get("api_key", "") for source in self.credential_sources
                if source.get("provider_id") == provider["provider_id"] and source.get("url") == provider["url"]), "")
            providers[key] = runtime
        # Validate the entire payload before mutation, then merge. A client cannot
        # erase an older revision that durable jobs still reference.
        for key, value in profiles.items():
            if key in self.profiles and self.profiles[key] != value: raise ApiError("VAL_REGISTRY_CONFLICT", "Profile revision is immutable", 409)
        for key, value in providers.items():
            existing = self.providers.get(key)
            if existing and {k:v for k,v in existing.items() if k not in {"api_key","api_key_env"}} != {k:v for k,v in value.items() if k not in {"api_key","api_key_env"}}: raise ApiError("VAL_REGISTRY_CONFLICT", "Provider revision is immutable", 409)
        self.profiles.update(profiles); self.providers.update(providers); self.enabled = True
        if persist: self._save()

    def profile(self, value):
        key = (value.get("profile_id"), value.get("revision"))
        if self.profiles.get(key) != value: raise ApiError("VAL_PROFILE_MISMATCH", "Profile snapshot does not match configured revision", 422)
        return self.profiles[key]

    def provider(self, value):
        key = (value.get("provider_id"), value.get("revision")); config = self.providers.get(key)
        if not config or public_provider(config) != value: raise ApiError("VAL_PROVIDER_MISMATCH", "Provider snapshot does not match configured revision", 422)
        return config
