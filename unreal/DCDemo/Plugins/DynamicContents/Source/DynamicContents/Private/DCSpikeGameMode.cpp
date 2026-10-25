#include "DCSpikeGameMode.h"

#include "DCContentActor.h"
#include "DCPackMounter.h"
#include "DCSlot.h"
#include "DynamicContents.h"

#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/DefaultPawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformTime.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "HAL/PlatformProcess.h"
#include "TimerManager.h"
#include "UnrealClient.h"

namespace
{
	const TCHAR* DCBuildConfigName()
	{
#if UE_BUILD_DEBUG
		return TEXT("Debug");
#elif UE_BUILD_DEVELOPMENT
		return TEXT("Development");
#elif UE_BUILD_TEST
		return TEXT("Test");
#else
		return TEXT("Shipping");
#endif
	}

	/** "<dir>/<pack name>" -> "/Game/DCContent/<pack name>/BP_DC_<pack name>.BP_DC_<pack name>_C" */
	FString DefaultClassPathFor(const FString& PackDir)
	{
		FString Name = FPaths::GetCleanFilename(PackDir);
		if (Name.IsEmpty())
		{
			Name = FPaths::GetCleanFilename(FPaths::GetPath(PackDir));
		}
		return FString::Printf(TEXT("/Game/DCContent/%s/BP_DC_%s.BP_DC_%s_C"), *Name, *Name, *Name);
	}

	/** Seconds the spike waits: let the world settle, then let the frame with the content render. */
	constexpr float DCFirstStepDelay = 2.0f;
	constexpr float DCSpawnToShotDelay = 1.5f;
	constexpr float DCShotToNextDelay = 1.5f;
}

ADCSpikeGameMode::ADCSpikeGameMode()
{
	// No character content is needed for the spike; the view is driven by a camera actor.
	DefaultPawnClass = ADefaultPawn::StaticClass();
}

void ADCSpikeGameMode::BeginPlay()
{
	Super::BeginPlay();

	RunStart = FPlatformTime::Seconds();

	UE_LOG(LogDC, Log, TEXT("================ DC pack round-trip spike ================"));
	UE_LOG(LogDC, Log, TEXT("build=%s  exe=%s"), DCBuildConfigName(), FPlatformProcess::ExecutablePath());
	UE_LOG(LogDC, Log, TEXT("cmdline=%s"), FCommandLine::Get());
	UE_LOG(LogDC, Log, TEXT("project dir=%s"), *FPaths::ConvertRelativePathToFull(FPaths::ProjectDir()));

	ParseCommandLine();

	// Slots are shipped with the map.
	for (TActorIterator<ADCSlot> It(GetWorld()); It; ++It)
	{
		Slots.Add(*It);
	}
	Slots.Sort([](const TWeakObjectPtr<ADCSlot>& A, const TWeakObjectPtr<ADCSlot>& B)
	{
		const int32 OrderA = A.IsValid() ? A->FillOrder : MAX_int32;
		const int32 OrderB = B.IsValid() ? B->FillOrder : MAX_int32;
		return OrderA < OrderB;
	});

	UE_LOG(LogDC, Log, TEXT("slots in map: %d"), Slots.Num());
	for (const TWeakObjectPtr<ADCSlot>& Slot : Slots)
	{
		if (Slot.IsValid())
		{
			const FVector Limits = Slot->GetClassLimits();
			UE_LOG(LogDC, Log, TEXT("  slot '%s' order=%d class limits=%.0fx%.0fx%.0f cm at %s"),
				*Slot->SlotId.ToString(), Slot->FillOrder, Limits.X, Limits.Y, Limits.Z,
				*Slot->GetActorLocation().ToCompactString());
		}
	}

	// Proof that the content is not in this build: the packages must not resolve yet.
	for (const FDCSpikeStep& Step : Steps)
	{
		FString PackageName = Step.ClassPath;
		int32 Dot = INDEX_NONE;
		if (PackageName.FindChar(TEXT('.'), Dot))
		{
			PackageName.LeftInline(Dot);
		}
		const bool bExists = FPackageName::DoesPackageExist(PackageName);
		UE_LOG(LogDC, Log, TEXT("PRECHECK before any mount: package '%s' exists=%s"),
			*PackageName, bExists ? TEXT("YES (unexpected!)") : TEXT("no"));
		// Written to the result file too: in a Shipping build UE_LOG is compiled out, and
		// this line is the proof that the build does not already contain the content.
		Report.Add(FString::Printf(TEXT("precheck  package=%s  in_build_before_mount=%s"),
			*PackageName, bExists ? TEXT("YES (unexpected!)") : TEXT("no")));
	}

	if (Steps.Num() == 0)
	{
		UE_LOG(LogDC, Error, TEXT("nothing to do: pass -DCSpikeMount=<pack dir>[;<class path>][+...]"));
		Finish();
		return;
	}

	GetWorldTimerManager().SetTimer(Timer, this, &ADCSpikeGameMode::Begin, DCFirstStepDelay, false);
}

