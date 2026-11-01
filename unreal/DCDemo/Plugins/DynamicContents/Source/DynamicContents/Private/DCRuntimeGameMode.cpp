#include "DCRuntimeGameMode.h"

#include "DCContentActor.h"
#include "DCInteractor.h"
#include "DCPreview.h"
#include "DCSlot.h"
#include "DCStateStore.h"
#include "DCStatusHud.h"
#include "DCSubsystem.h"
#include "DynamicContents.h"

#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/DefaultPawn.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/SpringArmComponent.h"
#include "HAL/FileManager.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Scalability.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "TimerManager.h"
#include "UnrealClient.h"

#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <Windows.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

namespace
{
	/**
	 * Seconds between pointing the camera and pressing the shutter. Lumen and the virtual
	 * shadow maps need a handful of frames to settle after a dozen new shadow-casting lights
	 * appear, and a picture taken too early is a dark, noisy one rather than a missing one -
	 * which is the sort of failure that gets believed (brief 006 learnt this the hard way).
	 */
	constexpr float DCSettleSeconds = 1.6f;
	constexpr float DCAfterShotSeconds = 0.6f;

	constexpr float DCOutsideFov = 75.0f;
	constexpr float DCThreeQuarterYaw = 32.0f;

	/** Walking. The Player pawn walks at 500 cm/s, so these are generous. */
	constexpr float DCWalkAccept = 130.0f;        // cm, a waypoint counts as reached
	constexpr float DCWalkAcceptFinal = 110.0f;
	constexpr float DCWalkTimeout = 75.0f;        // s per leg
	constexpr float DCWalkStuckSeconds = 4.0f;
	constexpr float DCWalkStuckMove = 30.0f;      // cm of progress that resets the stuck timer

	/** The spring arm pulls right in while the Player is inside a piece of content. */
	constexpr float DCArmOutside = 400.0f;
	constexpr float DCArmInside = 130.0f;

	/** …and swings over the shoulder for a picture of what the Player is looking at. */
	constexpr float DCArmShot = 300.0f;
	constexpr float DCShotRight = 125.0f;
	constexpr float DCShotUp = 40.0f;

	/** Frames within this of a shutter are thrown out of the frame-time figures. */
	constexpr double DCShotBlackout = 0.5;

	// ---- the state exit test ------------------------------------------------------------

	/** A whole round, from "content1 is up" to "checked". Generous: a pack takes ~4 s twice. */
	constexpr float DCStateRoundTimeout = 240.0f;

	/** Any single waiting step. */
	constexpr float DCStateStepTimeout = 100.0f;

	/** Between two presses of the same button, so each one is a separate press. */
	constexpr float DCStatePressGap = 0.35f;

	/** Give up on a button that is not doing what it should. */
	constexpr int32 DCStateMaxPresses = 12;

	/** A 90 degree swing takes about half a second; ten is a hang, not a slow door. */
	constexpr float DCStateDoorTimeout = 10.0f;

	/**
	 * How far outside the slot's bounds box the Player walks to let a held swap apply.
	 *
	 * It has to clear the **box**, not the building: SWAP PENDING is held while the Player is
	 * inside the class-limit volume, which for an L slot is 7 m from the middle in every
	 * direction - and the door itself is only about 4.9 m out, so standing at the door is
	 * standing inside the box.
	 */
	constexpr float DCStateClearExtra = 450.0f;

	/**
	 * Where the Player stands to use a door: on the slot's centre line, this far clear of the
	 * front of the piece. Two metres is a step back from a doorway - close enough that the
	 * prompt is obviously about this door, far enough that an inward-swinging leaf has nobody
	 * in the way of it.
	 */
	constexpr float DCStateFrontClearance = 200.0f;

	/** Further than this from the slot and the walk uses the map's approach path. */
	constexpr float DCStateFarAway = 2800.0f;

	// ---- the region preview window ------------------------------------------------------

	/** Eye level. The same 1.7 m the slot-map tool's thumbnails are taken from. */
	constexpr float DCPreviewEyeCm = 170.0f;

	/** A narrower frame than the tour's: a 960 x 540 window wants the piece bigger in it. */
	constexpr float DCPreviewFov = 65.0f;

	/** One lap of the drift. Slow enough to read as a held shot rather than a pan. */
	constexpr float DCPreviewDriftSeconds = 46.0f;

	/** How long the camera takes to catch up with the drift (seconds to close 63 % of it). */
	constexpr float DCPreviewSmoothing = 0.55f;

	/** Further than this and a change of slot is a cut, not a fly-through of the map. */
	constexpr float DCPreviewCutDistance = 6000.0f;

	/** Seconds after BeginPlay before the window is restyled - see PlacePreviewWindow. */
	constexpr float DCPreviewPlaceDelay = 2.0f;

	FString TwoDigits(int32 N)
	{
		return FString::Printf(TEXT("%02d"), N);
	}

	void DCSetCvar(const TCHAR* Name, const TCHAR* Value)
	{
		IConsoleVariable* Var = IConsoleManager::Get().FindConsoleVariable(Name);
		if (Var == nullptr)
		{
			DC_LOG(Warning, TEXT("CVAR  '%s' does not exist in this build"), Name);
			return;
		}
		const FString Before = Var->GetString();
		Var->Set(Value, ECVF_SetByCommandline);
		DC_LOG(Log, TEXT("CVAR  %s: %s -> %s"), Name, *Before, *Var->GetString());
	}

	FString BoolWord(bool b)
	{
		return b ? TEXT("yes") : TEXT("no");
	}
}

ADCRuntimeGameMode::ADCRuntimeGameMode()
{
	PrimaryActorTick.bCanEverTick = true;

	// A Blueprint in the game module's content: it carries the Enhanced Input actions and the
	// mannequin. Named by path so the plugin keeps no link dependency on the game module.
	PlayerPawnClassPath = FSoftClassPath(TEXT("/Game/Player/BP_DCPlayer.BP_DCPlayer_C"));
	PlayerControllerClassPath =
		FSoftClassPath(TEXT("/Game/Player/BP_DCPlayerController.BP_DCPlayerController_C"));

	// Fallbacks if those are not in the build: a flying DefaultPawn still proves the client.
	DefaultPawnClass = ADefaultPawn::StaticClass();
	HUDClass = ADCStatusHud::StaticClass();
}

void ADCRuntimeGameMode::InitGame(const FString& MapName, const FString& Options,
	FString& ErrorMessage)
{
	Super::InitGame(MapName, Options, ErrorMessage);

	const TCHAR* Cmd = FCommandLine::Get();
	bPreview = FParse::Param(Cmd, TEXT("DCPreview"));
	if (bPreview)
	{
		// No Player at all in the preview window: a bare APawn spawns, has no mesh and does
		// nothing, which is what "no input, and nobody standing in the shot" looks like.
		// It must not be the game module's mannequin Blueprint - that would put a character
		// at the spawn point of a window that is meant to show a place, and it would be
		// carrying the interaction component.
		DefaultPawnClass = APawn::StaticClass();
		HUDClass = ADCStatusHud::StaticClass();
		DC_LOG(Log, TEXT("PREVIEW this copy is the region preview window: no Player pawn"));
		return;
	}

	FString Override;
	if (FParse::Value(Cmd, TEXT("DCPawn="), Override, false) && !Override.IsEmpty())
	{
		PlayerPawnClassPath = FSoftClassPath(Override.TrimQuotes());
	}
	if (FParse::Value(Cmd, TEXT("DCController="), Override, false) && !Override.IsEmpty())
	{
		PlayerControllerClassPath = FSoftClassPath(Override.TrimQuotes());
	}

	if (UClass* Pawn = PlayerPawnClassPath.TryLoadClass<APawn>())
	{
		DefaultPawnClass = Pawn;
		DC_LOG(Log, TEXT("PLAYER pawn %s"), *Pawn->GetPathName());
	}
	else
	{
		DC_LOG(Warning, TEXT("PLAYER %s would not load - falling back to a DefaultPawn"),
			*PlayerPawnClassPath.ToString());
	}
	if (UClass* PC = PlayerControllerClassPath.TryLoadClass<APlayerController>())
	{
		PlayerControllerClass = PC;
		DC_LOG(Log, TEXT("PLAYER controller %s"), *PC->GetPathName());
	}
	else
	{
		DC_LOG(Warning, TEXT("PLAYER %s would not load - keeping the default controller"),
			*PlayerControllerClassPath.ToString());
	}
}

