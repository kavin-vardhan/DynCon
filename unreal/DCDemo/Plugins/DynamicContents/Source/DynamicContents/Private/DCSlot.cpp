#include "DCSlot.h"

#include "DCContentActor.h"
#include "DCStateStore.h"
#include "DCSubsystem.h"
#include "DynamicContents.h"

#include "Components/BoxComponent.h"
#include "Components/SceneComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/Pawn.h"
#include "HAL/PlatformTime.h"

namespace
{
	/**
	 * Telemetry: a view is content on screen, within 30 m of the piece's own bounds, for at
	 * least a second (demo plan v6 §9).
	 */
	constexpr float DCViewRadius = 3000.0f;       // cm
	constexpr float DCViewMinSeconds = 1.0f;

	/** How far off the centre of the screen still counts as "on screen" for the line check. */
	constexpr float DCViewCosLimit = 0.5f;        // ~60 degrees off the camera's forward
}

const TCHAR* DCSlotStateName(EDCSlotState State)
{
	switch (State)
	{
	case EDCSlotState::Idle:        return TEXT("IDLE");
	case EDCSlotState::Resolving:   return TEXT("RESOLVING");
	case EDCSlotState::Downloading: return TEXT("DOWNLOADING");
	case EDCSlotState::Verifying:   return TEXT("VERIFYING");
	case EDCSlotState::Mounting:    return TEXT("MOUNTING");
	case EDCSlotState::Active:      return TEXT("ACTIVE");
	case EDCSlotState::SwapPending: return TEXT("SWAP PENDING");
	case EDCSlotState::Error:       return TEXT("ERROR");
	case EDCSlotState::Fallback:    return TEXT("FALLBACK");
	default:                        return TEXT("?");
	}
}

ADCSlot::ADCSlot()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickInterval = 0.0f;

	Anchor = CreateDefaultSubobject<USceneComponent>(TEXT("Anchor"));
	RootComponent = Anchor;

	LimitsBox = CreateDefaultSubobject<UBoxComponent>(TEXT("LimitsBox"));
	LimitsBox->SetupAttachment(Anchor);
	LimitsBox->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	LimitsBox->SetHiddenInGame(true);
	LimitsBox->ShapeColor = FColor(90, 180, 220);
	LimitsBox->SetBoxExtent(FVector(350.0f, 350.0f, 250.0f), false);
	LimitsBox->SetRelativeLocation(FVector(0.0f, 0.0f, 250.0f));
}

FVector ADCSlot::GetClassLimits() const
{
	switch (SizeClass)
	{
	case EDCSizeClass::L:
		return FVector(1400.0f, 1400.0f, 900.0f);
	case EDCSizeClass::T:
		return FVector(1400.0f, 1400.0f, 2000.0f);
	case EDCSizeClass::S:
	default:
		return FVector(700.0f, 700.0f, 500.0f);
	}
}

FString ADCSlot::GetSizeClassName() const
{
	switch (SizeClass)
	{
	case EDCSizeClass::L: return TEXT("L");
	case EDCSizeClass::T: return TEXT("T");
	case EDCSizeClass::S:
	default:              return TEXT("S");
	}
}

FTransform ADCSlot::GetContentTransform() const
{
	FTransform Out = GetActorTransform();
	FRotator Rot = Out.Rotator();
	Rot.Yaw += ContentYawOffset;
	Out.SetRotation(Rot.Quaternion());
	Out.SetScale3D(FVector(1.0f));
	return Out;
}

bool ADCSlot::IsPointInsideBounds(const FVector& WorldPoint) const
{
	if (LimitsBox == nullptr)
	{
		return false;
	}
	const FVector Local = LimitsBox->GetComponentTransform().InverseTransformPosition(WorldPoint);
	const FVector Extent = LimitsBox->GetUnscaledBoxExtent();
	return FMath::Abs(Local.X) <= Extent.X
		&& FMath::Abs(Local.Y) <= Extent.Y
		&& FMath::Abs(Local.Z) <= Extent.Z;
}

