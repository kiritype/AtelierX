"""Cloudflare Access authentication and private frontend connection storage."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlsplit

import aiohttp
import jwt
from jwt.algorithms import RSAAlgorithm

from .common import ApiError


_MAX_JWKS_BYTES = 128 * 1024
_CACHE_SECONDS = 300
_REFRESH_COOLDOWN_SECONDS = 15
_MAX_ASSERTION_BYTES = 16 * 1024


def _bad_config(message):
    raise ValueError("Invalid frontend connection configuration: " + message)


def _https_origin(value, name):
    if not isinstance(value, str):
        _bad_config(name + " must be text")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        _bad_config(name + " has an invalid port")
    if (parsed.scheme != "https" or not parsed.netloc or not parsed.hostname or parsed.username or parsed.password or
            parsed.path not in ("", "/") or parsed.query or parsed.fragment or any(ord(char) < 32 for char in value)):
        _bad_config(name + " must be an HTTPS origin")
    return value.rstrip("/")


def validate_config(value):
    required = {"public_origin", "issuer", "audience", "allowed_emails", "core_token"}
    if not isinstance(value, dict) or set(value) != required:
        _bad_config("has missing or unknown fields")
    result = dict(value)
    result["public_origin"] = _https_origin(value["public_origin"], "public_origin")
    result["issuer"] = _https_origin(value["issuer"], "issuer")
    if not isinstance(value["audience"], str) or not value["audience"].strip() or len(value["audience"]) > 1000:
        _bad_config("audience must be nonempty text")
    if (not isinstance(value["core_token"], str) or not value["core_token"] or len(value["core_token"]) > 2000 or
            any(char in value["core_token"] for char in "\r\n\x00")):
        _bad_config("core_token must be nonempty text")
    try:
        value["core_token"].encode("utf-8")
    except UnicodeEncodeError:
        _bad_config("core_token must be UTF-8 text")
    if not isinstance(value["allowed_emails"], list) or not value["allowed_emails"]:
        _bad_config("allowed_emails must be a nonempty array")
    if any(not isinstance(email, str) or not email.strip() or len(email) > 320 for email in value["allowed_emails"]):
        _bad_config("allowed_emails must contain nonempty text")
    result["allowed_emails"] = list(value["allowed_emails"])
    return result


class FrontendConnection:
    def __init__(self, path, core_token):
        self.path = Path(path) if path else None
        self.core_token = core_token
        self.config = self._load()
        self._keys = {}
        self._keys_at = float("-inf")
        self._last_refresh = float("-inf")
        self._lock = asyncio.Lock()

    def _load(self):
        if self.path is None or not self.path.is_file():
            return None
        try:
            return validate_config(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("Unable to load frontend connection configuration") from exc

    def status(self, mode):
        config = self.config
        return {"configured": config is not None,
                "connected": self.matches_core_token(),
                "auth_mode": mode,
                "token_configured": bool(config and config["core_token"]),
                "public_origin": config["public_origin"] if config else None}

    def matches_core_token(self):
        return bool(self.config and hmac.compare_digest(self.config["core_token"].encode("utf-8"), self.core_token.encode("utf-8")))

    def save_token(self, token):
        if not isinstance(token, str) or len(token) > 2000 or any(char in token for char in "\r\n\x00"):
            raise ApiError("CORE_FRONTEND_TOKEN_INVALID", "Token does not match the current Core token", 400)
        try:
            matches = hmac.compare_digest(token.encode("utf-8"), self.core_token.encode("utf-8"))
        except UnicodeEncodeError:
            matches = False
        if not matches:
            raise ApiError("CORE_FRONTEND_TOKEN_INVALID", "Token does not match the current Core token", 400)
        if self.config is None or self.path is None:
            raise ApiError("CORE_FRONTEND_CONNECTION_UNCONFIGURED", "Frontend connection configuration is unavailable", 409)
        changed = dict(self.config, core_token=token)
        encoded = json.dumps(changed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent, text=True)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise ApiError("CORE_FRONTEND_CONNECTION_UNAVAILABLE", "Frontend connection configuration could not be saved", 503)
        finally:
            if temporary and os.path.exists(temporary): os.unlink(temporary)
        self.config = changed

    async def _refresh_keys(self, session):
        config = self.config
        if config is None: return {}
        url = config["issuer"] + "/cdn-cgi/access/certs"
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with session.get(url, allow_redirects=False, timeout=timeout, headers={"User-Agent": "AtelierX-AccessVerifier/1.0"}) as response:
                if response.status != 200: raise ValueError("JWKS unavailable")
                data = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    data.extend(chunk)
                    if len(data) > _MAX_JWKS_BYTES: raise ValueError("JWKS too large")
            payload = json.loads(data)
            if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list): raise ValueError("invalid JWKS")
            keys = {}
            for item in payload["keys"]:
                if not isinstance(item, dict) or not isinstance(item.get("kid"), str) or item.get("kty") != "RSA": continue
                keys[item["kid"]] = RSAAlgorithm.from_jwk(json.dumps(item))
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, TypeError, jwt.PyJWTError):
            self._last_refresh = time.monotonic()
            raise ApiError("CORE_ACCESS_UNAVAILABLE", "Cloudflare Access verification is unavailable", 503)
        if not keys:
            self._last_refresh = time.monotonic()
            raise ApiError("CORE_ACCESS_UNAVAILABLE", "Cloudflare Access verification is unavailable", 503)
        self._keys, self._keys_at = keys, time.monotonic()
        self._last_refresh = self._keys_at
        return keys

    async def _keys_for(self, session, kid):
        async with self._lock:
            fresh = time.monotonic() - self._keys_at < _CACHE_SECONDS
            cooled = time.monotonic() - self._last_refresh >= _REFRESH_COOLDOWN_SECONDS
            if not fresh and not cooled:
                raise ApiError("CORE_ACCESS_UNAVAILABLE", "Cloudflare Access verification is unavailable", 503)
            if (not fresh or kid not in self._keys) and cooled:
                await self._refresh_keys(session)
            return self._keys.get(kid)

    async def verify_access(self, request, session):
        config = self.config
        if config is None:
            raise ApiError("CORE_ACCESS_FORBIDDEN", "Cloudflare Access is not configured", 403)
        expected_host = urlsplit(config["public_origin"]).netloc
        if request.host.lower() != expected_host.lower():
            raise ApiError("CORE_ACCESS_FORBIDDEN", "Cloudflare Access host is not permitted", 403)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("Origin") != config["public_origin"]:
            raise ApiError("CORE_ACCESS_ORIGIN_FORBIDDEN", "Request origin is not permitted", 403)
        assertion = request.headers.get("Cf-Access-Jwt-Assertion")
        if not assertion or len(assertion.encode("utf-8", "ignore")) > _MAX_ASSERTION_BYTES:
            raise ApiError("CORE_ACCESS_FORBIDDEN", "Cloudflare Access assertion required", 403)
        try:
            header = jwt.get_unverified_header(assertion)
            kid = header.get("kid")
            if not isinstance(kid, str) or header.get("alg") != "RS256": raise jwt.InvalidTokenError()
            key = await self._keys_for(session, kid)
            if key is None: raise jwt.InvalidTokenError()
            claims = jwt.decode(assertion, key=key, algorithms=["RS256"], issuer=config["issuer"], audience=config["audience"],
                                options={"require": ["exp", "iat", "iss", "aud"]})
        except ApiError: raise
        except (jwt.PyJWTError, TypeError, ValueError, OverflowError):
            raise ApiError("CORE_ACCESS_FORBIDDEN", "Cloudflare Access assertion is invalid", 403)
        email = claims.get("email")
        if not isinstance(email, str) or not isinstance(claims.get("sub"), str) or email.casefold() not in {entry.casefold() for entry in config["allowed_emails"]}:
            raise ApiError("CORE_ACCESS_FORBIDDEN", "Cloudflare Access identity is not permitted", 403)
        return claims