void ADCSpikeGameMode::ParseCommandLine()
{
	const TCHAR* CmdLine = FCommandLine::Get();

	FString Spec;
	if (FParse::Value(CmdLine, TEXT("DCSpikeMount="), Spec, false))
	{
		TArray<FString> Pairs;
		Spec.ParseIntoArray(Pairs, TEXT("+"), true);
		for (const FString& Pair : Pairs)
		{
			FDCSpikeStep Step;
			FString Left;
			FString Right;
			if (Pair.Split(TEXT(";"), &Left, &Right))
			{
				Step.PackDir = Left.TrimQuotes();
				Step.ClassPath = Right.TrimQuotes();
			}
			else
			{
				Step.PackDir = Pair.TrimQuotes();
				Step.ClassPath = DefaultClassPathFor(Step.PackDir);
			}
			Step.PackDir = FPaths::ConvertRelativePathToFull(Step.PackDir);
			Steps.Add(Step);
		}
	}

	if (!FParse::Value(CmdLine, TEXT("DCSpikeShotDir="), ShotDir, false) || ShotDir.IsEmpty())
	{
		ShotDir = FPaths::ProjectSavedDir() / TEXT("DCSpike");
	}
	ShotDir = FPaths::ConvertRelativePathToFull(ShotDir.TrimQuotes());
	IFileManager::Get().MakeDirectory(*ShotDir, true);

	UE_LOG(LogDC, Log, TEXT("steps=%d  shot dir=%s"), Steps.Num(), *ShotDir);
	for (int32 i = 0; i < Steps.Num(); ++i)
	{
		UE_LOG(LogDC, Log, TEXT("  step %d: pack='%s'  class='%s'"), i + 1, *Steps[i].PackDir, *Steps[i].ClassPath);
	}
}

void ADCSpikeGameMode::Begin()
{
	// One camera actor, moved from slot to slot, so the screenshots are deterministic.
	if (UWorld* World = GetWorld())
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		ACameraActor* Cam = World->SpawnActor<ACameraActor>(ACameraActor::StaticClass(), FTransform::Identity, Params);
		Camera = Cam;

		if (Cam && Cam->GetCameraComponent())
		{
			Cam->GetCameraComponent()->SetFieldOfView(75.0f);
		}
		if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
		{
			if (Cam)
			{
				PC->SetViewTargetWithBlend(Cam, 0.0f);
			}
			// Nothing should move on its own during the spike.
			PC->SetIgnoreMoveInput(true);
			PC->SetIgnoreLookInput(true);
		}
	}

	StepIndex = 0;
	RunStep();
}

