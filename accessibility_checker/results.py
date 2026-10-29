"""List-compatible checker results with disclosures for manual-review locations."""


class Findings(list[dict[str, str]]):
    def __init__(self, values=(), limitations=()):
        super().__init__(values)
        self.limitations: list[str] = list(limitations)


def finalize_findings(findings: Findings) -> Findings:
    """Sort results without collapsing findings; normalize exact disclosures."""
    findings.sort(key=lambda item: (item["ruleId"], item["worksheet"], item["target"]))
    findings.limitations[:] = sorted(set(findings.limitations))
    return findings
