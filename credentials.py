"""Bearer credential matching, with backward-compatible hashed configuration."""
import hashlib
import re
import secrets


def subject_for(mapping, token):
    if not token:
        return None
    digest = 'sha256:' + hashlib.sha256(token.encode('utf-8')).hexdigest()
    matched = None
    for expected, subject in mapping.items():
        candidate = digest if expected.startswith('sha256:') else token
        if secrets.compare_digest(candidate.encode('utf-8'), expected.encode('utf-8')):
            matched = subject
    return matched


def validate(mapping):
    if not isinstance(mapping, dict) or any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        or key.startswith('sha256:') and not re.fullmatch(r'sha256:[0-9a-f]{64}', key)
        for key, value in mapping.items()
    ):
        raise ValueError('Credentials must map tokens or sha256:<hex> digests to subjects.')


def fingerprint(key):
    return key if key.startswith('sha256:') else 'sha256:' + hashlib.sha256(key.encode()).hexdigest()
