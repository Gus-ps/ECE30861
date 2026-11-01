"""The Phase 4 review bundle for Team 9 (scripts/build_review_bundle.py): complete, checksummed,
reproducible, and loadable by the tester once extracted."""

import csv
import hashlib
import importlib.util
import io
import json
import zipfile

from tester.config import FIXTURES
from tester.suite.plan import load_plan

from .test_phase4_fixtures import ROOT

spec = importlib.util.spec_from_file_location("build_review_bundle", ROOT / "scripts" / "build_review_bundle.py")
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


def test_bundle_is_reproducible_checksummed_and_loads(tmp_path):
    data, files = bundle.build()
    assert bundle.build()[0] == data
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(tmp_path)
    root = tmp_path / bundle.TOP
    lines = (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(files) - 1
    for line in lines:
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    plan = load_plan(FIXTURES / "manifest_phase4.json", FIXTURES / "pod_profile_phase4.json", root / "expectations.json")
    pack = json.loads((root / "expectations.json").read_text(encoding="utf-8"))
    assert set(plan["fixtures"]["files"]) == set(pack["fixtures"])


def test_review_form_has_a_row_for_every_expected_finding():
    data = json.loads((FIXTURES / "phase4" / "expectations.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader(io.StringIO(bundle.review_form(data))))
    findings = [r for r in rows if r["item"] == "finding"]
    expected = sum(len(e.get("findings", [])) for k, e in data["fixtures"].items() if k not in bundle.ALIASES)
    assert len(findings) == expected and all(len(r["findingId"]) == 64 for r in findings)
    assert {r["entry"] for r in rows if r["item"] == "hash"} == set(data["fixtures"]) - set(bundle.ALIASES)
