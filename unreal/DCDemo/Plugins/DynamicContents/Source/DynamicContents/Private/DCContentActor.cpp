#include "DCContentActor.h"

#include "DCSubsystem.h"
#include "DynamicContents.h"

#include "Components/PointLightComponent.h"
#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/Texture2D.h"
#include "HAL/PlatformTime.h"
#include "Materials/MaterialInstanceDynamic.h"

const TCHAR* DCInteractionName(EDCInteraction Kind)
{
	switch (Kind)
	{
	case EDCInteraction::Door:   return TEXT("door");
	case EDCInteraction::LightA: return TEXT("light A");
	case EDCInteraction::LightB: return TEXT("light B");
	case EDCInteraction::Screen: return TEXT("screen");
	case EDCInteraction::None:
	default:                     return TEXT("nothing");
	}
}

namespace
{
	/**
	 * How far out from the thing a Player stands to use it, centimetres.
	 *
	 * Outside the door it is a step back from the leaf, so nothing is standing in the swing
	 * (the leaf swings inward, but a Player standing in the opening is standing in a doorway);
	 * inside, it is far enough back from a wall-mounted switch to see it and near enough that
	 * the nearest-thing rule in UDCInteractor picks the one being looked at.
	 */
	constexpr float DCStandOutside = 240.0f;
	constexpr float DCStandInside = 150.0f;

	/** The screen is a 3 m panel: stand back far enough to see it, not to lean on it. */
	constexpr float DCStandScreen = 280.0f;

	/** The door's socket is on the floor; the prompt goes at about the middle of the leaf. */
	constexpr float DCDoorPromptHeight = 140.0f;

	/** Material slots that take a runtime input (content_assets_spec_v1 section 4). */
	const FName SlotBrandAccent(TEXT("M_BrandAccent"));
	const FName SlotSign(TEXT("M_Sign"));
	const FName SlotScreen(TEXT("M_Screen"));

	/** Material parameters on the base game's master materials. */
	const FName ParamBrandColor(TEXT("BrandColor"));
	const FName ParamBaseColor(TEXT("BaseColor"));
	const FName ParamEmblem(TEXT("Emblem"));
	const FName ParamScreenImage(TEXT("ScreenImage"));

	/**
	 * bWholeSlotIsBrand: the slot's whole colour is the brand colour (the accent band), so
	 * the plain master material's BaseColor is set as well as the sign master's BrandColor.
	 */
	void SetBrandOn(UStaticMeshComponent* Comp, FName SlotName, const FLinearColor& Color,
		UTexture2D* Emblem, UTexture2D* ScreenImage, bool bWholeSlotIsBrand = false)
	{
		if (Comp == nullptr || Comp->GetStaticMesh() == nullptr)
		{
			return;
		}

		int32 Index = Comp->GetMaterialIndex(SlotName);
		if (Index == INDEX_NONE)
		{
			// A single-slot part (sign, screen) may not carry the slot name through import.
			if (Comp->GetNumMaterials() == 1)
			{
				Index = 0;
			}
			else
			{
				return;
			}
		}

		UMaterialInstanceDynamic* Mid = Comp->CreateDynamicMaterialInstance(Index);
		if (Mid == nullptr)
		{
			DC_LOG(Warning, TEXT("  brand: no material to instance for slot %s on %s"),
				*SlotName.ToString(), *Comp->GetName());
			return;
		}

		Mid->SetVectorParameterValue(ParamBrandColor, Color);
		if (bWholeSlotIsBrand)
		{
			Mid->SetVectorParameterValue(ParamBaseColor, Color);
		}
		if (Emblem != nullptr)
		{
			Mid->SetTextureParameterValue(ParamEmblem, Emblem);
		}
		if (ScreenImage != nullptr)
		{
			Mid->SetTextureParameterValue(ParamScreenImage, ScreenImage);
		}
	}
}

ADCContentActor::ADCContentActor()
{
	// Ticking is off until the door is actually swinging: a slot full of content that nobody
	// is touching must not cost a tick, and three of them is the normal state of the booth.
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.bStartWithTickEnabled = false;

	Anchor = CreateDefaultSubobject<USceneComponent>(TEXT("Anchor"));
	RootComponent = Anchor;

	ShellComp = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Shell"));
	ShellComp->SetupAttachment(Anchor);
	ShellComp->SetMobility(EComponentMobility::Movable);
}

