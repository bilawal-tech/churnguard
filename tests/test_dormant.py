import yaml

from simulator.usage.hook import _is_dormant


def _cfg():
    with open("config/config_test.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_dormant_is_deterministic():
    cfg = _cfg()
    ids = [f"C{n:07d}" for n in range(1, 50)]
    assert [_is_dormant(cfg, c) for c in ids] == [_is_dormant(cfg, c) for c in ids]


def test_dormant_share_is_about_quarter():
    cfg = _cfg()
    ids = [f"C{n:07d}" for n in range(1, 2001)]
    share = sum(_is_dormant(cfg, c) for c in ids) / len(ids)
    assert 0.20 < share < 0.30