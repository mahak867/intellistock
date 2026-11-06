"""A trained model must load back with identical predictions (the custom attention layer has to serialise)."""
import numpy as np
import pytest

tf = pytest.importorskip("tensorflow")


def test_bilstm_attention_save_load_roundtrip(tmp_path):
    from ml.models.lstm import BahdanauAttention, build_bilstm_attention

    m = build_bilstm_attention(sequence_length=10, n_features=4)
    x = np.random.default_rng(0).normal(size=(3, 10, 4)).astype("float32")
    p = tmp_path / "m.keras"
    m.save(p)
    back = tf.keras.models.load_model(p, custom_objects={"BahdanauAttention": BahdanauAttention})
    assert np.abs(m.predict(x, verbose=0) - back.predict(x, verbose=0)).max() == 0.0