void ADCContentActor::BeginPlay()
{
	Super::BeginPlay();

	Rebuild();
}

FName ADCContentActor::ResolveSocket(const FString& BaseName) const
{
	if (ShellComp == nullptr)
	{
		return NAME_None;
	}

	// The FBX importer strips the "SOCKET_" prefix, but accept both spellings.
	const FName Plain(*BaseName);
	if (ShellComp->DoesSocketExist(Plain))
	{
		return Plain;
	}

	const FName Prefixed(*(FString(TEXT("SOCKET_")) + BaseName));
	if (ShellComp->DoesSocketExist(Prefixed))
	{
		return Prefixed;
	}

	return NAME_None;
}

UStaticMeshComponent* ADCContentActor::AddPart(UStaticMesh* Mesh, const FString& Name, const FString& SocketBaseName)
{
	if (Mesh == nullptr || ShellComp == nullptr)
	{
		return nullptr;
	}

	const FName Socket = ResolveSocket(SocketBaseName);
	if (bAttachPartsAtSockets && Socket == NAME_None)
	{
		DC_LOG(Warning, TEXT("  part %s: no socket '%s' on the shell, placing at the origin"),
			*Name, *SocketBaseName);
	}

	UStaticMeshComponent* Comp = NewObject<UStaticMeshComponent>(this, FName(*Name));
	Comp->SetMobility(EComponentMobility::Movable);
	Comp->SetStaticMesh(Mesh);
	Comp->SetupAttachment(ShellComp, bAttachPartsAtSockets ? Socket : NAME_None);
	Comp->RegisterComponent();
	AddInstanceComponent(Comp);

	return Comp;
}

void ADCContentActor::AddLights()
{
	LightsA.Reset();
	LightsB.Reset();

	if (ShellComp == nullptr)
	{
		return;
	}

	TArray<FName> SocketNames = ShellComp->GetAllSocketNames();
	SocketNames.Sort([](const FName& A, const FName& B) { return A.LexicalLess(B); });

	for (const FName& SocketName : SocketNames)
	{
		FString Name = SocketName.ToString();
		Name.RemoveFromStart(TEXT("SOCKET_"), ESearchCase::CaseSensitive);

		const bool bGroupA = Name.StartsWith(TEXT("LightA_"), ESearchCase::CaseSensitive);
		const bool bGroupB = Name.StartsWith(TEXT("LightB_"), ESearchCase::CaseSensitive);
		if (!bGroupA && !bGroupB)
		{
			continue;
		}

		UPointLightComponent* Light = NewObject<UPointLightComponent>(this, FName(*(FString(TEXT("PL_")) + Name)));
		Light->SetMobility(EComponentMobility::Movable);
		Light->SetupAttachment(ShellComp, SocketName);
		Light->RegisterComponent();

		// Lumens, not candelas: the defaults above are the numbers a real fitting is sold in,
		// and UPointLightComponent's own default unit is candelas, so say so explicitly.
		Light->SetIntensityUnits(ELightUnits::Lumens);
		Light->SetIntensity(bGroupA ? LightAIntensity : LightBIntensity);
		Light->SetLightColor(LightColor);
		Light->SetAttenuationRadius(bGroupA ? LightARadius : LightBRadius);
		Light->SetSourceRadius(LightSourceRadius);
		Light->SetCastShadows(bGroupA ? bLightsCastShadows : bLightBCastsShadows);
		AddInstanceComponent(Light);

		(bGroupA ? LightsA : LightsB).Add(Light);
	}
}

