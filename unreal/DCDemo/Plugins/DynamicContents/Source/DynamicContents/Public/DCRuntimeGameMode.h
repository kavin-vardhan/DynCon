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
//   -DCNoFlip                          ignore the portal's live flip  (UDCSubsystem)
//   -DCStatusFile=<path>               JSON a test script can watch   (UDCSubsystem)
//   -DCShotDir=<dir>                   photograph every change here
//   -DCAutoShot                        photograph even without a shot dir
//   -DCTour[=<seconds>]                the scripted tour: an overview shot, a framed shot of
//                                      every slot, then walk to each one and in through its
//                                      door, with a shot from inside. Writes dc_tour.json
//                                      with the walk results and the frame times.
//   -DCTourFor=<seconds>               keep touring for at least that long, starting the
//                                      round again when it ends: how the ten-minute frame
//                                      time run of plan v6 §11 is driven. Only the first
//                                      round photographs anything.
//   -DCTourLightB=0                    the tour leaves the wall lamps off (brief 018's
//                                      before/after crops of the lighting budget).
//   -DCPreview                         this copy is the REGION PREVIEW WINDOW (plan v6 §7):
//                                      no input, no audio, no telemetry, no status strip and
//                                      no waypoint marker; a 30 fps cap and the lowest
//                                      scalability; below-normal process priority; a
//                                      borderless window on the portal's monitor that starts
//                                      out of sight; and a camera that auto-pilots itself to
//                                      whatever slot GET /preview/region says the visitor has
//                                      just been bidding on, framing it from the front at eye
//                                      level with a slow drift.
//   -DCPreviewShown                    start it on screen instead of parked off-screen (the
//                                      soak test wants it visible from the first frame).
//   -DCPreviewRect=x,y,w,h             where the window goes, instead of the computed
//   -DCPreviewMonitor=<n>              right half of the portal's monitor.
//   -DCPreviewFile=<path>              the JSON the pad helper reads to find it again.
//   -DCPreviewTitle=<text>             the window title the helper matches on.
//   -DCPreviewFps=<n>                  the frame cap (default 30) and the drift, in degrees
//   -DCPreviewDrift=<deg>              either side of the front (default 11; 0 = still).
//   -DCStateTest[=<rounds>]            the state-across-a-swap exit test (plan v6 §14 step 6):
//                                      walk in, open the door, turn light B on, set the screen
//                                      to image 3, wait for the replacement the backend is
//                                      about to send, watch SWAP PENDING hold it, walk out,
//                                      walk back in and check. Ten rounds by default. Writes
//                                      dc_state_test.json, and -DCStateFile live as it goes.
//   -DCStateSlot=A1  -DCStateBase=content1  which slot and which piece the test uses
//   -DCStateFile=<path>                the handshake file the driving script watches
//   -DCWarmup=<seconds>                how long either scripted run waits for the backend to
//                                      fill the slots before it starts
//   -DCPawn=<class path>               override the Player pawn / controller classes
//   -DCController=<class path>
//   -DCRunSeconds=<n>                  quit after n seconds (0 = never)
//   -DCQuitWhenFileExists=<path>       quit as soon as that file turns up: how a test (or
//                                      the booth's start script) stops the game cleanly
//                                      without killing the process
//   -DCUiScale=<f>  -DCNoStrip         the status strip                (ADCStatusHud)

#pragma once

#include "CoreMinimal.h"
#include "DCContentActor.h"
#include "DCPreview.h"
#include "DCStateStore.h"
#include "GameFramework/GameModeBase.h"
#include "UObject/SoftObjectPath.h"

#include "DCRuntimeGameMode.generated.h"

