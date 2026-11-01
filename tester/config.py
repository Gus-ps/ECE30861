"""Tester settings from environment variables (names match Team 9's tester)."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

FIXTURES = Path(__file__).parent / "fixtures"
TARGET_ROLES = ("userA", "userB", "reviewer", "test-admin")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "production"] = "development"
    tester_db_path: str = "tester.db"
    ##  lowercase SHA256(operator token) -> operator subject
    tester_operator_token_hashes_json: dict[str, str] = {}
    ##  exact approved system base URLs
    allowed_target_urls: list[str] = []
    ##  exact base URL -> {userA, userB, reviewer, test-admin} raw tokens
    target_auth_map_json: dict[str, dict[str, SecretStr]] = {}
    manifest_path: Path = FIXTURES / "manifest.json"
    pod_profile_path: Path = FIXTURES / "pod_profile.json"
    ##  expectations.json of the adopted fixture pack; unset means no fixture pack
    expectations_path: Path | None = None
    ##  deployment evidence for the run record, supplied by the operator
    tester_revision: str | None = None
    ##  exact base URL -> the target's deployed revision
    target_revisions_json: dict[str, str] = {}

    @field_validator("tester_operator_token_hashes_json")
    @classmethod
    def lowercase_digests(cls, value):
        for digest in value:
            if len(digest) != 64 or digest != digest.lower() or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("operator token hashes must be lowercase SHA256 hex digests")
        return value

    @model_validator(mode="after")
    def targets_configured(self):
        for url in self.allowed_target_urls:
            problem = target_url_problem(url, self.app_env)
            if problem:
                raise ValueError(f"ALLOWED_TARGET_URLS entry {url!r}: {problem}")
            roles = self.target_auth_map_json.get(url)
            if roles is None or any(role not in roles for role in TARGET_ROLES):
                raise ValueError(f"TARGET_AUTH_MAP_JSON must give {', '.join(TARGET_ROLES)} tokens for {url!r}")
        return self


def target_url_problem(url, app_env):
    ##  Syntax rules for a system base URL; returns a reason or None.
    try:
        parts = urlsplit(url)
    except ValueError:
        return "not a valid URL"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "must be an absolute http(s) URL"
    if app_env == "production" and parts.scheme != "https":
        return "production targets must use HTTPS"
    if parts.username or parts.password:
        return "must not contain credentials"
    if parts.query or parts.fragment or "?" in url or "#" in url:
        return "must not contain a query or fragment"
    if parts.path.rstrip("/").endswith("/test") or "/test/" in parts.path + "/":
        return "must be the base URL, without a /test suffix"
    return None
