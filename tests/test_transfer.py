"""Multipart uploads, idempotency keys and download checks."""

import io
import json
import zipfile
from email.parser import BytesParser
from email.policy import HTTP

import httpx
import pytest

from tester.suite.runner import CaseResult
from tester.suite.transfer import XLSX, download_problems, generated_name, parse_disposition, upload_files
from tester.target import Deadline, TargetResponse

from .conftest import make_settings
from .test_fixtures_and_record import make_pack
from .test_fixtures_and_record import run as run_suite
from .test_fixtures_and_record import setup as setup_session
from .test_target import client


def xlsx_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
    return buffer.getvalue()


def download(body, **headers):
    base = {"content-type": XLSX, "content-length": str(len(body)), "cache-control": "no-store",
            "content-disposition": 'attachment; filename="budget-remediated.xlsx"'}
    base.update({k.replace("_", "-"): v for k, v in headers.items() if v is not None})
    for k in [k.replace("_", "-") for k, v in headers.items() if v is None]:
        base.pop(k, None)
    return TargetResponse(200, body, httpx.Headers(base))


def multipart_parts(request):
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
    return list(message.iter_parts())


##  ---- Uploads and request headers ----

def test_upload_is_one_file_part():
    seen = []
    client(lambda request: seen.append(request) or httpx.Response(202)).request(
        "POST", "/api/v1/workbooks", budget=5, deadline=Deadline(60), files=upload_files("Budget.xlsx", b"PK\x03\x04data"))
    [part] = multipart_parts(seen[0])
    assert part.get_param("name", header="content-disposition") == "file"
    assert part.get_filename() == "Budget.xlsx"
    assert part.get_content_type() == XLSX
    assert part.get_payload(decode=True) == b"PK\x03\x04data"


@pytest.mark.parametrize("name, media", [("legacy.xls", "application/vnd.ms-excel"), ("data.csv", "text/csv"),
                                         ("noextension", "application/octet-stream")])
def test_upload_part_type_follows_the_name(name, media):
    assert upload_files(name, b"x")["file"][2] == media


def test_idempotency_key_and_identity_encoding_headers():
    seen = []
    target = client(lambda request: seen.append(request) or httpx.Response(202))
    target.request("POST", "/api/v1/workbooks/w/versions/v/remediations", budget=5, deadline=Deadline(60),
                   json_body={}, idempotency_key="review-request-001")
    target.request("GET", "/api/v1/outputs/o/workbook", budget=5, deadline=Deadline(60), binary=True)
    assert seen[0].headers["idempotency-key"] == "review-request-001"
    assert "idempotency-key" not in seen[1].headers
    assert seen[1].headers["accept-encoding"] == "identity"


def test_context_uploads_a_frozen_fixture_and_downloads(tmp_path, make_client, fake):
    pack = make_pack(tmp_path / "pack")
    seen = {}

    def transfers(case, ctx):
        seen["upload"] = ctx.upload("/api/v1/workbooks", role="userA", fixture="unicode").status
        seen["download"] = ctx.download("/api/v1/outputs/o/workbook", role="userA").status
        seen["keys"] = {ctx.new_idempotency_key() for _ in range(3)}
        return CaseResult.passed("done")

    client_ = make_client(checks={"health": transfers}, settings=make_settings(tmp_path, expectations_path=pack))
    run_suite(client_, setup_session(client_).json()["session_id"])
    upload, download_ = [r for r in fake.requests if r[1].startswith("/system/api/v1/")]
    assert upload[0] == "POST" and upload[2]["x-test-session"] and upload[2]["authorization"] == "Bearer tok-a"
    assert b'name="file"; filename="unicode.xlsx"' in upload[3] and b"stand-in bytes for unicode" in upload[3]
    assert seen["upload"] == 422 and seen["download"] == 404       # stand-in bytes are not a ZIP
    assert download_[0] == "GET" and download_[2]["accept-encoding"] == "identity"
    assert len(seen["keys"]) == 3 and all(k.startswith("tester-") and len(k) <= 64 for k in seen["keys"])


##  ---- Download checks ----

def test_conforming_workbook_download_has_no_problems():
    assert download_problems(download(xlsx_bytes()), "workbook", "budget-remediated.xlsx") == []


@pytest.mark.parametrize("headers, problem", [
    ({"content_type": "application/octet-stream"}, "Content-Type is application/octet-stream"),
    ({"content_length": None}, "Content-Length is missing"),
    ({"content_length": "3"}, "does not match"),
    ({"cache_control": "private, max-age=60"}, "no-store"),
    ({"content_disposition": 'inline; filename="budget-remediated.xlsx"'}, "expected attachment"),
    ({"content_disposition": "attachment"}, "no filename fallback"),
    ({"content_disposition": 'attachment; filename="../budget.xlsx"'}, "not a sanitized ASCII name"),
    ({"content_disposition": 'attachment; filename="other.xlsx"'}, "expected 'budget-remediated.xlsx'"),
    ({"content_encoding": "gzip"}, "Content-Encoding gzip"),
])
def test_nonconforming_download_headers(headers, problem):
    problems = download_problems(download(xlsx_bytes(), **headers), "workbook", "budget-remediated.xlsx")
    assert any(problem in p for p in problems), problems


def test_partial_workbook_is_detected():
    body = xlsx_bytes()[:-10]
    assert "body is not a complete ZIP package" in download_problems(download(body), "workbook")


def test_non_ascii_name_needs_filename_star():
    name = "Résumé budget-remediated.xlsx"
    good = download(xlsx_bytes(), content_disposition="attachment; filename=\"R_sum_ budget-remediated.xlsx\"; "
                                                      "filename*=UTF-8''R%C3%A9sum%C3%A9%20budget-remediated.xlsx")
    assert download_problems(good, "workbook", name) == []
    bare = download(xlsx_bytes(), content_disposition='attachment; filename="R_sum_ budget-remediated.xlsx"')
    assert "lacks filename*" in " ".join(download_problems(bare, "workbook", name))


def test_report_download():
    body = json.dumps({"reportVersion": "2.0.0"}).encode()
    good = download(body, content_type="application/json; charset=utf-8",
                    content_disposition='attachment; filename="audit-a1.json"')
    assert download_problems(good, "report", "audit-a1.json") == []
    bad = download(b"\xff not json", content_type="application/json",
                   content_disposition='attachment; filename="audit-a1.json"')
    assert "body is not UTF-8 JSON" in download_problems(bad, "report")


@pytest.mark.parametrize("value, expected", [
    ('attachment; filename="a \\"b\\".xlsx"', ("attachment", {"filename": 'a "b".xlsx'})),
    ("Attachment;filename=plain.xlsx", ("attachment", {"filename": "plain.xlsx"})),
    ("attachment; filename=x.xlsx; filename*=utf-8''%E2%82%AC.xlsx",
     ("attachment", {"filename": "x.xlsx", "filename*": "€.xlsx"})),
])
def test_parse_disposition(value, expected):
    assert parse_disposition(value) == expected


@pytest.mark.parametrize("value", ['attachment; filename="open', "; filename=x", "attachment; filename",
                                   "attachment; filename=a; filename=b", "attachment; filename*=latin-1''x"])
def test_parse_disposition_rejects_malformed(value):
    with pytest.raises(ValueError):
        parse_disposition(value)


def test_generated_name_is_shortened_to_255():
    assert generated_name("Budget.xlsx") == "Budget-remediated.xlsx"
    long = generated_name("b" * 300 + ".xlsx")
    assert len(long) == 255 and long.endswith("-remediated.xlsx")
