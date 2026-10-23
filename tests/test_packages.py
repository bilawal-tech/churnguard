import csv

from simulator.masters.packages import CSV_PATH, build_packages

VALID_TYPES = {"combo", "social", "voice", "data"}


def test_count():
    assert len(build_packages()) == 29


def test_ids_unique():
    ids = [p["package_id"] for p in build_packages()]
    assert len(ids) == len(set(ids))


def test_names_unique():
    names = [p["name"] for p in build_packages()]
    assert len(names) == len(set(names))


def test_same_run_same_data():
    assert build_packages() == build_packages()


def test_types_valid():
    assert all(p["package_type"] in VALID_TYPES for p in build_packages())


def test_prices_positive():
    assert all(p["price_pkr"] > 0 for p in build_packages())


def test_has_some_quota():
    for p in build_packages():
        total = (p["quota_data_mb"] + p["quota_social_mb"] + p["quota_onnet_min"]
                 + p["quota_offnet_min"] + p["quota_anynet_min"]
                 + p["quota_intl_min"] + p["quota_sms"])
        assert total > 0


def test_ids_stable_when_rows_reordered(tmp_path):
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], rows[1:]
    body.reverse()
    p2 = tmp_path / "reordered.csv"
    with open(p2, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([header] + body)
    a = {p["package_id"]: p["name"] for p in build_packages()}
    b = {p["package_id"]: p["name"] for p in build_packages(p2)}
    assert a == b