void ADCRuntimeGameMode::BeginPlay()
{
	Super::BeginPlay();

	StartSeconds = FPlatformTime::Seconds();
	const TCHAR* Cmd = FCommandLine::Get();

	DC_LOG(Log, TEXT("================ DC runtime client ================"));
	DC_LOG(Log, TEXT("build=%s  exe=%s"), UDCSubsystem::GetBuildConfigName(),
		FPlatformProcess::ExecutablePath());
	DC_LOG(Log, TEXT("cmdline=%s"), Cmd);
	DC_LOG(Log, TEXT("map=%s"), *GetWorld()->GetMapName());
	DC_LOG(Log, TEXT("file log=%s"), *FDCFileLog::Get().GetPath());

	FString Value;
	if (FParse::Value(Cmd, TEXT("DCShotDir="), Value, false) && !Value.IsEmpty())
	{
		ShotDir = FPaths::ConvertRelativePathToFull(Value.TrimQuotes());
		IFileManager::Get().MakeDirectory(*ShotDir, true);
		bAutoShot = true;
	}
	if (FParse::Param(Cmd, TEXT("DCAutoShot")))
	{
		bAutoShot = true;
	}
	bTour = FParse::Param(Cmd, TEXT("DCTour"));
	float Warmup = 0.0f;
	if (FParse::Value(Cmd, TEXT("DCTour="), Warmup) && Warmup > 0.0f)
	{
		bTour = true;
		TourWarmupSeconds = Warmup;
	}
	if (FParse::Value(Cmd, TEXT("DCTourFor="), TourForSeconds) && TourForSeconds > 0.0f)
	{
		bTour = true;
	}
	// Both scripted runs wait this long before they start, so the backend has filled every
	// slot and the first picture is of a map that is already doing its job.
	if (FParse::Value(Cmd, TEXT("DCWarmup="), Warmup) && Warmup > 0.0f)
	{
		TourWarmupSeconds = Warmup;
	}

	bStateTest = FParse::Param(Cmd, TEXT("DCStateTest"));
	int32 Rounds = 0;
	if (FParse::Value(Cmd, TEXT("DCStateTest="), Rounds) && Rounds > 0)
	{
		bStateTest = true;
		StateRounds = Rounds;
	}
	if (FParse::Value(Cmd, TEXT("DCStateSlot="), Value, false) && !Value.IsEmpty())
	{
		StateSlotId = Value.TrimQuotes();
	}
	if (FParse::Value(Cmd, TEXT("DCStateBase="), Value, false) && !Value.IsEmpty())
	{
		StateBasePiece = Value.TrimQuotes();
	}
	if (FParse::Value(Cmd, TEXT("DCStateFile="), Value, false) && !Value.IsEmpty())
	{
		StateFilePath = FPaths::ConvertRelativePathToFull(Value.TrimQuotes());
		IFileManager::Get().MakeDirectory(*FPaths::GetPath(StateFilePath), true);
		IFileManager::Get().Delete(*StateFilePath, false, true, true);
	}

	if ((bAutoShot || bTour || bStateTest) && ShotDir.IsEmpty())
	{
		ShotDir = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("DCShots"));
		IFileManager::Get().MakeDirectory(*ShotDir, true);
	}
	// The tour and the state test drive their own camera and their own Player: a shot per
	// arriving piece would fight them for the view.
	if (bTour || bStateTest)
	{
		bAutoShot = false;
	}
	// So does the preview window, and it has no Player to drive at all. Its evidence is a
	// capture of the desktop, which is the only thing that can show it really is a window
	// on the portal's monitor.
	if (bPreview && (bTour || bStateTest || bAutoShot))
	{
		DC_LOG(Log, TEXT("PREVIEW ignoring the tour / state test / auto-shot: this copy is "
			"the preview window"));
		bTour = bStateTest = bAutoShot = false;
	}
	FParse::Value(Cmd, TEXT("DCRunSeconds="), RunSeconds);
	if (FParse::Value(Cmd, TEXT("DCQuitWhenFileExists="), Value, false) && !Value.IsEmpty())
	{
		QuitFilePath = FPaths::ConvertRelativePathToFull(Value.TrimQuotes());
		// Any file left over from a previous run would stop this one before it started.
		IFileManager::Get().Delete(*QuitFilePath, false, true, true);
	}

	// Plan v6 §11, "insurance anyway": never throttle and never mute when this window is
	// not the foreground one. Both copies run all day with the focus on whichever of them
	// the staff last touched, and the engine's own default is to silence the unfocused one
	// (BaseEngine.ini sets UnfocusedVolumeMultiplier=0).
	DCSetCvar(TEXT("t.IdleWhenNotForeground"), TEXT("0"));
	FApp::SetUnfocusedVolumeMultiplier(1.0f);

	UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (Subsystem == nullptr)
	{
		DC_LOG(Error, TEXT("no UDCSubsystem on this game instance - nothing will arrive"));
		return;
	}

	Subsystem->OnSlotActive.AddUObject(this, &ADCRuntimeGameMode::OnSlotActive);
	Subsystem->OnSlotFallback.AddUObject(this, &ADCRuntimeGameMode::OnSlotFallback);
	Subsystem->Start();

	if (bPreview)
	{
		StartPreview();
	}

	DC_LOG(Log, TEXT("slots in map: %d   auto-shot=%s tour=%s state-test=%s dir=%s   "
		"run_seconds=%.0f"),
		Subsystem->GetSlots().Num(), bAutoShot ? TEXT("yes") : TEXT("no"),
		bTour ? TEXT("yes") : TEXT("no"),
		bStateTest ? *FString::Printf(TEXT("%d round(s) on %s/%s"), StateRounds, *StateSlotId,
			*StateBasePiece) : TEXT("no"),
		ShotDir.IsEmpty() ? TEXT("(none)") : *ShotDir, RunSeconds);

	if (bStateTest)
	{
		// The Player is the camera for the whole of this test: everything it photographs is
		// what somebody standing there would see.
		if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
		{
			PC->SetIgnoreLookInput(true);
			PC->SetIgnoreMoveInput(false);
		}
		StateStepStarted = StartSeconds;
		StateRoundStarted = StartSeconds;
		WriteStateFile(TEXT("warming up"));
	}

	if (bAutoShot || bTour)
	{
		// One camera actor, moved from shot to shot, so every picture is framed the same way.
		if (UWorld* World = GetWorld())
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			ACameraActor* Cam = World->SpawnActor<ACameraActor>(ACameraActor::StaticClass(),
				FTransform::Identity, Params);
			Camera = Cam;
			if (Cam && Cam->GetCameraComponent())
			{
				Cam->GetCameraComponent()->SetFieldOfView(DCOutsideFov);
			}
			if (APlayerController* PC = World->GetFirstPlayerController())
			{
				if (Cam)
				{
					PC->SetViewTargetWithBlend(Cam, 0.0f);
				}
				// Nothing the human does moves anything during an automated run - but the
				// tour needs move input, because that is how it drives the pawn.
				PC->SetIgnoreLookInput(true);
				PC->SetIgnoreMoveInput(!bTour);
			}
		}
	}

	if (RunSeconds > 0.0f)
	{
		GetWorldTimerManager().SetTimer(RunTimer, this, &ADCRuntimeGameMode::Finish,
			RunSeconds, false);
	}
	if (!QuitFilePath.IsEmpty())
	{
		DC_LOG(Log, TEXT("will quit when %s appears"), *QuitFilePath);
		GetWorldTimerManager().SetTimer(QuitFileTimer, this, &ADCRuntimeGameMode::CheckQuitFile,
			0.5f, true);
	}
}

void ADCRuntimeGameMode::CheckQuitFile()
{
	if (!bFinished && !QuitFilePath.IsEmpty() && IFileManager::Get().FileExists(*QuitFilePath))
	{
		DC_LOG(Log, TEXT("%s appeared - stopping"), *QuitFilePath);
		// Let any screenshot still in flight land before the run ends.
		if (bShotInFlight || ShotQueue.Num() > 0)
		{
			return;
		}
		Finish();
	}
}

void ADCRuntimeGameMode::EndPlay(const EEndPlayReason::Type Reason)
{
	if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		Subsystem->OnSlotActive.RemoveAll(this);
		Subsystem->OnSlotFallback.RemoveAll(this);
	}
	Super::EndPlay(Reason);
}

// ===================================================================== slots and shots

ADCSlot* ADCRuntimeGameMode::FindSlot(const FString& SlotId) const
{
	if (const UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		for (ADCSlot* Slot : Subsystem->GetSlots())
		{
			if (Slot->SlotId.ToString() == SlotId)
			{
				return Slot;
			}
		}
	}
	return nullptr;
}

ADCSlot* ADCRuntimeGameMode::SlotByIndex(int32 Index) const
{
	if (const UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		const TArray<ADCSlot*> Slots = Subsystem->GetSlots();
		if (Slots.IsValidIndex(Index))
		{
			return Slots[Index];
		}
	}
	return nullptr;
}

void ADCRuntimeGameMode::OnSlotActive(ADCSlot* Slot, const FDCManifest& Manifest)
{
	if (Slot == nullptr || !bAutoShot)
	{
		return;
	}
	FShotRequest Request;
	Request.SlotId = Slot->SlotId.ToString();
	Request.Label = FString::Printf(TEXT("%s_%s"), *Manifest.Piece, *Manifest.Version);
	if (const UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		Request.ActivationSeq = Subsystem->GetLastActivationSeq();
	}
	ShotQueue.Add(Request);
	PumpShots();
}

void ADCRuntimeGameMode::OnSlotFallback(ADCSlot* Slot, const FString& Reason)
{
	// Nothing to photograph: a fallback is, by definition, the picture not changing.
	if (Slot != nullptr)
	{
		DC_LOG(Log, TEXT("RUN  slot %s stayed on %s (%s)"), *Slot->SlotId.ToString(),
			*Slot->DescribeShowing(), *Reason);
	}
}

void ADCRuntimeGameMode::PumpShots()
{
	if (bShotInFlight || ShotQueue.Num() == 0 || bFinished)
	{
		return;
	}
	const FShotRequest Request = ShotQueue[0];
	ShotQueue.RemoveAt(0);

	ADCSlot* Slot = FindSlot(Request.SlotId);
	if (Slot == nullptr)
	{
		PumpShots();
		return;
	}

	bShotInFlight = true;
	PointCameraAt(*Slot);

	++ShotCount;
	PendingShotSlot = Request.SlotId;
	PendingShotSeq = Request.ActivationSeq;
	PendingShotFile = FString::Printf(TEXT("%02d_%s_%s.png"), ShotCount, *Request.SlotId,
		*Request.Label);

	GetWorldTimerManager().SetTimer(ShotTimer, this, &ADCRuntimeGameMode::TakeQueuedShot,
		DCSettleSeconds, false);
}

void ADCRuntimeGameMode::TakeQueuedShot()
{
	const FString Path = ShotDir / PendingShotFile;

	// bShowUI = false: the status strip is drawn on the HUD canvas, which is part of the
	// viewport's own render target, so it is in the picture either way - and the Slate path
	// needs a focused window, which a booth PC cannot be relied on to have.
	FScreenshotRequest::RequestScreenshot(Path, false, false);
	LastShotSeconds = FPlatformTime::Seconds();
	DC_LOG(Log, TEXT("SHOT  %s   (slot %s, activation #%d)"), *Path, *PendingShotSlot,
		PendingShotSeq);

	if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		Subsystem->NoteShot(PendingShotSeq, PendingShotFile);
	}

	GetWorldTimerManager().SetTimer(ShotTimer, this, &ADCRuntimeGameMode::AfterShot,
		DCAfterShotSeconds, false);
}

void ADCRuntimeGameMode::AfterShot()
{
	bShotInFlight = false;
	PumpShots();
}

void ADCRuntimeGameMode::PointCameraAt(const ADCSlot& Slot)
{
	ACameraActor* Cam = Camera.Get();
	if (Cam == nullptr)
	{
		return;
	}

	// Frame what is actually there, not what the slot's class allows: a small piece in a
	// large slot would otherwise sit in the middle of an empty picture.
	FVector Centre = Slot.GetActorLocation();
	float Height = Slot.ViewHeight;
	float Reach = Slot.ViewDistance;

	if (const ADCContentActor* Built = Cast<ADCContentActor>(Slot.GetContentActor()))
	{
		const FBox Bounds = Built->GetBuiltBounds();
		if (Bounds.IsValid)
		{
			Centre = Bounds.GetCenter();
			const FVector Extent = Bounds.GetExtent();
			Height = Bounds.Max.Z * 0.62f;
			// Stand off far enough that the piece fits inside a 75 degree frame and close
			// enough that it fills most of it. The frame is 16:9, so height is the binding
			// constraint on anything taller than it is wide (the T class especially).
			Reach = FMath::Max(Extent.Size2D() * 1.7f, Bounds.GetSize().Z * 1.5f) + 200.0f;
		}
	}

	const FVector Forward = Slot.GetActorForwardVector().RotateAngleAxis(DCThreeQuarterYaw,
		FVector::UpVector);
	const FVector Eye = FVector(Centre.X, Centre.Y, Slot.GetActorLocation().Z) + Forward * Reach
		+ FVector(0.0f, 0.0f, Height + 220.0f);
	const FVector Look = FVector(Centre.X, Centre.Y, Slot.GetActorLocation().Z + Height);

	Cam->SetActorLocation(Eye);
	Cam->SetActorRotation((Look - Eye).Rotation());
	if (Cam->GetCameraComponent())
	{
		Cam->GetCameraComponent()->SetFieldOfView(DCOutsideFov);
	}
	if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		PC->SetViewTargetWithBlend(Cam, 0.0f);
	}

	DC_LOG(Log, TEXT("VIEW  slot %s: camera at %s looking at %s (reach %.0f)"),
		*Slot.SlotId.ToString(), *Eye.ToCompactString(), *Look.ToCompactString(), Reach);
}

void ADCRuntimeGameMode::PointCameraOverview()
{
	ACameraActor* Cam = Camera.Get();
	if (Cam == nullptr)
	{
		return;
	}

	// Everything the map has, from above and to one side: the box round every slot decides
	// where to stand, so one line of code frames a 180 m plaza and a 90 m waterfront alike.
	FBox Box(ForceInit);
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (Subsystem != nullptr)
	{
		for (const ADCSlot* Slot : Subsystem->GetSlots())
		{
			Box += Slot->GetActorLocation();
		}
	}
	if (!Box.IsValid)
	{
		Box = FBox(FVector(-3000.0f, -3000.0f, 0.0f), FVector(3000.0f, 3000.0f, 0.0f));
	}
	Box = Box.ExpandBy(FVector(1500.0f, 1500.0f, 0.0f));

	const FVector Centre = Box.GetCenter();
	const float Reach = FMath::Max(Box.GetSize().Size2D() * 0.42f, 4500.0f);
	const FVector Eye = Centre + FVector(-Reach * 0.78f, -Reach * 0.52f, Reach * 0.40f);

	Cam->SetActorLocation(Eye);
	Cam->SetActorRotation((Centre - Eye).Rotation());
	if (Cam->GetCameraComponent())
	{
		Cam->GetCameraComponent()->SetFieldOfView(72.0f);
	}
	if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		PC->SetViewTargetWithBlend(Cam, 0.0f);
	}
	DC_LOG(Log, TEXT("VIEW  overview: camera at %s looking at %s"),
		*Eye.ToCompactString(), *Centre.ToCompactString());
}

