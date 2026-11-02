#include "DynamicContents.h"

#include "DCPreview.h"

#include "Containers/Ticker.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

/**
 * The runtime module. One job of its own: in the region preview window (`-DCPreview`), hide
 * the game window the frame it appears.
 *
 * It has to happen here rather than in ADCRuntimeGameMode, which is where the rest of the
 * preview lives, because a Shipping build always starts in the default map and travels to
 * the one it was asked for (`-DCMap=`) - so the runtime game mode's BeginPlay is several
 * seconds after the window exists, and for those seconds the booth would be looking at a
 * bordered window of the spike map. Plan v6 §7 wants this window visible only during the
 * region check.
 *
 * A ticker rather than a delegate because the window is made by the engine's own start-up
 * and there is no "the game window now exists" hook that fires before the first frame; this
 * is the first frame, and it stops itself the moment it has a handle.
 */
class FDynamicContentsModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		if (!FParse::Param(FCommandLine::Get(), TEXT("DCPreview")))
		{
			return;
		}
		HideTicker = FTSTicker::GetCoreTicker().AddTicker(
			FTickerDelegate::CreateLambda([this](float) { return TryHide(); }));
	}

	virtual void ShutdownModule() override
	{
		if (HideTicker.IsValid())
		{
			FTSTicker::GetCoreTicker().RemoveTicker(HideTicker);
			HideTicker.Reset();
		}
	}

private:
	/** True to keep ticking. Gives up after a few seconds rather than ticking all day. */
	bool TryHide()
	{
		++Attempts;
		if (FDCPreviewWindow::HideAtBoot())
		{
			DC_LOG(Log, TEXT("PREVIEW window hidden at boot (attempt %d)"), Attempts);
			HideTicker.Reset();
			return false;
		}
		return Attempts < 2000;
	}

	FTSTicker::FDelegateHandle HideTicker;
	int32 Attempts = 0;
};

IMPLEMENT_MODULE(FDynamicContentsModule, DynamicContents);
