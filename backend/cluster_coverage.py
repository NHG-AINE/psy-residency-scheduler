"""Cluster exposure from recognised posting months; no allocation preferences."""

CLUSTERS = {
    "NHG": {"IMH", "TTSH", "KTPH", "WH"},
    "SHS": {"CGH", "SGH", "SKH", "KKH", "NNI"},
    "NUHS": {"NUH", "NTFGH", "AH"},
}


def cluster_coverage(months):
    """Summarise validated R1-R4 evidence, without inferring credit from labels."""
    institutions = {month.get("institution") for month in months
                    if month.get("status") == "expected"
                    and month.get("requirement_year") in {"R1", "R2", "R3", "R4"}}
    visited = [cluster for cluster, sites in CLUSTERS.items() if institutions & sites]
    return {"visited": visited, "missing": [cluster for cluster in CLUSTERS if cluster not in visited]}