FVector ADCSlot::GetContentCentre() const
{
	const FBox Bounds = GetContentBounds();
	return Bounds.IsValid ? Bounds.GetCenter()
		: (LimitsBox ? LimitsBox->GetComponentLocation() : GetActorLocation());
}

FBox ADCSlot::GetContentBounds() const
{
	if (const ADCContentActor* Built = Cast<ADCContentActor>(Content.Get()))
	{
		const FBox Bounds = Built->GetBuiltBounds();
		if (Bounds.IsValid)
		{
			return Bounds;
		}
	}
	if (LimitsBox)
	{
		const FVector Centre = LimitsBox->GetComponentLocation();
		const FVector Extent = LimitsBox->GetUnscaledBoxExtent();
		return FBox(Centre - Extent, Centre + Extent);
	}
	return FBox(GetActorLocation(), GetActorLocation());
}

FVector ADCSlot::GetDoorApproachPoint(float Extra) const
{
	const FVector Limits = GetClassLimits();
	const FVector Here = GetActorLocation();
	const FVector Forward = GetActorForwardVector();
	const float Reach = Limits.X * 0.5f + Extra;
	return FVector(Here.X + Forward.X * Reach, Here.Y + Forward.Y * Reach, Here.Z);
}

FVector ADCSlot::GetFrontStandPoint(float Clearance) const
{
	const FVector Here = GetActorLocation();
	const FVector Forward = GetActorForwardVector();

	// How far the piece actually reaches towards the approach, measured on its own bounds.
	float Front = GetClassLimits().X * 0.5f;
	const FBox Bounds = GetContentBounds();
	if (Bounds.IsValid)
	{
		float Reach = 0.0f;
		for (int32 Corner = 0; Corner < 8; ++Corner)
		{
			const FVector Point(
				(Corner & 1) ? Bounds.Max.X : Bounds.Min.X,
				(Corner & 2) ? Bounds.Max.Y : Bounds.Min.Y,
				(Corner & 4) ? Bounds.Max.Z : Bounds.Min.Z);
			Reach = FMath::Max(Reach,
				static_cast<float>(FVector::DotProduct(Point - Here, Forward)));
		}
		Front = Reach;
	}
	const FVector Out = Here + Forward * (Front + Clearance);
	return FVector(Out.X, Out.Y, Here.Z);
}

void ADCSlot::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);

	// Box = the class limit volume: footprint centred on the slot, sitting on the ground.
	const FVector Limits = GetClassLimits();
	if (LimitsBox)
	{
		LimitsBox->SetBoxExtent(FVector(Limits.X * 0.5f, Limits.Y * 0.5f, Limits.Z * 0.5f), false);
		LimitsBox->SetRelativeLocation(FVector(0.0f, 0.0f, Limits.Z * 0.5f));
	}
}

void ADCSlot::BeginPlay()
{
	Super::BeginPlay();

	StateEnteredSeconds = FPlatformTime::Seconds();

	if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		Subsystem->RegisterSlot(this);
	}
}

void ADCSlot::EndPlay(const EEndPlayReason::Type Reason)
{
	// A run that ends with the Player standing inside still counts the seconds they were in.
	EndDwell(TEXT("the run ended"));
	if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		Subsystem->UnregisterSlot(this);
	}
	Super::EndPlay(Reason);
}

double ADCSlot::GetSecondsInState() const
{
	return FPlatformTime::Seconds() - StateEnteredSeconds;
}

void ADCSlot::SetState(EDCSlotState NewState)
{
	if (State == NewState)
	{
		return;
	}
	const EDCSlotState Was = State;
	State = NewState;
	StateEnteredSeconds = FPlatformTime::Seconds();

	DC_LOG(Log, TEXT("SLOT %s  %s -> %s   %s"), *SlotId.ToString(),
		DCSlotStateName(Was), DCSlotStateName(NewState), *DescribeShowing());
}

