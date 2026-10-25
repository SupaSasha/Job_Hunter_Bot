"""Offline fixture validation; never reads or writes production users."""

import json
from pathlib import Path

from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.services.filters import FilterService
from src.services.normalization import NormalizationService
from src.services.scoring import ScoringService


def validate_profiles() -> list[dict]:
    fixture = (
        Path(__file__).resolve().parents[2] / "tests/fixtures/universal_profiles.json"
    )
    data = json.loads(fixture.read_text())
    jobs = [NormalizationService().normalize(JobDTO(**raw)) for raw in data["jobs"]]
    results = []
    for profile in data["profiles"]:
        filters = UserFilterDTO(**profile["filters"])
        accepted = [
            job for job in jobs if FilterService().evaluate(job, filters).accepted
        ]
        ranked = sorted(
            accepted,
            key=lambda job: ScoringService().calculate(job, filters).score,
            reverse=True,
        )
        top = ranked[:3]
        if [job.external_id for job in top] != profile["expected_top_ids"]:
            raise AssertionError(f"Unexpected ranking for {profile['name']}")
        results.append(
            {
                "profile": profile["name"],
                "jobs": [
                    {
                        "title": job.title,
                        "score": ScoringService().calculate(job, filters).score,
                    }
                    for job in top
                ],
            }
        )
    return results


if __name__ == "__main__":
    print("Authored fixtures only; no production users or external API requests.")
    print("| Profile | Top 1 | Top 2 | Top 3 |")
    print("| --- | --- | --- | --- |")
    for result in validate_profiles():
        jobs = " | ".join(f"{job['title']} ({job['score']})" for job in result["jobs"])
        print(f"| {result['profile']} | {jobs} |")
