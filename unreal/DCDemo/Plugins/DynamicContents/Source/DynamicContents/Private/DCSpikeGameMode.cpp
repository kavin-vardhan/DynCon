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
#include "HAL/PlatformProcess.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformTime.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
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

	FString PackageNameOf(const FString& ClassPath)
	{
		FString PackageName = ClassPath;
		int32 Dot = INDEX_NONE;
		if (PackageName.FindChar(TEXT('.'), Dot))
		{
			PackageName.LeftInline(Dot);
		}
		return PackageName;
	}

	// Seconds the run waits at each point. The generous ones are after the camera moves:
	// Lumen and the virtual shadow maps need a handful of frames to settle after a dozen new
	// shadow-casting lights appear, and a screenshot taken too early is a dark, noisy picture
	// rather than a missing one - which is the sort of failure that gets believed.
	constexpr float DCFirstStepDelay = 2.0f;
	constexpr float DCSpawnToShotDelay = 1.6f;
	constexpr float DCShotToMoveDelay = 1.0f;
	constexpr float DCMoveToShotDelay = 1.6f;
	constexpr float DCShotToNextDelay = 1.0f;

	/** Eye height above SOCKET_Inside, centimetres: where a standing visitor's head is. */
	constexpr float DCEyeHeight = 165.0f;

	/** How far round from straight-on the outside shot stands, degrees. */
	constexpr float DCThreeQuarterYaw = 32.0f;

	/** Horizontal field of view. Wider inside, where there is nowhere to step back to. */
	constexpr float DCOutsideFov = 75.0f;
	constexpr float DCInsideFov = 95.0f;
}

ADCSpikeGameMode::ADCSpikeGameMode()
{
	// No character content is needed for the spike; the view is driven by a camera actor.
	DefaultPawnClass = ADefaultPawn::StaticClass();
}

bool ADCSpikeGameMode::RedirectToRequestedMap()
{
	FString Wanted;
	if (!FParse::Value(FCommandLine::Get(), TEXT("DCMap="), Wanted, false) || Wanted.IsEmpty())
	{
		return false;
	}
	Wanted = Wanted.TrimQuotes();

	// Already there: never travel in a circle if the target map's own game mode override
	// failed to take and we ended up back in this one.
	const FString Here = FPaths::GetBaseFilename(GetWorld()->GetMapName());
	const FString There = FPaths::GetBaseFilename(Wanted);
	if (Here.EndsWith(There))
	{
		DC_LOG(Warning, TEXT("-DCMap=%s but this map IS %s and it is still running the spike "
			"game mode - the map's GameMode Override did not take"), *Wanted, *Here);
		return false;
	}

	DC_LOG(Log, TEXT("-DCMap=%s: travelling there (this build is Shipping, and a Shipping build "
		"ignores a map named on the command line - see unreal\\README.md)"), *Wanted);
	UGameplayStatics::OpenLevel(this, FName(*Wanted), true,
		TEXT("game=/Script/DynamicContents.DCRuntimeGameMode"));
	return true;
}

void ADCSpikeGameMode::BeginPlay()
{
	Super::BeginPlay();

	// The one job this game mode has before its own: a Shipping build throws away the map
	// named on the command line (UGameInstance::StartGameInstance, guarded by
	// UE_ALLOW_MAP_OVERRIDE_IN_SHIPPING, which an installed engine cannot be made to define),
	// so every run starts in GameDefaultMap - the spike map. -DCMap= travels out of it, which
	// is a client travel and is not gated. A run with no -DCMap is brief 006's run, unchanged.
	if (RedirectToRequestedMap())
	{
		return;
	}

	RunStart = FPlatformTime::Seconds();

	DC_LOG(Log, TEXT("================ DC pack round-trip run ================"));
	DC_LOG(Log, TEXT("build=%s  exe=%s"), DCBuildConfigName(), FPlatformProcess::ExecutablePath());
	DC_LOG(Log, TEXT("cmdline=%s"), FCommandLine::Get());
	DC_LOG(Log, TEXT("project dir=%s"), *FPaths::ConvertRelativePathToFull(FPaths::ProjectDir()));
	DC_LOG(Log, TEXT("file log=%s"), *FDCFileLog::Get().GetPath());

	ApplyCvarOverrides();
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

	DC_LOG(Log, TEXT("slots in map: %d"), Slots.Num());
	for (const TWeakObjectPtr<ADCSlot>& Slot : Slots)
	{
		if (Slot.IsValid())
		{
			const FVector Limits = Slot->GetClassLimits();
			DC_LOG(Log, TEXT("  slot '%s' order=%d class=%s limits=%.0fx%.0fx%.0f cm at %s"),
				*Slot->SlotId.ToString(), Slot->FillOrder, *Slot->GetSizeClassName(),
				Limits.X, Limits.Y, Limits.Z, *Slot->GetActorLocation().ToCompactString());
		}
	}

	// Proof that the content is not in this build: the packages must not resolve yet.
	for (const FDCSpikeStep& Step : Steps)
	{
		const FString PackageName = PackageNameOf(Step.ClassPath);
		const bool bExists = FPackageName::DoesPackageExist(PackageName);
		DC_LOG(Log, TEXT("PRECHECK before any mount: package '%s' exists=%s"),
			*PackageName, bExists ? TEXT("YES (unexpected!)") : TEXT("no"));
		Report.Add(FString::Printf(TEXT("precheck  package=%s  in_build_before_mount=%s"),
			*PackageName, bExists ? TEXT("YES (unexpected!)") : TEXT("no")));
	}

	if (Steps.Num() == 0)
	{
		DC_LOG(Error, TEXT("nothing to do: pass -DCSpikeMount=<pack dir>[;<class path>[;<size class>]][+...]"));
		Finish();
		return;
	}

	GetWorldTimerManager().SetTimer(Timer, this, &ADCSpikeGameMode::Begin, DCFirstStepDelay, false);
}

