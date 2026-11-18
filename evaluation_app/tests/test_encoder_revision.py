from types import SimpleNamespace
import sys

from spotify.src.embeddings import Clap


def test_clap_uses_the_pinned_revision_for_model_and_processor(monkeypatch):
    calls = []

    class Model:
        def eval(self):
            return self

        def to(self, device):
            return self

    def load_model(repo, **kwargs):
        calls.append((repo, kwargs))
        return Model()

    def load_processor(repo, **kwargs):
        calls.append((repo, kwargs))

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        ClapModel=SimpleNamespace(from_pretrained=load_model),
        ClapProcessor=SimpleNamespace(from_pretrained=load_processor),
    ))

    Clap(device="cpu", revision="pinned-revision")

    assert calls == [(Clap.repo, {"revision": "pinned-revision"})] * 2