void ADCContentActor::Rebuild()
{
	const double Start = FPlatformTime::Seconds();

	if (ShellMesh == nullptr)
	{
		DC_LOG(Error, TEXT("BUILD FAIL  %s_%s has no ShellMesh"),
			*ContentId.ToString(), *ContentVersion.ToString());
		return;
	}

	if (bBuilt)
	{
		// Idempotent: drop whatever a previous build made before making it again.
		for (UStaticMeshComponent* Comp : SwitchComps)
		{
			if (Comp) { Comp->DestroyComponent(); }
		}
		SwitchComps.Reset();
		for (UPointLightComponent* Light : LightsA) { if (Light) { Light->DestroyComponent(); } }
		for (UPointLightComponent* Light : LightsB) { if (Light) { Light->DestroyComponent(); } }
		LightsA.Reset();
		LightsB.Reset();
		if (DoorComp) { DoorComp->DestroyComponent(); DoorComp = nullptr; }
		if (ScreenComp) { ScreenComp->DestroyComponent(); ScreenComp = nullptr; }
		if (SignComp) { SignComp->DestroyComponent(); SignComp = nullptr; }
	}

	ShellComp->SetStaticMesh(ShellMesh);
	ShellComp->SetRelativeScale3D(FVector(ContentUnitScale));

	DoorComp   = AddPart(DoorMesh,   TEXT("Door"),   TEXT("Door"));
	ScreenComp = AddPart(ScreenMesh, TEXT("Screen"), TEXT("Screen"));
	SignComp   = AddPart(SignMesh,   TEXT("Sign"),   TEXT("Sign"));

	// One switch mesh, placed twice.
	if (UStaticMeshComponent* SwitchA = AddPart(SwitchMesh, TEXT("SwitchA"), TEXT("SwitchA")))
	{
		SwitchComps.Add(SwitchA);
	}
	if (UStaticMeshComponent* SwitchB = AddPart(SwitchMesh, TEXT("SwitchB"), TEXT("SwitchB")))
	{
		SwitchComps.Add(SwitchB);
	}

	AddLights();

	bBuilt = true;

	// The components are new, so whatever was pushed into the old ones means nothing.
	AppliedScreenIndex = -1;
	DoorYaw = WantedDoorYaw();

	ApplyBrand();
	ApplyState();

	DC_LOG(Log, TEXT("BUILD ok     %s in %.1f ms"), *DescribeBuild(), DCElapsedMs(Start));
}

void ADCContentActor::ApplyBrand()
{
	SetBrandOn(ShellComp, SlotBrandAccent, BrandColor, nullptr, nullptr, /*bWholeSlotIsBrand=*/true);
	SetBrandOn(SignComp, SlotSign, BrandColor, EmblemTexture, nullptr);
	SetBrandOn(ScreenComp, SlotScreen, BrandColor, nullptr, ScreenImage);
}

float ADCContentActor::WantedDoorYaw() const
{
	// Closed is relative rotation zero: the leaf's own origin is its hinge edge and the socket
	// already carries the door's orientation, so a closed door needs no correction.
	return bDoorOpen ? (DoorOpenSign >= 0 ? DoorOpenDegrees : -DoorOpenDegrees) : 0.0f;
}

void ADCContentActor::ApplyDoorYaw()
{
	if (DoorComp)
	{
		DoorComp->SetRelativeRotation(FRotator(0.0f, DoorYaw, 0.0f));
	}
}

void ADCContentActor::ApplyScreenImage()
{
	if (ScreenComp == nullptr || ScreenIndex == AppliedScreenIndex)
	{
		return;
	}
	// The set belongs to the base game, like the emblems: a pack never carries one. A run with
	// no subsystem (the brief-006 pack round-trip) simply keeps the pack's own default image.
	UTexture2D* Image = nullptr;
	if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		Image = Subsystem->GetScreenImage(ScreenIndex);
	}
	if (Image == nullptr)
	{
		return;
	}
	ScreenImage = Image;
	AppliedScreenIndex = ScreenIndex;
	SetBrandOn(ScreenComp, SlotScreen, BrandColor, nullptr, ScreenImage);
}

void ADCContentActor::ApplyState()
{
	for (UPointLightComponent* Light : LightsA)
	{
		if (Light) { Light->SetVisibility(bLightAOn); }
	}
	for (UPointLightComponent* Light : LightsB)
	{
		if (Light) { Light->SetVisibility(bLightBOn); }
	}

	DoorYaw = WantedDoorYaw();
	ApplyDoorYaw();
	SetActorTickEnabled(false);

	ApplyScreenImage();
}

bool ADCContentActor::IsDoorMoving() const
{
	return DoorComp != nullptr && !FMath::IsNearlyEqual(DoorYaw, WantedDoorYaw(), 0.05f);
}