// ================================================================ the preview window

void ADCRuntimeGameMode::StartPreview()
{
	const TCHAR* Cmd = FCommandLine::Get();

	bPreviewShown = FParse::Param(Cmd, TEXT("DCPreviewShown"));
	FParse::Value(Cmd, TEXT("DCPreviewFps="), PreviewFps);
	FParse::Value(Cmd, TEXT("DCPreviewDrift="), PreviewDriftDegrees);

	PreviewTitle = FDCPreviewWindow::DefaultTitle();
	FString Value;
	if (FParse::Value(Cmd, TEXT("DCPreviewTitle="), Value, false) && !Value.IsEmpty())
	{
		PreviewTitle = Value.TrimQuotes();
	}
	PreviewFilePath = FPaths::ProjectSavedDir() / TEXT("dc_preview_window.json");
	if (FParse::Value(Cmd, TEXT("DCPreviewFile="), Value, false) && !Value.IsEmpty())
	{
		PreviewFilePath = Value.TrimQuotes();
	}
	PreviewFilePath = FPaths::ConvertRelativePathToFull(PreviewFilePath);

	// ---- the budget (plan v6 §11) ------------------------------------------------------
	//
	// "30 fps cap, half resolution, lowest settings, below-normal process priority, its own
	// pack cache folder." The resolution is the window: 960 x 540 is half of 1080p on each
	// axis, a quarter of the pixels, and the window is exactly the size it renders because
	// it is borderless (DCPreview.h). The cache folder is -DCCacheDir, which the start
	// script passes. The rest is here, so that -DCPreview alone is enough.
	DCSetCvar(TEXT("t.MaxFPS"), *FString::Printf(TEXT("%.0f"), FMath::Max(PreviewFps, 1.0f)));
	DCSetCvar(TEXT("r.ScreenPercentage"), TEXT("100"));

	Scalability::FQualityLevels Levels;
	Levels.SetFromSingleQualityLevel(0);
	Scalability::SetQualityLevels(Levels);
	DC_LOG(Log, TEXT("PREVIEW scalability set to the lowest level"));

	// ...and this is why the preview needs `-UserDir=` (run_preview.ps1 passes it).
	//
	// The engine persists the scalability groups and the window resolution into
	// GameUserSettings.ini under the project's user directory - which, for two copies of
	// one packaged build, is the SAME file. Left alone, the preview's lowest-quality,
	// half-resolution settings become the main game's settings the next time it starts:
	// `sg.ResolutionQuality=50` and every group at 0, quietly, overnight, with nothing in
	// any log to say why the booth's screen looks soft. It is caught here rather than
	// trusted to a start script because the failure is invisible and a day late.
	const FString SavedDir = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir());
	if (!FParse::Param(Cmd, TEXT("UserDir")) &&
		!FCString::Strifind(Cmd, TEXT("-UserDir=")))
	{
		DC_LOG(Warning, TEXT("PREVIEW no -UserDir= : this copy shares %s with the main "
			"game, and the lowest-quality settings it has just applied will be saved into "
			"the GameUserSettings.ini the main game reads"), *SavedDir);
	}
	else
	{
		DC_LOG(Log, TEXT("PREVIEW its own saved dir: %s"), *SavedDir);
	}

	// Silent, whether or not -nosound was passed.
	FApp::SetVolumeMultiplier(0.0f);

#if PLATFORM_WINDOWS
	const BOOL bPriority = ::SetPriorityClass(::GetCurrentProcess(),
		BELOW_NORMAL_PRIORITY_CLASS);
	DC_LOG(Log, TEXT("PREVIEW process priority -> below normal: %s"),
		bPriority ? TEXT("ok") : TEXT("FAILED"));
#endif

	// ---- out of sight before anything is drawn ----------------------------------------
	FDCPreviewWindow::HideAtBoot();

	// ---- the camera -------------------------------------------------------------------
	if (UWorld* World = GetWorld())
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		ACameraActor* Cam = World->SpawnActor<ACameraActor>(ACameraActor::StaticClass(),
			FTransform::Identity, Params);
		Camera = Cam;
		if (Cam != nullptr && Cam->GetCameraComponent() != nullptr)
		{
			Cam->GetCameraComponent()->SetFieldOfView(DCPreviewFov);
		}
		if (APlayerController* PC = World->GetFirstPlayerController())
		{
			if (Cam != nullptr)
			{
				PC->SetViewTargetWithBlend(Cam, 0.0f);
			}
			// Nothing a human does reaches this copy. Pad 2 is the helper's and pad 1 is
			// the main game's; this window is furniture.
			PC->SetIgnoreMoveInput(true);
			PC->SetIgnoreLookInput(true);
		}
	}

	// The engine is still making up its mind about its own window for a frame or two after
	// BeginPlay (resolution, window mode), and a style change it then undoes leaves a
	// bordered window in the wrong place. Two seconds is long after all of that, and the
	// window is hidden for every one of them.
	FTimerHandle Handle;
	GetWorldTimerManager().SetTimer(Handle, this, &ADCRuntimeGameMode::PlacePreviewWindow,
		DCPreviewPlaceDelay, false);
}

void ADCRuntimeGameMode::PlacePreviewWindow()
{
	FString How;
	PreviewHome = FDCPreviewWindow::ComputeHomeRect(How);

	FString Error;
	if (!FDCPreviewWindow::Apply(PreviewHome, bPreviewShown, PreviewTitle, Error))
	{
		DC_LOG(Error, TEXT("PREVIEW could not place the window: %s"), *Error);
		return;
	}
	bPreviewWindowPlaced = true;

	FDCPreviewRect Now;
	const bool bHaveNow = FDCPreviewWindow::GetWindowRect(Now);
	DC_LOG(Log, TEXT("PREVIEW window '%s' borderless at %s (%s)%s, %s"),
		*PreviewTitle, *PreviewHome.Describe(), *How,
		bHaveNow ? *FString::Printf(TEXT("; now at %s"), *Now.Describe()) : TEXT(""),
		bPreviewShown ? TEXT("shown") : TEXT("parked off-screen until the portal asks"));

	if (FDCPreviewWindow::WriteStateFile(PreviewFilePath, PreviewTitle, PreviewHome,
		bPreviewShown))
	{
		DC_LOG(Log, TEXT("PREVIEW wrote %s - the pad helper reads this to find the window"),
			*PreviewFilePath);
	}
	else
	{
		DC_LOG(Warning, TEXT("PREVIEW could not write %s"), *PreviewFilePath);
	}
}

ADCSlot* ADCRuntimeGameMode::PreviewFocusSlot() const
{
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (Subsystem == nullptr)
	{
		return nullptr;
	}
	const TArray<ADCSlot*> Slots = Subsystem->GetSlots();
	if (Slots.Num() == 0)
	{
		return nullptr;
	}

	const FString WantGame = Subsystem->GetFocusGame();
	const FString WantSlot = Subsystem->GetFocusSlot();

	// The focus can name a slot in the *other* game - a visitor is free to bid on Game B
	// while Game A is the one on the booth's screens. This copy plays the map it was
	// started on, so it keeps framing the slot it has and the log says why; swapping map
	// would be a level load in a window that is meant to be a still of somewhere else.
	if (!WantSlot.IsEmpty() && (WantGame.IsEmpty() || WantGame == Subsystem->GetGame()))
	{
		for (ADCSlot* Slot : Slots)
		{
			if (Slot->SlotId.ToString() == WantSlot)
			{
				return Slot;
			}
		}
	}
	return Slots[0];                  // the map's first slot: always something to look at
}

void ADCRuntimeGameMode::FramePreviewOn(const ADCSlot& Slot, float Drift, FVector& OutEye,
	FRotator& OutLook) const
{
	// What is actually standing there, not what the class allows: a small piece in a large
	// slot would otherwise be a dot in the middle of an empty frame.
	FBox Bounds = Slot.GetContentBounds();
	if (!Bounds.IsValid)
	{
		const FVector Limits = Slot.GetClassLimits();
		Bounds = FBox(Slot.GetActorLocation() - FVector(Limits.X, Limits.Y, 0.0f) * 0.5f,
			Slot.GetActorLocation() + FVector(Limits.X * 0.5f, Limits.Y * 0.5f, Limits.Z));
	}
	const FVector Centre = Bounds.GetCenter();
	const FVector Extent = Bounds.GetExtent();
	const float GroundZ = Slot.GetActorLocation().Z;

	// Stand far enough back that the piece fits the frame, in the tighter of the two axes:
	// the window is 16:9, so a 20 m tall T piece is held by its height and a 14 m wide L
	// piece by its width.
	//
	// The height needs one correction. The camera is at eye level and the piece is aimed at
	// its own middle, so the camera is *below* what it is looking at and the top of the
	// building is further off the middle of the frame than half its height: without the
	// allowance for that drop, an L piece has its roof on the top edge of the window.
	const float HalfFovH = FMath::DegreesToRadians(DCPreviewFov * 0.5f);
	const float HalfFovV = FMath::Atan(FMath::Tan(HalfFovH) * 9.0f / 16.0f);
	const float AimZ = Centre.Z;
	const float HalfUp = FMath::Max(Bounds.Max.Z - AimZ, AimZ - Bounds.Min.Z)
		+ FMath::Abs(AimZ - (GroundZ + DCPreviewEyeCm)) * 0.5f;
	const float ReachW = FMath::Max(Extent.X, Extent.Y) / FMath::Tan(HalfFovH);
	const float ReachH = HalfUp / FMath::Max(FMath::Tan(HalfFovV), 0.01f);
	const float Reach = FMath::Max(ReachW, ReachH) * 1.15f + 250.0f;

	// The slot's +X is the door direction (ADCSlot::GetDoorApproachPoint), so "from the
	// front" is along it, and the drift swings a few degrees either side of that.
	const FVector Forward = Slot.GetActorForwardVector().RotateAngleAxis(Drift,
		FVector::UpVector);

	OutEye = FVector(Centre.X, Centre.Y, GroundZ) + Forward * Reach
		+ FVector(0.0f, 0.0f, DCPreviewEyeCm);
	// Aim at the middle of the piece's height, which from eye level is a slight look up -
	// the way somebody standing in front of a building looks at it.
	const FVector Look(Centre.X, Centre.Y, Centre.Z);
	OutLook = (Look - OutEye).Rotation();
}

