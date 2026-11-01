// The game mode the real demo map runs: it starts the DC client, draws the status strip, and
// - when a test asks it to - photographs every change it makes.
//
// It is deliberately separate from ADCSpikeGameMode. The spike mode is brief 006's pack
// round-trip driver: it is handed packs on the command line and talks to nothing. This one
// talks to the backend and is handed nothing. Keeping them apart is what lets
// `run_all_packs.ps1` keep working exactly as it did.
//
// Command line:
//   -DCBackend=http://127.0.0.1:8700   where the backend is          (UDCSubsystem)
//   -DCRegion=r1   -DCGame=A           which region and game          (UDCSubsystem)
//   -DCFollowRegion                    follow GET /preview/region     (UDCSubsystem)
//   -DCStatusFile=<path>               JSON a test script can watch   (UDCSubsystem)
//   -DCShotDir=<dir>                   photograph every change here
//   -DCAutoShot                        photograph even without a shot dir
//   -DCRunSeconds=<n>                  quit after n seconds (0 = never)
//   -DCQuitWhenFileExists=<path>       quit as soon as that file turns up: how a test (or
//                                      the booth's start script) stops the game cleanly
//                                      without killing the process
//   -DCUiScale=<f>  -DCNoStrip         the status strip               (ADCStatusHud)

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"

#include "DCRuntimeGameMode.generated.h"

class ACameraActor;
class ADCContentActor;
class ADCSlot;
struct FDCManifest;

UCLASS()
class DYNAMICCONTENTS_API ADCRuntimeGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	ADCRuntimeGameMode();

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
	/** One queued "something changed, photograph it" request. */
	struct FShotRequest
	{
		FString SlotId;
		FString Label;

		/** Which activation this picture is of, so it is filed against the right one. */
		int32 ActivationSeq = 0;
	};

	void OnSlotActive(ADCSlot* Slot, const FDCManifest& Manifest);
	void OnSlotFallback(ADCSlot* Slot, const FString& Reason);

	void PumpShots();
	void TakeQueuedShot();
	void AfterShot();

	void PointCameraAt(const ADCSlot& Slot);
	ADCSlot* FindSlot(const FString& SlotId) const;

	void Finish();
	void WriteResultFile();
	void CheckQuitFile();

	TArray<FShotRequest> ShotQueue;
	bool bShotInFlight = false;
	int32 ShotCount = 0;
	FString PendingShotSlot;
	FString PendingShotFile;
	int32 PendingShotSeq = 0;

	FString ShotDir;
	FString QuitFilePath;
	bool bAutoShot = false;
	float RunSeconds = 0.0f;

	TWeakObjectPtr<ACameraActor> Camera;
	FTimerHandle ShotTimer;
	FTimerHandle RunTimer;
	FTimerHandle QuitFileTimer;
	double StartSeconds = 0.0;
	bool bFinished = false;
};
