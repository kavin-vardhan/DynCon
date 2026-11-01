// The region preview window: where the second copy of the game puts itself, and how.
//
// Plan v6 §7 and §11. The preview is not a different program - it is the *same packaged
// build* started with `-DCPreview -DCRegion=r2 -DCFollowRegion`, which makes it a player in
// another region with no input, no audio, a 30 fps cap and the cheapest settings. All this
// class does is put its window where the booth needs it:
//
//   * borderless, so there is no title bar or frame on a booth screen;
//   * on the right-hand monitor, over the rectangle the portal's Region-check step leaves
//     empty: the **right half of that monitor, vertically centred, half the monitor's width
//     and height** - 960 x 540 at (960, 270) on a 1920 x 1080 screen. The same rule is
//     written in `portal/style.css` (`.preview-reserve`) and in
//     `booth/pad_helper.py` (`PreviewWindow.monitor_rect`), and each of the three says so;
//   * topmost while it is shown, so it sits over the kiosk browser;
//   * **off-screen, not minimised, when it is hidden** - a minimised Unreal window stops
//     drawing, and the point of this window is to be already showing the right thing the
//     moment the portal asks for it;
//   * never activated. Every move carries SWP_NOACTIVATE: the main game keeps focus and
//     pad 1 all day (plan v6 §11), and a window that took focus when it appeared would
//     take the Player's controller with it.
//
// Showing and hiding it afterwards is the **pad helper's** job, not the game's - the portal
// tells the helper when the Region-check step opens and closes, and the helper moves the
// window. So this class also writes a small JSON file saying where "there" is, which is how
// the helper knows where to put it back without a magic number shared between two programs.
//
// Windows only, by construction: the booth is one Windows PC. On any other platform every
// call reports that it did nothing, and the preview still runs - it is simply a normal
// window.

#pragma once

#include "CoreMinimal.h"

/** The home rectangle, in desktop pixels. */
struct FDCPreviewRect
{
	int32 X = 0;
	int32 Y = 0;
	int32 W = 960;
	int32 H = 540;

	bool IsValid() const { return W > 0 && H > 0; }
	FString Describe() const { return FString::Printf(TEXT("%d,%d %dx%d"), X, Y, W, H); }
};

class DYNAMICCONTENTS_API FDCPreviewWindow
{
public:
	/** The game's own top-level window, or nullptr before Slate has one. */
	static void* GetGameWindowHandle();

	/**
	 * The right half of the monitor the preview belongs on, vertically centred.
	 *
	 * Which monitor: the right-most **non-primary** one, because the booth's portal screen
	 * is the second monitor and the game has the primary. With one monitor there is nothing
	 * to choose and it uses that - which is what a development PC has.
	 * `-DCPreviewMonitor=<n>` (1-based, in the order the platform lists them) overrides the
	 * choice and `-DCPreviewRect=x,y,w,h` overrides the whole answer.
	 */
	static FDCPreviewRect ComputeHomeRect(FString& OutHow);

	/** Hide it *now*, before anything has been drawn: how the window starts out of sight. */
	static bool HideAtBoot();

	/**
	 * Make it borderless, put it on the home rectangle, name it, and leave it either shown
	 * or parked off-screen. Returns false (with a reason) if there is no window yet.
	 */
	static bool Apply(const FDCPreviewRect& Home, bool bShown, const FString& Title,
		FString& OutError);

	/** Move between the home rectangle and off-screen, never activating. */
	static bool SetShown(const FDCPreviewRect& Home, bool bShown);

	/** Where the window actually is, for the log and the JSON file. */
	static bool GetWindowRect(FDCPreviewRect& Out);

	/** What the pad helper reads: the title, the home rectangle and this process. */
	static bool WriteStateFile(const FString& Path, const FString& Title,
		const FDCPreviewRect& Home, bool bShown);

	/** The exact title the pad helper matches on. Changing it changes both sides. */
	static const TCHAR* DefaultTitle();

	/**
	 * Where "hidden" is. Agrees with booth/pad_helper.py's OFFSCREEN_X / _Y.
	 *
	 * 30,000 rather than something rounder: Windows clamps a window position to a signed
	 * 16-bit number, so anything past 32,767 silently becomes 32,767 - which is still far
	 * off any real desktop, but it means the number that went in is not the number that
	 * comes out, and "is it hidden?" then reads as a bug. (It did.)
	 */
	static constexpr int32 OffScreenX = 30000;
	static constexpr int32 OffScreenY = 30000;
};
