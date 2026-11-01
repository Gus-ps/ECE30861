"""Loads and cross-checks the suite manifest, pod profile and fixture pack.

A session freezes all three at setup, so later edits to the files never change
a session that has already been prepared. Fixture bytes are verified against
their recorded SHA256 at setup and again each time a check reads them.
"""

import hashlib
import json
from pathlib import Path

from ..models import FixturePack, Manifest, PodProfile


class PlanError(ValueError):
    """The manifest, profile or fixture pack is unusable; the message says why."""


def load_plan(manifest_path, profile_path, expectations_path=None):
    manifest = Manifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    profile = PodProfile.model_validate(json.loads(profile_path.read_text(encoding="utf-8")))
    if set(manifest.components) != set(profile.coverage.components):
        raise PlanError("manifest components do not match the pod profile coverage catalog")
    if set(manifest.acceptance) != set(profile.coverage.acceptance):
        raise PlanError("manifest acceptance criteria do not match the pod profile coverage catalog")
    fixtures = None if expectations_path is None else load_fixtures(Path(expectations_path), manifest)
    return {"manifest": manifest.model_dump(mode="json"), "profile": profile.model_dump(mode="json"),
            "fixtures": fixtures}


def load_fixtures(expectations_path, manifest):
    ##  Fixture files resolve relative to the expectations file and must stay inside its folder.
    raw = expectations_path.read_bytes()
    pack = FixturePack.model_validate(json.loads(raw))
    if pack.ruleset_version != manifest.ruleset_version:
        raise PlanError(f"fixture pack ruleset {pack.ruleset_version} does not match "
                        f"manifest ruleset {manifest.ruleset_version}")
    named = {case.parameters["fixture"] for case in manifest.tests if "fixture" in case.parameters}
    missing = sorted(str(key) for key in named - set(pack.fixtures))
    if missing:
        raise PlanError(f"fixture pack has no entry for {', '.join(missing)}")
    root = expectations_path.resolve().parent
    files = {}
    for key, entry in pack.fixtures.items():
        path = (root / entry.file).resolve()
        if not path.is_relative_to(root):
            raise PlanError(f"fixture {key} path {entry.file} is outside the fixture pack folder")
        try:
            data = path.read_bytes()
        except OSError:
            raise PlanError(f"fixture {key} file {entry.file} could not be read") from None
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry.sha256:
            raise PlanError(f"fixture {key} ({entry.file}) has SHA256 {digest}, expected {entry.sha256}")
        files[key] = str(path)
    return {"expectations_path": str(expectations_path.resolve()),
            "expectations_sha256": hashlib.sha256(raw).hexdigest(),
            "ruleset_version": pack.ruleset_version,
            "entries": {key: entry.model_dump(mode="json") for key, entry in pack.fixtures.items()},
            "files": files}


def fixture_bytes(plan, key):
    ##  The fixture's bytes, re-verified against the hash frozen at setup.
    fixtures = plan.get("fixtures")
    if not fixtures or key not in fixtures["entries"]:
        raise PlanError(f"fixture {key} is not in this session's fixture pack")
    try:
        data = Path(fixtures["files"][key]).read_bytes()
    except OSError:
        raise PlanError(f"fixture {key} could not be read after setup") from None
    if hashlib.sha256(data).hexdigest() != fixtures["entries"][key]["sha256"]:
        raise PlanError(f"fixture {key} changed after setup; its bytes no longer match the frozen SHA256")
    return data


def manifest_of(plan):
    return Manifest.model_validate(plan["manifest"])


def profile_of(plan):
    return PodProfile.model_validate(plan["profile"])