void ADCSpikeGameMode::ApplyCvarOverrides()
{
	FString Spec;
	if (!FParse::Value(FCommandLine::Get(), TEXT("DCCvars="), Spec, false) || Spec.IsEmpty())
	{
		return;
	}

	TArray<FString> Pairs;
	Spec.TrimQuotes().ParseIntoArray(Pairs, TEXT(","), true);
	for (const FString& Pair : Pairs)
	{
		FString Name;
		FString Value;
		if (!Pair.Split(TEXT("="), &Name, &Value))
		{
			DC_LOG(Warning, TEXT("CVAR  '%s' is not name=value, ignored"), *Pair);
			continue;
		}
		Name.TrimStartAndEndInline();
		Value.TrimStartAndEndInline();

		IConsoleVariable* Var = IConsoleManager::Get().FindConsoleVariable(*Name);
		if (Var == nullptr)
		{
			DC_LOG(Warning, TEXT("CVAR  '%s' does not exist in this build"), *Name);
			continue;
		}
		const FString Before = Var->GetString();
		Var->Set(*Value, ECVF_SetByCommandline);
		DC_LOG(Log, TEXT("CVAR  %s: %s -> %s"), *Name, *Before, *Var->GetString());
	}
}

void ADCSpikeGameMode::ParseCommandLine()
{
	const TCHAR* CmdLine = FCommandLine::Get();

	FString Spec;
	if (FParse::Value(CmdLine, TEXT("DCSpikeMount="), Spec, false))
	{
		TArray<FString> Entries;
		Spec.ParseIntoArray(Entries, TEXT("+"), true);
		for (const FString& Entry : Entries)
		{
			TArray<FString> Fields;
			Entry.ParseIntoArray(Fields, TEXT(";"), false);

			FDCSpikeStep Step;
			Step.PackDir = Fields.IsValidIndex(0) ? Fields[0].TrimQuotes() : FString();
			Step.ClassPath = Fields.IsValidIndex(1) && !Fields[1].IsEmpty()
				? Fields[1].TrimQuotes() : DefaultClassPathFor(Step.PackDir);
			Step.SizeClass = Fields.IsValidIndex(2) ? Fields[2].TrimQuotes().ToUpper() : FString();
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

	DC_LOG(Log, TEXT("steps=%d  shot dir=%s"), Steps.Num(), *ShotDir);
	for (int32 i = 0; i < Steps.Num(); ++i)
	{
		DC_LOG(Log, TEXT("  step %d: pack='%s'  class='%s'  size='%s'"),
			i + 1, *Steps[i].PackDir, *Steps[i].ClassPath,
			Steps[i].SizeClass.IsEmpty() ? TEXT("(any)") : *Steps[i].SizeClass);
	}
}

void ADCSpikeGameMode::Begin()
{
	// One camera actor, moved from shot to shot, so the screenshots are deterministic.
	if (UWorld* World = GetWorld())
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		ACameraActor* Cam = World->SpawnActor<ACameraActor>(ACameraActor::StaticClass(), FTransform::Identity, Params);
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
			// Nothing should move on its own during the run.
			PC->SetIgnoreMoveInput(true);
			PC->SetIgnoreLookInput(true);
		}
	}

	StepIndex = 0;
	RunStep();
}

