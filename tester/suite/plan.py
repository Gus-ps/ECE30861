"""Loads and cross-checks the suite manifest and pod profile.

A session freezes both at setup, so later edits to the files never change a
session that has already been prepared.
"""

import json

from ..models import Manifest, PodProfile


def load_plan(manifest_path, profile_path):
    manifest = Manifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    profile = PodProfile.model_validate(json.loads(profile_path.read_text(encoding="utf-8")))
    if set(manifest.components) != set(profile.coverage.components):
        raise ValueError("manifest components do not match the pod profile coverage catalog")
    if set(manifest.acceptance) != set(profile.coverage.acceptance):
        raise ValueError("manifest acceptance criteria do not match the pod profile coverage catalog")
    return {"manifest": manifest.model_dump(mode="json"), "profile": profile.model_dump(mode="json")}


def manifest_of(plan):
    return Manifest.model_validate(plan["manifest"])


def profile_of(plan):
    return PodProfile.model_validate(plan["profile"])
