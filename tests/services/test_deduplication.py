from unittest.mock import AsyncMock, patch

import pytest

from src.models.job import JobORM
from src.repositories.jobs import JobRepository
from src.schemas.job import JobDTO
from src.services.deduplication import DeduplicationService


def build_job(**overrides: object) -> JobDTO:
    data = dict(
        source="remoteok",
        external_id="1",
        company="Acme Inc.",
        title="Python Backend Developer",
        url="https://example.com/jobs/1",
    )
    data.update(overrides)
    return JobDTO(**data)


@pytest.mark.parametrize(
    ("company", "title"),
    [
        ("acme inc", "python   backend developer"),
        (" ACME Inc. ", " Python Backend Developer "),
        ("Acme, Inc.", "Python-Backend_Developer"),
    ],
)
def test_fingerprint_canonicalization(company: str, title: str) -> None:
    job = build_job()
    before = job.model_dump()
    fingerprint = DeduplicationService.calculate_fingerprint(job)
    assert fingerprint == DeduplicationService.calculate_fingerprint(
        build_job(company=company, title=title)
    )
    assert len(fingerprint) == 64
    assert job.model_dump() == before


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Senior Python Developer", "Junior Python Developer"),
        ("Lead Python Developer", "Python Developer"),
        ("C++ Developer", "C Developer"),
        ("C# Developer", "C Developer"),
    ],
)
def test_fingerprint_preserves_meaningful_title_words(first: str, second: str) -> None:
    assert DeduplicationService.calculate_fingerprint(
        build_job(title=first)
    ) != DeduplicationService.calculate_fingerprint(build_job(title=second))


def test_company_suffix_is_preserved() -> None:
    assert DeduplicationService.calculate_fingerprint(
        build_job(company="Acme Inc.")
    ) != DeduplicationService.calculate_fingerprint(build_job(company="Acme LLC"))


def test_fingerprint_missing_company_and_separators() -> None:
    assert DeduplicationService.calculate_fingerprint(
        build_job(company=None)
    ) == DeduplicationService.calculate_fingerprint(build_job(company=""))
    assert DeduplicationService.calculate_fingerprint(
        build_job(company="Acme & Sons")
    ) == DeduplicationService.calculate_fingerprint(build_job(company="acme and sons"))


def test_fingerprint_separates_company_from_title() -> None:
    assert DeduplicationService.calculate_fingerprint(
        build_job(company="Acme Python", title="Developer")
    ) != DeduplicationService.calculate_fingerprint(
        build_job(company="Acme", title="Python Developer")
    )


def test_fingerprint_does_not_depend_on_source_or_url() -> None:
    assert DeduplicationService.calculate_fingerprint(
        build_job()
    ) == DeduplicationService.calculate_fingerprint(
        build_job(source="other", external_id="new", url="https://example.org/changed")
    )


async def test_source_identity_short_circuits_fingerprint() -> None:
    repository = AsyncMock(spec=JobRepository)
    repository.get_by_source_external_id.return_value = JobORM(id=42)
    service = DeduplicationService(repository)
    with patch.object(
        service, "calculate_fingerprint", side_effect=AssertionError("must not run")
    ):
        result = await service.check(build_job())
    assert result.is_duplicate is True
    assert result.reason == "source_external_id"
    assert result.existing_job_id == 42
    repository.get_by_source_external_id.assert_awaited_once_with("remoteok", "1")
    repository.get_by_fingerprint.assert_not_awaited()


async def test_fingerprint_duplicate() -> None:
    repository = AsyncMock(spec=JobRepository)
    repository.get_by_source_external_id.return_value = None
    repository.get_by_fingerprint.return_value = JobORM(id=43)
    job = build_job()
    result = await DeduplicationService(repository).check(job)
    assert result.is_duplicate is True
    assert result.reason == "fingerprint"
    assert result.existing_job_id == 43
    repository.get_by_fingerprint.assert_awaited_once_with(
        DeduplicationService.calculate_fingerprint(job)
    )
    assert [call[0] for call in repository.mock_calls] == [
        "get_by_source_external_id",
        "get_by_fingerprint",
    ]


async def test_new_job() -> None:
    repository = AsyncMock(spec=JobRepository)
    repository.get_by_source_external_id.return_value = None
    repository.get_by_fingerprint.return_value = None
    result = await DeduplicationService(repository).check(build_job())
    assert result.is_duplicate is False
    assert result.reason is None
    assert result.existing_job_id is None
    assert result.fingerprint == DeduplicationService.calculate_fingerprint(build_job())


async def test_wwr_matches_remoteok_via_existing_fingerprint():
    remote = build_job()
    wwr = build_job(
        source="weworkremotely",
        external_id="wwr-guid",
        url="https://weworkremotely.com/remote-jobs/acme",
        company="ACME Inc.",
        title="Python Backend Developer",
    )
    repository = AsyncMock(spec=JobRepository)
    repository.get_by_source_external_id.return_value = None
    repository.get_by_fingerprint.return_value = JobORM(id=42, source="remoteok")
    assert DeduplicationService.calculate_fingerprint(
        remote
    ) == DeduplicationService.calculate_fingerprint(wwr)
    result = await DeduplicationService(repository).check(wwr)
    assert (result.is_duplicate, result.reason, result.existing_job_id) == (
        True,
        "fingerprint",
        42,
    )


@pytest.mark.parametrize("existing_source", ["remoteok", "weworkremotely"])
async def test_getonboard_cross_source_fingerprint(existing_source):
    original = build_job(source=existing_source)
    incoming = build_job(
        source="getonboard",
        external_id="different-id",
        url="https://www.getonbrd.com/jobs/different-id",
    )
    assert DeduplicationService.calculate_fingerprint(
        original
    ) == DeduplicationService.calculate_fingerprint(incoming)
    repository = AsyncMock(spec=JobRepository)
    repository.get_by_source_external_id.return_value = None
    repository.get_by_fingerprint.return_value = JobORM(id=42, source=existing_source)
    outcome = await DeduplicationService(repository).check(incoming)
    assert outcome.is_duplicate and outcome.reason == "fingerprint"