void ADCSlot::EnterFallback(const FString& Reason, double NowSeconds, float BaseDelaySeconds,
	float MaxDelaySeconds)
{
	LastError = Reason;
	++Attempts;

	// Backoff doubles per attempt: 2, 4, 8, ... capped. The slot keeps whatever is on screen,
	// which is the whole point of the rule in demo plan v6 §15 - the visitor sees the default
	// content, never an error.
	const float Delay = FMath::Min(BaseDelaySeconds * FMath::Pow(2.0f, static_cast<float>(Attempts - 1)),
		MaxDelaySeconds);
	RetryAtSeconds = NowSeconds + Delay;

	SetState(EDCSlotState::Fallback);
	DC_LOG(Warning, TEXT("SLOT %s  FALLBACK (attempt %d): %s   keeping %s, retrying in %.1f s"),
		*SlotId.ToString(), Attempts, *Reason, *DescribeShowing(), Delay);
}

bool ADCSlot::IsRetryDue(double NowSeconds) const
{
	return RetryAtSeconds > 0.0 && NowSeconds >= RetryAtSeconds;
}

bool ADCSlot::SpawnFromClass(UClass* ContentClass, const FDCManifest& Manifest, FString& OutError)
{
	UWorld* World = GetWorld();
	if (World == nullptr || ContentClass == nullptr)
	{
		OutError = TEXT("no world or no class to spawn");
		return false;
	}

	DespawnContent();

	const FTransform Where = GetContentTransform();
	const double Start = FPlatformTime::Seconds();

	// Deferred, so the brand is set before BeginPlay builds the piece: ADCContentActor wires
	// the colour and the emblem into its material instances in Rebuild(), and doing it after
	// the fact would show one frame of the pack's own default identity.
	AActor* Actor = World->SpawnActorDeferred<AActor>(ContentClass, Where, nullptr, nullptr,
		ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
	if (Actor == nullptr)
	{
		OutError = FString::Printf(TEXT("SpawnActorDeferred failed for %s"), *ContentClass->GetPathName());
		return false;
	}

	FString RestoredLine;
	if (ADCContentActor* Built = Cast<ADCContentActor>(Actor))
	{
		Built->ContentId = FName(*Manifest.Piece);
		Built->ContentVersion = FName(*Manifest.Version);
		Built->StateSchemaVersion = Manifest.StateSchemaVersion;
		if (Manifest.Brand.bValid)
		{
			Built->BrandColor = Manifest.Brand.ToLinearColour();
			if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
			{
				if (UTexture2D* Emblem = Subsystem->GetEmblemTexture(Manifest.Brand.Emblem))
				{
					Built->EmblemTexture = Emblem;
				}
			}
		}

		// The patent's promise, and it happens here: **before** FinishSpawning, so BeginPlay
		// builds the piece already holding what the Player left. Keyed by slot + content, not
		// by version, so version 2 picks up where version 1 stopped - and not by anything
		// else, so a *different* piece arriving in this slot gets its own defaults.
		if (UDCStateStore* Store = UDCStateStore::Get(this))
		{
			FDCContentState Kept;
			if (Store->Restore(SlotId.ToString(), Manifest.Piece, Manifest.StateSchemaVersion,
				Kept))
			{
				Built->bLightAOn = Kept.bLightAOn;
				Built->bLightBOn = Kept.bLightBOn;
				Built->bDoorOpen = Kept.bDoorOpen;
				Built->ScreenIndex = Kept.ScreenIndex;
				RestoredLine = FString::Printf(TEXT("  restored: %s"), *Kept.Describe());
			}
		}
	}

	Actor->FinishSpawning(Where);
	LastSpawnMs = DCElapsedMs(Start);

	Content = Actor;
	ActiveManifest = Manifest;
	ActiveAllocKey = Manifest.AllocKey;
	ActiveSinceUtc = FDateTime::UtcNow();
	ViewSeconds = 0.0f;
	bViewReported = false;
	LastError.Reset();
	Attempts = 0;
	RetryAtSeconds = 0.0;

	FString FitLine;
	if (const ADCContentActor* Built = Cast<ADCContentActor>(Actor))
	{
		const FBox Bounds = Built->GetBuiltBounds();
		const FVector Size = Bounds.IsValid ? Bounds.GetSize() : FVector::ZeroVector;
		const FVector Limits = GetClassLimits();
		const bool bFits = Size.X <= Limits.X + 1.0f && Size.Y <= Limits.Y + 1.0f
			&& Size.Z <= Limits.Z + 1.0f;
		FitLine = FString::Printf(TEXT("  %.0fx%.0fx%.0f cm in %s %.0fx%.0fx%.0f cm -> %s"),
			Size.X, Size.Y, Size.Z, *GetSizeClassName(), Limits.X, Limits.Y, Limits.Z,
			bFits ? TEXT("fits") : TEXT("DOES NOT FIT"));
	}

	DC_LOG(Log, TEXT("SPAWN ok   slot %s  %s  at %s yaw=%.0f in %.2f ms%s%s"),
		*SlotId.ToString(), *Manifest.Describe(), *Actor->GetActorLocation().ToCompactString(),
		Actor->GetActorRotation().Yaw, LastSpawnMs, *FitLine, *RestoredLine);

	// Something new is standing here: point the Player at it until they have seen it.
	bWaypointActive = true;
	WaypointElapsed = 0.0f;

	// A Player who is standing inside while the content is replaced is still visiting: carry
	// the dwell on against the new allocation rather than losing it.
	if (bPlayerInside)
	{
		DwellAllocKey = ActiveAllocKey;
	}

	return true;
}

bool ADCSlot::ApplyOrHold(UClass* ContentClass, const FDCManifest& Manifest, FString& OutError)
{
	UpdatePlayerInside();

	if (bPlayerInside && Content.IsValid())
	{
		// Nothing changes under the Player's feet. Hold it; Tick applies it when they leave.
		PendingClass = ContentClass;
		PendingManifest = Manifest;
		bHasPending = true;
		SetState(EDCSlotState::SwapPending);
		DC_LOG(Log, TEXT("SLOT %s  SWAP PENDING: %s is ready, the Player is inside the bounds box"),
			*SlotId.ToString(), *Manifest.Describe());
		return false;
	}

	if (!SpawnFromClass(ContentClass, Manifest, OutError))
	{
		return false;
	}
	bHasPending = false;
	PendingClass = nullptr;
	SetState(EDCSlotState::Active);
	return true;
}

bool ADCSlot::ApplyPendingIfClear(FString& OutError)
{
	if (!bHasPending || PendingClass == nullptr)
	{
		return false;
	}
	UpdatePlayerInside();
	if (bPlayerInside)
	{
		return false;
	}

	UClass* ContentClass = PendingClass;
	const FDCManifest Manifest = PendingManifest;
	bHasPending = false;
	PendingClass = nullptr;

	if (!SpawnFromClass(ContentClass, Manifest, OutError))
	{
		return false;
	}
	SetState(EDCSlotState::Active);
	return true;
}

bool ADCSlot::GetContentState(FDCContentState& Out) const
{
	if (const ADCContentActor* Built = Cast<ADCContentActor>(Content.Get()))
	{
		Out = Built->GetContentState();
		return true;
	}
	return false;
}

void ADCSlot::SaveContentState()
{
	const ADCContentActor* Built = Cast<ADCContentActor>(Content.Get());
	if (Built == nullptr || ActiveManifest.Piece.IsEmpty())
	{
		return;
	}
	if (UDCStateStore* Store = UDCStateStore::Get(this))
	{
		Store->Save(SlotId.ToString(), ActiveManifest.Piece, Built->StateSchemaVersion,
			Built->GetContentState());
	}
}

void ADCSlot::DespawnContent()
{
	if (AActor* Actor = Content.Get())
	{
		// UNLOAD & PRESERVE, in that order: what the Player did is taken off the piece before
		// the piece goes, because once it is destroyed there is nothing left to ask.
		SaveContentState();

		// The pack stays mounted: unmounting a container whose objects are still referenced
		// is how a swap turns into a crash, and a mounted pack costs nothing but a file
		// handle. The cache's LRU is what eventually gets rid of the bytes.
		Actor->Destroy();
	}
	Content = nullptr;
}

void ADCSlot::EndDwell(const TCHAR* Why)
{
	if (DwellSeconds <= 0.0f)
	{
		return;
	}
	const float Seconds = DwellSeconds;
	DwellSeconds = 0.0f;
	TotalDwellSeconds += Seconds;

	if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		Subsystem->QueueTelemetry(TEXT("dwell"), SlotId.ToString(),
			DwellAllocKey.IsEmpty() ? ActiveAllocKey : DwellAllocKey, Seconds);
	}
	DC_LOG(Log, TEXT("SLOT %s  dwell %.1f s (%s); %d visit(s), %.1f s in all"),
		*SlotId.ToString(), Seconds, Why, VisitCount, TotalDwellSeconds);
	DwellAllocKey.Reset();
}

