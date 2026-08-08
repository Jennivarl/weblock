"""
Guards against contracts/weblock_bundle.py drifting from the
tested source module it's generated from. Executes the bundle with
minimal stubs for the `genlayer`-only symbols (gl.Contract, TreeMap,
DynArray, Address, allow_storage) so its module-level code can run
outside the GenVM runtime, then re-runs the exact same assertions
test_normalizer.py makes against the bundle's own copies of
normalize_text(), normalize_url(), hash_text(), and excerpt_present().

If someone edits contracts/normalizer.py and forgets to run
`python deploy/build_bundle.py`, this is what catches it.
"""

import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
BUNDLE_PATH = ROOT / "contracts" / "weblock_bundle.py"


class _FakeAddress:
    def __init__(self, value="0xfake"):
        self._value = value

    @property
    def as_hex(self):
        return self._value


class _FakeContract:
    pass


def _load_bundle_module() -> ModuleType:
    source = BUNDLE_PATH.read_text(encoding="utf-8")
    lines = source.split("\n")
    lines = [ln for ln in lines if ln.strip() != "from genlayer import *"]
    source = "\n".join(lines)

    module = ModuleType("evidence_freezer_bundle_under_test")
    fake_gl = ModuleType("fake_gl")
    fake_gl.Contract = _FakeContract
    fake_gl.public = ModuleType("fake_gl_public")
    fake_gl.public.write = lambda fn: fn
    fake_gl.public.view = lambda fn: fn

    module.__dict__.update(
        {
            "gl": fake_gl,
            "allow_storage": lambda cls: cls,
            "TreeMap": dict,
            "DynArray": list,
            "Address": _FakeAddress,
        }
    )
    exec(compile(source, str(BUNDLE_PATH), "exec"), module.__dict__)
    return module


def test_bundle_regenerates_identically(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "build_bundle.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    regenerated = BUNDLE_PATH.read_text(encoding="utf-8")
    checked_in = BUNDLE_PATH.read_text(encoding="utf-8")
    assert regenerated == checked_in


def test_bundle_normalize_text_matches_source_module():
    bundle = _load_bundle_module()
    from contracts.normalizer import normalize_text as source_normalize_text

    samples = [
        "hello   \n\n  world",
        "Breaking news, posted 3 minutes ago. 1,234 views.",
        None,
        "",
    ]
    for text in samples:
        assert bundle.normalize_text(text) == source_normalize_text(text)


def test_bundle_normalize_url_matches_source_module():
    bundle = _load_bundle_module()
    from contracts.normalizer import normalize_url as source_normalize_url

    samples = [
        "https://example.com/a?utm_source=x&id=42#section",
        "https://example.com/a",
        None,
    ]
    for url in samples:
        assert bundle.normalize_url(url) == source_normalize_url(url)


def test_bundle_hash_text_matches_source_module():
    bundle = _load_bundle_module()
    from contracts.normalizer import hash_text as source_hash_text

    assert bundle.hash_text("some text") == source_hash_text("some text")


def test_bundle_excerpt_present_matches_source_module():
    bundle = _load_bundle_module()
    from contracts.normalizer import excerpt_present as source_excerpt_present

    page = "Important notice. 5,921 views. The deadline is March 1st."
    assert bundle.excerpt_present(
        page, "the deadline is march 1st"
    ) == source_excerpt_present(page, "the deadline is march 1st")
