import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest

from src.collectors.base import CollectionError
from src.collectors.getonboard import GetOnBoardCollector, parse_job, parse_page
from src.schemas.filters import UserFilterDTO
from src.services.filters import FilterService
from src.services.normalization import NormalizationService


def relation(*names):
    return {
        "data": [
            {"id": str(i), "type": "resource", "attributes": {"name": name}}
            for i, name in enumerate(names)
        ]
    }


def raw_job(job_id="acme-python"):
    return {
        "id": job_id,
        "type": "job",
        "links": {"public_url": f"https://www.getonbrd.com/jobs/{job_id}"},
        "attributes": {
            "title": "Python Backend Developer",
            "company": relation("Acme"),
            "description": "<p>Build <b>APIs</b> &amp; services.</p>",
            "functions": "<p>Own the backend.</p>",
            "remote": True,
            "remote_modality": "remote_local",
            "countries": ["Remote"],
            "location_regions": relation("Latin America"),
            "location_tenants": relation(),
            "location_cities": relation(),
            "tags": relation("Python", "FastAPI", "PostgreSQL", "Docker"),
            "modality": relation("Full time"),
            "seniority": relation("Semi Senior"),
            "min_salary": 2000,
            "max_salary": 3500,
            "currency": "USD",
            "salary_period": "month",
            "remote_zone": "UTC-5 to UTC-2",
            "published_at": 1790596800,
        },
    }


def page(items=None, total=1):
    return {
        "data": items if items is not None else [raw_job()],
        "meta": {"page": 1, "per_page": 50, "total_pages": total},
    }


def test_mapping_all_explicit_fields_and_no_invention():
    raw = raw_job()
    before = copy.deepcopy(raw)
    job = parse_job(raw)
    assert raw == before
    assert (job.source, job.external_id, job.company) == (
        "getonboard",
        "acme-python",
        "Acme",
    )
    assert job.title == "Python Backend Developer"
    assert job.url == "https://www.getonbrd.com/jobs/acme-python"
    assert job.description == "Build APIs & services.\n\nOwn the backend."
    assert job.remote and job.location == "Latin America"
    assert job.remote_regions == ["Latin America"]
    assert job.technologies == ["Python", "FastAPI", "PostgreSQL", "Docker"]
    assert (job.salary_min, job.salary_max, job.currency, job.salary_period) == (
        2000,
        3500,
        "USD",
        "month",
    )
    assert (job.employment_type, job.experience_level) == ("Full time", "Semi Senior")
    assert job.timezone_text == "UTC-5 to UTC-2"
    assert job.timezone_min_utc_offset is job.timezone_max_utc_offset is None
    assert job.published_at == datetime.fromtimestamp(1790596800, UTC)
    assert job.collected_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "region,expected",
    [
        ("Latin America", "latam"),
        ("LATAM", "latam"),
        ("South America", "south_america"),
        ("Worldwide", "worldwide"),
        ("Uruguay", "uruguay"),
    ],
)
def test_latam_regions_pass_existing_normalizer_and_eligibility(region, expected):
    raw = raw_job()
    raw["attributes"]["location_regions"] = relation(region)
    normalized = NormalizationService().normalize(parse_job(raw))
    assert normalized.remote_regions == [expected]
    assert normalized.technologies == ["python", "fastapi", "postgresql", "docker"]
    assert normalized.employment_type == "full_time"
    assert normalized.experience_level == "middle"
    assert (normalized.timezone_min_utc_offset, normalized.timezone_max_utc_offset) == (
        -5,
        -2,
    )
    assert (
        FilterService()
        .evaluate(
            normalized,
            UserFilterDTO(
                remote_only=True,
                required_technologies=["python"],
                allowed_regions=["worldwide"],
            ),
        )
        .accepted
    )


@pytest.mark.parametrize(
    "country", ["Chile", "Argentina", "Uruguay", "Brazil", "Mexico", "Colombia", "Peru"]
)
def test_explicit_country_not_replaced_by_company_country(country):
    raw = raw_job()
    raw["attributes"].update(countries=[country], location_regions=relation())
    raw["attributes"]["company"]["data"][0]["attributes"]["country"] = "US"
    assert parse_job(raw).remote_regions == [country]


@pytest.mark.parametrize(
    "mode,flag,expected",
    [
        ("hybrid", True, False),
        ("no_remote", False, False),
        ("temporarily_remote", True, False),
        ("remote_local", True, True),
        ("fully_remote", True, True),
        (None, None, False),
        (None, "true", False),
    ],
)
def test_remote_requires_explicit_remote_data(mode, flag, expected):
    raw = raw_job()
    raw["attributes"].update(remote_modality=mode, remote=flag)
    assert parse_job(raw).remote is expected


def test_remote_marker_is_not_worldwide_or_country_eligibility():
    raw = raw_job()
    raw["attributes"]["location_regions"] = relation()
    job = parse_job(raw)
    assert job.remote_regions == [] and job.location is None
    raw["attributes"]["remote_modality"] = "fully_remote"
    assert parse_job(raw).remote_regions == ["Worldwide"]
    raw["attributes"]["countries"] = ["Chile"]
    assert parse_job(raw).remote_regions == ["Chile"]


def test_missing_optional_fields_and_unexpanded_relations():
    raw = raw_job()
    raw["attributes"] = {
        "title": "Engineer",
        "company": {"data": {"id": "acme"}},
        "seniority": {"data": {"id": "3"}},
        "tags": {"data": [{"id": "python"}]},
    }
    job = parse_job(raw)
    assert job.company is job.description is job.location is None
    assert job.published_at is job.experience_level is job.employment_type is None
    assert job.salary_min is job.salary_max is job.currency is job.salary_period is None
    assert job.remote is False
    assert job.remote_regions == job.technologies == []