void ADCSlot::UpdatePlayerInside()
{
	bool bInside = false;
	if (const UWorld* World = GetWorld())
	{
		if (const APlayerController* PC = World->GetFirstPlayerController())
		{
			if (const APawn* Pawn = PC->GetPawn())
			{
				bInside = IsPointInsideBounds(Pawn->GetActorLocation());
			}
		}
	}
	if (bInside == bPlayerInside)
	{
		return;
	}
	bPlayerInside = bInside;
	DC_LOG(Log, TEXT("SLOT %s  the Player %s the bounds box"), *SlotId.ToString(),
		bInside ? TEXT("entered") : TEXT("left"));

	if (bInside)
	{
		// A visit is entering the slot's bounds (plan v6 §9). The bounds box is the class
		// limit volume, so it is the slot that is visited, not whatever is standing in it.
		++VisitCount;
		DwellSeconds = 0.0f;
		DwellAllocKey = ActiveAllocKey;
		if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
		{
			Subsystem->QueueTelemetry(TEXT("visit"), SlotId.ToString(), ActiveAllocKey, 1.0);
		}
	}
	else
	{
		EndDwell(TEXT("walked out"));
	}
}

void ADCSlot::UpdateWaypoint(float DeltaSeconds)
{
	if (!bWaypointActive)
	{
		return;
	}
	WaypointElapsed += DeltaSeconds;

	const UWorld* World = GetWorld();
	const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	if (Pawn != nullptr)
	{
		// Near enough counts as arrived: the marker's job is to get the Player looking this
		// way, not to follow them in. Measured to the bounds, like the view radius.
		const FBox Bounds = GetContentBounds();
		const float Distance = Bounds.IsValid
			? FMath::Sqrt(Bounds.ComputeSquaredDistanceToPoint(Pawn->GetActorLocation()))
			: FVector::Dist(GetActorLocation(), Pawn->GetActorLocation());
		if (Distance <= WaypointClearRadius)
		{
			bWaypointActive = false;
			DC_LOG(Log, TEXT("SLOT %s  waypoint marker cleared: the Player got within %.0f m"),
				*SlotId.ToString(), Distance / 100.0f);
			return;
		}
	}
	if (WaypointElapsed >= WaypointSeconds)
	{
		bWaypointActive = false;
		DC_LOG(Log, TEXT("SLOT %s  waypoint marker timed out after %.0f s"),
			*SlotId.ToString(), WaypointElapsed);
	}
}

