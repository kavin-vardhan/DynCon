"""Stage-4 exit test (demo plan v6 §14 step 4, server side).

*"A pair of strangers goes from 'create your brand' to walking into their content unaided."*

This drives the API exactly as the portal will, in tour order, against a running server:

   1 the booth opens        — health, reset, create a brand
   2 your computer          — the curated upload list, upload Content 1, the four checks
   3 pick a game            — the games list and Game A's slot map
   4 bid on A1 for Japan    — the lot, the opening price, credits held
   5 the rival counter-bids — once, 3 s later, capped at twice the opening
   6 raise                  — back in front
   7 the clock runs out     — in real time, settled by the next request (no timers)
   8 won                    — credits charged, the block written from the lot
   9 the game mounts it     — fake_client.py for Japan; India shows its own rival
  10 push version 2         — the update list, the push, the game swaps
  11 the report             — the views the game posted, cost per view, time left
  12 multi-region           — one total split by footfall across all three regions of A1
  13 a lowball loses        — the rival wins the block and its piece shows

Run it with the server up:

    python tools\\stage4_exit_test.py
    python tools\\stage4_exit_test.py --fast     # skip the 45 s real-time wait in step 7
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

SERVER_DIR = Path(__file__).resolve().parent.parent
TOOLS = SERVER_DIR / "tools"
BRAND = {"colour": "#E23D3D", "emblem": "star"}
RIVAL_R2 = {"colour": "#F28C28", "emblem": "ring"}
RIVAL_R3 = {"colour": "#7B5CD6", "emblem": "diamond"}


class Stage4:
    def __init__(self, url: str, cache: Path, fast: bool, keep: bool):
        self.url = url.rstrip("/")
        self.http = httpx.Client(base_url=self.url, timeout=180.0)
        self.cache = cache
        self.fast = fast
        self.keep = keep
        self.checks: list[tuple[bool, str, str]] = []
        self.client_lines: list[str] = []

    # ---- plumbing ------------------------------------------------------------------

    def api(self, method: str, path: str, **kw) -> dict[str, Any]:
        response = self.http.request(method, path, **kw)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {response.status_code} "
                               f"{response.text[:300]}")
        return response.json()

    def step(self, number: int, title: str) -> None:
        print(f"\n=== {number} · {title} " + "=" * max(4, 62 - len(title)), flush=True)

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        self.checks.append((bool(ok), label, detail))
        print(f"    [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""),
              flush=True)
        return bool(ok)

    def say(self, text: str) -> None:
        print(f"    {text}", flush=True)

    def purse(self) -> dict[str, Any]:
        return self.api("GET", "/wallet")

    def run_client(self, game: str, region: str, slots: str = "") -> list[str]:
        cmd = [sys.executable, str(TOOLS / "fake_client.py"), "--url", self.url,
               "--game", game, "--region", region, "--once", "--cache", str(self.cache)]
        if slots:
            cmd += ["--slots", slots]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        lines = [ln.rstrip() for ln in done.stdout.splitlines() if ln.strip()]
        if done.returncode not in (0, 1):
            lines.append(f"CLIENT EXIT {done.returncode}: {done.stderr.strip()[:300]}")
        for line in lines:
            print(f"      {line}", flush=True)
        self.client_lines += lines
        return lines

    # ---- the tour ------------------------------------------------------------------

    def go(self) -> int:
        started = time.time()
        shutil.rmtree(self.cache, ignore_errors=True)

        # ---------------------------------------------------------------- 1
        self.step(1, "the booth opens")
        health = self.api("GET", "/admin/health")
        self.say(f"server {health['mode']} · key {health['key_fingerprint']} · "
                 f"demo time {health['clock']['demo_time']} · block "
                 f"{health['clock']['block_seconds']:.0f}s")
        self.check(all(row["pack_id"] for row in health["system_packs"].values()),
                   "the rival and default packs are registered",
                   ", ".join(f"{p}={v['version']}" for p, v in health["system_packs"].items()))
        reset = self.api("POST", "/admin/reset")
        self.say(f"reset: generation {reset['reset_generation']}")
        brand = self.api("POST", "/brand", json=BRAND)["brand"]
        self.check(brand["colour"] == BRAND["colour"] and brand["emblem"] == BRAND["emblem"],
                   "brand created", f"{brand['colour']} {brand['emblem']}")
        self.check(self.purse() == {"available": 2000, "held": 0, "charged": 0},
                   "wallet starts at 2,000 demo credits")

        # ---------------------------------------------------------------- 2
        self.step(2, "your computer, and the upload")
        listing = self.api("GET", "/demo-files")["files"]
        self.say("offered: " + ", ".join(f"{row['name']} ({row['bytes'] / 1048576:.1f} MB"
                                         + (f", {row['note']}" if row["note"] else "") + ")"
                                         for row in listing))
        self.check(len(listing) == 5 and sum(1 for r in listing if r["note"]) == 1,
                   "the curated list is v1 of each piece plus one built-to-fail file",
                   f"{len(listing)} files")
        pick = next(row for row in listing if row["piece"] == "content1")
        blob = self.http.get(f"/demo-files/{pick['name']}").content
        upload = self.api("POST", "/content",
                          files={"file": (pick["name"], blob, "application/octet-stream")})
        for row in upload["checks"]:
            self.say(f"check {row['check']:8} {row['state']:7} {row['detail']}")
        self.content_id = upload["content_id"]
        self.check(upload["status"] == "approved" and len(upload["pack"]["files"]) == 3,
                   "Content 1 approved and signed",
                   f"{self.content_id} {upload['piece']} {upload['version']} "
                   f"pack {upload['pack']['id']}")
        mine = self.api("GET", "/content")["content"][0]
        self.check(mine["fits"]["A1"]["ok"] and not mine["fits"]["A3"]["ok"],
                   "it fits A1 but not the small slots", mine["fits"]["A3"]["reason"])

        # ---------------------------------------------------------------- 3
        self.step(3, "pick a game, open the slot map")
        games = self.api("GET", "/games")["games"]
        self.say(" · ".join(f"{g['label']}: {g['slot_count']} slots, "
                            f"{g['players_online']} players online"
                            + (" [playing at this booth]" if g["live_at_booth"] else "")
                            for g in games))
        card = self.api("GET", "/games/A")
        a1 = next(s for s in card["slots"] if s["id"] == "A1")
        self.say(f"A1 is class {a1['size_class']} — {a1['limits_words']}")
        for region, lot in a1["lots"].items():
            foot = a1["footfall"][region]
            self.say(f"  {lot['region_label']:7} opening {lot['opening']:>4} · "
                     f"held by {lot['holder']:5} · footfall {foot['per_demo_hour']}/demo hour "
                     f"({foot['simulated']} simulated + {foot['live']} live) · "
                     f"{lot['credits_per_1000_views']} credits per 1,000 views")
        self.check(a1["lots"]["r1"]["opening"] == 300 and a1["lots"]["r1"]["holder"] == "rival",
                   "A1 / Japan opens at 300 with the rival holding")
        self.check(a1["lots"]["r1"]["closes_in_s"] is None,
                   "no clock until the first bid")
        self.lot_id = a1["lots"]["r1"]["lot_id"]

        # ---------------------------------------------------------------- 4
        self.step(4, "bid on A1 for Japan")
        result = self.api("POST", "/bids", json={
            "slot": "A1", "content_id": self.content_id,
            "bids": [{"region": "r1", "amount": 325, "lot_id": self.lot_id}]})["results"][0]
        self.say(f"bid 325 → {result['reason']}")
        self.check(result["accepted"] and result["lot"]["state"] == "running",
                   "the first bid starts the clock",
                   f"{result['lot']['closes_in_s']:.0f}s left")
        self.check(self.purse() == {"available": 1675, "held": 325, "charged": 0},
                   "325 credits held while leading")

        # ---------------------------------------------------------------- 5
        self.step(5, "the rival counter-bids, once")
        deadline = time.monotonic() + 15
        lot = self.api("GET", f"/lots/{self.lot_id}")
        while not lot["rival_has_bid"] and time.monotonic() < deadline:
            time.sleep(1.0)
            lot = self.api("GET", f"/lots/{self.lot_id}")
        for row in lot["history"]:
            self.say(f"  {row['at'][11:19]}  {row['bidder']:5} {row['amount']:>4}  {row['note']}")
        self.check(lot["rival_has_bid"] and lot["holder"] == "rival" and lot["highest"] == 350,
                   "the rival raised to 350 and took the lead",
                   f"its ceiling is {lot['rival_max']}")
        self.check(self.purse()["held"] == 0, "being outbid released the credits")

        # ---------------------------------------------------------------- 6
        self.step(6, "raise")
        raised = self.api("POST", "/bids", json={
            "slot": "A1", "content_id": self.content_id,
            "bids": [{"region": "r1", "amount": lot["next_bid"], "lot_id": self.lot_id}]
        })["results"][0]
        self.say(f"bid {lot['next_bid']} → {raised['reason']}")
        self.check(raised["accepted"] and raised["lot"]["holder"] == "you",
                   "back in front at 375")
        self.won_amount = raised["lot"]["highest"]
        self.check(self.purse()["held"] == self.won_amount, "375 credits held again")

        # ---------------------------------------------------------------- 7
        self.step(7, "the clock runs out")
        if self.fast:
            self.say("--fast: closing the lot with the staff control instead of waiting")
            self.api("POST", "/admin/close-auction", json={"lot_id": self.lot_id})
        else:
            lot = self.api("GET", f"/lots/{self.lot_id}")
            while lot["state"] != "closed":
                left = lot["closes_in_s"]
                self.say(f"  {left:5.1f}s left · highest {lot['highest']} ({lot['holder']})")
                time.sleep(min(6.0, max(left + 0.4, 0.5)))
                lot = self.api("GET", f"/lots/{self.lot_id}")
            self.say("  the next request after the close settled it — no timers anywhere")
        lot = self.api("GET", f"/lots/{self.lot_id}")
        self.check(lot["state"] == "closed" and lot["won_by"] == "you",
                   "the auction closed and the visitor won", f"settled {lot['settled_at']}")

        # ---------------------------------------------------------------- 8
        self.step(8, "won: credits charged, the block written")
        purse = self.purse()
        self.check(purse == {"available": 2000 - self.won_amount, "held": 0,
                             "charged": self.won_amount},
                   "the win charged the credits", str(purse))
        live = [row for row in self.api("GET", "/status/live")["showing"]
                if row["slot"] == "A1" and row["region"] == "r1"][0]
        self.check(live["kind"] == "visitor" and live["piece"] == "content1",
                   "A1 / Japan is showing the visitor's content",
                   f"source {live['source']}, ends {live['ends_at']}")
        self.check(lot["charged"] == self.won_amount and lot["allocation_id"] is not None,
                   "the lot records the charge and the allocation it wrote",
                   f"allocation {lot['allocation_id']}")

        # ---------------------------------------------------------------- 9
        self.step(9, "the game mounts it — and India is not affected")
        india_lot = next(s for s in self.api("GET", "/games/A")["slots"]
                         if s["id"] == "A1")["lots"]["r2"]
        self.api("POST", "/admin/close-auction", json={"lot_id": india_lot["lot_id"]})
        self.say("India's lot had no visitor bid, so closing it hands the block to its rival")
        japan = self.run_client("A", "r1", slots="A1")
        self.check(f"MOUNT A1 content1 v1 brand {BRAND['colour']} {BRAND['emblem']}" in japan,
                   "Japan mounts the visitor's content with their brand")
        india = self.run_client("A", "r2", slots="A1")
        self.check(f"MOUNT A1 rival2 v1 rival {RIVAL_R2['colour']} {RIVAL_R2['emblem']}" in india,
                   "India mounts its own rival, in the rival's colours")

        # ---------------------------------------------------------------- 10
        self.step(10, "push version 2")
        updates = self.api("GET", "/demo-files", params={"purpose": "update"})["files"]
        self.say("the update screen offers: " + ", ".join(row["name"] for row in updates))
        self.check(all(row["version"] == "v2" for row in updates) and len(updates) == 4,
                   "only the version-2 files are on the update list")
        pick = next(row for row in updates if row["piece"] == "content1")
        before = self.api("GET", "/changes", params={"game": "A", "region": "r1"})["slots"]["A1"]
        blob = self.http.get(f"/demo-files/{pick['name']}").content
        pushed = self.api("POST", f"/content/{self.content_id}/versions",
                          files={"file": (pick["name"], blob, "application/octet-stream")})
        after = self.api("GET", "/changes", params={"game": "A", "region": "r1"})["slots"]["A1"]
        self.say(f"alloc_key A1/r1 {before} → {after}")
        self.check(pushed["status"] == "approved" and pushed["version_n"] == 2 and
                   after != before,
                   "version 2 approved and the live block picked it up")
        swapped = self.run_client("A", "r1", slots="A1")
        self.check(f"MOUNT A1 content1 v2 brand {BRAND['colour']} {BRAND['emblem']}" in swapped,
                   "the game swapped to version 2 with the brand kept")

        # ---------------------------------------------------------------- 11
        self.step(11, "the report")
        report = self.api("GET", "/report")
        self.say(f"views are {report['views_model']}")
        for row in report["regions"]:
            self.say(f"  {row['label']:7} blocks {row['blocks']} · views {row['views']:>5} "
                     f"({row['views_simulated']} simulated + {row['views_live']} live) · "
                     f"visits {row['visits']} · dwell {row['dwell_s']:>5.1f}s · "
                     f"interactions {row['interactions']:>2} · charged {row['charged']:>4} · "
                     f"{row['cost_per_1000_views']} per 1,000 views · "
                     f"{row['time_left_s']:.0f}s left")
        japan = next(r for r in report["regions"] if r["region"] == "r1")
        self.check(japan["views_live"] >= 2 and japan["mounts"] >= 2,
                   "the report counts what the game posted",
                   f"{japan['views_live']} live views from {japan['mounts']} mounts")
        self.check(japan["views"] == japan["views_simulated"] + japan["views_live"]
                   and japan["views_simulated"] == 3600,
                   "views are simulated + live, shown split",
                   f"{japan['views_simulated']} + {japan['views_live']} = {japan['views']}")
        # the slot card quoted a price per 1,000 views before the bid; the report has to
        # agree with it afterwards, give or take the live views that only improve it
        quoted = self.api("GET", f"/lots/{self.lot_id}")["credits_per_1000_views"]
        self.check(japan["charged"] == self.won_amount
                   and 0 < japan["cost_per_1000_views"] <= quoted,
                   "cost per 1,000 views agrees with the slot card",
                   f"report {japan['cost_per_1000_views']} vs card {quoted} "
                   f"(charged {japan['charged']}, per view {japan['cost_per_view']})")
        self.check(japan["time_left_s"] > 0, "the block has time left on it",
                   f"{japan['time_left_s']:.0f}s")

        # ---------------------------------------------------------------- 12
        self.step(12, "a multi-region round on A1, split by footfall")
        total = 900
        split = self.api("GET", "/bids/split",
                         params={"slot": "A1", "total": total, "regions": "r1,r2,r3"})
        for row in split["bids"]:
            self.say(f"  {row['label']:7} footfall {row['footfall']:>4} → {row['amount']:>4} "
                     f"(next bid {row['next_bid']}, enough: {row['enough']})")
        self.check(sum(row["amount"] for row in split["bids"]) == total,
                   f"{total} split by footfall across three regions",
                   " / ".join(str(row["amount"]) for row in split["bids"]))
        placed = self.api("POST", "/bids", json={
            "slot": "A1", "content_id": self.content_id,
            "bids": [{"region": row["region"], "amount": max(row["amount"], row["next_bid"])}
                     for row in split["bids"]]})
        for row in placed["results"]:
            self.say(f"  {row['region']}: {'accepted' if row['accepted'] else 'refused'} — "
                     f"{row['reason']}")
        self.check(all(row["accepted"] for row in placed["results"]),
                   "every region accepted the bid", f"held {placed['wallet']['held']}")

        time.sleep(4)                                     # let the three rivals counter once
        lots = {row["region"]: row for row in
                self.api("GET", "/lots", params={"slot": "A1"})["lots"]
                if row["state"] != "closed"}
        for region, lot in lots.items():
            self.say(f"  {lot['region_label']:7} rival counter → {lot['highest']} "
                     f"({lot['holder']})")
        beat = self.api("POST", "/bids", json={
            "slot": "A1", "content_id": self.content_id,
            "bids": [{"region": r, "amount": lot["next_bid"], "lot_id": lot["lot_id"]}
                     for r, lot in lots.items()]})
        self.check(all(row["accepted"] for row in beat["results"]),
                   "the visitor beats the rival in all three regions",
                   f"held {beat['wallet']['held']}, available {beat['wallet']['available']}")
        self.api("POST", "/admin/close-auction", json={"lot_id": "all"})
        purse = self.purse()
        self.check(purse["available"] >= 0 and purse["charged"] <= 2000,
                   "all three regions of A1 won inside the 2,000 wallet", str(purse))
        booked = {row["region"]: row for row in self.api("GET", "/report")["regions"]}
        self.check(all(booked[r]["blocks"] >= 1 for r in ("r1", "r2", "r3")),
                   "a block is booked in every region",
                   ", ".join(f"{r}={booked[r]['blocks']}" for r in ("r1", "r2", "r3")))
        self.check(booked["r1"]["next_block_at"] is not None,
                   "Japan's new block queues behind the one already playing",
                   f"starts {booked['r1']['next_block_at']}")

        # ---------------------------------------------------------------- 13
        self.step(13, "a lowball round loses")
        small = next(s for s in self.api("GET", "/games/A")["slots"] if s["id"] == "A3")
        lot = small["lots"]["r3"]
        self.say(f"A3 / Europe opens at {lot['opening']}, the rival will go to "
                 f"{lot['rival_max']}")
        cabin = self.api("GET", "/demo-files")["files"]
        pick = next(row for row in cabin if row["piece"] == "content4")
        blob = self.http.get(f"/demo-files/{pick['name']}").content
        small_content = self.api("POST", "/content",
                                 files={"file": (pick["name"], blob,
                                                 "application/octet-stream")})
        lowball = self.api("POST", "/bids", json={
            "slot": "A3", "content_id": small_content["content_id"],
            "bids": [{"region": "r3", "amount": lot["next_bid"], "lot_id": lot["lot_id"]}]
        })["results"][0]
        self.say(f"bid {lot['next_bid']} → {lowball['reason']}")
        time.sleep(4)
        beaten = self.api("GET", f"/lots/{lot['lot_id']}")
        self.check(beaten["holder"] == "rival",
                   "the rival outbids the lowball and the visitor does not come back",
                   f"{beaten['highest']} vs {lowball['lot']['highest']}")
        self.api("POST", "/admin/close-auction", json={"lot_id": lot["lot_id"]})
        settled = self.api("GET", f"/lots/{lot['lot_id']}")
        self.check(settled["won_by"] == "rival" and settled["charged"] == 0,
                   "the rival won the block and the visitor was charged nothing")
        europe = self.run_client("A", "r3", slots="A3")
        self.check(f"MOUNT A3 rivalsmall v1 rival {RIVAL_R3['colour']} "
                   f"{RIVAL_R3['emblem']}" in europe,
                   "the slot shows the rival's own small piece, in the rival's colours")

        # ---------------------------------------------------------------- verdict
        passed = sum(1 for ok, _, _ in self.checks if ok)
        total_checks = len(self.checks)
        print("\n" + "=" * 78)
        for ok, label, _ in self.checks:
            print(f"{'PASS' if ok else 'FAIL'}  {label}")
        print("=" * 78)
        print(f"STAGE-4 EXIT TEST: {passed}/{total_checks} checks in "
              f"{time.time() - started:.0f}s")
        if not self.keep:
            self.api("POST", "/admin/reset")
            print("server reset (pass --keep to leave the campaign in place)")
        return 0 if passed == total_checks else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8700")
    ap.add_argument("--cache", default=str(SERVER_DIR / "data" / "stage4_cache"))
    ap.add_argument("--fast", action="store_true",
                    help="close the first auction with the staff control instead of waiting")
    ap.add_argument("--keep", action="store_true", help="leave the campaign in place")
    args = ap.parse_args(argv)
    test = Stage4(args.url, Path(args.cache), args.fast, args.keep)
    try:
        return test.go()
    except Exception as e:
        print(f"EXIT TEST COULD NOT RUN: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
