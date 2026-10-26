"""Stage-1 exit test (demo plan v6 §14 step 1, server side).

*"A hand-written allocation makes the content appear, ten times out of ten."*

With the server running, this writes ten allocations by hand — different games, slots,
regions and pieces, one of them a **real cooked pack**, one a **version-2 push** onto a live
allocation, one a **brand change**, one a **corrupt-pack sabotage** round, one a **rival**
block — and after each one runs `fake_client.py` as a separate process and checks the line
it printed. The client verifies the manifest's RS256 signature and every file's SHA-256
before it prints MOUNT, so a passing round means the whole delivery path worked.

    python tools\\stage1_exit_test.py                       # against 127.0.0.1:8700
    python tools\\stage1_exit_test.py --url http://127.0.0.1:8701 --keep
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

SERVER_DIR = Path(__file__).resolve().parent.parent
TOOLS = SERVER_DIR / "tools"
LONG = 30.0            # minutes: the rounds must not expire while the test is running


@dataclass
class Round:
    n: int
    what: str
    game: str
    region: str
    slot: str
    expect: list[str]                      # lines that must appear, in this order
    slots_filter: str = ""
    before: Any = None                     # callable(ctx) run before the client
    lines: list[str] = field(default_factory=list)
    ok: bool = False
    detail: str = ""


class ExitTest:
    def __init__(self, url: str, cache: Path, keep: bool, verbose: bool):
        self.url = url.rstrip("/")
        self.http = httpx.Client(base_url=self.url, timeout=180.0)
        self.cache = cache
        self.keep = keep
        self.verbose = verbose
        self.content: dict[str, str] = {}      # demo file -> content id
        self.all_lines: list[str] = []

    # ---- helpers -------------------------------------------------------------------

    def api(self, method: str, path: str, **kw) -> dict[str, Any]:
        response = self.http.request(method, path, **kw)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {response.status_code} {response.text[:300]}")
        return response.json()

    def upload(self, filename: str, content_id: str | None = None) -> dict[str, Any]:
        path = SERVER_DIR / "demo_files" / filename
        if not path.is_file():
            raise RuntimeError(f"{path} is missing — run tools/make_fake_packs.py first")
        data = path.read_bytes()
        files = {"file": (filename, data, "application/octet-stream")}
        where = f"/content/{content_id}/versions" if content_id else "/content"
        result = self.api("POST", where, files=files)
        if result["status"] != "approved":
            raise RuntimeError(f"{filename} was rejected: {result.get('reason')}")
        if not content_id:
            self.content[filename] = result["content_id"]
        print(f"  uploaded {filename:34} -> {result['content_id']} "
              f"{result['piece']} {result['version']} "
              f"({result['pack']['total_bytes'] / (1024 * 1024):.1f} MB, "
              f"pack {result['pack']['id']})", flush=True)
        return result

    def allocate(self, game: str, slot: str, region: str, content_id: str,
                 minutes: float = LONG) -> dict[str, Any]:
        return self.api("POST", "/admin/allocate",
                        json={"game": game, "slot": slot, "region": region,
                              "content_id": content_id, "minutes": minutes})

    def alloc_key(self, game: str, slot: str, region: str) -> str:
        return self.api("GET", "/changes", params={"game": game, "region": region})["slots"][slot]

    def run_client(self, game: str, region: str, slots: str = "") -> list[str]:
        cmd = [sys.executable, str(TOOLS / "fake_client.py"), "--url", self.url,
               "--game", game, "--region", region, "--once", "--cache", str(self.cache)]
        if slots:
            cmd += ["--slots", slots]
        if self.verbose:
            cmd += ["--verbose"]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        lines = [ln.rstrip() for ln in done.stdout.splitlines() if ln.strip()]
        if done.returncode not in (0, 1):
            lines.append(f"CLIENT EXIT {done.returncode}: {done.stderr.strip()[:300]}")
        for line in lines:
            print(f"    {line}", flush=True)
        self.all_lines += lines
        return lines

    # ---- the ten rounds -------------------------------------------------------------

    def build_rounds(self) -> list[Round]:
        brand1 = {"colour": "#E23D3D", "emblem": "star"}
        brand2 = {"colour": "#2F6FEB", "emblem": "chevron"}
        b1 = f"brand {brand1['colour']} {brand1['emblem']}"
        b2 = f"brand {brand2['colour']} {brand2['emblem']}"
        keys: dict[str, str] = {}

        def alloc(game: str, slot: str, region: str, file: str):
            def go(_ctx):
                self.allocate(game, slot, region, self.content[file])
            return go

        def push_v2(_ctx):
            keys["before_push"] = self.alloc_key("A", "A1", "r1")
            self.upload("content1_v2.dcpack", content_id=self.content["content1_v1.dcpack"])
            keys["after_push"] = self.alloc_key("A", "A1", "r1")
            if keys["after_push"] == keys["before_push"]:
                raise RuntimeError("alloc_key did not change when version 2 was pushed")
            print(f"    alloc_key A1/r1 {keys['before_push']} -> {keys['after_push']} "
                  f"(changed by the push)", flush=True)

        def change_brand(_ctx):
            before = self.alloc_key("A", "A1", "r1")
            self.api("POST", "/brand", json=brand2)
            after = self.alloc_key("A", "A1", "r1")
            if after == before:
                raise RuntimeError("alloc_key did not change when the brand changed")
            print(f"    alloc_key A1/r1 {before} -> {after} (changed by the new brand)",
                  flush=True)

        def sabotage(_ctx):
            self.allocate("B", "B2", "r3", self.content["content4_v2.dcpack"])
            armed = self.api("POST", "/admin/sabotage", json={"mode": "corrupt"})
            print(f"    sabotage armed: {armed['armed']}", flush=True)

        def rival(_ctx):
            written = self.allocate("A", "A3", "r1", "sys_rivalsmall")
            # the rotation would put the same piece here, so prove the *allocation* is
            # what is showing rather than the attract rotation
            showing = self.api("GET", "/resolve",
                               params={"game": "A", "slot": "A3", "region": "r1"})["showing"]
            if showing["source"] != f"alloc:{written['allocation_id']}":
                raise RuntimeError(f"A3/r1 is showing {showing['source']}, not the "
                                   f"allocation that was just written")
            print(f"    showing source: {showing['source']} ({showing['kind']})", flush=True)

        return [
            Round(1, "hand allocation, fake pack", "A", "r1", "A1",
                  [f"MOUNT A1 content1 v1 {b1}"], before=alloc("A", "A1", "r1", "content1_v1.dcpack")),
            Round(2, "tall piece in the tall slot", "A", "r2", "A2",
                  [f"MOUNT A2 content3 v1 {b1}"], before=alloc("A", "A2", "r2", "content3_v1.dcpack")),
            Round(3, "small piece, third region", "A", "r3", "A3",
                  [f"MOUNT A3 content4 v1 {b1}"], before=alloc("A", "A3", "r3", "content4_v1.dcpack")),
            Round(4, "other game", "B", "r1", "B1",
                  [f"MOUNT B1 content2 v1 {b1}"], before=alloc("B", "B1", "r1", "content2_v1.dcpack")),
            Round(5, "same content, another slot and region (cache hit)", "B", "r2", "B2",
                  [f"MOUNT B2 content4 v1 {b1}"], before=alloc("B", "B2", "r2", "content4_v1.dcpack")),
            Round(6, "REAL cooked pack from unreal/_packs", "A", "r3", "A1",
                  [f"MOUNT A1 content1 v1 {b1}"],
                  before=alloc("A", "A1", "r3", "content1_v1.real.dcpack")),
            Round(7, "push version 2 onto the live allocation", "A", "r1", "A1",
                  [f"MOUNT A1 content1 v2 {b1}"], before=push_v2),
            Round(8, "new brand on the same allocation", "A", "r1", "A1",
                  [f"MOUNT A1 content1 v2 {b2}"], before=change_brand),
            Round(9, "corrupt sabotage: one fallback, then a clean retry", "B", "r3", "B2",
                  ["FALLBACK B2 default (sha256 mismatch", f"MOUNT B2 content4 v2 {b2}"],
                  slots_filter="B2", before=sabotage),
            Round(10, "rival block written by hand (identity from config)", "A", "r1", "A3",
                  ["MOUNT A3 rivalsmall v1 rival #1FA39A triangle"], before=rival),
        ]

    # ---- driving --------------------------------------------------------------------

    def setup(self) -> None:
        health = self.api("GET", "/admin/health")
        print(f"server ok: mode={health['mode']} key={health['key_fingerprint']} "
              f"demo_time={health['clock']['demo_time']} "
              f"block={health['clock']['block_seconds']}s", flush=True)
        missing = [p for p, v in health["system_packs"].items() if not v["pack_id"]]
        if missing:
            raise RuntimeError(f"the server has no pack for {', '.join(missing)} — run "
                               f"tools/make_fake_packs.py and restart it")
        print("system packs: " + ", ".join(
            f"{p}={v['version']}" for p, v in health["system_packs"].items()), flush=True)
        reset = self.api("POST", "/admin/reset")
        print(f"reset: generation {reset['reset_generation']}, "
              f"purge {len(reset['purge_packs'])} pack(s)", flush=True)
        self.api("POST", "/brand", json={"colour": "#E23D3D", "emblem": "star"})
        for name in ("content1_v1.dcpack", "content2_v1.dcpack", "content3_v1.dcpack",
                     "content4_v1.dcpack", "content4_v2.dcpack", "content1_v1.real.dcpack"):
            self.upload(name)

    def go(self) -> int:
        started = time.time()
        self.setup()
        rounds = self.build_rounds()
        for r in rounds:
            print(f"\n--- round {r.n}/10 · {r.what} · {r.game}/{r.slot}/{r.region}", flush=True)
            try:
                if r.before:
                    r.before(self)
                r.lines = self.run_client(r.game, r.region, r.slots_filter)
            except Exception as e:                        # a round can fail for any reason
                r.ok, r.detail = False, f"{type(e).__name__}: {e}"
                print(f"    ROUND FAILED: {r.detail}", flush=True)
                continue
            r.ok, r.detail = self.check(r)
            print(f"    {'PASS' if r.ok else 'FAIL'}: {r.detail}", flush=True)

        passed = sum(1 for r in rounds if r.ok)
        print("\n" + "=" * 78)
        for r in rounds:
            print(f"{'PASS' if r.ok else 'FAIL'}  round {r.n:2}  {r.game}/{r.slot}/{r.region:3} "
                  f" {r.what}")
        print("=" * 78)
        print(f"STAGE-1 EXIT TEST: {passed}/10 in {time.time() - started:.0f}s")
        if not self.keep:
            self.api("POST", "/admin/reset")
            print("server reset (pass --keep to leave the allocations in place)")
        return 0 if passed == len(rounds) else 1

    def check(self, r: Round) -> tuple[bool, str]:
        at = 0
        for want in r.expect:
            found = next((i for i, line in enumerate(r.lines[at:], start=at)
                          if line.startswith(want)), None)
            if found is None:
                return False, f"no line starting '{want}'"
            at = found + 1
        return True, " then ".join(f"'{w}'" for w in r.expect)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8700")
    ap.add_argument("--cache", default=str(SERVER_DIR / "data" / "exit_test_cache"))
    ap.add_argument("--keep", action="store_true", help="leave the allocations in place")
    ap.add_argument("--verbose", action="store_true", help="the client's per-file notes too")
    args = ap.parse_args(argv)
    test = ExitTest(args.url, Path(args.cache), args.keep, args.verbose)
    try:
        return test.go()
    except Exception as e:
        print(f"EXIT TEST COULD NOT RUN: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