FVector ADCSlot::GetWaypointLocation() const
{
	FTransform Socket;
	if (const ADCContentActor* Built = Cast<ADCContentActor>(Content.Get()))
	{
		if (Built->GetSocketWorldTransform(TEXT("Waypoint"), Socket))
		{
			return Socket.GetLocation();
		}
	}
	const FBox Bounds = GetContentBounds();
	if (Bounds.IsValid)
	{
		return FVector(Bounds.GetCenter().X, Bounds.GetCenter().Y, Bounds.Max.Z + 120.0f);
	}
	return GetActorLocation() + FVector(0.0f, 0.0f, GetClassLimits().Z + 120.0f);
}

void ADCSlot::UpdateViewSeconds(float DeltaSeconds)
{
	if (!Content.IsValid() || bViewReported)
	{
		return;
	}

	const UWorld* World = GetWorld();
	const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (PC == nullptr)
	{
		return;
	}

	FVector Eye;
	FRotator Look;
	PC->GetPlayerViewPoint(Eye, Look);

	// Within 30 m of the **piece**, not of the middle of it. A T slot's content is 20 m tall,
	// so a Player standing a comfortable 25 m from its door is 32 m from its centre, and
	// measuring to the centre quietly threw that view away. The distance is therefore to the
	// nearest point of the content's own bounds; the line check below still aims at the
	// middle, which is the right place to ask "can it be seen from here".
	const FBox Bounds = GetContentBounds();
	const FVector Centre = Bounds.IsValid ? Bounds.GetCenter() : GetContentCentre();
	const double BoundsDistance = Bounds.IsValid
		? FMath::Sqrt(Bounds.ComputeSquaredDistanceToPoint(Eye))
		: FVector::Dist(Centre, Eye);
	if (BoundsDistance > DCViewRadius)
	{
		ViewSeconds = 0.0f;
		return;
	}

	const FVector ToContent = Centre - Eye;
	const float Distance = ToContent.Size();
	if (Distance <= KINDA_SMALL_NUMBER)
	{
		ViewSeconds = 0.0f;
		return;
	}
	if (FVector::DotProduct(Look.Vector(), ToContent / Distance) < DCViewCosLimit)
	{
		ViewSeconds = 0.0f;
		return;
	}

	// The "simple line check" of demo plan v6 §9: if something solid is between the camera
	// and the middle of the piece, it does not count as seen. The piece itself is ignored.
	FHitResult Hit;
	FCollisionQueryParams Params(FName(TEXT("DCView")), /*bTraceComplex=*/false);
	Params.AddIgnoredActor(Content.Get());
	if (const APawn* Pawn = PC->GetPawn())
	{
		Params.AddIgnoredActor(Pawn);
	}
	if (World->LineTraceSingleByChannel(Hit, Eye, Centre, ECC_Visibility, Params))
	{
		ViewSeconds = 0.0f;
		return;
	}

	ViewSeconds += DeltaSeconds;
	if (ViewSeconds >= DCViewMinSeconds)
	{
		if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
		{
			Subsystem->QueueTelemetry(TEXT("view"), SlotId.ToString(), ActiveAllocKey, 1.0);
		}
		bViewReported = true;
	}
}

