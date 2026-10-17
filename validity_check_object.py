"""
Validity Checker for uploaded files (file-like object version)

Intention: Verify that an uploaded file is valid for the site to check for
ADA Title II digital accessibility and suggest changes for.

Input:  file (any type), given as a binary file-like object plus its filename
        (e.g. an open file, io.BytesIO, or FastAPI's UploadFile.file)
Output: If valid   -> statement that the file is valid
        If invalid -> error statement listing each violated requirement and why

Requirements for the file:
    - Must be a .xlsx file
    - Cannot be password protected
    - Cannot be corrupted
    - Cannot be encrypted
    - Maximum file size of 25 MB
    - Maximum worksheet quantity of 50 worksheets
    - Maximum nonempty cell quantity of 250,000 cells

Usage:
    python validity_check_object.py <path_to_file>

    or from code:
        errors = validate_file(file_obj, filename)

Only the Python standard library is used.
"""

import os
import posixpath
import sys
import zipfile
import xml.etree.ElementTree as ET

MAX_FILE_SIZE_MB = 25
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_WORKSHEETS = 50
MAX_NONEMPTY_CELLS = 250_000

# Encrypted / password-to-open Office files are not zip archives; they are
# stored in the older OLE2 "Compound File" container instead.
OLE2_SIGNATURE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
ZIP_SIGNATURE = b"PK\x03\x04"

# Name of the stream that holds encryption details inside an encrypted file.
ENCRYPTION_MARKERS = ("EncryptionInfo".encode("utf-16-le"),
                      "EncryptedPackage".encode("utf-16-le"))

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORKSHEET_REL_TYPE = REL_NS + "/worksheet"

REQUIRED_PARTS = ("[Content_Types].xml", "xl/workbook.xml")

# A <workbookProtection> element only protects the workbook when one of these
# is turned on; some tools write an empty element into every workbook.
WORKBOOK_LOCKS = ("lockStructure", "lockWindows", "lockRevision")


def read_header(file_obj, length):
    """Read the first `length` bytes of the file, leaving it at the start."""
    file_obj.seek(0)
    header = file_obj.read(length)
    file_obj.seek(0)
    return header


def check_file_type(filename):
    """Requirement: must be a .xlsx file."""
    if os.path.splitext(filename)[1].lower() != ".xlsx":
        ext = os.path.splitext(filename)[1] or "no extension"
        return [f"Invalid file type: expected a .xlsx file but got '{ext}'."]
    return []


def check_file_size(file_obj):
    """Requirement: maximum file size of 25 MB."""
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > MAX_FILE_SIZE_BYTES:
        return [f"File too large: {size / (1024 * 1024):.2f} MB exceeds the "
                f"{MAX_FILE_SIZE_MB} MB limit."]
    return []


def check_encryption(file_obj):
    """Requirements: cannot be encrypted, cannot be password protected (to open).

    Returns (errors, is_encrypted).
    """
    if read_header(file_obj, 8) != OLE2_SIGNATURE:
        return [], False
    contents = file_obj.read()
    file_obj.seek(0)

    if any(marker in contents for marker in ENCRYPTION_MARKERS):
        return ["File is encrypted: the workbook requires a password to open. "
                "Remove the password/encryption and upload again.",
                "File is password protected: a password is required to open "
                "the workbook."], True

    # An OLE2 file without encryption streams is an old .xls workbook (or
    # other legacy Office file) that was renamed to .xlsx.
    return ["File is corrupted or not a real .xlsx file: it uses the legacy "
            "binary Office format (e.g. .xls). Re-save it as an Excel "
            "Workbook (.xlsx)."], True


def check_corruption(file_obj):
    """Requirement: cannot be corrupted.

    Returns (errors, zip_archive) where zip_archive is an open ZipFile if the
    archive is usable, otherwise None.
    """
    if read_header(file_obj, 4) != ZIP_SIGNATURE or not zipfile.is_zipfile(file_obj):
        return ["File is corrupted: it is not a valid .xlsx (zip) archive."], None
    file_obj.seek(0)

    try:
        archive = zipfile.ZipFile(file_obj)
    except (zipfile.BadZipFile, OSError) as e:
        return [f"File is corrupted: the archive could not be opened ({e})."], None

    try:
        bad_member = archive.testzip()
    except Exception as e:
        archive.close()
        return [f"File is corrupted: the archive could not be read ({e})."], None
    if bad_member is not None:
        archive.close()
        return [f"File is corrupted: archive member '{bad_member}' failed its "
                "integrity check."], None

    names = set(archive.namelist())
    missing = [part for part in REQUIRED_PARTS if part not in names]
    if missing:
        archive.close()
        return [f"File is corrupted: missing required workbook part(s) "
                f"{', '.join(missing)}."], None

    return [], archive


def is_true(value):
    """Return True for an XML boolean attribute set to true ("1" or "true")."""
    return value is not None and value.strip().lower() in ("1", "true")


