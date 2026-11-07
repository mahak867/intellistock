"""Probabilistic price paths from Kronos, a foundation model for candlesticks.

Kronos (https://github.com/shiyu-coder/Kronos, MIT) is vendored in ml/kronos/vendor with one change: the sampler can
return every path instead of their average, because IntelliStock shows a range, never a single line.

Optional: needs `pip install -r requirements-kronos.txt` (PyTorch) and the weights from Hugging Face on first use.
Nothing in the app depends on it until it passes scripts/evaluate_kronos.py on NSE prices.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MODEL = "NeoQuasar/Kronos-small"
TOKENIZER = "NeoQuasar/Kronos-Tokenizer-base"
# The revisions Kronos's own regression tests pin, so results are reproducible.
MODEL_REV = "901c26c1332695a2a8f243eb2f37243a37bea320"
TOKENIZER_REV = "0e0117387f39004a9016484a186a908917e22426"
COLS = ["open", "high", "low", "close", "volume", "amount"]


def future_days(last: pd.Timestamp, n: int) -> pd.DatetimeIndex:
    """The next n weekdays. Exchange holidays are ignored; Kronos only uses them as calendar features."""
    return pd.bdate_range(pd.Timestamp(last) + pd.Timedelta(days=1), periods=n)


def _stamps(idx) -> np.ndarray:
    idx = pd.DatetimeIndex(idx)
    return np.stack([idx.minute, idx.hour, idx.weekday, idx.day, idx.month], axis=1).astype(np.float32)


class KronosPaths:
    def __init__(self, model=None, tokenizer=None, model_id: str = MODEL, tokenizer_id: str = TOKENIZER,
                 model_rev: str | None = MODEL_REV, tokenizer_rev: str | None = TOKENIZER_REV,
                 max_context: int = 512, device: str = "cpu", clip: float = 5.0):
        import torch  # noqa: F401  (fail here, clearly, if the optional dependency is missing)

        from .vendor import Kronos, KronosTokenizer
        self.tokenizer = tokenizer or KronosTokenizer.from_pretrained(tokenizer_id, revision=tokenizer_rev)
        self.model = model or Kronos.from_pretrained(model_id, revision=model_rev)
        self.tokenizer.eval().to(device)
        self.model.eval().to(device)
        self.max_context, self.device, self.clip = max_context, device, clip

    def paths(self, frames: list[pd.DataFrame], horizon: int, samples: int = 50, T: float = 1.0,
              top_p: float = 0.9, seed: int = 0) -> np.ndarray:
        """Close-price paths, shape (len(frames), samples, horizon). Frames: same length, DatetimeIndex, OHLCV."""
        import torch

        from .vendor import auto_regressive_inference
        if not frames:
            return np.empty((0, samples, horizon))
        n = {len(f) for f in frames}
        if len(n) != 1:
            raise ValueError(f"all frames must have the same length for one batch, got {sorted(n)}")
        xs, xst, yst, mu, sd = [], [], [], [], []
        for f in frames:
            f = f.copy()
            if "volume" not in f:
                f["volume"] = 0.0
            f["amount"] = f["volume"] * f[["open", "high", "low", "close"]].mean(axis=1)
            x = f[COLS].to_numpy(np.float32)
            if np.isnan(x).any():
                raise ValueError("prices contain gaps (NaN)")
            m, s = x.mean(0), x.std(0)
            xs.append(np.clip((x - m) / (s + 1e-5), -self.clip, self.clip))
            xst.append(_stamps(f.index))
            yst.append(_stamps(future_days(f.index[-1], horizon)))
            mu.append(m)
            sd.append(s)
        torch.manual_seed(seed)
        t = lambda a: torch.from_numpy(np.stack(a)).to(self.device)  # noqa: E731
        z = auto_regressive_inference(self.tokenizer, self.model, t(xs), t(xst), t(yst), self.max_context, horizon,
                                      self.clip, T, 0, top_p, samples, False, keep_samples=True)
        z = z[:, :, -horizon:, 3]                                   # (B, samples, horizon), close, normalised
        mu, sd = np.stack(mu)[:, 3][:, None, None], np.stack(sd)[:, 3][:, None, None]
        return z * (sd + 1e-5) + mu


def bands(paths: np.ndarray, qs=(0.1, 0.5, 0.9)) -> np.ndarray:
    """Quantiles across samples: shape (len(qs), ..., horizon)."""
    return np.quantile(paths, qs, axis=-2)
