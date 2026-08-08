# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Stage 5: WebLock, the Intelligent Contract wrapper.

Other contracts call freeze() when a claim is filed and verify() before
payout. Freezing records a normalized content hash of a web page and a
specific excerpt at a moment in time; verifying re-fetches the page later
and reports whether it is unchanged, changed only cosmetically, changed
in the substance of the excerpt itself, or gone.

Scope note: this contract freezes and verifies page *text* only. The
build plan also describes capturing and hashing a screenshot for visual
confirmation, but two validators screenshotting the same page rarely
produce byte-identical images (font rendering, anti-aliasing, dynamic
elements within the viewport), which makes screenshot hashes a poor fit
for gl.eq_principle.strict_eq's exact-equality requirement. Getting that
right needs either a perceptual-hash approach or a documented tolerance
for validator disagreement on image bytes, neither of which is built
here. Rather than guess at an unverified image-comparison API, this is
left as a known, documented limitation -- see the README.

This file needs the GenVM runtime to execute (it imports `genlayer`,
which only exists inside that runtime) so it isn't unit-tested directly.
The part that matters for correctness -- normalization -- lives in
normalizer.py and is fully covered by test/test_normalizer.py. This file
is thin wiring on top of that, verified against the GenLayer docs'
current API (gl.nondet.web.render, gl.eq_principle.strict_eq,
gl.eq_principle.prompt_non_comparative) but not yet exercised against a
live GenVM -- do that via Studio before deploying to Bradbury.
"""

import hashlib
from dataclasses import dataclass

from genlayer import *

from contracts.normalizer import excerpt_present, normalize_and_hash, normalize_text, normalize_url


@allow_storage
@dataclass
class Snapshot:
    url: str
    excerpt: str
    text_hash: str
    excerpt_hash: str
    submitter: Address
    status: str


class WebLock(gl.Contract):
    snapshots: TreeMap[str, Snapshot]
    by_submitter: TreeMap[Address, DynArray[str]]

    def __init__(self):
        pass

    def _snapshot_id(self, url: str, excerpt: str) -> str:
        material = "\x00".join(
            [
                gl.message.sender_address.as_hex,
                str(gl.message.chain_id),
                normalize_url(url),
                normalize_text(excerpt),
            ]
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()[:24]

    @gl.public.write
    def freeze(self, url: str, excerpt: str) -> str:
        """
        Fetch `url`, confirm `excerpt` actually appears on the page, and
        record a normalized content hash under a snapshot id derived
        from the sender, url, and excerpt. Raises if the excerpt is not
        found, or if this exact (sender, url, excerpt) combination has
        already been frozen.
        """
        snapshot_id = self._snapshot_id(url, excerpt)
        if snapshot_id in self.snapshots:
            raise gl.vm.UserError(f"already frozen: {snapshot_id}")

        normalized_url = normalize_url(url)

        def fetch_and_hash() -> dict:
            page_text = gl.nondet.web.render(normalized_url, mode="text")
            normalized = normalize_and_hash(page_text)
            return {
                "text_hash": normalized.text_hash,
                "excerpt_found": excerpt_present(page_text, excerpt),
            }

        result = gl.eq_principle.strict_eq(fetch_and_hash)

        if not result["excerpt_found"]:
            raise gl.vm.UserError(f"excerpt not found on page: {url}")

        excerpt_hash = normalize_and_hash(excerpt).text_hash

        self.snapshots[snapshot_id] = Snapshot(
            url=url,
            excerpt=excerpt,
            text_hash=result["text_hash"],
            excerpt_hash=excerpt_hash,
            submitter=gl.message.sender_address,
            status="frozen",
        )
        self.by_submitter.get_or_insert_default(gl.message.sender_address).append(
            snapshot_id
        )

        return snapshot_id

    @gl.public.write
    def verify(self, snapshot_id: str) -> str:
        """
        Re-fetch the frozen page and classify what happened since
        freeze(): "unchanged", "changed_cosmetic", "changed_material",
        or "dead". Updates and returns the snapshot's status.
        """
        if snapshot_id not in self.snapshots:
            raise gl.vm.UserError(f"unknown snapshot: {snapshot_id}")
        snapshot = self.snapshots[snapshot_id]
        url = snapshot.url
        excerpt = snapshot.excerpt

        def fetch_current() -> dict:
            try:
                page_text = gl.nondet.web.render(url, mode="text")
            except Exception:
                return {"dead": True, "text_hash": "", "excerpt_found": False}
            normalized = normalize_and_hash(page_text)
            return {
                "dead": False,
                "text_hash": normalized.text_hash,
                "excerpt_found": excerpt_present(page_text, excerpt),
            }

        result = gl.eq_principle.strict_eq(fetch_current)

        if result["dead"]:
            status = "dead"
        elif result["text_hash"] == snapshot.text_hash:
            status = "unchanged"
        elif result["excerpt_found"]:
            status = "changed_cosmetic"
        else:
            status = self._judge_material_change(url, excerpt)

        snapshot.status = status
        return status

    def _judge_material_change(self, url: str, excerpt: str) -> str:
        """
        The excerpt is no longer found verbatim on the page. That alone
        doesn't prove the meaning changed (a typo fix reads the same as
        a retraction under plain substring matching), so this asks
        GenVM's own non-comparative judgment to classify the page.

        `get_input` supplies context only -- GenVM performs the actual
        LLM classification internally from `task`/`criteria`, and
        validators independently judge the leader's answer against
        `criteria` rather than requiring identical text. The contract
        does not build or call an LLM prompt itself here; doing so was
        an earlier bug, caught by a local direct-mode test that failed
        with "Unknown gl_call request type: ExecPromptTemplate" once it
        became clear this method issues its own internal host call
        rather than routing through gl.nondet.exec_prompt.
        """

        def get_input() -> str:
            page_text = gl.nondet.web.render(url, mode="text")
            return f"Original excerpt:\n{excerpt}\n\nCurrent page text:\n{page_text}"

        verdict = gl.eq_principle.prompt_non_comparative(
            get_input,
            task=(
                "Classify whether the current page text still conveys the "
                'same substance as the original excerpt. Respond with '
                'exactly one word: "unchanged" or "changed".'
            ),
            criteria=(
                'The response must be exactly one word, either "unchanged" '
                'or "changed". Answer "unchanged" only if the core factual '
                "claim or commitment in the original excerpt still holds "
                "according to the current page text. Minor rewording, "
                "formatting, or unrelated changes elsewhere on the page do "
                'not count. Answer "changed" if the substance of the '
                "excerpt has shifted, been retracted, or been contradicted."
            ),
        )
        normalized_verdict = (verdict or "").strip().lower()
        return "changed_cosmetic" if "unchanged" in normalized_verdict else "changed_material"

    @gl.public.view
    def get(self, snapshot_id: str) -> dict:
        snapshot = self.snapshots[snapshot_id]
        return {
            "url": snapshot.url,
            "excerpt": snapshot.excerpt,
            "text_hash": snapshot.text_hash,
            "excerpt_hash": snapshot.excerpt_hash,
            "submitter": snapshot.submitter.as_hex,
            "status": snapshot.status,
        }

    @gl.public.view
    def get_by_submitter(self, submitter: str) -> dict:
        # GenLayer's calldata layer auto-decodes an address-shaped string
        # into an Address before it reaches this method, regardless of the
        # `str` type hint, so wrapping it again in Address(...) crashes
        # with "cannot convert 'Address' object to bytes". Confirmed live
        # on Bradbury; handle both shapes rather than assume one.
        addr = submitter if isinstance(submitter, Address) else Address(submitter)
        ids = self.by_submitter.get(addr, [])
        return {"snapshot_ids": list(ids)}
