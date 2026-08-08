# WEBLOCK

**Evidence on the web is editable. A verdict based on a page that changed afterward cannot be defended. WEBLOCK freezes what was there, and proves what moved.**

WEBLOCK is a Python Intelligent Contract on GenLayer. It captures a web page, and a specific excerpt from it, at a moment in time. Later, any contract can ask WEBLOCK to check that same page again and learn exactly what happened: nothing, something cosmetic, something that changed the substance of the excerpt itself, or the page is simply gone.

## Why this needs consensus

Anyone can screenshot a web page and claim it proves something. The problem is trust: a single party checking a page and reporting back gives no guarantee they checked honestly, or that the page will still say the same thing tomorrow. That is true everywhere, not just on GenLayer.

What GenLayer adds is a guarantee no single party can offer alone. When WEBLOCK freezes a page, multiple independent validators each fetch it and must agree on a normalized content hash before the snapshot is accepted. When WEBLOCK verifies a page later, the same independent agreement happens again. No single validator's fetch is trusted by itself, and the frozen record lives on chain permanently, so any other contract can rely on it without redoing the work.

## How it works

**1. The normalizer.** Plain Python, no network involved. Two validators fetching the same page a few seconds apart will see slightly different bytes: a rotating ad, a view counter, a "posted 3 minutes ago" timestamp. Hashed raw, that noise would make validators disagree about a page that never actually changed. The normalizer strips exactly that class of noise, so the same underlying page always produces the same hash regardless of which validator fetched it or when.

**2. Freezing.** `freeze(url, excerpt)` fetches the page, confirms the excerpt actually appears on it, and records a normalized content hash under a snapshot id. Every validator independently fetches and normalizes the same page and must agree on the exact hash before the snapshot is accepted.

**3. Verifying.** `verify(snapshot_id)` re-fetches the page later and classifies what happened. If the new hash matches exactly, nothing changed. If the hash differs but the excerpt is still found on the page word for word, the change is cosmetic. If the page cannot be reached at all, it is marked dead. Only when the excerpt itself is no longer found verbatim does WEBLOCK ask GenLayer's own judgment mechanism whether the underlying meaning actually shifted, since a simple rewording can look identical to a real retraction under plain text matching.

**4. The contract.** Another contract calls `freeze()` when a claim is filed and `verify()` before acting on it. `get()` returns the full stored record, and `get_by_submitter()` lists every snapshot a given address has frozen.

## Status

All core build stages are complete, tested, and confirmed working on live testnet Bradbury. The contract passes `genvm-lint check` with zero warnings and `genvm-lint validate` against the real GenLayer SDK.

| Stage | What it is | Status |
|-------|------------|--------|
| 1 | Decide what a snapshot contains | Done |
| 2 | The normalizer | Done, unit tested |
| 3 | Freezing | Done, confirmed live on Bradbury |
| 4 | Verifying | Done, confirmed live on Bradbury |
| 5 | The contract wrapper | Done |
| 6 | Test coverage | Done, 36 tests passing |
| 7 | Deployment | Done |

