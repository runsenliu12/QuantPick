"""新增专题页路由的 smoke 测试：保证页面可渲染、含导航与关键内容。"""
import pytest
from src import server as srv


@pytest.fixture
def client():
    srv.app.config["TESTING"] = True
    with srv.app.test_client() as c:
        yield c


def test_index_has_nav(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "topnav" in body
    assert 'href="/backtest"' in body
    assert 'href="/factors"' in body
    assert 'href="/us-etf"' in body
    assert 'href="/methodology"' in body


def test_backtest_page(client):
    r = client.get("/backtest")
    assert r.status_code == 200
    assert "历史回测" in r.get_data(as_text=True)


def test_factors_page(client):
    r = client.get("/factors")
    assert r.status_code == 200
    assert "因子有效性" in r.get_data(as_text=True)


def test_us_etf_page(client):
    r = client.get("/us-etf")
    assert r.status_code == 200
    assert "美股 ETF" in r.get_data(as_text=True)


def test_methodology_page(client):
    r = client.get("/methodology")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "方法论" in body
    # 六步法应被渲染
    assert "运行方法论" in body