void ADCSpikeGameMode::RunStep()
{
	if (!Steps.IsValidIndex(StepIndex))
	{
		Finish();
		return;
	}

	const FDCSpikeStep& Step = Steps[StepIndex];
	ADCSlot* Slot = Slots.IsValidIndex(StepIndex) && Slots[StepIndex].IsValid() ? Slots[StepIndex].Get() : nullptr;

	UE_LOG(LogDC, Log, TEXT("---------------- step %d/%d: %s -> slot '%s' ----------------"),
		StepIndex + 1, Steps.Num(), *FPaths::GetCleanFilename(Step.PackDir),
		Slot ? *Slot->SlotId.ToString() : TEXT("<none>"));

	// 1. mount
	const FDCMountResult Mount = UDCPackMounter::MountPackDir(Step.PackDir);

	// 2. load the class out of the pack
	float LoadMs = 0.0f;
	UClass* ContentClass = nullptr;
	if (Mount.bMounted)
	{
		FString PackageName = Step.ClassPath;
		int32 Dot = INDEX_NONE;
		if (PackageName.FindChar(TEXT('.'), Dot))
		{
			PackageName.LeftInline(Dot);
		}
		UE_LOG(LogDC, Log, TEXT("LOAD  package '%s' exists after mount=%s"),
			*PackageName, FPackageName::DoesPackageExist(PackageName) ? TEXT("yes") : TEXT("NO"));

		const double T0 = FPlatformTime::Seconds();
		ContentClass = StaticLoadClass(AActor::StaticClass(), nullptr, *Step.ClassPath, nullptr, LOAD_None, nullptr);
		LoadMs = DCElapsedMs(T0);

		if (ContentClass)
		{
			UE_LOG(LogDC, Log, TEXT("LOAD ok      %s in %.1f ms"), *ContentClass->GetPathName(), LoadMs);
		}
		else
		{
			UE_LOG(LogDC, Error, TEXT("LOAD FAIL    %s after %.1f ms"), *Step.ClassPath, LoadMs);
		}
	}

	// 3. spawn it at the slot (BeginPlay builds the piece out of its sockets)
	float SpawnMs = 0.0f;
	AActor* Spawned = nullptr;
	if (ContentClass && Slot)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

		const double T0 = FPlatformTime::Seconds();
		Spawned = GetWorld()->SpawnActor<AActor>(ContentClass, Slot->GetContentTransform(), Params);
		SpawnMs = DCElapsedMs(T0);

		if (Spawned)
		{
			UE_LOG(LogDC, Log, TEXT("SPAWN ok     %s at %s yaw=%.0f in %.1f ms"),
				*Spawned->GetName(), *Spawned->GetActorLocation().ToCompactString(),
				Spawned->GetActorRotation().Yaw, SpawnMs);

			if (const ADCContentActor* Content = Cast<ADCContentActor>(Spawned))
			{
				const FBox Bounds = Content->GetBuiltBounds();
				const FVector Limits = Slot->GetClassLimits();
				const FVector Size = Bounds.IsValid ? Bounds.GetSize() : FVector::ZeroVector;
				const bool bFits = Size.X <= Limits.X + 1.0f && Size.Y <= Limits.Y + 1.0f && Size.Z <= Limits.Z + 1.0f;
				UE_LOG(LogDC, Log, TEXT("FIT   content %.0fx%.0fx%.0f cm in slot %.0fx%.0fx%.0f cm -> %s"),
					Size.X, Size.Y, Size.Z, Limits.X, Limits.Y, Limits.Z, bFits ? TEXT("fits") : TEXT("DOES NOT FIT"));

				Report.Add(FString::Printf(TEXT("step %d  built     %s"), StepIndex + 1, *Content->DescribeBuild()));
				Report.Add(FString::Printf(
					TEXT("step %d  fit       content %.0fx%.0fx%.0f cm in slot class %.0fx%.0fx%.0f cm -> %s"),
					StepIndex + 1, Size.X, Size.Y, Size.Z, Limits.X, Limits.Y, Limits.Z,
					bFits ? TEXT("fits") : TEXT("DOES NOT FIT")));
			}
		}
		else
		{
			UE_LOG(LogDC, Error, TEXT("SPAWN FAIL   %s"), *Step.ClassPath);
		}
	}

	if (Slot)
	{
		PointCameraAt(*Slot);
	}

	Report.Add(FString::Printf(
		TEXT("step %d  pack=%s  slot=%s  mount=%s(%s, %.1f ms)  shaders=%s(%.1f ms)  ")
		TEXT("load=%s(%.1f ms)  spawn=%s(%.1f ms)  pak=%lld B  utoc=%lld B  ucas=%lld B  mountpoint=%s"),
		StepIndex + 1, *FPaths::GetCleanFilename(Step.PackDir),
		Slot ? *Slot->SlotId.ToString() : TEXT("none"),
		Mount.bMounted ? TEXT("ok") : TEXT("FAIL"), *Mount.Api, Mount.Milliseconds,
		Mount.bShaderLibraryOpened ? TEXT("ok") : TEXT("none"), Mount.ShaderLibraryMilliseconds,
		ContentClass ? TEXT("ok") : TEXT("FAIL"), LoadMs,
		Spawned ? TEXT("ok") : TEXT("FAIL"), SpawnMs,
		Mount.PakBytes, Mount.UtocBytes, Mount.UcasBytes, *Mount.MountPoint));

	GetWorldTimerManager().SetTimer(Timer, this, &ADCSpikeGameMode::TakeShot, DCSpawnToShotDelay, false);
}