void ADCSlot::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	UpdatePlayerInside();
	if (bPlayerInside)
	{
		DwellSeconds += DeltaSeconds;
	}
	UpdateWaypoint(DeltaSeconds);

	if (State == EDCSlotState::SwapPending)
	{
		FString Error;
		if (!ApplyPendingIfClear(Error) && !Error.IsEmpty())
		{
			DC_LOG(Error, TEXT("SLOT %s  the held swap would not spawn: %s"), *SlotId.ToString(), *Error);
			if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
			{
				EnterFallback(Error, FPlatformTime::Seconds(), Subsystem->GetRetryBaseSeconds(),
					Subsystem->GetRetryMaxSeconds());
			}
		}
	}

	UpdateViewSeconds(DeltaSeconds);
}

FString ADCSlot::DescribeShowing() const
{
	if (!Content.IsValid())
	{
		return TEXT("nothing yet");
	}
	return FString::Printf(TEXT("%s %s %s"), *ActiveManifest.Piece, *ActiveManifest.Version,
		*ActiveManifest.Brand.Describe());
}

FString ADCSlot::DescribeState() const
{
	FString Line = FString::Printf(TEXT("%-3s %s  %-12s  %s"), *SlotId.ToString(),
		*GetSizeClassName(), DCSlotStateName(State), *DescribeShowing());
	if (State == EDCSlotState::Fallback && !LastError.IsEmpty())
	{
		Line += FString::Printf(TEXT("   (%s)"), *LastError);
	}
	if (bPlayerInside)
	{
		Line += TEXT("   [Player inside]");
	}
	return Line;
}