ADCSlot* ADCSpikeGameMode::PickSlot(const FString& SizeClass) const
{
	ADCSlot* Fallback = nullptr;
	for (const TWeakObjectPtr<ADCSlot>& Weak : Slots)
	{
		ADCSlot* Slot = Weak.Get();
		if (Slot == nullptr)
		{
			continue;
		}
		if (Fallback == nullptr)
		{
			Fallback = Slot;
		}
		if (!SizeClass.IsEmpty() && Slot->GetSizeClassName().Equals(SizeClass, ESearchCase::IgnoreCase))
		{
			return Slot;
		}
	}
	return Fallback;
}

void ADCSpikeGameMode::RunStep()
{
	if (!Steps.IsValidIndex(StepIndex))
	{
		Finish();
		return;
	}

	StepShots.Reset();

	const FDCSpikeStep& Step = Steps[StepIndex];
	const FString PackName = FPaths::GetCleanFilename(Step.PackDir);
	ADCSlot* Slot = PickSlot(Step.SizeClass);

	DC_LOG(Log, TEXT("---------------- step %d/%d: %s (class %s) -> slot '%s' ----------------"),
		StepIndex + 1, Steps.Num(), *PackName,
		Step.SizeClass.IsEmpty() ? TEXT("any") : *Step.SizeClass,
		Slot ? *Slot->SlotId.ToString() : TEXT("<none>"));

	// 1. mount
	const FDCMountResult Mount = UDCPackMounter::MountPackDir(Step.PackDir);

	// 2. load the class out of the pack
	float LoadMs = 0.0f;
	UClass* ContentClass = nullptr;
	if (Mount.bMounted)
	{
		const FString PackageName = PackageNameOf(Step.ClassPath);
		DC_LOG(Log, TEXT("LOAD  package '%s' exists after mount=%s"),
			*PackageName, FPackageName::DoesPackageExist(PackageName) ? TEXT("yes") : TEXT("NO"));

		const double T0 = FPlatformTime::Seconds();
		ContentClass = StaticLoadClass(AActor::StaticClass(), nullptr, *Step.ClassPath, nullptr, LOAD_None, nullptr);
		LoadMs = DCElapsedMs(T0);

		if (ContentClass)
		{
			DC_LOG(Log, TEXT("LOAD ok      %s in %.1f ms"), *ContentClass->GetPathName(), LoadMs);
		}
		else
		{
			DC_LOG(Error, TEXT("LOAD FAIL    %s after %.1f ms"), *Step.ClassPath, LoadMs);
		}
	}

	// 3. spawn it at the slot (BeginPlay builds the piece out of its sockets)
	float SpawnMs = 0.0f;
	AActor* Actor = nullptr;
	bool bFits = false;
	FVector Size = FVector::ZeroVector;
	FVector Limits = FVector::ZeroVector;
	if (ContentClass && Slot)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

		const double T0 = FPlatformTime::Seconds();
		Actor = GetWorld()->SpawnActor<AActor>(ContentClass, Slot->GetContentTransform(), Params);
		SpawnMs = DCElapsedMs(T0);
		Spawned = Actor;

		if (Actor)
		{
			DC_LOG(Log, TEXT("SPAWN ok     %s at %s yaw=%.0f in %.1f ms"),
				*Actor->GetName(), *Actor->GetActorLocation().ToCompactString(),
				Actor->GetActorRotation().Yaw, SpawnMs);

			if (const ADCContentActor* Content = Cast<ADCContentActor>(Actor))
			{
				const FBox Bounds = Content->GetBuiltBounds();
				Limits = Slot->GetClassLimits();
				Size = Bounds.IsValid ? Bounds.GetSize() : FVector::ZeroVector;
				bFits = Size.X <= Limits.X + 1.0f && Size.Y <= Limits.Y + 1.0f && Size.Z <= Limits.Z + 1.0f;
				DC_LOG(Log, TEXT("FIT   content %.0fx%.0fx%.0f cm in slot %.0fx%.0fx%.0f cm -> %s"),
					Size.X, Size.Y, Size.Z, Limits.X, Limits.Y, Limits.Z,
					bFits ? TEXT("fits") : TEXT("DOES NOT FIT"));

				Report.Add(FString::Printf(TEXT("step %d  built     %s"), StepIndex + 1, *Content->DescribeBuild()));
			}
		}
		else
		{
			DC_LOG(Error, TEXT("SPAWN FAIL   %s"), *Step.ClassPath);
		}
	}

	if (Actor != nullptr && bFits)
	{
		++StepsOk;
	}

	Report.Add(FString::Printf(
		TEXT("step %d  pack=%s  slot=%s(%s)  mount=%s(%s, %.1f ms)  shaders=%s(%.1f ms)  ")
		TEXT("load=%s(%.1f ms)  spawn=%s(%.1f ms)  size=%.0fx%.0fx%.0f cm  limits=%.0fx%.0fx%.0f cm  ")
		TEXT("fit=%s  pak=%lld B  utoc=%lld B  ucas=%lld B  total=%lld B"),
		StepIndex + 1, *PackName,
		Slot ? *Slot->SlotId.ToString() : TEXT("none"),
		Slot ? *Slot->GetSizeClassName() : TEXT("-"),
		Mount.bMounted ? TEXT("ok") : TEXT("FAIL"), *Mount.Api, Mount.Milliseconds,
		Mount.bShaderLibraryOpened ? TEXT("ok") : TEXT("none"), Mount.ShaderLibraryMilliseconds,
		ContentClass ? TEXT("ok") : TEXT("FAIL"), LoadMs,
		Actor ? TEXT("ok") : TEXT("FAIL"), SpawnMs,
		Size.X, Size.Y, Size.Z, Limits.X, Limits.Y, Limits.Z,
		bFits ? TEXT("yes") : TEXT("NO"),
		Mount.PakBytes, Mount.UtocBytes, Mount.UcasBytes,
		Mount.PakBytes + Mount.UtocBytes + Mount.UcasBytes));

	if (Slot)
	{
		PointCameraOutside(*Slot, Actor);
	}

	GetWorldTimerManager().SetTimer(Timer, this, &ADCSpikeGameMode::TakeOutsideShot, DCSpawnToShotDelay, false);
}