void ADCSpikeGameMode::PointCameraAt(const ADCSlot& Slot)
{
	if (!Camera.IsValid())
	{
		return;
	}

	// Content faces the slot's +X once the slot's yaw offset is applied, so stand off along +X.
	const FVector SlotLoc = Slot.GetActorLocation();
	const FVector Forward = Slot.GetActorForwardVector();
	const FVector Eye = SlotLoc + Forward * Slot.ViewDistance + FVector(0.0f, 0.0f, Slot.ViewHeight);
	const FVector Look = SlotLoc + FVector(0.0f, 0.0f, Slot.ViewHeight * 0.55f);

	Camera->SetActorLocation(Eye);
	Camera->SetActorRotation((Look - Eye).Rotation());

	UE_LOG(LogDC, Log, TEXT("VIEW  camera at %s looking at %s"),
		*Eye.ToCompactString(), *Look.ToCompactString());
}

void ADCSpikeGameMode::TakeShot()
{
	const FString Name = FString::Printf(TEXT("%02d_%s.png"), StepIndex + 1,
		*FPaths::GetCleanFilename(Steps[StepIndex].PackDir));
	const FString Path = ShotDir / Name;

	FScreenshotRequest::RequestScreenshot(Path, false, false);
	UE_LOG(LogDC, Log, TEXT("SHOT  requested %s"), *Path);

	Report.Add(FString::Printf(TEXT("step %d  shot=%s"), StepIndex + 1, *Path));

	// Give the renderer the frames it needs to write the file before moving on.
	++StepIndex;
	if (Steps.IsValidIndex(StepIndex))
	{
		GetWorldTimerManager().SetTimer(Timer, this, &ADCSpikeGameMode::RunStep, DCShotToNextDelay, false);
	}
	else
	{
		GetWorldTimerManager().SetTimer(Timer, this, &ADCSpikeGameMode::Finish, DCShotToNextDelay, false);
	}
}

void ADCSpikeGameMode::Finish()
{
	const float TotalMs = DCElapsedMs(RunStart);

	UE_LOG(LogDC, Log, TEXT("---------------- spike done in %.0f ms ----------------"), TotalMs);
	for (const FString& Line : Report)
	{
		UE_LOG(LogDC, Log, TEXT("%s"), *Line);
	}

	FString Text = FString::Printf(TEXT("DC pack round-trip spike\nbuild=%s\ntotal_ms=%.0f\n"),
		DCBuildConfigName(), TotalMs);
	for (const FString& Line : Report)
	{
		Text += Line + TEXT("\n");
	}
	const FString ResultPath = ShotDir / TEXT("spike_result.txt");
	FFileHelper::SaveStringToFile(Text, *ResultPath);
	UE_LOG(LogDC, Log, TEXT("wrote %s"), *ResultPath);

	// A headless run must not leave anything running.
	UE_LOG(LogDC, Log, TEXT("requesting exit"));
	FPlatformMisc::RequestExit(false, TEXT("DCSpike complete"));
}