void ADCContentActor::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	const float Want = WantedDoorYaw();
	if (FMath::IsNearlyEqual(DoorYaw, Want, 0.05f))
	{
		DoorYaw = Want;
		ApplyDoorYaw();
		SetActorTickEnabled(false);
		return;
	}
	DoorYaw = FMath::FInterpConstantTo(DoorYaw, Want, DeltaSeconds, DoorSwingSpeed);
	ApplyDoorYaw();
}

// --------------------------------------------------------------------------- interaction

FVector ADCContentActor::StandPointFor(const FVector& Where, float Extra, bool bOutward) const
{
	// Out of, or into, the piece - horizontally. The pieces are closed boxes with one door, so
	// "away from the middle" is out of the building and "towards it" is into the room, and
	// that holds for the door on the front wall and the screen on the back one alike.
	const FVector Middle = GetActorLocation();
	FVector Away(Where.X - Middle.X, Where.Y - Middle.Y, 0.0f);
	if (Away.IsNearlyZero())
	{
		Away = GetActorForwardVector() * -1.0f;
	}
	Away.Normalize();
	const FVector Step = Away * (bOutward ? Extra : -Extra);
	return FVector(Where.X + Step.X, Where.Y + Step.Y, Middle.Z);
}

void ADCContentActor::GetInteractionPoints(TArray<FDCInteractionPoint>& Out) const
{
	Out.Reset();
	if (!bBuilt)
	{
		return;
	}

	auto AddPoint = [this, &Out](EDCInteraction Kind, const FVector& Where, bool bOutward,
		float Clearance, const FString& Prompt)
	{
		FDCInteractionPoint Point;
		Point.Kind = Kind;
		Point.Location = Where;
		Point.Prompt = Prompt;
		Point.StandPoint = StandPointFor(Where, Clearance, bOutward);
		Out.Add(Point);
	};

	FTransform Socket;
	if (DoorComp != nullptr && GetSocketWorldTransform(TEXT("Door"), Socket))
	{
		// On the **hinge**, not on the leaf, and lifted to about the middle of the door.
		//
		// The leaf swings a metre into the room when it opens, which moves both the prompt
		// and the distance that decides whether the door is in reach - so a Player standing
		// at an open door could be further from "the door" than the same Player standing at
		// the same shut one. (By one centimetre, the first time this was run.) The hinge is
		// the doorway, it does not move, and it is where the prompt belongs anyway.
		const FVector Where = Socket.GetLocation() + FVector(0.0f, 0.0f, DCDoorPromptHeight);
		AddPoint(EDCInteraction::Door, Where, /*bOutward=*/true, DCStandOutside,
			bDoorOpen ? TEXT("Close the door") : TEXT("Open the door"));
	}
	if (LightsA.Num() > 0 && GetSocketWorldTransform(TEXT("SwitchA"), Socket))
	{
		AddPoint(EDCInteraction::LightA, Socket.GetLocation(), /*bOutward=*/false,
			DCStandInside, bLightAOn ? TEXT("Lights A - turn off") : TEXT("Lights A - turn on"));
	}
	if (LightsB.Num() > 0 && GetSocketWorldTransform(TEXT("SwitchB"), Socket))
	{
		AddPoint(EDCInteraction::LightB, Socket.GetLocation(), /*bOutward=*/false,
			DCStandInside, bLightBOn ? TEXT("Lights B - turn off") : TEXT("Lights B - turn on"));
	}
	if (ScreenComp != nullptr)
	{
		AddPoint(EDCInteraction::Screen, ScreenComp->Bounds.Origin, /*bOutward=*/false,
			DCStandScreen, FString::Printf(TEXT("Screen - next image (%d)"), ScreenIndex));
	}
}

bool ADCContentActor::GetInteractionPoint(EDCInteraction Kind, FDCInteractionPoint& Out) const
{
	TArray<FDCInteractionPoint> Points;
	GetInteractionPoints(Points);
	for (const FDCInteractionPoint& Point : Points)
	{
		if (Point.Kind == Kind)
		{
			Out = Point;
			return true;
		}
	}
	return false;
}