void ADCSpikeGameMode::PointCameraOutside(const ADCSlot& Slot, const AActor* Content, float Zoom)
{
	if (!Camera.IsValid())
	{
		return;
	}

	// Frame what is actually there, not what the slot's class allows: a small piece in a large
	// slot would otherwise sit in the middle of an empty picture.
	FVector Centre = Slot.GetActorLocation();
	float Height = Slot.ViewHeight;
	float Reach = Slot.ViewDistance;

	if (const ADCContentActor* Built = Cast<ADCContentActor>(Content))
	{
		const FBox Bounds = Built->GetBuiltBounds();
		if (Bounds.IsValid)
		{
			Centre = Bounds.GetCenter();
			const FVector Extent = Bounds.GetExtent();
			Height = Bounds.Max.Z * 0.62f;
			// Stand off far enough that the piece fits inside a 75 degree frame and close
			// enough that it fills most of it: the frame is 16:9, so height is the binding
			// constraint on everything taller than it is wide (the T class especially).
			Reach = FMath::Max(Extent.Size2D() * 1.7f, Bounds.GetSize().Z * 1.5f) + 200.0f;
		}
	}

	Reach *= FMath::Max(Zoom, 0.05f);
	SetCameraFov(DCOutsideFov);

	// Three-quarter: swing round from the slot's forward so the front and one side both show.
	const FVector Forward = Slot.GetActorForwardVector().RotateAngleAxis(DCThreeQuarterYaw, FVector::UpVector);
	// The eye stays at the piece's own height whatever the zoom: dropping it with the zoom
	// put the close-up of a low, wide piece underneath its own roof.
	const FVector Eye = FVector(Centre.X, Centre.Y, Slot.GetActorLocation().Z) + Forward * Reach
		+ FVector(0.0f, 0.0f, Height + 220.0f);
	const FVector Look = FVector(Centre.X, Centre.Y, Slot.GetActorLocation().Z + Height);

	Camera->SetActorLocation(Eye);
	Camera->SetActorRotation((Look - Eye).Rotation());

	DC_LOG(Log, TEXT("VIEW  outside: camera at %s looking at %s (reach %.0f, zoom %.2f)"),
		*Eye.ToCompactString(), *Look.ToCompactString(), Reach, Zoom);
}