class ACameraActor;
class ADCSlot;
class UDCInteractor;
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
	FString TourShot(const FString& Label);
	void SetViewToPawn();
	void SetSpringArm(float Length, float Right = 0.0f, float Up = 0.0f);

	// ---------------------------------------------------------------- the state exit test
	//
	// Plan v6 §14 step 6: "step 9 works ten times out of ten, including when the block ends
	// while the Player is inside." One round is the whole of step 9 - walk in, use the door,
	// the switches and the screen, let the backend send a replacement while the Player is
	// standing inside, watch SWAP PENDING hold it, walk out, and check what comes back.
	//
	// The game does not know which kind of round it is in, and that is deliberate: the script
	// driving it pushes an update or ends the block, and the game works out what to expect
	// from what actually arrived - the same content (any version) must come back wearing what
	// the Player left, a different piece must not.

	enum class EStateStep : uint8
	{
		WaitForContent,
		WalkToDoor,
		CloseDoorIfOpen,
		OpenDoor,
		WalkInside,
		SetLights,
		WalkToScreen,
		SetScreen,
		ShotSet,
		Arm,
		WaitPending,
		WalkToInside2,
		ShotPending,
		WalkClear,
		WaitSwapped,
		ShotSwapped,
		WalkBackToDoor,
		WalkBackInside,
		ShotBack,
		WalkClearAgain,
		RoundDone,
		Done
	};

	struct FStateRound
	{
		int32 N = 0;
		FString BeforePiece;
		FString BeforeVersion;
		FString BeforeAllocKey;
		FString AfterPiece;
		FString AfterVersion;
		FString AfterAllocKey;
		FString Kind;                 // "same content" | "different content"
		FDCContentState Left;         // what the Player left
		FDCContentState Expected;
		FDCContentState Found;
		bool bSetOk = false;
		bool bPendingSeen = false;
		bool bSwapped = false;
		bool bStateOk = false;
		bool bRestoredOnReturn = false;
		bool bOk = false;
		float PendingSeconds = 0.0f;
		float SwapSeconds = 0.0f;
		int32 Interactions = 0;
		FString Note;
		TArray<FString> Shots;
	};

	void TickStateTest(float DeltaSeconds);
	void StateStepTo(EStateStep Next);
	bool StateWalk(const FVector& To, const FString& Leg);
	bool StateWalkPath(const TArray<FVector>& Through, const FString& Leg);
	void StateFail(const FString& Why);
	void StateNextRound();
	ADCSlot* StateSlot() const;
	ADCContentActor* StateContent() const;
	UDCInteractor* StateInteractor() const;
	void WriteStateFile(const TCHAR* Phase);
	void WriteStateResultFile();
	void FaceTowards(const FVector& Where);

	// ---------------------------------------------------------------- the preview window
	//
	// Plan v6 §7: "the same game, for a player in India". This copy has no Player and no
	// input; it is a camera that stands in front of whatever slot the visitor has just been
	// bidding on and drifts slowly, so a visitor glancing at the right-hand monitor sees
	// the same spot in another region at the same moment.

	/** The cheap settings, the window, and the camera. Called from BeginPlay. */
	void StartPreview();

	/** Borderless, placed, named and parked. Runs a couple of seconds in, once the engine
	 *  has finished deciding things about its own window. */
	void PlacePreviewWindow();

	void TickPreview(float DeltaSeconds);

	/** The slot this copy should be framing: the server's focus if this map has it. */
	ADCSlot* PreviewFocusSlot() const;

	/** Where to stand to see `Slot` from the front at eye level, `Drift` degrees round. */
	void FramePreviewOn(const ADCSlot& Slot, float Drift, FVector& OutEye,
		FRotator& OutLook) const;

	/** Where to put a camera that is drifting over the whole map, `Drift` degrees round. */
	void FrameOverview(float Drift, FVector& OutEye, FRotator& OutLook) const;

	/**
	 * The auto-pilot, which the region preview window and the attract camera share.
	 *
	 * Brief 017 built it for the preview: stand in front of a slot at eye level, drift a few
	 * degrees either side of the front, cut rather than fly when the slot changes and the
	 * two are far apart. The attract loop of plan v6 §4 step 0 is the same camera with a
	 * different idea of which slot to look at and an overview leg between laps, so it is the
	 * same function with the slot passed in instead of asked for.
	 */
	void TickAutoPilot(float DeltaSeconds, const ADCSlot* Focus, bool bOverview);

	// ---------------------------------------------------------------- the shell (brief 018)

	/** Puts the Player in, or takes them out, to match what the shell says the booth is doing. */
	void MatchShellMode();

	/** The three things the shell's scripted run asks the game mode to do. */
	bool UiShot(const FString& Label);
	bool UiWalkTo(const FString& Target);
	bool UiUse(int32 Kind);

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

	/** -DCTourFor: keep going round until the run is this old. 0 = one round. */
	float TourForSeconds = 0.0f;
	int32 TourRound = 0;

	/** -DCTourLightB=0: leave the wall lamps off, for the lighting budget's "before" crops. */
	bool bTourLightB = true;

	// preview state
	bool bPreview = false;
	bool bPreviewShown = false;
	bool bPreviewWindowPlaced = false;
	float PreviewFps = 30.0f;
	float PreviewDriftDegrees = 11.0f;
	FString PreviewFilePath;
	FString PreviewTitle;
	FDCPreviewRect PreviewHome;
	FString PreviewFocusId;
	double PreviewSeconds = 0.0;

	TArray<FVector> WalkTargets;
	int32 WalkTarget = -1;
	int32 WalkSlotIndex = 0;
	FString WalkLeg;
	double WalkStartSeconds = 0.0;
	float WalkMetres = 0.0f;
	float WalkStuckSeconds = 0.0f;
	FVector WalkLastPosition = FVector::ZeroVector;

	// state-test state
	bool bStateTest = false;
	int32 StateRounds = 10;
	FString StateSlotId = TEXT("A1");
	FString StateBasePiece = TEXT("content1");
	FString StateFilePath;
	EStateStep StateStep = EStateStep::WaitForContent;
	int32 StateRoundIndex = 0;
	double StateStepStarted = 0.0;
	double StateRoundStarted = 0.0;
	float StateWaitLeft = 0.0f;
	int32 StateSubStep = 0;

	/** Which half of a two-part step this is: drive to the baseline, then to the target. */
	int32 StatePhase = 0;
	int32 StateUsesAtRoundStart = 0;

	/** The Player has turned to look at the thing they are about to use. */
	bool bStateAimed = false;

	/** When the walk out of the bounds box began - what "applied after" is measured from. */
	double StateWalkOutStarted = 0.0;
	TArray<FStateRound> StateResults;
	FStateRound StateRound;

	// frame times, for the report
	TArray<float> FrameMs;
	bool bCollectFrames = false;

	// the shell
	bool bShell = false;
	bool bAttractCamera = false;
	float LastDeltaSeconds = 1.0f / 60.0f;
	FString UiWalkTarget;

	TWeakObjectPtr<UDCInteractor> Interactor;

	TWeakObjectPtr<ACameraActor> Camera;
	FTimerHandle ShotTimer;
	FTimerHandle RunTimer;
	FTimerHandle QuitFileTimer;
	double StartSeconds = 0.0;
	bool bFinished = false;
};
