"""V0.58.1: proxy_util fast unit tests — V0.48.2 #26 代理层接入 env infra.

Test scope: parse_proxy_env + ProxyConfig.to_playwright_kwargs + masked() 纯函数, 0 第三方
依赖, 0 真接代理 (autonomous safe). 真接付费代理 + 真测 akamai 403→200 = V0.58.x.1 maintainer 红线.
"""

from __future__ import annotations

import pytest

from web_agent.proxy_util import ProxyConfig, parse_proxy_env


# --- parse_proxy_env ---


def test_parse_proxy_env_unset_returns_none() -> None:
    """V0.58.1: env 空 → None (autonomous 默关)."""
    assert parse_proxy_env("") is None
    assert parse_proxy_env(None) is None or isinstance(parse_proxy_env(None), ProxyConfig)
    # ↑ 真 env 可能含值 (本机 user 配 WEB_AGENT_PROXY); 显式传 "" 才稳测


def test_parse_proxy_env_unset_via_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """V0.58.1: 真 env unset → None."""
    monkeypatch.delenv("WEB_AGENT_PROXY", raising=False)
    assert parse_proxy_env() is None


def test_parse_proxy_env_no_scheme_returns_none() -> None:
    """V0.58.1: 缺 scheme (`host:port` without http://) → None 防意外解析."""
    assert parse_proxy_env("proxy.example.com:8080") is None


def test_parse_proxy_env_http_no_auth() -> None:
    """V0.58.1: `http://host:port` 无 auth → server 设, username/password 空."""
    cfg = parse_proxy_env("http://proxy.example.com:8080")
    assert cfg is not None
    assert cfg.server == "http://proxy.example.com:8080"
    assert cfg.username == ""
    assert cfg.password == ""


def test_parse_proxy_env_http_with_auth() -> None:
    """V0.58.1: `http://user:pw@host:port` 拆 auth → server 不含 auth."""
    cfg = parse_proxy_env("http://alice:s3cret@proxy.example.com:8080")
    assert cfg is not None
    assert cfg.server == "http://proxy.example.com:8080"  # auth 拆出
    assert cfg.username == "alice"
    assert cfg.password == "s3cret"


def test_parse_proxy_env_socks5_no_port() -> None:
    """V0.58.1: socks5 默无 port (1080 标准) → server 不含 port suffix."""
    cfg = parse_proxy_env("socks5://proxy.example.com")
    assert cfg is not None
    assert cfg.server == "socks5://proxy.example.com"  # 无 :port suffix


def test_parse_proxy_env_via_env_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """V0.58.1: env 通过 monkeypatch 注入 (无显式 env_value 参数)."""
    monkeypatch.setenv("WEB_AGENT_PROXY", "http://localhost:3128")
    cfg = parse_proxy_env()
    assert cfg is not None
    assert cfg.server == "http://localhost:3128"


def test_parse_proxy_env_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """V0.58.1: env 前后空白 strip (常见 .env 文件复制粘贴)."""
    monkeypatch.setenv("WEB_AGENT_PROXY", "  http://x:8080  ")
    cfg = parse_proxy_env()
    assert cfg is not None
    assert cfg.server == "http://x:8080"


# --- ProxyConfig.to_playwright_kwargs ---


def test_to_playwright_kwargs_no_auth() -> None:
    """V0.58.1: 无 auth → kwargs 仅 server (Playwright 不期望空 username/password)."""
    cfg = parse_proxy_env("http://proxy.example.com:8080")
    assert cfg is not None
    kwargs = cfg.to_playwright_kwargs()
    assert kwargs == {"server": "http://proxy.example.com:8080"}


def test_to_playwright_kwargs_with_auth() -> None:
    """V0.58.1: 含 auth → kwargs 含 username/password (Playwright auth 路径)."""
    cfg = parse_proxy_env("http://alice:s3cret@proxy.example.com:8080")
    assert cfg is not None
    kwargs = cfg.to_playwright_kwargs()
    assert kwargs == {
        "server": "http://proxy.example.com:8080",
        "username": "alice",
        "password": "s3cret",
    }


