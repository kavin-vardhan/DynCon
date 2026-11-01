// The game mode the demo maps run: it starts the DC client, puts the Player in, draws the
// status strip, and - when a test asks it to - photographs and walks the whole map.
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
//   -DCTour[=<seconds>]                the scripted tour: an overview shot, a framed shot of
//                                      every slot, then walk to each one and in through its
//                                      door, with a shot from inside. Writes dc_tour.json
//                                      with the walk results and the frame times.
//   -DCPawn=<class path>               override the Player pawn / controller classes
//   -DCController=<class path>
//   -DCRunSeconds=<n>                  quit after n seconds (0 = never)
//   -DCQuitWhenFileExists=<path>       quit as soon as that file turns up: how a test (or
//                                      the booth's start script) stops the game cleanly
//                                      without killing the process
//   -DCUiScale=<f>  -DCNoStrip         the status strip                (ADCStatusHud)

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "UObject/SoftObjectPath.h"

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

	/**
	 * The Player, by path rather than by class.
	 *
	 * The pawn is a Blueprint in the *game* module's content (it has the Enhanced Input
	 * actions on it), and this game mode lives in the plugin. Naming it by path is what lets
	 * the plugin stay independent of the game module - no link dependency, and a project that
	 * drops the plugin in gets a working default it can override on the command line.
	 */
	UPROPERTY(EditDefaultsOnly, Category = "DC|Player")
	FSoftClassPath PlayerPawnClassPath;

	UPROPERTY(EditDefaultsOnly, Category = "DC|Player")
	FSoftClassPath PlayerControllerClassPath;

	virtual void InitGame(const FString& MapName, const FString& Options, FString& ErrorMessage) override;
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void Tick(float DeltaSeconds) override;

private:
	/** One queued "something changed, photograph it" request. */
	struct FShotRequest
	{
		FString SlotId;
		FString Label;

		/** Which activation this picture is of, so it is filed against the right one. */
		int32 ActivationSeq = 0;
	};

	// ---------------------------------------------------------------- the scripted tour

	/**
	 * The tour is a tiny list of actions run by Tick, rather than a nest of timers: a camera
	 * move, a wait, a shutter, a walk. It is easy to read in the log and easy to extend.
	 */
	enum class ETourKind : uint8
	{
		Wait,
		OverviewCamera,
		SlotCamera,
		Shot,
		ViewPawn,
		WalkToDoor,
		OpenDoor,
		WalkInside,
		StepBackOut,
		End,
	};

	struct FTourAction
	{
		ETourKind Kind = ETourKind::Wait;
		float Seconds = 0.0f;
		int32 SlotIndex = 0;
		FString Label;
	};

	struct FTourWalk
	{
		FString SlotId;
		FString Leg;
		bool bArrived = false;
		float Seconds = 0.0f;
		float MetresWalked = 0.0f;
		float FinalGapCm = 0.0f;
		FString Note;
	};

	void OnSlotActive(ADCSlot* Slot, const FDCManifest& Manifest);
	void OnSlotFallback(ADCSlot* Slot, const FString& Reason);

	void PumpShots();
	void TakeQueuedShot();
	void AfterShot();

	void PointCameraAt(const ADCSlot& Slot);
	void PointCameraOverview();
	ADCSlot* FindSlot(const FString& SlotId) const;
	ADCSlot* SlotByIndex(int32 Index) const;

	void BuildTour();
	void TickTour(float DeltaSeconds);
	void NextTourAction();
	void StartWalk(int32 SlotIndex, const TArray<FVector>& Targets, const FString& Leg);
	bool TickWalk(float DeltaSeconds);
	void FinishWalk(bool bArrived, const FString& Note);
	void TourShot(const FString& Label);
	void SetViewToPawn();
	void SetSpringArm(float Length);

	void Finish();
	void WriteResultFile();
	void WriteTourFile();
	void CheckQuitFile();

	TArray<FShotRequest> ShotQueue;
	bool bShotInFlight = false;
	int32 ShotCount = 0;
	FString PendingShotSlot;
	FString PendingShotFile;
	int32 PendingShotSeq = 0;
	double LastShotSeconds = 0.0;

	FString ShotDir;
	FString QuitFilePath;
	bool bAutoShot = false;
	float RunSeconds = 0.0f;

	// tour state
	bool bTour = false;
	float TourWarmupSeconds = 14.0f;
	TArray<FTourAction> Tour;
	int32 TourIndex = -1;
	float TourWaitLeft = 0.0f;
	bool bTourBuilt = false;
	TArray<FTourWalk> Walks;

	TArray<FVector> WalkTargets;
	int32 WalkTarget = -1;
	int32 WalkSlotIndex = 0;
	FString WalkLeg;
	double WalkStartSeconds = 0.0;
	float WalkMetres = 0.0f;
	float WalkStuckSeconds = 0.0f;
	FVector WalkLastPosition = FVector::ZeroVector;

	// frame times, for the report
	TArray<float> FrameMs;
	bool bCollectFrames = false;

	TWeakObjectPtr<ACameraActor> Camera;
	FTimerHandle ShotTimer;
	FTimerHandle RunTimer;
	FTimerHandle QuitFileTimer;
	double StartSeconds = 0.0;
	bool bFinished = false;
};
