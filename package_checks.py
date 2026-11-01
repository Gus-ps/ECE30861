"""Service intake boundaries beyond the path validator's workbook validity checks."""
import re
from zipfile import ZipFile, BadZipFile
from service_errors import ApiError


def check_package(path):
    def reject(message):
        raise ApiError(422, 'INVALID_WORKBOOK', message, {'valid': False})

    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                reject('Duplicate archive members are unsupported.')
            if any(name.startswith('/') or '\\' in name or '..' in name.split('/')
                   or re.match(r'^[A-Za-z]:', name) for name in names):
                reject('Unsafe archive member paths are unsupported.')
            if len(names) > 10_000 or sum(i.file_size for i in archive.infolist()) > 200*1024**2:
                reject('The expanded workbook exceeds safe package limits.')
            if any('vbaproject' in name.lower() or name.lower().startswith(('xl/macrosheets/','xl/intlmacrosheets/')) for name in names):
                reject('Macro-enabled workbook content is unsupported.')
            for info in archive.infolist():
                if not info.filename.lower().endswith(('.xml','.rels')):
                    continue
                if info.file_size > 50*1024**2:
                    reject('A workbook XML part exceeds safe package limits.')
                with archive.open(info) as stream:
                    tail = b''
                    while chunk := stream.read(65536):
                        data = tail + chunk
                        normalized = data.replace(b'\x00',b'').upper()
                        if b'<!DOCTYPE' in normalized or b'<!ENTITY' in normalized:
                            reject('XML document type and entity declarations are unsupported.')
                        if info.filename == '[Content_Types].xml' and any(marker in normalized for marker in (b'MACROENABLED',b'VBAPROJECT',b'MACROSHEET')):
                            reject('Macro-enabled workbook content is unsupported.')
                        tail = data[-64:]
    except (BadZipFile, RuntimeError, OSError):
        reject('The workbook package could not be read safely.')
