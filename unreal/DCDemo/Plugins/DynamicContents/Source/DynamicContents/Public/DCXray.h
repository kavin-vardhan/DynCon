// The X-ray view: the overlay that answers "isn't this just ChunkDownloader?".
//
// Plan v6's glossary calls it "Optional overlay: pre-fetch ring on the ground, the manifest,
// the cache list", and plan v6 §10 item 1 puts it in the game build. Off by default, toggled
// from the pause menu and with View / Back on the player pad.
//
// Five things, because five things are what a download manager has not got:
//
//   1. a **pre-fetch ring** on the ground round every slot, at the slot's real pre-fetch
//      radius, coloured by where that slot is in the lifecycle. A slot is a place in a
//      shipped map with a contract attached, not a file;
//   2. the **manifest** of the nearest slot - content and version, the pack, its size, the
//      SHA-256, whether the signature checked out, the region, the lot and block it is
//      showing under, and when it stops being valid. Signed, per slot, per region, per
//      block;
//   3. the **cache**: the packs on disk, their size, whether they are mounted, in
//      least-recently-used order;
//   4. the **lifecycle log**: the last few transitions with their milliseconds;
//   5. a **frame-time graph** over the last ten seconds with a tick at every mount, spawn
//      and unload - so anybody can watch a swap happen and see that nothing spikes.
//
// Every heading and every value is English (English only, decided 2026-11-02). The
// headings used to carry a Japanese word in front of them; the values never did, and never
// would have — a hash, a file name, a state name out of the lifecycle figure and a number
// of milliseconds are what the client is really doing, and translating them would be a lie
// about it.
//
// It is drawn on the HUD canvas for the reasons in DCStatusHud.h - no .uasset, no UMG, it
// survives a Shipping build and it lands in a screenshot - and it is built out of the
// counters the subsystem already keeps, so turning it on costs a few hundred canvas items
// and no new work per frame. A graph of frame time that cost frame time would be a liar.

#pragma once

#include "CoreMinimal.h"

class UCanvas;
class UFont;
class UDCSubsystem;

namespace FDCXray
{
	/**
	 * Draw the whole overlay.
	 *
	 * `TopY` is the bottom of the status strip: the panels start under it so the two never
	 * overlap, whatever the strip's longest line happens to be.
	 */
	DYNAMICCONTENTS_API void Draw(UCanvas* Canvas, const UDCSubsystem* Subsystem,
		float UiScale, float TopY);
}