void ADCRuntimeGameMode::TickPreview(float DeltaSeconds)
{
	ACameraActor* Cam = Camera.Get();
	if (Cam == nullptr)
	{
		return;
	}
	// The camera is driven from the first tick, whether or not the window has been placed
	// yet: the first frame the portal ever shows is then already framed.
	const ADCSlot* Slot = PreviewFocusSlot();
	if (Slot == nullptr)
	{
		return;
	}

	PreviewSeconds += DeltaSeconds;
	const float Phase = static_cast<float>(PreviewSeconds) * 2.0f * PI / DCPreviewDriftSeconds;
	const float Drift = PreviewDriftDegrees * FMath::Sin(Phase);

	FVector Eye;
	FRotator Look;
	FramePreviewOn(*Slot, Drift, Eye, Look);

	const FString Id = Slot->SlotId.ToString();
	const bool bNewSlot = Id != PreviewFocusId;
	if (bNewSlot)
	{
		DC_LOG(Log, TEXT("PREVIEW framing slot %s (%s): %s"), *Id,
			*Slot->GetSizeClassName(),
			*Slot->DescribeShowing());
		PreviewFocusId = Id;
	}

	// A change of slot is a cut when the two are far apart - flying across a plaza and
	// through a wall is not what "the same slot, another region" is meant to look like -
	// and a smooth catch-up otherwise, which is what carries the drift.
	const float Jump = FVector::Dist(Cam->GetActorLocation(), Eye);
	if (bNewSlot && Jump > DCPreviewCutDistance)
	{
		Cam->SetActorLocationAndRotation(Eye, Look);
		return;
	}
	const float Alpha = FMath::Clamp(DeltaSeconds / FMath::Max(DCPreviewSmoothing, 0.01f),
		0.0f, 1.0f);
	Cam->SetActorLocation(FMath::Lerp(Cam->GetActorLocation(), Eye, Alpha));
	Cam->SetActorRotation(FMath::RInterpTo(Cam->GetActorRotation(), Look, DeltaSeconds,
		1.0f / FMath::Max(DCPreviewSmoothing, 0.01f)));
}

// ===================================================================== the scripted tour

void ADCRuntimeGameMode::BuildTour()
{
	Tour.Reset();
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	const int32 SlotCount = Subsystem ? Subsystem->GetSlots().Num() : 0;

	auto Add = [this](ETourKind Kind, float Seconds, int32 Index, const FString& Label)
	{
		// Only the first round round photographs anything: a ten-minute -DCTourFor run is
		// seven laps, and seven sets of the same pictures is not seven times the evidence.
		if (Kind == ETourKind::Shot && TourRound > 0)
		{
			return;
		}
		FTourAction A;
		A.Kind = Kind;
		A.Seconds = Seconds;
		A.SlotIndex = Index;
		A.Label = Label;
		Tour.Add(A);
	};

	Add(ETourKind::OverviewCamera, 0.0f, 0, TEXT(""));
	Add(ETourKind::Wait, 2.2f, 0, TEXT(""));
	Add(ETourKind::Shot, 0.0f, 0, TEXT("overview"));

	for (int32 i = 0; i < SlotCount; ++i)
	{
		const ADCSlot* Slot = SlotByIndex(i);
		const FString Id = Slot ? Slot->SlotId.ToString() : FString::Printf(TEXT("slot%d"), i);
		Add(ETourKind::SlotCamera, 0.0f, i, TEXT(""));
		Add(ETourKind::Wait, DCSettleSeconds, i, TEXT(""));
		Add(ETourKind::Shot, 0.0f, i, Id + TEXT("_outside"));
		Add(ETourKind::ViewPawn, 0.0f, i, TEXT(""));
		Add(ETourKind::WalkToDoor, 0.0f, i, TEXT(""));
		Add(ETourKind::Wait, 0.6f, i, TEXT(""));
		Add(ETourKind::Shot, 0.0f, i, Id + TEXT("_door"));
		Add(ETourKind::OpenDoor, 0.0f, i, TEXT(""));
		Add(ETourKind::WalkInside, 0.0f, i, TEXT(""));
		Add(ETourKind::Wait, 1.4f, i, TEXT(""));
		Add(ETourKind::Shot, 0.0f, i, Id + TEXT("_inside"));
		Add(ETourKind::StepBackOut, 0.0f, i, TEXT(""));
	}
	Add(ETourKind::End, 0.0f, 0, TEXT(""));

	TourIndex = 0;
	bTourBuilt = true;
	DC_LOG(Log, TEXT("TOUR  round %d: %d action(s) over %d slot(s)"), TourRound + 1,
		Tour.Num(), SlotCount);
}

void ADCRuntimeGameMode::SetViewToPawn()
{
	if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		if (APawn* Pawn = PC->GetPawn())
		{
			PC->SetViewTargetWithBlend(Pawn, 0.35f);
		}
	}
}

void ADCRuntimeGameMode::SetSpringArm(float Length, float Right, float Up)
{
	if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		if (APawn* Pawn = PC->GetPawn())
		{
			if (USpringArmComponent* Arm = Pawn->FindComponentByClass<USpringArmComponent>())
			{
				Arm->TargetArmLength = Length;
				// Over the shoulder for a picture of something the Player is looking at: a
				// camera straight behind a character puts the character in front of the thing
				// being photographed, which for a 3 m screen is all of it.
				Arm->SocketOffset = FVector(0.0f, Right, Up);
			}
		}
	}
}

FString ADCRuntimeGameMode::TourShot(const FString& Label)
{
	++ShotCount;
	const FString Name = TwoDigits(ShotCount) + TEXT("_") + Label + TEXT(".png");
	const FString Path = ShotDir / Name;
	FScreenshotRequest::RequestScreenshot(Path, false, false);
	LastShotSeconds = FPlatformTime::Seconds();
	DC_LOG(Log, TEXT("SHOT  %s"), *Path);
	return Name;
}

void ADCRuntimeGameMode::FaceTowards(const FVector& Where)
{
	APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
	const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	if (Pawn == nullptr)
	{
		return;
	}
	FRotator Look = (Where - Pawn->GetActorLocation()).Rotation();
	Look.Pitch = FMath::Clamp(Look.Pitch, -18.0f, 6.0f);
	Look.Roll = 0.0f;
	PC->SetControlRotation(Look);
}

void ADCRuntimeGameMode::StartWalk(int32 SlotIndex, const TArray<FVector>& Targets,
	const FString& Leg)
{
	WalkTargets = Targets;
	WalkTarget = Targets.Num() > 0 ? 0 : -1;
	WalkSlotIndex = SlotIndex;
	WalkLeg = Leg;
	WalkStartSeconds = FPlatformTime::Seconds();
	WalkMetres = 0.0f;
	WalkStuckSeconds = 0.0f;

	if (const APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		if (const APawn* Pawn = PC->GetPawn())
		{
			WalkLastPosition = Pawn->GetActorLocation();
		}
	}
	const ADCSlot* Slot = SlotByIndex(SlotIndex);
	DC_LOG(Log, TEXT("WALK  %s %s: %d waypoint(s) from %s"),
		Slot ? *Slot->SlotId.ToString() : TEXT("?"), *Leg, Targets.Num(),
		*WalkLastPosition.ToCompactString());
}

bool ADCRuntimeGameMode::TickWalk(float DeltaSeconds)
{
	if (WalkTarget < 0 || !WalkTargets.IsValidIndex(WalkTarget))
	{
		return true;
	}
	APlayerController* PC = GetWorld()->GetFirstPlayerController();
	APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	if (Pawn == nullptr)
	{
		FinishWalk(false, TEXT("no pawn to walk"));
		return true;
	}

	const FVector Here = Pawn->GetActorLocation();
	WalkMetres += FVector::Dist2D(Here, WalkLastPosition) * 0.01f;
	if (FVector::Dist2D(Here, WalkLastPosition) > DCWalkStuckMove * DeltaSeconds * 4.0f)
	{
		WalkStuckSeconds = 0.0f;
	}
	else
	{
		WalkStuckSeconds += DeltaSeconds;
	}
	WalkLastPosition = Here;

	const FVector Target = WalkTargets[WalkTarget];
	const float Gap = FVector::Dist2D(Here, Target);
	const bool bLast = (WalkTarget == WalkTargets.Num() - 1);
	if (Gap <= (bLast ? DCWalkAcceptFinal : DCWalkAccept))
	{
		++WalkTarget;
		WalkStuckSeconds = 0.0f;
		if (WalkTarget >= WalkTargets.Num())
		{
			FinishWalk(true, FString());
			return true;
		}
		return false;
	}

	FVector Dir = FVector(Target.X - Here.X, Target.Y - Here.Y, 0.0f).GetSafeNormal();

	// If the straight line stops working, slide along whatever is in the way and try again.
	// A plaza has benches and trees in it; this is the cheapest thing that gets round one
	// without a navigation mesh, and the stuck timer still ends the leg if it never does.
	if (WalkStuckSeconds > 0.7f)
	{
		const float Side = (FMath::FloorToInt(WalkStuckSeconds / 1.6f) % 2 == 0) ? 1.0f : -1.0f;
		const FVector Right = FVector::CrossProduct(FVector::UpVector, Dir);
		Dir = (Dir * 0.45f + Right * Side).GetSafeNormal();
	}
	Pawn->AddMovementInput(Dir, 1.0f);

	// Turn the camera with the walk, so the pictures are not taken over the Player's shoulder
	// into a wall.
	const FRotator Want(-8.0f, (Target - Here).Rotation().Yaw, 0.0f);
	PC->SetControlRotation(FMath::RInterpTo(PC->GetControlRotation(), Want, DeltaSeconds, 3.0f));

	const double Elapsed = FPlatformTime::Seconds() - WalkStartSeconds;
	if (WalkStuckSeconds > DCWalkStuckSeconds)
	{
		FinishWalk(false, FString::Printf(TEXT("stuck %.0f cm short of waypoint %d"),
			Gap, WalkTarget + 1));
		return true;
	}
	if (Elapsed > DCWalkTimeout)
	{
		FinishWalk(false, FString::Printf(TEXT("timed out %.0f cm short of waypoint %d"),
			Gap, WalkTarget + 1));
		return true;
	}
	return false;
}

void ADCRuntimeGameMode::FinishWalk(bool bArrived, const FString& Note)
{
	FTourWalk Result;
	const ADCSlot* Slot = SlotByIndex(WalkSlotIndex);
	Result.SlotId = Slot ? Slot->SlotId.ToString() : FString();
	Result.Leg = WalkLeg;
	Result.bArrived = bArrived;
	Result.Seconds = static_cast<float>(FPlatformTime::Seconds() - WalkStartSeconds);
	Result.MetresWalked = WalkMetres;
	Result.Note = Note;

	if (const APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		if (const APawn* Pawn = PC->GetPawn())
		{
			const FVector Last = WalkTargets.Num() > 0 ? WalkTargets.Last() : Pawn->GetActorLocation();
			Result.FinalGapCm = FVector::Dist2D(Pawn->GetActorLocation(), Last);
		}
	}
	Walks.Add(Result);
	WalkTarget = -1;

	// DC_LOG stringifies its verbosity, so it cannot be chosen with a ternary.
	if (bArrived)
	{
		DC_LOG(Log, TEXT("WALK  %s %s arrived in %.1f s, %.0f m walked, %.0f cm from the mark"),
			*Result.SlotId, *Result.Leg, Result.Seconds, Result.MetresWalked, Result.FinalGapCm);
	}
	else
	{
		DC_LOG(Warning, TEXT("WALK  %s %s DID NOT ARRIVE after %.1f s, %.0f m walked, "
			"%.0f cm from the mark - %s"),
			*Result.SlotId, *Result.Leg, Result.Seconds, Result.MetresWalked,
			Result.FinalGapCm, *Note);
	}
}

void ADCRuntimeGameMode::NextTourAction()
{
	// Only the index moves. An action that wants a settle time sets TourWaitLeft itself, and
	// clearing it here would quietly throw that away.
	++TourIndex;
}

