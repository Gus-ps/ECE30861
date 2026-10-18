"""Generate a tester operator token and the hash entry for TESTER_OPERATOR_TOKEN_HASHES_JSON.

Usage: uv run python scripts/make_operator_token.py --subject team12-operator
Prints the raw token once (give it to graders/podmates privately) and the JSON entry to merge
into the tester's settings. The raw token is never written to disk.
"""

import argparse
import hashlib
import json
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subject", required=True, help="operator name recorded as the session owner")
    args = parser.parse_args()
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    print(f"Raw operator token (share privately, do not store in the repo):\n  {token}\n")
    print("Entry for TESTER_OPERATOR_TOKEN_HASHES_JSON (merge with any existing entries):")
    print(f"  {json.dumps({digest: args.subject}, separators=(',', ':'))}")


if __name__ == "__main__":
    main()