def test_currency_and_period_are_unknown_when_api_omits_them():
    raw = raw_job()
    del raw["attributes"]["currency"], raw["attributes"]["salary_period"]
    job = parse_job(raw)
    assert job.salary_min == 2000
    assert job.currency is None and job.salary_period is None


@pytest.mark.parametrize("value", [True, -10, "2000", 1200.5])
def test_invalid_salary_is_not_coerced(value):
    raw = raw_job()
    raw["attributes"]["min_salary"] = value
    assert parse_job(raw).salary_min is None


@pytest.mark.parametrize("value", [None, True, "invalid", "2026-09-28T12:00:00", 1e100])
def test_invalid_or_naive_date_is_unknown(value):
    raw = raw_job()
    raw["attributes"]["published_at"] = value
    assert parse_job(raw).published_at is None


@pytest.mark.parametrize(
    "body", [None, [], {}, {"data": {}}, page(total=-1), page(total=True), page([{}])]
)
def test_invalid_response_is_not_successful_empty_batch(body):
    with pytest.raises(CollectionError):
        parse_page(body)


def test_empty_and_mixed_pages():
    assert parse_page(page([])) == ([], 1)
    jobs, _ = parse_page(page([{}, raw_job()]))
    assert len(jobs) == 1


@pytest.fixture
def transport(monkeypatch):
    client_type = httpx.AsyncClient

    def install(handler):
        client = client_type(transport=httpx.MockTransport(handler))
        factory = Mock(return_value=client)
        monkeypatch.setattr("src.collectors.getonboard.httpx.AsyncClient", factory)
        return factory

    return install


async def test_bounded_pagination_headers_expansion_and_page_dedup(transport):
    calls = []

    def handle(request):
        calls.append(request)
        number = int(request.url.params["page"])
        return httpx.Response(
            200, json=page([raw_job(), raw_job(f"job-{number}")], total=100)
        )

    factory = transport(handle)
    jobs = await GetOnBoardCollector(max_pages=2, timeout=7).collect()
    assert [job.external_id for job in jobs] == ["acme-python", "job-1", "job-2"]
    assert len(calls) == 2
    assert calls[0].url.params["per_page"] == "50"
    assert set(calls[0].url.params.get_list("expand[]")) == set(
        GetOnBoardCollector.expansions
    )
    assert factory.call_args.kwargs["timeout"] == 7
    assert factory.call_args.kwargs["headers"]["User-Agent"].startswith("JobHunterBot/")


@pytest.mark.parametrize("body", [page([]), page(total=1), {"data": [raw_job()]}])
async def test_stops_at_empty_last_or_short_page(transport, body):
    calls = []
    transport(lambda r: (calls.append(r) or httpx.Response(200, json=body)))
    await GetOnBoardCollector().collect()
    assert len(calls) == 1


async def test_stops_repeated_page_instead_of_crawling_forever(transport):
    calls = []
    transport(lambda r: (calls.append(r) or httpx.Response(200, json=page(total=100))))
    assert len(await GetOnBoardCollector(max_pages=5).collect()) == 1
    assert len(calls) == 2


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_error_no_retry_or_partial_success(transport, status):
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "7200"})

    transport(response)
    before = datetime.now(UTC)
    with pytest.raises(CollectionError, match=str(status)) as error:
        await GetOnBoardCollector().collect()
    assert len(calls) == 1
    if status == 429:
        assert error.value.retry_at >= before + timedelta(hours=2)


async def test_second_page_failure_does_not_return_partial_batch(transport):
    def response(request):
        return (
            httpx.Response(200, json=page(total=2))
            if request.url.params["page"] == "1"
            else httpx.Response(503)
        )

    transport(response)
    with pytest.raises(CollectionError, match="503"):
        await GetOnBoardCollector().collect()


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
async def test_network_failure_is_sanitized(transport, error):
    def response(request):
        raise error("private transport details", request=request)

    transport(response)
    with pytest.raises(CollectionError) as caught:
        await GetOnBoardCollector().collect()
    assert "private transport" not in str(caught.value)


async def test_invalid_json_and_size_limit(transport, monkeypatch):
    transport(lambda _: httpx.Response(200, text="not JSON"))
    with pytest.raises(CollectionError, match="invalid JSON"):
        await GetOnBoardCollector().collect()
    monkeypatch.setattr(GetOnBoardCollector, "max_response_bytes", 5)
    transport(lambda _: httpx.Response(200, json=page()))
    with pytest.raises(CollectionError, match="size limit"):
        await GetOnBoardCollector().collect()


@pytest.mark.parametrize(
    "options",
    [
        {"max_pages": 0},
        {"max_pages": 6},
        {"max_pages": True},
        {"per_page": 121},
        {"per_page": 0},
    ],
)
def test_invalid_pagination_configuration(options):
    with pytest.raises(ValueError):
        GetOnBoardCollector(**options)


def test_collector_uses_profession_neutral_remote_search():
    assert GetOnBoardCollector.api_url == "https://www.getonbrd.com/api/v0/search/jobs"
    raw = raw_job()
    raw["attributes"]["title"] = "Accountant"
    raw["attributes"]["tags"] = relation("Excel")
    assert NormalizationService().normalize(parse_job(raw)).technologies == ["excel"]