The deployed contract on Bradbury is at [`0x8C49E1D053928Cc36584b2f228C94438ff78A780`](https://explorer-bradbury.genlayer.com/address/0x8C49E1D053928Cc36584b2f228C94438ff78A780). A live end to end run against it: `freeze("https://example.com", "This domain is for use in documentation examples without needing permission.")` fetched the page through validator consensus and recorded a normalized hash, then `verify()` re-fetched the same page and correctly reported `"unchanged"`.

One code path remains genuinely unverified live rather than just locally: the branch that escalates to GenLayer's non-comparative judgment when an excerpt is no longer found verbatim (see Known limitations). Everything else in the freeze and verify flow, including the normalizer, consensus hashing, duplicate detection, and dead page handling, has run successfully against real GenLayer infrastructure.

## Running the tests

```bash
pip install -r requirements.txt
python -m pytest test/ -v
```

Most of these tests use GenLayer's Direct Execution Mode: the contract runs for real, in process, with web and language model responses mocked, so the actual `freeze()` and `verify()` logic is exercised end to end with no network calls and no blockchain involved. Two tests are skipped and documented rather than deleted: the direct mode testing tool in use does not yet mock the specific internal call GenLayer's non-comparative judgment principle relies on, so that particular code path needs a live network to exercise. Everything else, including duplicate detection, missing excerpts, counter noise, dead pages, and cosmetic changes, runs and passes locally.

## Deploying

GenVM deploys a single file's raw bytes as the contract code. It cannot see other files in this repository, so the contract as written in `contracts/weblock.py`, which imports from `contracts/normalizer.py`, cannot be deployed directly. A small script bundles both into one self-contained file before deployment.

```bash
python deploy/build_bundle.py
genlayer deploy --contract contracts/weblock_bundle.py
```

`test/test_bundle_consistency.py` checks that the generated bundle behaves identically to the tested source module, so an edit to `normalizer.py` that is not followed by rebuilding the bundle will fail a test rather than silently going out of sync.

## Known limitations

This is a first version, and some things are deliberately out of scope rather than guessed at.

**Screenshots are not hashed.** The build plan describes capturing and hashing a page screenshot alongside the text for visual confirmation. Two validators screenshotting the same page rarely produce byte identical images: font rendering, anti-aliasing, and dynamic elements within the viewport all vary. That makes a screenshot hash a poor fit for GenLayer's exact equality consensus check without either a perceptual hashing approach or an explicit tolerance for validator disagreement, neither of which is built here.

**Pages that require JavaScript, a login, or a paywall are not supported.** WEBLOCK reads whatever `gl.nondet.web.render` returns in text mode. A page that only renders its real content after JavaScript runs, or that shows a paywall message to an unauthenticated fetch, will be frozen against that paywall or placeholder text rather than the content a logged in visitor would see.

**A soft 404 will not be marked dead.** WEBLOCK treats a page as dead only when fetching it raises an error, which covers a domain that no longer resolves or a connection that is refused. A page that still loads successfully but displays a "not found" message will instead be treated as ordinary changed content, since GenLayer's page renderer does not appear to expose the underlying HTTP status code to a contract.

## A note for other builders

`gl.eq_principle.prompt_non_comparative(fn, task=..., criteria=...)` does not work the way its name might suggest. `fn` is not supposed to call the language model itself. `fn` supplies plain input data as a string, and GenLayer's own runtime builds the actual prompt internally from `task` and `criteria`, running it once for the leader and once per validator through its own comparison logic. The return value is the model's generated output itself, used directly.

An earlier version of this contract had `fn` build and send its own prompt, then pass `task` and `criteria` on top of that. That is redundant at best, and a local integration test caught it immediately: the mocked language model response never took effect, because the actual host call this function makes, `ExecPromptTemplate`, is different from the plain `ExecPrompt` call that `gl.nondet.exec_prompt` makes on its own. The fix, and the confirmed correct pattern, can be seen in `contracts/weblock.py`.

A second one, found live on Bradbury rather than locally: GenLayer's calldata layer will auto-decode a string argument that looks like an address into an actual `Address` object before it reaches a contract method, regardless of whether the method's type hint says `str`. Code that then wraps the parameter in `Address(...)` again, assuming it is still a plain string, fails with `cannot convert 'Address' object to bytes`. `get_by_submitter()` in `contracts/weblock.py` checks with `isinstance` first rather than assuming either shape. The local direct execution test for this method passed both before and after the fix, since its mocked calldata path does not appear to reproduce this specific auto-decoding behavior, which is why this one was only caught live.

## Requirements

- A running GenLayer Studio, or the hosted version at [studio.genlayer.com](https://studio.genlayer.com)
- Python 3.11 or newer
- Node.js, used by the deploy script at `deploy/deployScript.ts`

## License

MIT. See [LICENSE](LICENSE).
