// The game's on-screen layer: the status strip, the interaction prompt and the waypoint
// marker. All three are drawn on the HUD canvas rather than in UMG on purpose - a Canvas HUD
// needs no .uasset, no UMG module and no editor work, it survives a Shipping build, and it
// lands in the viewport render target, so a screenshot taken with FScreenshotRequest carries
// it.
//
//   * the **status strip** is plan v6's "build · uptime · restarts: 0 · content loading
//     screens: 0" plus a line per slot, because the two zeroes are the claim: content
//     changed, and the game never restarted and never showed a loading screen;
//   * the **prompt** is the context label next to the door, a switch or the screen when the
//     Player is near enough to use it (plan v6 §3);
//   * the **waypoint marker** points at a slot whose content has just changed, until the
//     Player gets close.
//
// In the region preview window (`-DCPreview`) none of those three is drawn - it is not
// somebody's game, it is a picture of somewhere else - and the HUD draws one thing instead:
// a **tiny corner caption**, bilingual like the portal, saying which region this copy plays
// as. Japanese on top, English under it, in the words the server's own config gives
// (`/preview/region`'s `label_jp` and `label`). CJK on the HUD canvas works because the
// engine's Roboto is a composite font whose fallback typeface is DroidSansFallback, and that
// face is cooked into the build.
//
// Nothing here ever says anything about advertising, brands or money: the Player's screen is
// a game's screen (plan v6 §3). The only words are the strip's own instrumentation, four
// plain prompts and the preview's caption.
//
//   -DCUiScale=<f>   text scale
//   -DCNoStrip       hide the status strip (the prompt and the marker stay - they are the
//                    game's UI, not the demo's instrumentation)
//   -DCNoMarker      hide the waypoint marker
//   -DCPreview       the caption, and nothing else

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"

#include "DCStatusHud.generated.h"

class ADCSlot;

UCLASS()
class DYNAMICCONTENTS_API ADCStatusHud : public AHUD
{
	GENERATED_BODY()

public:
	ADCStatusHud();

	/** Text scale; -DCUiScale= on the command line. Booth screens are looked at from a metre. */
	UPROPERTY(EditDefaultsOnly, Category = "DC|UI")
	float UiScale = 1.3f;

	UPROPERTY(EditDefaultsOnly, Category = "DC|UI")
	FLinearColor PanelColour = FLinearColor(0.02f, 0.03f, 0.04f, 0.62f);

	/** The marker and the prompt: neutral, cool, nothing that reads as a brand colour. */
	UPROPERTY(EditDefaultsOnly, Category = "DC|UI")
	FLinearColor MarkerColour = FLinearColor(0.60f, 0.86f, 1.0f, 0.95f);

	virtual void BeginPlay() override;
	virtual void DrawHUD() override;

private:
	void DrawStrip();
	void DrawPrompt();
	void DrawMarkers();

	/** The preview window's corner caption: which region this copy is playing as. */
	void DrawPreviewCaption();

	/** A filled box with a border, the one shape all three of these are built out of. */
	void DrawPanel(float X, float Y, float W, float H, const FLinearColor& Fill);

	/**
	 * World point -> screen point. `bOffScreen` says it had to be pulled in to the edge,
	 * which is when the marker becomes an arrow instead of a diamond.
	 */
	bool ProjectToScreen(const FVector& World, FVector2D& Out, bool& bOffScreen) const;

	bool bStrip = true;
	bool bMarker = true;
	bool bPreview = false;
};