bool ADCContentActor::Interact(EDCInteraction Kind)
{
	switch (Kind)
	{
	case EDCInteraction::Door:
		if (DoorComp == nullptr)
		{
			return false;
		}
		bDoorOpen = !bDoorOpen;
		// The swing is the only part of the state that is animated: it is the one a Player is
		// standing next to when they press the button, and an instant 90 degrees reads as a
		// glitch rather than as a door.
		SetActorTickEnabled(true);
		if (!IsActorTickEnabled())
		{
			// A pack whose Blueprint was saved with ticking off would otherwise have a door
			// that never finishes opening, and anything waiting for the swing would wait for
			// ever. Snap it instead: an instant door beats a stuck one.
			DoorYaw = WantedDoorYaw();
			ApplyDoorYaw();
			DC_LOG(Warning, TEXT("USE   %s_%s cannot tick, so the door snaps instead of "
				"swinging"), *ContentId.ToString(), *ContentVersion.ToString());
		}
		DC_LOG(Log, TEXT("USE   %s_%s door -> %s"), *ContentId.ToString(),
			*ContentVersion.ToString(), bDoorOpen ? TEXT("open") : TEXT("closed"));
		return true;

	case EDCInteraction::LightA:
		if (LightsA.Num() == 0)
		{
			return false;
		}
		bLightAOn = !bLightAOn;
		for (UPointLightComponent* Light : LightsA)
		{
			if (Light) { Light->SetVisibility(bLightAOn); }
		}
		DC_LOG(Log, TEXT("USE   %s_%s lights A -> %s (%d fixture(s))"), *ContentId.ToString(),
			*ContentVersion.ToString(), bLightAOn ? TEXT("on") : TEXT("off"), LightsA.Num());
		return true;

	case EDCInteraction::LightB:
		if (LightsB.Num() == 0)
		{
			return false;
		}
		bLightBOn = !bLightBOn;
		for (UPointLightComponent* Light : LightsB)
		{
			if (Light) { Light->SetVisibility(bLightBOn); }
		}
		DC_LOG(Log, TEXT("USE   %s_%s lights B -> %s (%d lamp(s))"), *ContentId.ToString(),
			*ContentVersion.ToString(), bLightBOn ? TEXT("on") : TEXT("off"), LightsB.Num());
		return true;

	case EDCInteraction::Screen:
	{
		if (ScreenComp == nullptr)
		{
			return false;
		}
		int32 Count = 0;
		if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
		{
			Count = Subsystem->GetScreenImageCount();
		}
		if (Count <= 0)
		{
			DC_LOG(Warning, TEXT("USE   %s_%s screen: the base game has no screen image set"),
				*ContentId.ToString(), *ContentVersion.ToString());
			return false;
		}
		ScreenIndex = (ScreenIndex % Count) + 1;        // 1-based, wraps
		ApplyScreenImage();
		DC_LOG(Log, TEXT("USE   %s_%s screen -> image %d of %d"), *ContentId.ToString(),
			*ContentVersion.ToString(), ScreenIndex, Count);
		return true;
	}

	case EDCInteraction::None:
	default:
		return false;
	}
}

FDCContentState ADCContentActor::GetContentState() const
{
	FDCContentState State;
	State.bLightAOn = bLightAOn;
	State.bLightBOn = bLightBOn;
	State.bDoorOpen = bDoorOpen;
	State.ScreenIndex = ScreenIndex;
	return State;
}

void ADCContentActor::ApplyContentState(const FDCContentState& State, bool bInstant)
{
	bLightAOn = State.bLightAOn;
	bLightBOn = State.bLightBOn;
	bDoorOpen = State.bDoorOpen;
	ScreenIndex = State.ScreenIndex;

	if (bInstant)
	{
		ApplyState();
		return;
	}
	for (UPointLightComponent* Light : LightsA)
	{
		if (Light) { Light->SetVisibility(bLightAOn); }
	}
	for (UPointLightComponent* Light : LightsB)
	{
		if (Light) { Light->SetVisibility(bLightBOn); }
	}
	ApplyScreenImage();
	SetActorTickEnabled(true);
}

bool ADCContentActor::GetSocketWorldTransform(const FString& SocketBaseName, FTransform& OutTransform) const
{
	if (ShellComp == nullptr)
	{
		return false;
	}

	const FName Socket = ResolveSocket(SocketBaseName);
	if (Socket == NAME_None)
	{
		return false;
	}

	OutTransform = ShellComp->GetSocketTransform(Socket, RTS_World);
	return true;
}