void ADCRuntimeGameMode::TickTour(float DeltaSeconds)
{
	if (!bTourBuilt || !Tour.IsValidIndex(TourIndex))
	{
		return;
	}
	if (TourWaitLeft > 0.0f)
	{
		TourWaitLeft -= DeltaSeconds;
		return;
	}
	if (WalkTarget >= 0)
	{
		if (!TickWalk(DeltaSeconds))
		{
			return;
		}
		NextTourAction();
		return;
	}

	const FTourAction Action = Tour[TourIndex];
	ADCSlot* Slot = SlotByIndex(Action.SlotIndex);

	switch (Action.Kind)
	{
	case ETourKind::Wait:
		TourWaitLeft = Action.Seconds;
		NextTourAction();
		return;

	case ETourKind::OverviewCamera:
		PointCameraOverview();
		NextTourAction();
		return;

	case ETourKind::SlotCamera:
		if (Slot)
		{
			PointCameraAt(*Slot);
		}
		NextTourAction();
		return;

	case ETourKind::Shot:
		TourShot(Action.Label);
		TourWaitLeft = DCAfterShotSeconds;
		NextTourAction();
		return;

	case ETourKind::ViewPawn:
		SetSpringArm(DCArmOutside);
		SetViewToPawn();
		TourWaitLeft = 0.5f;
		NextTourAction();
		return;

	case ETourKind::WalkToDoor:
	{
		TArray<FVector> Targets;
		if (Slot)
		{
			Targets = Slot->ApproachPath;
			Targets.Add(Slot->GetDoorApproachPoint(420.0f));
		}
		StartWalk(Action.SlotIndex, Targets, TEXT("to the door"));
		return;
	}

	case ETourKind::OpenDoor:
		if (Slot)
		{
			if (ADCContentActor* Built = Cast<ADCContentActor>(Slot->GetContentActor()))
			{
				// The demo's interaction will do this from the pad; for the tour the point is
				// only that a closed door really is closed - it blocks - and an open one is
				// walked through.
				Built->bDoorOpen = true;
				Built->bLightBOn = true;
				Built->ApplyState();
				DC_LOG(Log, TEXT("TOUR  opened the door of %s"), *Built->GetName());
			}
		}
		TourWaitLeft = 0.5f;
		NextTourAction();
		return;

	case ETourKind::WalkInside:
	{
		TArray<FVector> Targets;
		if (Slot)
		{
			FTransform Inside;
			if (const ADCContentActor* Built = Cast<ADCContentActor>(Slot->GetContentActor()))
			{
				if (Built->GetSocketWorldTransform(TEXT("Inside"), Inside))
				{
					Targets.Add(Inside.GetLocation());
				}
			}
			if (Targets.Num() == 0)
			{
				Targets.Add(Slot->GetActorLocation());
			}
		}
		SetSpringArm(DCArmInside);
		StartWalk(Action.SlotIndex, Targets, TEXT("in through the door"));
		return;
	}

	case ETourKind::StepBackOut:
	{
		TArray<FVector> Targets;
		if (Slot)
		{
			Targets.Add(Slot->GetDoorApproachPoint(500.0f));
		}
		SetSpringArm(DCArmOutside);
		StartWalk(Action.SlotIndex, Targets, TEXT("back out"));
		return;
	}

	case ETourKind::End:
	default:
	{
		// -DCTourFor: go round again until the run is that old. That is how the ten-minute
		// frame-time run of plan v6 §11 is driven - one lap of Game A is about 90 seconds,
		// so a long measurement is laps of the same honest walk rather than a camera left
		// standing still, which would measure nothing.
		const float Elapsed = static_cast<float>(FPlatformTime::Seconds() - StartSeconds);
		if (TourForSeconds > 0.0f && Elapsed < TourForSeconds)
		{
			++TourRound;
			DC_LOG(Log, TEXT("TOUR  round %d done at %.0f s of %.0f - going round again"),
				TourRound, Elapsed, TourForSeconds);
			BuildTour();
			return;
		}
		DC_LOG(Log, TEXT("TOUR  done (%d round(s), %.0f s)"), TourRound + 1, Elapsed);
		Finish();
		return;
	}
	}
}

// ============================================================ the state exit test (step 6)

ADCSlot* ADCRuntimeGameMode::StateSlot() const
{
	return FindSlot(StateSlotId);
}

ADCContentActor* ADCRuntimeGameMode::StateContent() const
{
	const ADCSlot* Slot = StateSlot();
	return Slot ? Cast<ADCContentActor>(Slot->GetContentActor()) : nullptr;
}

UDCInteractor* ADCRuntimeGameMode::StateInteractor() const
{
	return Interactor.Get();
}

void ADCRuntimeGameMode::StateStepTo(EStateStep Next)
{
	StateStep = Next;
	StateStepStarted = FPlatformTime::Seconds();
	StateSubStep = 0;
	StatePhase = 0;
	bStateAimed = false;
	StateWaitLeft = 0.0f;
}

bool ADCRuntimeGameMode::StateWalk(const FVector& To, const FString& Leg)
{
	TArray<FVector> One;
	One.Add(To);
	return StateWalkPath(One, Leg);
}

bool ADCRuntimeGameMode::StateWalkPath(const TArray<FVector>& Through, const FString& Leg)
{
	const ADCSlot* Slot = StateSlot();
	int32 Index = 0;
	if (const UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		const TArray<ADCSlot*> Slots = Subsystem->GetSlots();
		for (int32 i = 0; i < Slots.Num(); ++i)
		{
			if (Slots[i] == Slot)
			{
				Index = i;
				break;
			}
		}
	}

	TArray<FVector> Targets;
	const APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
	const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	if (Slot != nullptr && Pawn != nullptr
		&& FVector::Dist2D(Pawn->GetActorLocation(), Slot->GetActorLocation()) > DCStateFarAway)
	{
		// Only when the Player is actually somewhere else: the map's approach path starts at
		// the spawn, and following it from four metres away would walk back to the plaza.
		Targets.Append(Slot->ApproachPath);
	}
	Targets.Append(Through);
	StartWalk(Index, Targets, Leg);
	return true;
}

void ADCRuntimeGameMode::StateFail(const FString& Why)
{
	StateRound.bOk = false;
	StateRound.Note = Why;
	DC_LOG(Error, TEXT("STATETEST round %d FAILED: %s"), StateRound.N, *Why);
	StateStepTo(EStateStep::WalkClearAgain);
}

void ADCRuntimeGameMode::StateNextRound()
{
	StateRound.bOk = StateRound.bSetOk && StateRound.bPendingSeen && StateRound.bSwapped
		&& StateRound.bStateOk;
	if (UDCInteractor* Use = StateInteractor())
	{
		StateRound.Interactions = Use->GetTotalUses() - StateUsesAtRoundStart;
	}
	StateResults.Add(StateRound);

	DC_LOG(Log, TEXT("STATETEST round %d %s  %s %s -> %s %s (%s)  set=%s pending=%s(%.1fs) "
		"swapped=%s(%.1fs) state=%s  left[%s] expected[%s] found[%s]  %s"),
		StateRound.N, StateRound.bOk ? TEXT("PASS") : TEXT("FAIL"),
		*StateRound.BeforePiece, *StateRound.BeforeVersion,
		*StateRound.AfterPiece, *StateRound.AfterVersion, *StateRound.Kind,
		*BoolWord(StateRound.bSetOk), *BoolWord(StateRound.bPendingSeen),
		StateRound.PendingSeconds, *BoolWord(StateRound.bSwapped), StateRound.SwapSeconds,
		*BoolWord(StateRound.bStateOk), *StateRound.Left.Describe(),
		*StateRound.Expected.Describe(), *StateRound.Found.Describe(), *StateRound.Note);

	WriteStateFile(TEXT("round done"));

	if (StateRoundIndex >= StateRounds)
	{
		StateStepTo(EStateStep::Done);
		return;
	}
	StateRound = FStateRound();
	StateRoundStarted = FPlatformTime::Seconds();
	StateStepTo(EStateStep::WaitForContent);
}