bool ADCSpikeGameMode::PointCameraInside(const ADCContentActor& Content)
{
	if (!Camera.IsValid())
	{
		return false;
	}

	FTransform Inside;
	if (!Content.GetSocketWorldTransform(TEXT("Inside"), Inside))
	{
		DC_LOG(Warning, TEXT("VIEW  inside: no SOCKET_Inside on this piece, keeping the outside view"));
		return false;
	}

	const FVector Eye = Inside.GetLocation() + FVector(0.0f, 0.0f, DCEyeHeight);

	FVector Target;
	if (!Content.GetScreenWorldLocation(Target))
	{
		// No screen (the placeholder piece): look the way the socket faces instead.
		Target = Eye + Inside.GetRotation().GetForwardVector() * 500.0f;
	}

	SetCameraFov(DCInsideFov);
	Camera->SetActorLocation(Eye);
	Camera->SetActorRotation((Target - Eye).Rotation());

	DC_LOG(Log, TEXT("VIEW  inside: camera at %s looking at %s"),
		*Eye.ToCompactString(), *Target.ToCompactString());
	return true;
}

void ADCSpikeGameMode::SetCameraFov(float Degrees)
{
	if (ACameraActor* Cam = Camera.Get())
	{
		if (UCameraComponent* Comp = Cam->GetCameraComponent())
		{
			Comp->SetFieldOfView(Degrees);
		}
	}
}

void ADCSpikeGameMode::RequestShot(const TCHAR* Suffix)
{
	const FString Name = FString::Printf(TEXT("%02d_%s_%s.png"), StepIndex + 1,
		*FPaths::GetCleanFilename(Steps[StepIndex].PackDir), Suffix);
	const FString Path = ShotDir / Name;

	FScreenshotRequest::RequestScreenshot(Path, false, false);
	StepShots.Add(Name);
	DC_LOG(Log, TEXT("SHOT  requested %s"), *Path);
}

void ADCSpikeGameMode::TakeOutsideShot()
{
	RequestShot(TEXT("out"));
	GetWorldTimerManager().SetTimer(Timer, this, &ADCSpikeGameMode::MoveCameraInside, DCShotToMoveDelay, false);
}

void ADCSpikeGameMode::MoveCameraInside()
{
	if (const ADCContentActor* Content = Cast<ADCContentActor>(Spawned.Get()))
	{
		// The placeholder piece is a closed shell with no SOCKET_Inside and nothing to see
		// inside it; a close-up of the entrance face is the honest second picture.
		if (!PointCameraInside(*Content))
		{
			if (const ADCSlot* Slot = PickSlot(Steps[StepIndex].SizeClass))
			{
				PointCameraOutside(*Slot, Content, 0.6f);
			}
		}
	}
	GetWorldTimerManager().SetTimer(Timer, this, &ADCSpikeGameMode::TakeInsideShot, DCMoveToShotDelay, false);
}

void ADCSpikeGameMode::TakeInsideShot()
{
	RequestShot(TEXT("in"));
	GetWorldTimerManager().SetTimer(Timer, this, &ADCSpikeGameMode::EndStep, DCShotToNextDelay, false);
}

void ADCSpikeGameMode::EndStep()
{
	Report.Add(FString::Printf(TEXT("step %d  shots=%s"),
		StepIndex + 1, *FString::Join(StepShots, TEXT(" "))));

	// One piece at a time: the next pack goes into the same slot, and a run that kept every
	// piece alive would end up with a hundred shadow-casting lights in one level.
	if (AActor* Actor = Spawned.Get())
	{
		Actor->Destroy();
	}
	Spawned = nullptr;

	++StepIndex;
	if (Steps.IsValidIndex(StepIndex))
	{
		RunStep();
	}
	else
	{
		Finish();
	}
}

void ADCSpikeGameMode::Finish()
{
	const float TotalMs = DCElapsedMs(RunStart);

	DC_LOG(Log, TEXT("---------------- run done in %.0f ms: %d/%d steps ok ----------------"),
		TotalMs, StepsOk, Steps.Num());
	for (const FString& Line : Report)
	{
		DC_LOG(Log, TEXT("%s"), *Line);
	}

	FString Text = FString::Printf(
		TEXT("DC pack round-trip run\nbuild=%s\ntotal_ms=%.0f\nsteps_ok=%d/%d\nlog=%s\n"),
		DCBuildConfigName(), TotalMs, StepsOk, Steps.Num(), *FDCFileLog::Get().GetPath());
	for (const FString& Line : Report)
	{
		Text += Line + TEXT("\n");
	}
	const FString ResultPath = ShotDir / TEXT("spike_result.txt");
	FFileHelper::SaveStringToFile(Text, *ResultPath);
	DC_LOG(Log, TEXT("wrote %s"), *ResultPath);

	// A headless run must not leave anything running.
	DC_LOG(Log, TEXT("requesting exit"));
	FPlatformMisc::RequestExit(false, TEXT("DCSpike complete"));
}