# --- ProxyConfig.masked (log safety, CLAUDE.md secrets 处理) ---


def test_masked_no_auth_no_change() -> None:
    """V0.58.1: 无 auth proxy → masked 等于 server (无 auth 信息可 leak)."""
    cfg = parse_proxy_env("http://proxy.example.com:8080")
    assert cfg is not None
    assert cfg.masked() == "http://proxy.example.com:8080"


def test_masked_with_auth_redacted() -> None:
    """V0.58.1: 含 auth proxy → masked replace `user:pw` → `<auth>` (host/port 留可调试)."""
    cfg = parse_proxy_env("http://alice:s3cret@proxy.example.com:8080")
    assert cfg is not None
    masked = cfg.masked()
    assert "alice" not in masked
    assert "s3cret" not in masked
    assert "<auth>" in masked
    assert "proxy.example.com:8080" in masked  # host:port 留


# --- ProxyConfig frozen+slots ---


def test_proxy_config_frozen() -> None:
    """V0.58.1: ProxyConfig frozen (跟 Action/Mark/Usage 同模式) — 防 caller 误改."""
    cfg = ProxyConfig(server="http://x:8080", username="", password="", raw="http://x:8080")
    with pytest.raises(AttributeError):
        cfg.server = "evil"  # type: ignore[misc]


# --- V0.60.0: get_eval_proxy_kwargs (双 env opt-in 防 cassette leak) ---


def test_get_eval_proxy_kwargs_both_env_unset_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V0.60.0: 一级 + 二级 env 都 unset → None (eval 默关 proxy 防 cassette leak)."""
    from web_agent.proxy_util import get_eval_proxy_kwargs
    monkeypatch.delenv("WEB_AGENT_PROXY", raising=False)
    monkeypatch.delenv("WEB_AGENT_PROXY_EVAL", raising=False)
    assert get_eval_proxy_kwargs() is None


def test_get_eval_proxy_kwargs_only_primary_set_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V0.60.0 核心 leak guard: 一级 set 但二级 unset → None.

    cli/prod 路径 (V0.58.1 start_chrome.sh) 用 WEB_AGENT_PROXY 接 proxy, 但 eval 不该自动跟进
    (cassette leak 风险). 二级 WEB_AGENT_PROXY_EVAL=1 必须显式 set 才接 proxy.
    """
    from web_agent.proxy_util import get_eval_proxy_kwargs
    monkeypatch.setenv("WEB_AGENT_PROXY", "http://proxy.example.com:8080")
    monkeypatch.delenv("WEB_AGENT_PROXY_EVAL", raising=False)
    assert get_eval_proxy_kwargs() is None


def test_get_eval_proxy_kwargs_both_set_returns_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V0.60.0: 双 env set → Playwright launch kwargs dict (eval 显式 opt-in)."""
    from web_agent.proxy_util import get_eval_proxy_kwargs
    monkeypatch.setenv("WEB_AGENT_PROXY", "http://alice:s3cret@proxy.example.com:8080")
    monkeypatch.setenv("WEB_AGENT_PROXY_EVAL", "1")
    kwargs = get_eval_proxy_kwargs()
    assert kwargs == {
        "server": "http://proxy.example.com:8080",
        "username": "alice",
        "password": "s3cret",
    }


def test_get_eval_proxy_kwargs_secondary_not_one_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V0.60.0: 二级 env 值 != '1' (e.g. 'true'/'yes'/'TRUE') → None (跟 RUN_SLOW 同严格 '=="1"' 比对)."""
    from web_agent.proxy_util import get_eval_proxy_kwargs
    monkeypatch.setenv("WEB_AGENT_PROXY", "http://proxy.example.com:8080")
    for val in ("true", "yes", "TRUE", "0", " 1 ", ""):
        monkeypatch.setenv("WEB_AGENT_PROXY_EVAL", val)
        # " 1 " strip 后 == "1", 应过; 测剩余应 None
        if val.strip() == "1":
            assert get_eval_proxy_kwargs() is not None, f"val={val!r} strip 后等 '1' 应 opt-in"
        else:
            assert get_eval_proxy_kwargs() is None, f"val={val!r} != '1' 应 None"