void ADCRuntimeGameMode::TickStateTest(float DeltaSeconds)
{
	if (StateStep == EStateStep::Done)
	{
		WriteStateFile(TEXT("done"));
		DC_LOG(Log, TEXT("STATETEST done"));
		Finish();
		return;
	}

	if (StateWaitLeft > 0.0f)
	{
		StateWaitLeft -= DeltaSeconds;
		return;
	}

	// A walk in progress owns the frame; every walking step advances to the next one when the
	// Player gets there, which is what keeps the list below a straight sequence.
	if (WalkTarget >= 0)
	{
		if (!TickWalk(DeltaSeconds))
		{
			return;
		}
		StateStepTo(static_cast<EStateStep>(static_cast<uint8>(StateStep) + 1));
		return;
	}

	const double Now = FPlatformTime::Seconds();
	if (StateRoundIndex > 0 && StateStep != EStateStep::WalkClearAgain
		&& StateStep != EStateStep::RoundDone
		&& Now - StateRoundStarted > DCStateRoundTimeout)
	{
		StateFail(FString::Printf(TEXT("the round ran past %.0f s at step %d"),
			DCStateRoundTimeout, static_cast<int32>(StateStep)));
		return;
	}

	ADCSlot* Slot = StateSlot();
	if (Slot == nullptr)
	{
		if (Now - StateStepStarted > DCStateStepTimeout)
		{
			DC_LOG(Error, TEXT("STATETEST there is no slot %s in this map"), *StateSlotId);
			StateStepTo(EStateStep::Done);
		}
		return;
	}
	ADCContentActor* Content = StateContent();
	UDCInteractor* Use = StateInteractor();
	FDCInteractionPoint Point;

	switch (StateStep)
	{
	// ---------------------------------------------------------------- the round starts
	case EStateStep::WaitForContent:
	{
		if (StateSubStep == 0)
		{
			++StateRoundIndex;
			StateRound = FStateRound();
			StateRound.N = StateRoundIndex;
			StateRoundStarted = Now;
			StateUsesAtRoundStart = Use ? Use->GetTotalUses() : 0;
			StateSubStep = 1;
			WriteStateFile(TEXT("waiting"));
			DC_LOG(Log, TEXT("STATETEST ---- round %d / %d ----"), StateRoundIndex, StateRounds);
		}
		if (Content == nullptr || Slot->GetState() != EDCSlotState::Active
			|| Slot->GetActiveManifest().Piece != StateBasePiece || Content->IsDoorMoving())
		{
			if (Now - StateStepStarted > DCStateStepTimeout)
			{
				StateFail(FString::Printf(TEXT("%s never came up in %s"), *StateBasePiece,
					*StateSlotId));
			}
			return;
		}
		// What the Player finds on walking up to a slot that has been through somebody else's
		// content since they were last here. If the round before this one ended with a
		// *different* piece taking the block, then this is the record surviving that - the
		// state outlived the content it belongs to, which is the other half of the promise.
		if (StateResults.Num() > 0)
		{
			FStateRound& Previous = StateResults.Last();
			if (Previous.AfterPiece != Previous.BeforePiece && !Previous.AfterPiece.IsEmpty())
			{
				Previous.bRestoredOnReturn = Content->GetContentState() == Previous.Left;
				DC_LOG(Log, TEXT("STATETEST round %d: %s came back to %s wearing %s - the "
					"record %s a block of somebody else's content"),
					Previous.N, *StateBasePiece, *StateSlotId,
					*Content->GetContentState().Describe(),
					Previous.bRestoredOnReturn ? TEXT("outlived") : TEXT("DID NOT outlive"));
			}
		}
		StateStepTo(EStateStep::WalkToDoor);
		return;
	}

	case EStateStep::WalkToDoor:
	{
		if (Content == nullptr || !Content->GetInteractionPoint(EDCInteraction::Door, Point))
		{
			StateFail(TEXT("the piece that came up has no door"));
			return;
		}
		StateWalk(Slot->GetFrontStandPoint(DCStateFrontClearance), TEXT("to the door"));
		return;
	}

	// ---------------------------------------------------------------- the door
	case EStateStep::CloseDoorIfOpen:
	{
		if (Content == nullptr)
		{
			StateFail(TEXT("the content went away at the door"));
			return;
		}
		if (StateSubStep == 0)
		{
			StateSubStep = 1;
			if (Content->GetInteractionPoint(EDCInteraction::Door, Point))
			{
				FaceTowards(Point.Location);
			}
			StateWaitLeft = 0.25f;
			return;
		}
		if (Content->bDoorOpen)
		{
			// Every round starts from a door that is shut, so "the Player opens the door" is
			// a real use of it and not a no-op left over from the round before.
			if (Use == nullptr || !Use->TryUseKind(EDCInteraction::Door))
			{
				StateFail(TEXT("could not close the door from where the Player is standing"));
				return;
			}
			StateWaitLeft = 0.8f;
			return;
		}
		if (Content->IsDoorMoving())
		{
			if (Now - StateStepStarted > DCStateDoorTimeout)
			{
				StateFail(TEXT("the door never finished closing"));
			}
			return;
		}
		StateStepTo(EStateStep::OpenDoor);
		return;
	}

	case EStateStep::OpenDoor:
	{
		if (Content == nullptr)
		{
			StateFail(TEXT("the content went away at the door"));
			return;
		}
		if (StateSubStep == 0)
		{
			StateSubStep = 1;
			if (Use == nullptr || !Use->TryUseKind(EDCInteraction::Door))
			{
				StateFail(TEXT("could not open the door from where the Player is standing"));
				return;
			}
			StateWaitLeft = 0.9f;
			return;
		}
		if (Content->IsDoorMoving())
		{
			if (Now - StateStepStarted > DCStateDoorTimeout)
			{
				StateFail(TEXT("the door never finished opening"));
			}
			return;
		}
		if (!Content->bDoorOpen)
		{
			StateFail(TEXT("the door did not open"));
			return;
		}
		StateStepTo(EStateStep::WalkInside);
		return;
	}

	case EStateStep::WalkInside:
	{
		FTransform Inside;
		if (Content == nullptr || !Content->GetSocketWorldTransform(TEXT("Inside"), Inside))
		{
			StateFail(TEXT("the piece has no inside to walk to"));
			return;
		}
		SetSpringArm(DCArmInside);
		StateWalk(Inside.GetLocation(), TEXT("in through the door"));
		return;
	}

	// ---------------------------------------------------------------- the switches
	case EStateStep::SetLights:
	{
		if (Content == nullptr || Use == nullptr)
		{
			StateFail(TEXT("the content went away inside"));
			return;
		}
		if (StateSubStep > DCStateMaxPresses)
		{
			StateFail(TEXT("the light switches would not reach the state the round wanted"));
			return;
		}
		// What the round wants next: the baseline (A on, B off) first, then the one thing it
		// is about, light B on. StatePhase 1 is the baseline, 2 is the target.
		if (StatePhase == 0)
		{
			StatePhase = (Content->bLightAOn && !Content->bLightBOn) ? 2 : 1;
		}
		EDCInteraction Want = EDCInteraction::None;
		if (!Content->bLightAOn)
		{
			Want = EDCInteraction::LightA;              // the baseline wants A on
		}
		else if (StatePhase == 1 && Content->bLightBOn)
		{
			Want = EDCInteraction::LightB;              // ...and B off, to start from
		}
		else if (StatePhase == 1)
		{
			StatePhase = 2;
			return;
		}
		else if (!Content->bLightBOn)
		{
			Want = EDCInteraction::LightB;              // the round's own change
		}
		if (Want == EDCInteraction::None)
		{
			StateStepTo(EStateStep::WalkToScreen);
			return;
		}
		// Look at it, *then* press it a tick later. The prompt is chosen from the camera's
		// view point, and the camera is a spring arm behind the Player that catches up a
		// frame later - so pressing in the same tick as the turn would have the prompt still
		// showing whatever was in front of the Player before they turned.
		if (!bStateAimed)
		{
			if (Content->GetInteractionPoint(Want, Point))
			{
				FaceTowards(Point.Location);
			}
			bStateAimed = true;
			StateWaitLeft = DCStatePressGap;
			return;
		}
		if (!Use->TryUseKind(Want))
		{
			StateFail(FString::Printf(TEXT("switch %s is not in reach from inside the door"),
				DCInteractionName(Want)));
			return;
		}
		++StateSubStep;
		bStateAimed = false;
		StateWaitLeft = DCStatePressGap;
		return;
	}

	// ---------------------------------------------------------------- the screen
	case EStateStep::WalkToScreen:
	{
		if (Content == nullptr || !Content->GetInteractionPoint(EDCInteraction::Screen, Point))
		{
			StateFail(TEXT("the piece has no screen"));
			return;
		}
		StateWalk(Point.StandPoint, TEXT("across to the screen"));
		return;
	}

	case EStateStep::SetScreen:
	{
		if (Content == nullptr || Use == nullptr)
		{
			StateFail(TEXT("the content went away at the screen"));
			return;
		}
		if (StatePhase == 0)
		{
			if (Content->GetInteractionPoint(EDCInteraction::Screen, Point))
			{
				FaceTowards(Point.Location);
			}
			StatePhase = 1;
			StateWaitLeft = 0.25f;
			return;
		}
		if (StateSubStep > DCStateMaxPresses)
		{
			StateFail(TEXT("the screen would not reach image 3"));
			return;
		}
		// Baseline first (image 1), then the round's target (image 3). Without the baseline
		// a round that started with the screen already on 3 - because the last round's state
		// was restored - would press the button no times and prove nothing.
		const int32 Want = (StatePhase == 1) ? 1 : 3;
		if (Content->ScreenIndex != Want)
		{
			if (!Use->TryUseKind(EDCInteraction::Screen))
			{
				StateFail(TEXT("the screen is not in reach"));
				return;
			}
			++StateSubStep;
			StateWaitLeft = DCStatePressGap;
			return;
		}
		if (StatePhase == 1)
		{
			StatePhase = 2;
			return;
		}
		StateStepTo(EStateStep::ShotSet);
		return;
	}

	case EStateStep::ShotSet:
	{
		if (Content == nullptr)
		{
			StateFail(TEXT("the content went away before the picture"));
			return;
		}
		if (StateSubStep == 0)
		{
			StateSubStep = 1;
			SetSpringArm(DCArmShot, DCShotRight, DCShotUp);
			if (Content->GetInteractionPoint(EDCInteraction::Screen, Point))
			{
				FaceTowards(Point.Location);
			}
			StateWaitLeft = DCSettleSeconds;
			return;
		}
		StateRound.Shots.Add(TourShot(FString::Printf(TEXT("r%02d_set"), StateRound.N)));
		StateWaitLeft = DCAfterShotSeconds;
		StateStepTo(EStateStep::Arm);
		return;
	}

	// ---------------------------------------------------------------- hand over to the script
	case EStateStep::Arm:
	{
		if (Content == nullptr)
		{
			StateFail(TEXT("the content went away before the round was armed"));
			return;
		}
		StateRound.Left = Content->GetContentState();
		StateRound.BeforePiece = Slot->GetActiveManifest().Piece;
		StateRound.BeforeVersion = Slot->GetActiveManifest().Version;
		StateRound.BeforeAllocKey = Slot->GetActiveAllocKey();
		StateRound.bSetOk = StateRound.Left.bDoorOpen && StateRound.Left.bLightBOn
			&& StateRound.Left.ScreenIndex == 3 && Slot->IsPlayerInside();
		if (!StateRound.bSetOk)
		{
			StateFail(FString::Printf(TEXT("the Player did not end up with what the round "
				"wanted: %s, inside=%s"), *StateRound.Left.Describe(),
				*BoolWord(Slot->IsPlayerInside())));
			return;
		}
		// The driving script is watching this file: it pushes a new version, or ends the
		// block, the moment it sees "armed". The game is told neither which it was nor what
		// to expect - it works that out from whatever turns up.
		WriteStateFile(TEXT("armed"));
		DC_LOG(Log, TEXT("STATETEST round %d armed: %s %s is up, the Player is inside with %s"),
			StateRound.N, *StateRound.BeforePiece, *StateRound.BeforeVersion,
			*StateRound.Left.Describe());
		StateStepTo(EStateStep::WaitPending);
		return;
	}

	case EStateStep::WaitPending:
	{
		if (Slot->GetState() == EDCSlotState::SwapPending)
		{
			StateRound.bPendingSeen = true;
			StateRound.PendingSeconds = static_cast<float>(Now - StateStepStarted);
			DC_LOG(Log, TEXT("STATETEST round %d SWAP PENDING after %.1f s; %s %s is still up"),
				StateRound.N, StateRound.PendingSeconds, *Slot->GetActiveManifest().Piece,
				*Slot->GetActiveManifest().Version);
			StateStepTo(EStateStep::WalkToInside2);
			return;
		}
		if (Slot->GetActiveAllocKey() != StateRound.BeforeAllocKey
			&& !StateRound.BeforeAllocKey.IsEmpty())
		{
			StateFail(TEXT("the content changed without ever being held as SWAP PENDING - "
				"the Player was not inside the bounds box"));
			return;
		}
		if (Now - StateStepStarted > DCStateStepTimeout)
		{
			StateFail(TEXT("nothing arrived to swap in"));
		}
		return;
	}

	case EStateStep::WalkToInside2:
	{
		FTransform Inside;
		if (Content == nullptr || !Content->GetSocketWorldTransform(TEXT("Inside"), Inside))
		{
			StateStepTo(EStateStep::ShotPending);
			return;
		}
		StateWalk(Inside.GetLocation(), TEXT("back to the door, still inside"));
		return;
	}

	case EStateStep::ShotPending:
	{
		if (StateSubStep == 0)
		{
			StateSubStep = 1;
			SetSpringArm(DCArmShot, DCShotRight, DCShotUp);
			if (Content != nullptr
				&& Content->GetInteractionPoint(EDCInteraction::Screen, Point))
			{
				FaceTowards(Point.Location);
			}
			StateWaitLeft = DCSettleSeconds;
			return;
		}
		StateRound.Shots.Add(TourShot(FString::Printf(TEXT("r%02d_pending"), StateRound.N)));
		StateWaitLeft = DCAfterShotSeconds;
		StateStepTo(EStateStep::WalkClear);
		return;
	}

	// ---------------------------------------------------------------- walk out, let it swap
	case EStateStep::WalkClear:
		SetSpringArm(DCArmOutside);
		StateWalkOutStarted = Now;
		StateWalk(Slot->GetDoorApproachPoint(DCStateClearExtra), TEXT("out of the bounds box"));
		return;

	case EStateStep::WaitSwapped:
	{
		if (Slot->GetState() == EDCSlotState::Active && Slot->HasContent()
			&& Slot->GetActiveAllocKey() != StateRound.BeforeAllocKey)
		{
			ADCContentActor* Now2 = StateContent();
			StateRound.bSwapped = true;
			// Measured from the moment the Player set off out of the bounds box, not from
			// the moment this step started: the held swap often applies while they are still
			// walking, which is the point.
			StateRound.SwapSeconds = static_cast<float>(Now - StateWalkOutStarted);
			StateRound.AfterPiece = Slot->GetActiveManifest().Piece;
			StateRound.AfterVersion = Slot->GetActiveManifest().Version;
			StateRound.AfterAllocKey = Slot->GetActiveAllocKey();
			StateRound.Found = Now2 ? Now2->GetContentState() : FDCContentState();

			// The rule under test, decided by the game from what arrived: the same content,
			// whatever its version, comes back wearing what the Player left; a different
			// piece gets its own defaults and must not be wearing somebody else's state.
			const bool bSameContent = StateRound.AfterPiece == StateRound.BeforePiece;
			StateRound.Kind = bSameContent ? TEXT("same content") : TEXT("different content");
			StateRound.Expected = bSameContent ? StateRound.Left : FDCContentState();
			StateRound.bStateOk = StateRound.Found == StateRound.Expected;
			if (!bSameContent && StateRound.Found == StateRound.Left)
			{
				StateRound.bStateOk = false;
				StateRound.Note = TEXT("a different piece came up wearing the state the "
					"Player left on the last one");
			}
			DC_LOG(Log, TEXT("STATETEST round %d swapped after %.1f s: %s %s -> %s %s (%s)  "
				"found[%s] expected[%s] -> %s"),
				StateRound.N, StateRound.SwapSeconds, *StateRound.BeforePiece,
				*StateRound.BeforeVersion, *StateRound.AfterPiece, *StateRound.AfterVersion,
				*StateRound.Kind, *StateRound.Found.Describe(),
				*StateRound.Expected.Describe(),
				StateRound.bStateOk ? TEXT("KEPT") : TEXT("WRONG"));
			StateStepTo(EStateStep::ShotSwapped);
			return;
		}
		if (Now - StateStepStarted > DCStateStepTimeout)
		{
			StateFail(TEXT("the held swap never applied after the Player walked out"));
		}
		return;
	}

	case EStateStep::ShotSwapped:
	{
		if (StateSubStep == 0)
		{
			StateSubStep = 1;
			FaceTowards(Slot->GetContentCentre());
			StateWaitLeft = DCSettleSeconds;
			return;
		}
		StateRound.Shots.Add(TourShot(FString::Printf(TEXT("r%02d_swapped"), StateRound.N)));
		StateWaitLeft = DCAfterShotSeconds;
		StateStepTo(EStateStep::WalkBackToDoor);
		return;
	}

	// ---------------------------------------------------------------- walk back in and look
	case EStateStep::WalkBackToDoor:
	{
		if (Content == nullptr || !Content->GetInteractionPoint(EDCInteraction::Door, Point))
		{
			StateStepTo(EStateStep::ShotBack);
			return;
		}
		StateWalk(Slot->GetFrontStandPoint(DCStateFrontClearance), TEXT("back to the door"));
		return;
	}

	case EStateStep::WalkBackInside:
	{
		FTransform Inside;
		// Only through a door that is already open. Opening a closed one would be the Player
		// *changing* the piece they came back to look at - and on a round where somebody
		// else's content took the block, that change would be saved and would turn up in the
		// next round as a state nobody set.
		if (Content == nullptr || !Content->bDoorOpen
			|| !Content->GetSocketWorldTransform(TEXT("Inside"), Inside))
		{
			StateStepTo(EStateStep::ShotBack);
			return;
		}
		SetSpringArm(DCArmInside);
		{
			// In through the door and on across to the screen, so the picture of "exactly as
			// they left it" actually has the screen in it.
			TArray<FVector> Targets;
			Targets.Add(Inside.GetLocation());
			if (Content->GetInteractionPoint(EDCInteraction::Screen, Point))
			{
				Targets.Add(Point.StandPoint);
			}
			StateWalkPath(Targets, TEXT("back in through the door"));
		}
		return;
	}

	case EStateStep::ShotBack:
	{
		if (StateSubStep == 0)
		{
			StateSubStep = 1;
			SetSpringArm(DCArmShot, DCShotRight, DCShotUp);
			if (Content != nullptr
				&& Content->GetInteractionPoint(EDCInteraction::Screen, Point))
			{
				FaceTowards(Point.Location);
			}
			else
			{
				FaceTowards(Slot->GetContentCentre());
			}
			StateWaitLeft = DCSettleSeconds;
			return;
		}
		StateRound.Shots.Add(TourShot(FString::Printf(TEXT("r%02d_back"), StateRound.N)));
		StateWaitLeft = DCAfterShotSeconds;
		StateStepTo(EStateStep::WalkClearAgain);
		return;
	}

	case EStateStep::WalkClearAgain:
		SetSpringArm(DCArmOutside);
		StateWalk(Slot->GetDoorApproachPoint(DCStateClearExtra), TEXT("clear of the slot"));
		return;

	case EStateStep::RoundDone:
		StateNextRound();
		return;

	default:
		StateStepTo(EStateStep::Done);
		return;
	}
}

