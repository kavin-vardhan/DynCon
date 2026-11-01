#include "DCRuntimeGameMode.h"

#include "DCContentActor.h"
#include "DCSlot.h"
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
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "TimerManager.h"
#include "UnrealClient.h"

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

	/** Frames within this of a shutter are thrown out of the frame-time figures. */
	constexpr double DCShotBlackout = 0.5;

	FString TwoDigits(int32 N)
	{
		return FString::Printf(TEXT("%02d"), N);
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
	if ((bAutoShot || bTour) && ShotDir.IsEmpty())
	{
		ShotDir = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("DCShots"));
		IFileManager::Get().MakeDirectory(*ShotDir, true);
	}
	// The tour drives its own camera: a shot per arriving piece would fight it for the view.
	if (bTour)
	{
		bAutoShot = false;
	}
	FParse::Value(Cmd, TEXT("DCRunSeconds="), RunSeconds);
	if (FParse::Value(Cmd, TEXT("DCQuitWhenFileExists="), Value, false) && !Value.IsEmpty())
	{
		QuitFilePath = FPaths::ConvertRelativePathToFull(Value.TrimQuotes());
		// Any file left over from a previous run would stop this one before it started.
		IFileManager::Get().Delete(*QuitFilePath, false, true, true);
	}

	UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (Subsystem == nullptr)
	{
		DC_LOG(Error, TEXT("no UDCSubsystem on this game instance - nothing will arrive"));
		return;
	}

	Subsystem->OnSlotActive.AddUObject(this, &ADCRuntimeGameMode::OnSlotActive);
	Subsystem->OnSlotFallback.AddUObject(this, &ADCRuntimeGameMode::OnSlotFallback);
	Subsystem->Start();

	DC_LOG(Log, TEXT("slots in map: %d   auto-shot=%s tour=%s dir=%s   run_seconds=%.0f"),
		Subsystem->GetSlots().Num(), bAutoShot ? TEXT("yes") : TEXT("no"),
		bTour ? TEXT("yes") : TEXT("no"),
		ShotDir.IsEmpty() ? TEXT("(none)") : *ShotDir, RunSeconds);

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

// ===================================================================== the scripted tour

void ADCRuntimeGameMode::BuildTour()
{
	Tour.Reset();
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	const int32 SlotCount = Subsystem ? Subsystem->GetSlots().Num() : 0;

	auto Add = [this](ETourKind Kind, float Seconds, int32 Index, const FString& Label)
	{
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
	DC_LOG(Log, TEXT("TOUR  %d action(s) over %d slot(s)"), Tour.Num(), SlotCount);
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

void ADCRuntimeGameMode::SetSpringArm(float Length)
{
	if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		if (APawn* Pawn = PC->GetPawn())
		{
			if (USpringArmComponent* Arm = Pawn->FindComponentByClass<USpringArmComponent>())
			{
				Arm->TargetArmLength = Length;
			}
		}
	}
}

void ADCRuntimeGameMode::TourShot(const FString& Label)
{
	++ShotCount;
	const FString Name = TwoDigits(ShotCount) + TEXT("_") + Label + TEXT(".png");
	const FString Path = ShotDir / Name;
	FScreenshotRequest::RequestScreenshot(Path, false, false);
	LastShotSeconds = FPlatformTime::Seconds();
	DC_LOG(Log, TEXT("SHOT  %s"), *Path);
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
		DC_LOG(Log, TEXT("TOUR  done"));
		Finish();
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
		FrameMs.Add(DeltaSeconds * 1000.0f);
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
	W->WriteValue(TEXT("shots"), ShotCount);
	W->WriteValue(TEXT("seconds"), FPlatformTime::Seconds() - StartSeconds);

	W->WriteObjectStart(TEXT("frame_ms"));
	W->WriteValue(TEXT("frames"), Sorted.Num());
	W->WriteValue(TEXT("average"), Average);
	W->WriteValue(TEXT("median"), Median);
	W->WriteValue(TEXT("worst_1_percent"), Worst1);
	W->WriteValue(TEXT("worst"), Worst);
	W->WriteValue(TEXT("average_fps"), Average > 0.0f ? 1000.0f / Average : 0.0f);
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

	DC_LOG(Log, TEXT("---------------- run done after %.0f s, %d shot(s) ----------------"),
		FPlatformTime::Seconds() - StartSeconds, ShotCount);

	// A headless run must not leave anything running.
	DC_LOG(Log, TEXT("requesting exit"));
	FPlatformMisc::RequestExit(false, TEXT("DCRuntime complete"));
}
