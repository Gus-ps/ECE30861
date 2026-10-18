"""List-compatible checker results with disclosures for manual-review locations."""


class Findings(list):
    def __init__(self, values=(), limitations=()):
        super().__init__(values)
        self.limitations = list(limitations)