// ===================================================================== tick

void ADCRuntimeGameMode::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	if (bFinished)
	{
		return;
	}

	const double Now = FPlatformTime::Seconds();
	if (!bCollectFrames && Now - StartSeconds > 4.0)
	{
		bCollectFrames = true;
	}
	if (bCollectFrames && DeltaSeconds > 0.0f && Now - LastShotSeconds > DCShotBlackout)
	{
		const float Ms = DeltaSeconds * 1000.0f;
		FrameMs.Add(Ms);
		// The same sample goes to the subsystem, which keeps the running counters the
		// status file carries - so a script watching the file and the tour report at the
		// end of the run can never disagree about what a frame cost.
		if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
		{
			Subsystem->NoteFrame(Ms);
		}
	}

	if (bPreview)
	{
		TickPreview(DeltaSeconds);
		return;
	}

	// The interaction component belongs to the plugin, not to the game module's pawn
	// Blueprint, so the game mode puts it on whatever pawn the Player ends up driving. The
	// pawn arrives a frame or two after BeginPlay, hence the check every tick until it does.
	if (!Interactor.IsValid())
	{
		if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
		{
			if (APawn* Pawn = PC->GetPawn())
			{
				Interactor = UDCInteractor::EnsureOn(Pawn);
			}
		}
	}

	if (bTour)
	{
		if (!bTourBuilt)
		{
			if (Now - StartSeconds >= TourWarmupSeconds)
			{
				BuildTour();
			}
			return;
		}
		TickTour(DeltaSeconds);
	}
	else if (bStateTest)
	{
		if (Now - StartSeconds < TourWarmupSeconds)
		{
			return;                       // let the slots fill from the backend first
		}
		TickStateTest(DeltaSeconds);
	}
}

// ===================================================================== reports

void ADCRuntimeGameMode::WriteResultFile()
{
	if (ShotDir.IsEmpty())
	{
		return;
	}
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (Subsystem == nullptr)
	{
		return;
	}

	TArray<FString> Lines;
	Lines.Add(TEXT("DC runtime client run"));
	Lines.Add(FString::Printf(TEXT("build=%s"), UDCSubsystem::GetBuildConfigName()));
	Lines.Add(FString::Printf(TEXT("map=%s"), *GetWorld()->GetMapName()));
	Lines.Add(FString::Printf(TEXT("backend=%s  game=%s  region=%s"),
		*Subsystem->GetBackendUrl(), *Subsystem->GetGame(), *Subsystem->GetRegion()));
	Lines.Add(FString::Printf(TEXT("crypto=%s"), *Subsystem->GetCryptoApi()));
	Lines.Add(FString::Printf(TEXT("uptime_s=%.0f  restarts=%d  content_loading_screens=%d"),
		Subsystem->GetUptimeSeconds(), Subsystem->GetRestartCount(),
		Subsystem->GetLoadingScreenCount()));
	Lines.Add(FString::Printf(TEXT("polls=%d  changes=%d  packs_mounted=%d  shots=%d"),
		Subsystem->GetPollCount(), Subsystem->GetChangeCount(),
		Subsystem->GetMountedPackCount(), ShotCount));
	Lines.Add(TEXT(""));
	Lines.Add(TEXT("activations:"));
	for (const UDCSubsystem::FActivation& A : Subsystem->GetActivations())
	{
		Lines.Add(FString::Printf(
			TEXT("  #%-3d %-3s %-14s %-3s %-8s %-9s key=%s  resolve=%.0f download=%.0f "
				"verify=%.0f mount=%.0f load=%.0f spawn=%.1f total=%.0f ms  net=%lld B  "
				"cached=%d ranges=%d  visible=%s  shot=%s"),
			A.Seq, *A.SlotId, *A.Piece, *A.Version,
			A.BrandColour.IsEmpty() ? TEXT("-") : *A.BrandColour,
			A.BrandEmblem.IsEmpty() ? TEXT("-") : *A.BrandEmblem,
			*A.AllocKey, A.ResolveMs, A.DownloadMs, A.VerifyMs, A.MountMs, A.LoadMs,
			A.SpawnMs, A.TotalMs, A.NetworkBytes, A.CachedFiles, A.RangeRequests,
			*A.VisibleUtc, A.Shot.IsEmpty() ? TEXT("-") : *A.Shot));
	}
	Lines.Add(TEXT(""));
	Lines.Add(TEXT("fallbacks:"));
	for (const UDCSubsystem::FFallbackNote& F : Subsystem->GetFallbacks())
	{
		Lines.Add(FString::Printf(TEXT("  #%-3d %-3s %s  %s"), F.Seq, *F.SlotId, *F.Utc, *F.Reason));
	}
	Lines.Add(TEXT(""));
	Lines.Add(TEXT("status strip at the end:"));
	for (const FString& Line : Subsystem->GetStatusLines())
	{
		Lines.Add(TEXT("  ") + Line);
	}

	const FString Path = ShotDir / TEXT("dc_runtime_result.txt");
	FFileHelper::SaveStringToFile(FString::Join(Lines, TEXT("\n")) + TEXT("\n"), *Path);
	DC_LOG(Log, TEXT("wrote %s"), *Path);
}