bool ADCContentActor::GetScreenWorldLocation(FVector& OutLocation) const
{
	if (ScreenComp != nullptr)
	{
		OutLocation = ScreenComp->Bounds.Origin;
		return true;
	}

	FTransform Socket;
	if (GetSocketWorldTransform(TEXT("Screen"), Socket))
	{
		OutLocation = Socket.GetLocation();
		return true;
	}

	return false;
}

FString ADCContentActor::DescribeBuild() const
{
	const FBox Bounds = GetBuiltBounds();
	const FVector Size = Bounds.IsValid ? Bounds.GetSize() : FVector::ZeroVector;

	// The door's position in the actor's own space says which way the piece faces, which is
	// what the slot's ContentYawOffset has to cancel out: the pieces are built facing -Y in
	// Blender, so a door at local -Y means the yaw offset has the wrong sign.
	FVector DoorLocal = FVector::ZeroVector;
	if (DoorComp)
	{
		DoorLocal = GetActorTransform().InverseTransformPosition(DoorComp->GetComponentLocation());
	}

	// Where the sign ends up, and which way it faces, is the other thing worth printing: a
	// sign that has gone dark in a screenshot is almost always a sign that is facing the wrong
	// way, and this line says so without a screenshot.
	FVector SignLocal = FVector::ZeroVector;
	FVector SignNormal = FVector::ZeroVector;
	if (SignComp)
	{
		const FTransform Inverse = GetActorTransform().Inverse();
		// The sign quad is authored in its own XZ plane, so its outward normal is the
		// component's +Y axis. In the actor's own space it should come out close to (0,1,0),
		// the piece's front: anything else and the sign is facing into the wall.
		SignLocal = Inverse.TransformPosition(SignComp->GetComponentLocation());
		SignNormal = Inverse.TransformVector(SignComp->GetRightVector());
	}

	return FString::Printf(
		TEXT("%s_%s  shell=%s unit_scale=%.0f door=%d screen=%d sign=%d switches=%d ")
		TEXT("lightsA=%d(%s %.0flm r%.0f) lightsB=%d(%s %.0flm r%.0f) shadowsA=%s shadowsB=%s sockets=%d ")
		TEXT("bounds=%.0fx%.0fx%.0f cm door_local=(%.0f,%.0f,%.0f) door_open=%d screen_index=%d ")
		TEXT("sign_local=(%.0f,%.0f,%.0f) sign_out=(%.2f,%.2f,%.2f) ")
		TEXT("brand=(%.2f,%.2f,%.2f) emblem=%s screen_img=%s"),
		*ContentId.ToString(), *ContentVersion.ToString(),
		ShellMesh ? *ShellMesh->GetName() : TEXT("none"), ContentUnitScale,
		DoorComp ? 1 : 0, ScreenComp ? 1 : 0, SignComp ? 1 : 0,
		SwitchComps.Num(),
		LightsA.Num(), bLightAOn ? TEXT("on") : TEXT("off"), LightAIntensity, LightARadius,
		LightsB.Num(), bLightBOn ? TEXT("on") : TEXT("off"), LightBIntensity, LightBRadius,
		bLightsCastShadows ? TEXT("yes") : TEXT("no"),
		bLightBCastsShadows ? TEXT("yes") : TEXT("no"),
		ShellComp ? ShellComp->GetAllSocketNames().Num() : 0,
		Size.X, Size.Y, Size.Z,
		DoorLocal.X, DoorLocal.Y, DoorLocal.Z, bDoorOpen ? 1 : 0, ScreenIndex,
		SignLocal.X, SignLocal.Y, SignLocal.Z,
		SignNormal.X, SignNormal.Y, SignNormal.Z,
		BrandColor.R, BrandColor.G, BrandColor.B,
		EmblemTexture ? *EmblemTexture->GetName() : TEXT("none"),
		ScreenImage ? *ScreenImage->GetName() : TEXT("none"));
}

FBox ADCContentActor::GetBuiltBounds() const
{
	return GetComponentsBoundingBox(true);
}
