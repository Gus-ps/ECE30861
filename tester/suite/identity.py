"""Pod finding identity, whitespace trimming and ordering (ref/phase3.md,
"Audit policy and deterministic identity"). Independent of any system."""

import hashlib
import json

##  Unicode White_Space, listed explicitly; U+200B zero-width space is excluded.
WHITESPACE = "".join(chr(c) for c in (*range(0x09, 0x0E), 0x20, 0x85, 0xA0, 0x1680,
                                      *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000))


def trim(text):
    return (text or "").strip(WHITESPACE)


def finding_id(source_sha256, ruleset_version, rule_id, worksheet, target):
    ##  Lowercase SHA256 of compact UTF-8 JSON; no normalization, BOM or newline.
    encoded = json.dumps([source_sha256, ruleset_version, rule_id, worksheet, target],
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sort_key(finding):
    ##  Python compares str by code point, which is the contract's ordering.
    return (finding["ruleId"], finding["worksheet"], finding["target"])