def check_protection(archive):
    """Requirement: cannot be password protected (workbook / sheet protection)."""
    errors = []
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    wb_protection = workbook.find(f"{{{MAIN_NS}}}workbookProtection")
    if wb_protection is not None and any(
            is_true(wb_protection.get(lock)) for lock in WORKBOOK_LOCKS):
        errors.append("File is password protected: the workbook structure is "
                      "protected. Unprotect the workbook and upload again.")

    protected_sheets = []
    for name, part in get_worksheet_parts(archive, workbook):
        if part not in archive.namelist():
            continue
        for _, elem in ET.iterparse(archive.open(part)):
            if (elem.tag == f"{{{MAIN_NS}}}sheetProtection"
                    and is_true(elem.get("sheet"))):
                protected_sheets.append(name)
                break
            elem.clear()
    if protected_sheets:
        errors.append("File is password protected: the following worksheet(s) "
                      f"are protected: {', '.join(protected_sheets)}. Unprotect "
                      "them and upload again.")
    return errors


def get_worksheet_parts(archive, workbook):
    """Return a list of (sheet name, zip path) for every worksheet."""
    rels_path = "xl/_rels/workbook.xml.rels"
    if rels_path not in archive.namelist():
        return []
    rels = ET.fromstring(archive.read(rels_path))
    targets = {}
    for rel in rels.findall(f"{{{PKG_REL_NS}}}Relationship"):
        if rel.get("Type") == WORKSHEET_REL_TYPE:
            target = rel.get("Target", "")
            if target.startswith("/"):
                path = target.lstrip("/")
            else:
                path = posixpath.normpath(posixpath.join("xl", target))
            targets[rel.get("Id")] = path

    parts = []
    sheets = workbook.find(f"{{{MAIN_NS}}}sheets")
    if sheets is None:
        return parts
    for sheet in sheets.findall(f"{{{MAIN_NS}}}sheet"):
        rel_id = sheet.get(f"{{{REL_NS}}}id")
        if rel_id in targets:
            parts.append((sheet.get("name", "?"), targets[rel_id]))
    return parts


def check_worksheet_count(archive):
    """Requirement: maximum of 50 worksheets."""
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    count = len(get_worksheet_parts(archive, workbook))
    if count > MAX_WORKSHEETS:
        return [f"Too many worksheets: {count} worksheets exceeds the limit "
                f"of {MAX_WORKSHEETS}."]
    return []


def check_cell_count(archive):
    """Requirement: maximum of 250,000 nonempty cells across all worksheets.

    A cell counts as nonempty if it holds a value, inline string, or formula.
    Cells that only carry formatting are ignored.
    """
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    cell_tag = f"{{{MAIN_NS}}}c"
    content_tags = {f"{{{MAIN_NS}}}v", f"{{{MAIN_NS}}}is", f"{{{MAIN_NS}}}f"}
    total = 0
    for _, part in get_worksheet_parts(archive, workbook):
        if part not in archive.namelist():
            raise ET.ParseError(f"worksheet part '{part}' is missing")
        for _, elem in ET.iterparse(archive.open(part)):
            if elem.tag == cell_tag:
                if any(child.tag in content_tags for child in elem):
                    total += 1
                elem.clear()
    if total > MAX_NONEMPTY_CELLS:
        return [f"Too many nonempty cells: {total:,} cells exceeds the limit "
                f"of {MAX_NONEMPTY_CELLS:,}."]
    return []


def validate_file(file_obj, filename):
    """Check a file against every requirement.

    file_obj: a binary file-like object supporting read() and seek()
              (open(..., "rb"), io.BytesIO, UploadFile.file, etc.)
    filename: the original name of the file, used for the .xlsx check

    Returns a list of error strings. An empty list means the file is valid.
    The file object is left open and rewound to the start for the caller.
    """
    if file_obj is None or not hasattr(file_obj, "read") or not hasattr(file_obj, "seek"):
        return ["No file provided: expected a readable, seekable file object."]

    try:
        errors = []
        errors += check_file_size(file_obj)

        type_errors = check_file_type(filename or "")
        if type_errors:
            # Not an .xlsx file, so the workbook checks don't apply.
            return type_errors + errors

        encryption_errors, is_ole = check_encryption(file_obj)
        errors += encryption_errors
        if is_ole:
            # Encrypted/legacy files can't be opened, so the remaining checks
            # cannot be run.
            return errors

        corruption_errors, archive = check_corruption(file_obj)
        errors += corruption_errors
        if archive is None:
            return errors

        with archive:
            try:
                errors += check_protection(archive)
                errors += check_worksheet_count(archive)
                errors += check_cell_count(archive)
            except (ET.ParseError, KeyError, zipfile.BadZipFile) as e:
                errors.append(f"File is corrupted: workbook contents could not "
                              f"be read ({e}).")
        return errors
    finally:
        file_obj.seek(0)


def main():
    if len(sys.argv) != 2:
        print("Usage: python validity_check_object.py <path_to_file>")
        sys.exit(2)

    filepath = sys.argv[1]
    filename = os.path.basename(filepath)
    if not os.path.isfile(filepath):
        errors = [f"File not found: '{filepath}' does not exist or is not a file."]
    else:
        with open(filepath, "rb") as file_obj:
            errors = validate_file(file_obj, filename)

    if not errors:
        print(f"'{filename}' is valid and ready to be checked for accessibility.")
        sys.exit(0)

    print(f"Error: '{filename}' is invalid. Violated requirement(s):")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)


if __name__ == "__main__":
    main()
