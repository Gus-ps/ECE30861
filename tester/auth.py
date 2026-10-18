"""Operator bearer-token check: only SHA256 digests are configured."""

import hashlib
import hmac

from .errors import TesterError


def operator_subject(authorization, token_hashes):
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise TesterError(401, "A bearer token is required.")
    digest = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
    for known, subject in token_hashes.items():
        if hmac.compare_digest(known, digest):
            return subject
    raise TesterError(401, "The bearer token is not recognized.")
