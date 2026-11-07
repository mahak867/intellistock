"""Plumbing tests for the optional Kronos forecaster, with a tiny randomly initialised model (no download).

Skipped unless PyTorch is installed (requirements-kronos.txt). Accuracy is measured by scripts/evaluate_kronos.py.
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")
pytest.importorskip("einops")

from ml.kronos.forecast import KronosPaths, bands, future_days  # noqa: E402
from ml.kronos.vendor import Kronos, KronosTokenizer  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def tiny():
    tok = KronosTokenizer(d_in=6, d_model=32, n_heads=2, ff_dim=64, n_enc_layers=1, n_dec_layers=1, ffn_dropout_p=0,
                          attn_dropout_p=0, resid_dropout_p=0, s1_bits=4, s2_bits=4, beta=0.05, gamma0=1, gamma=1.1,
                          zeta=0.05, group_size=4)
    mod = Kronos(s1_bits=4, s2_bits=4, n_layers=1, d_model=32, n_heads=2, ff_dim=64, ffn_dropout_p=0, attn_dropout_p=0,
                 resid_dropout_p=0, token_dropout_p=0, learn_te=True)
    return KronosPaths(model=mod, tokenizer=tok)


def frame(n=120, seed=0):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(0.01 * rng.standard_normal(n)))
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6},
                        index=pd.bdate_range("2024-01-01", periods=n))


def test_paths_keep_every_sample():
    kp, f = tiny(), frame()
    p = kp.paths([f, f], horizon=5, samples=7)
    assert p.shape == (2, 7, 5) and np.isfinite(p).all()
    assert p[0].std(axis=0).max() > 0                      # the samples differ: nothing was averaged away
    assert np.allclose(kp.paths([f], 5, 7, seed=3), kp.paths([f], 5, 7, seed=3))
    b = bands(p)
    assert b.shape == (3, 2, 5) and (b[0] <= b[1]).all() and (b[1] <= b[2]).all()


def test_input_checks_and_calendar():
    kp = tiny()
    with pytest.raises(ValueError):
        kp.paths([frame(100), frame(90)], 5)
    g = frame()
    g.iloc[3, 0] = np.nan
    with pytest.raises(ValueError):
        kp.paths([g], 5)
    assert list(future_days(pd.Timestamp("2026-11-06"), 2).day) == [9, 10]   # Friday -> Monday, Tuesday


def test_evaluate_and_summary(tmp_path):
    spec = importlib.util.spec_from_file_location("evaluate_kronos", ROOT / "scripts" / "evaluate_kronos.py")
    ek = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_kronos"] = ek
    spec.loader.exec_module(ek)
    r = ek.evaluate("TEST", frame(400), tiny(), context=64, span=200, step=20, samples=5, batch=4)
    assert r["origins"] == 10
    for h in ("h5", "h10"):
        assert 0 <= r[h]["coverage"] <= 1 and r[h]["pinball"] > 0 and r[h]["baseline_pinball"] > 0
    (tmp_path / "TEST.json").write_text(json.dumps(r))

    class A:
        dir, md = str(tmp_path), str(tmp_path / "s.md")
    assert ek.summary(A) == 0
    assert "Verdict" in (tmp_path / "s.md").read_text()
    assert ek.pinball(np.zeros(3), np.zeros((3, 3))) == 0