void ADCRuntimeGameMode::WriteTourFile()
{
	if (ShotDir.IsEmpty())
	{
		return;
	}

	// Frame times: the average, and the worst 1 % - which is the number that says whether a
	// second copy of this build (the region preview window, plan v6 §11) will fit alongside.
	TArray<float> Sorted = FrameMs;
	Sorted.Sort();
	float Average = 0.0f;
	for (float Ms : Sorted)
	{
		Average += Ms;
	}
	Average = Sorted.Num() > 0 ? Average / Sorted.Num() : 0.0f;
	const float Worst1 = Sorted.Num() > 0
		? Sorted[FMath::Clamp(FMath::FloorToInt(Sorted.Num() * 0.99f), 0, Sorted.Num() - 1)]
		: 0.0f;
	const float Median = Sorted.Num() > 0 ? Sorted[Sorted.Num() / 2] : 0.0f;
	const float Worst = Sorted.Num() > 0 ? Sorted.Last() : 0.0f;

	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);

	FString Text;
	const TSharedRef<TJsonWriter<TCHAR>> W = TJsonWriterFactory<TCHAR>::Create(&Text);
	W->WriteObjectStart();
	W->WriteValue(TEXT("map"), GetWorld()->GetMapName());
	W->WriteValue(TEXT("build"), UDCSubsystem::GetBuildConfigName());
	W->WriteValue(TEXT("tour"), bTour);
	W->WriteValue(TEXT("rounds"), TourRound + 1);
	W->WriteValue(TEXT("shots"), ShotCount);
	W->WriteValue(TEXT("seconds"), FPlatformTime::Seconds() - StartSeconds);
	W->WriteValue(TEXT("region"), Subsystem ? Subsystem->GetRegion() : FString());

	int32 Over16 = 0;
	int32 Over25 = 0;
	int32 Over33 = 0;
	for (float Ms : Sorted)
	{
		Over16 += Ms > 16.0f ? 1 : 0;
		Over25 += Ms > 25.0f ? 1 : 0;
		Over33 += Ms > 33.0f ? 1 : 0;
	}

	W->WriteObjectStart(TEXT("frame_ms"));
	W->WriteValue(TEXT("frames"), Sorted.Num());
	W->WriteValue(TEXT("average"), Average);
	W->WriteValue(TEXT("median"), Median);
	W->WriteValue(TEXT("worst_1_percent"), Worst1);
	W->WriteValue(TEXT("worst"), Worst);
	W->WriteValue(TEXT("average_fps"), Average > 0.0f ? 1000.0f / Average : 0.0f);
	// Plan v6 §11's pass line is "the worst 1 % stays under 25 ms", so the count of frames
	// that did not is worth having next to it rather than derivable from it.
	W->WriteValue(TEXT("over_16ms"), Over16);
	W->WriteValue(TEXT("over_25ms"), Over25);
	W->WriteValue(TEXT("over_33ms"), Over33);
	W->WriteObjectEnd();

	W->WriteArrayStart(TEXT("walks"));
	for (const FTourWalk& Walk : Walks)
	{
		W->WriteObjectStart();
		W->WriteValue(TEXT("slot"), Walk.SlotId);
		W->WriteValue(TEXT("leg"), Walk.Leg);
		W->WriteValue(TEXT("arrived"), Walk.bArrived);
		W->WriteValue(TEXT("seconds"), Walk.Seconds);
		W->WriteValue(TEXT("metres"), Walk.MetresWalked);
		W->WriteValue(TEXT("final_gap_cm"), Walk.FinalGapCm);
		W->WriteValue(TEXT("note"), Walk.Note);
		W->WriteObjectEnd();
	}
	W->WriteArrayEnd();

	W->WriteArrayStart(TEXT("slots"));
	if (Subsystem != nullptr)
	{
		for (const ADCSlot* Slot : Subsystem->GetSlots())
		{
			W->WriteObjectStart();
			W->WriteValue(TEXT("slot"), Slot->SlotId.ToString());
			W->WriteValue(TEXT("size_class"), Slot->GetSizeClassName());
			W->WriteValue(TEXT("state"), DCSlotStateName(Slot->GetState()));
			W->WriteValue(TEXT("piece"), Slot->GetActiveManifest().Piece);
			W->WriteValue(TEXT("version"), Slot->GetActiveManifest().Version);
			W->WriteValue(TEXT("brand"), Slot->GetActiveManifest().Brand.bValid
				? Slot->GetActiveManifest().Brand.ColourHex : FString());
			W->WriteValue(TEXT("emblem"), Slot->GetActiveManifest().Brand.bValid
				? Slot->GetActiveManifest().Brand.Emblem : FString());
			W->WriteValue(TEXT("kind"), Slot->GetActiveManifest().ShowingKind);
			W->WriteObjectEnd();
		}
	}
	W->WriteArrayEnd();
	W->WriteObjectEnd();
	W->Close();

	const FString Path = ShotDir / TEXT("dc_tour.json");
	FFileHelper::SaveStringToFile(Text, *Path, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	DC_LOG(Log, TEXT("TOUR  frames=%d  average %.2f ms (%.0f fps)  median %.2f  worst 1%% %.2f  "
		"worst %.2f   walks=%d"),
		Sorted.Num(), Average, Average > 0.0f ? 1000.0f / Average : 0.0f, Median, Worst1,
		Worst, Walks.Num());
	DC_LOG(Log, TEXT("wrote %s"), *Path);
}

void ADCRuntimeGameMode::WriteStateFile(const TCHAR* Phase)
{
	if (StateFilePath.IsEmpty())
	{
		return;
	}
	const ADCSlot* Slot = StateSlot();
	const ADCContentActor* Content = StateContent();

	FString Text;
	const TSharedRef<TJsonWriter<TCHAR>> W = TJsonWriterFactory<TCHAR>::Create(&Text);
	W->WriteObjectStart();
	W->WriteValue(TEXT("phase"), Phase);
	W->WriteValue(TEXT("round"), StateRoundIndex);
	W->WriteValue(TEXT("rounds"), StateRounds);
	W->WriteValue(TEXT("slot"), StateSlotId);
	W->WriteValue(TEXT("base_piece"), StateBasePiece);
	W->WriteValue(TEXT("step"), static_cast<int32>(StateStep));
	W->WriteValue(TEXT("updated_utc"), FDateTime::UtcNow().ToIso8601());
	W->WriteValue(TEXT("uptime_s"), FPlatformTime::Seconds() - StartSeconds);
	W->WriteValue(TEXT("slot_state"), Slot ? DCSlotStateName(Slot->GetState()) : TEXT("-"));
	W->WriteValue(TEXT("piece"), Slot ? Slot->GetActiveManifest().Piece : FString());
	W->WriteValue(TEXT("version"), Slot ? Slot->GetActiveManifest().Version : FString());
	W->WriteValue(TEXT("alloc_key"), Slot ? Slot->GetActiveAllocKey() : FString());
	W->WriteValue(TEXT("player_inside"), Slot ? Slot->IsPlayerInside() : false);
	if (Content != nullptr)
	{
		const FDCContentState State = Content->GetContentState();
		W->WriteObjectStart(TEXT("state"));
		W->WriteValue(TEXT("light_a_on"), State.bLightAOn);
		W->WriteValue(TEXT("light_b_on"), State.bLightBOn);
		W->WriteValue(TEXT("door_open"), State.bDoorOpen);
		W->WriteValue(TEXT("screen_image_index"), State.ScreenIndex);
		W->WriteObjectEnd();
	}
	W->WriteValue(TEXT("passed"), StateResults.FilterByPredicate(
		[](const FStateRound& R) { return R.bOk; }).Num());
	W->WriteValue(TEXT("finished"), StateResults.Num());
	W->WriteObjectEnd();
	W->Close();

	// Written aside and moved into place, like the status file: the script watching this
	// never reads half of one.
	const FString Temp = StateFilePath + TEXT(".tmp");
	if (FFileHelper::SaveStringToFile(Text, *Temp,
		FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
	{
		IFileManager::Get().Move(*StateFilePath, *Temp, true, true);
	}
}

void ADCRuntimeGameMode::WriteStateResultFile()
{
	if (ShotDir.IsEmpty() || !bStateTest)
	{
		return;
	}
	const UDCInteractor* Use = StateInteractor();
	const UDCStateStore* Store = UDCStateStore::Get(this);

	auto WriteState = [](const TSharedRef<TJsonWriter<TCHAR>>& W, const TCHAR* Name,
		const FDCContentState& S)
	{
		W->WriteObjectStart(Name);
		W->WriteValue(TEXT("light_a_on"), S.bLightAOn);
		W->WriteValue(TEXT("light_b_on"), S.bLightBOn);
		W->WriteValue(TEXT("door_open"), S.bDoorOpen);
		W->WriteValue(TEXT("screen_image_index"), S.ScreenIndex);
		W->WriteObjectEnd();
	};

	FString Text;
	const TSharedRef<TJsonWriter<TCHAR>> W = TJsonWriterFactory<TCHAR>::Create(&Text);
	W->WriteObjectStart();
	W->WriteValue(TEXT("map"), GetWorld()->GetMapName());
	W->WriteValue(TEXT("build"), UDCSubsystem::GetBuildConfigName());
	W->WriteValue(TEXT("slot"), StateSlotId);
	W->WriteValue(TEXT("base_piece"), StateBasePiece);
	W->WriteValue(TEXT("rounds_asked"), StateRounds);
	W->WriteValue(TEXT("rounds_run"), StateResults.Num());
	W->WriteValue(TEXT("passed"), StateResults.FilterByPredicate(
		[](const FStateRound& R) { return R.bOk; }).Num());
	W->WriteValue(TEXT("seconds"), FPlatformTime::Seconds() - StartSeconds);
	if (Use != nullptr)
	{
		W->WriteObjectStart(TEXT("interaction"));
		W->WriteValue(TEXT("uses"), Use->GetTotalUses());
		W->WriteValue(TEXT("door"), Use->GetUseCount(EDCInteraction::Door));
		W->WriteValue(TEXT("light_a"), Use->GetUseCount(EDCInteraction::LightA));
		W->WriteValue(TEXT("light_b"), Use->GetUseCount(EDCInteraction::LightB));
		W->WriteValue(TEXT("screen"), Use->GetUseCount(EDCInteraction::Screen));
		W->WriteValue(TEXT("prompt_agreed"), Use->GetPromptAgreed());
		W->WriteValue(TEXT("prompt_checked"), Use->GetPromptChecked());
		W->WriteValue(TEXT("reach_cm"), Use->GetReach());
		W->WriteObjectEnd();
	}

	W->WriteArrayStart(TEXT("rounds"));
	for (const FStateRound& R : StateResults)
	{
		W->WriteObjectStart();
		W->WriteValue(TEXT("n"), R.N);
		W->WriteValue(TEXT("ok"), R.bOk);
		W->WriteValue(TEXT("kind"), R.Kind);
		W->WriteValue(TEXT("before_piece"), R.BeforePiece);
		W->WriteValue(TEXT("before_version"), R.BeforeVersion);
		W->WriteValue(TEXT("before_alloc_key"), R.BeforeAllocKey);
		W->WriteValue(TEXT("after_piece"), R.AfterPiece);
		W->WriteValue(TEXT("after_version"), R.AfterVersion);
		W->WriteValue(TEXT("after_alloc_key"), R.AfterAllocKey);
		W->WriteValue(TEXT("set_ok"), R.bSetOk);
		W->WriteValue(TEXT("swap_pending_seen"), R.bPendingSeen);
		W->WriteValue(TEXT("swap_pending_s"), R.PendingSeconds);
		W->WriteValue(TEXT("swapped"), R.bSwapped);
		W->WriteValue(TEXT("swap_s"), R.SwapSeconds);
		W->WriteValue(TEXT("state_ok"), R.bStateOk);
		W->WriteValue(TEXT("restored_on_return"), R.bRestoredOnReturn);
		W->WriteValue(TEXT("interactions_so_far"), R.Interactions);
		W->WriteValue(TEXT("note"), R.Note);
		WriteState(W, TEXT("left"), R.Left);
		WriteState(W, TEXT("expected"), R.Expected);
		WriteState(W, TEXT("found"), R.Found);
		W->WriteArrayStart(TEXT("shots"));
		for (const FString& Shot : R.Shots)
		{
			W->WriteValue(Shot);
		}
		W->WriteArrayEnd();
		W->WriteObjectEnd();
	}
	W->WriteArrayEnd();

	W->WriteArrayStart(TEXT("state_store"));
	if (Store != nullptr)
	{
		for (const FString& Line : Store->DescribeAll())
		{
			W->WriteValue(Line);
		}
	}
	W->WriteArrayEnd();

	W->WriteArrayStart(TEXT("slots"));
	if (const UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		for (const ADCSlot* Slot : Subsystem->GetSlots())
		{
			W->WriteObjectStart();
			W->WriteValue(TEXT("slot"), Slot->SlotId.ToString());
			W->WriteValue(TEXT("visits"), Slot->GetVisitCount());
			W->WriteValue(TEXT("dwell_s"), Slot->GetTotalDwellSeconds());
			W->WriteObjectEnd();
		}
	}
	W->WriteArrayEnd();
	W->WriteObjectEnd();
	W->Close();

	const FString Path = ShotDir / TEXT("dc_state_test.json");
	FFileHelper::SaveStringToFile(Text, *Path, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	DC_LOG(Log, TEXT("wrote %s"), *Path);
}

void ADCRuntimeGameMode::Finish()
{
	if (bFinished)
	{
		return;
	}
	bFinished = true;

	if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		Subsystem->WriteStatusFile();
	}
	WriteResultFile();
	WriteTourFile();
	WriteStateResultFile();
	WriteStateFile(TEXT("finished"));

	DC_LOG(Log, TEXT("---------------- run done after %.0f s, %d shot(s) ----------------"),
		FPlatformTime::Seconds() - StartSeconds, ShotCount);

	// A headless run must not leave anything running.
	DC_LOG(Log, TEXT("requesting exit"));
	FPlatformMisc::RequestExit(false, TEXT("DCRuntime complete"));
}
