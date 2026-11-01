// The status strip: the one piece of UI the demo always shows.
//
// Plan v6 wants "build · uptime · restarts: 0 · content loading screens: 0" plus a line per
// slot, because the two zeroes are the claim: content changed, and the game never restarted
// and never showed a loading screen. It is drawn on the HUD canvas rather than in UMG on
// purpose - a Canvas HUD needs no .uasset, no UMG module and no editor work, it survives a
// Shipping build, and it lands in the viewport render target, so a screenshot taken with
// FScreenshotRequest carries it.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"

#include "DCStatusHud.generated.h"

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

	virtual void BeginPlay() override;
	virtual void DrawHUD() override;
};
