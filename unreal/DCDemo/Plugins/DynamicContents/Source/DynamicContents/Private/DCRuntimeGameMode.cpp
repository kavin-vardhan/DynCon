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
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
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
}

ADCRuntimeGameMode::ADCRuntimeGameMode()
{
	// No character content is in this project (the mannequin pack was deliberately not
	// copied in), and nothing here needs one: a DefaultPawn walks the bounds boxes.
	DefaultPawnClass = ADefaultPawn::StaticClass();
	HUDClass = ADCStatusHud::StaticClass();
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
		if (ShotDir.IsEmpty())
		{
			ShotDir = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("DCShots"));
			IFileManager::Get().MakeDirectory(*ShotDir, true);
		}
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

	DC_LOG(Log, TEXT("slots in map: %d   auto-shot=%s dir=%s   run_seconds=%.0f"),
		Subsystem->GetSlots().Num(), bAutoShot ? TEXT("yes") : TEXT("no"),
		ShotDir.IsEmpty() ? TEXT("(none)") : *ShotDir, RunSeconds);

	if (bAutoShot)
	{
		// One camera actor, moved from slot to slot, so every picture is framed the same way.
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
				// Nothing moves on its own during an automated run.
				PC->SetIgnoreMoveInput(true);
				PC->SetIgnoreLookInput(true);
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

	for (TActorIterator<ADCContentActor> It(GetWorld()); It; ++It)
	{
		if (Slot.IsPointInsideBounds(It->GetActorLocation()))
		{
			const FBox Bounds = It->GetBuiltBounds();
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
			break;
		}
	}

	const FVector Forward = Slot.GetActorForwardVector().RotateAngleAxis(DCThreeQuarterYaw,
		FVector::UpVector);
	const FVector Eye = FVector(Centre.X, Centre.Y, Slot.GetActorLocation().Z) + Forward * Reach
		+ FVector(0.0f, 0.0f, Height + 220.0f);
	const FVector Look = FVector(Centre.X, Centre.Y, Slot.GetActorLocation().Z + Height);

	Cam->SetActorLocation(Eye);
	Cam->SetActorRotation((Look - Eye).Rotation());

	DC_LOG(Log, TEXT("VIEW  slot %s: camera at %s looking at %s (reach %.0f)"),
		*Slot.SlotId.ToString(), *Eye.ToCompactString(), *Look.ToCompactString(), Reach);
}

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

	DC_LOG(Log, TEXT("---------------- run done after %.0f s, %d shot(s) ----------------"),
		FPlatformTime::Seconds() - StartSeconds, ShotCount);

	// A headless run must not leave anything running.
	DC_LOG(Log, TEXT("requesting exit"));
	FPlatformMisc::RequestExit(false, TEXT("DCRuntime complete"));
}
