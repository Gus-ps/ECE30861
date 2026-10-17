"""
Validity Checker for uploaded files

Intention: Verify that an uploaded file is valid for the site to check for
ADA Title II digital accessibility and suggest changes for.

Input:  file (any type)
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
    python validity_check.py <path_to_file>

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


def check_file_type(filepath):
    """Requirement: must be a .xlsx file."""
    if os.path.splitext(filepath)[1].lower() != ".xlsx":
        ext = os.path.splitext(filepath)[1] or "no extension"
        return [f"Invalid file type: expected a .xlsx file but got '{ext}'."]
    return []


def check_file_size(filepath):
    """Requirement: maximum file size of 25 MB."""
    size = os.path.getsize(filepath)
    if size > MAX_FILE_SIZE_BYTES:
        return [f"File too large: {size / (1024 * 1024):.2f} MB exceeds the "
                f"{MAX_FILE_SIZE_MB} MB limit."]
    return []


def check_encryption(filepath):
    """Requirements: cannot be encrypted, cannot be password protected (to open).

    Returns (errors, is_encrypted).
    """
    with open(filepath, "rb") as file:
        header = file.read(8)
        if header != OLE2_SIGNATURE:
            return [], False
        contents = header + file.read()

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


def check_corruption(filepath):
    """Requirement: cannot be corrupted.

    Returns (errors, zip_archive) where zip_archive is an open ZipFile if the
    archive is usable, otherwise None.
    """
    with open(filepath, "rb") as file:
        header = file.read(4)
    if header != ZIP_SIGNATURE or not zipfile.is_zipfile(filepath):
        return ["File is corrupted: it is not a valid .xlsx (zip) archive."], None

    try:
        archive = zipfile.ZipFile(filepath)
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


def check_protection(archive):
    """Requirement: cannot be password protected (workbook / sheet protection)."""
    errors = []
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    if workbook.find(f"{{{MAIN_NS}}}workbookProtection") is not None:
        errors.append("File is password protected: the workbook structure is "
                      "protected. Unprotect the workbook and upload again.")

    protected_sheets = []
    for name, part in get_worksheet_parts(archive, workbook):
        if part not in archive.namelist():
            continue
        for _, elem in ET.iterparse(archive.open(part)):
            if elem.tag == f"{{{MAIN_NS}}}sheetProtection":
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


def validate_file(filepath):
    """Check a file against every requirement.

    Returns a list of error strings. An empty list means the file is valid.
    """
    if not os.path.isfile(filepath):
        return [f"File not found: '{filepath}' does not exist or is not a file."]

    errors = []
    errors += check_file_size(filepath)

    type_errors = check_file_type(filepath)
    if type_errors:
        # Not an .xlsx file, so the workbook checks don't apply.
        return type_errors + errors

    encryption_errors, is_ole = check_encryption(filepath)
    errors += encryption_errors
    if is_ole:
        # Encrypted/legacy files can't be opened, so the remaining checks
        # cannot be run.
        return errors

    corruption_errors, archive = check_corruption(filepath)
    errors += corruption_errors
    if archive is None:
        return errors

    with archive:
        try:
            errors += check_protection(archive)
            errors += check_worksheet_count(archive)
            errors += check_cell_count(archive)
        except (ET.ParseError, KeyError, zipfile.BadZipFile) as e:
            errors.append(f"File is corrupted: workbook contents could not be "
                          f"read ({e}).")
    return errors


def check_validity(filepath):
    """Check a file, print the result, and return whether it is valid.

    Returns True if the file meets every requirement, or False if it violates
    one or more of them.
    """
    filename = os.path.basename(filepath)
    errors = validate_file(filepath)

    if not errors:
        print(f"'{filename}' is valid and ready to be checked for accessibility.")
        return True

    print(f"Error: '{filename}' is invalid. Violated requirement(s):")
    for error in errors:
        print(f"  - {error}")
    return False


def main():
    if len(sys.argv) != 2:
        print("Usage: python validity_check.py <path_to_file>")
        sys.exit(2)

    sys.exit(0 if check_validity(sys.argv[1]) else 1)


if __name__ == "__main__":
    main()
