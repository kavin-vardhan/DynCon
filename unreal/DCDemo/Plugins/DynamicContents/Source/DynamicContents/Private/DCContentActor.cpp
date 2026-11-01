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
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

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

// ===================================================================== the lighting budget
//
// Brief 018 part 1. Brief 016 gave every piece a second group of lamps a visitor can switch
// on, and the solo frame-time baseline of the ten-minute tour went 12.47 -> 17.82 ms. Three
// pieces of content with group B on is 18 extra point lights, and under Lumen a local light
// costs far more than its deferred shading pass: **every light whose indirect lighting scale
// is above zero is also a light the Lumen surface cache has to be lit by**, once per card
// page it touches, every frame it is on (`LumenSceneDirectLighting.cpp`:
// `Proxy->GetIndirectLightingScale() > 0.0f`).
//
// So the knobs are here, every one of them readable from the command line, and the defaults
// in DCContentActor.h are whatever the measurement said. `unreal\Tools\light_sweep.py` runs
// the same scripted tour once per setting and prints the table; nothing else in the build
// changes between those runs, which is the only way a frame-time comparison means anything.
//
//   -DCLightBOff                 do not build group B at all (the lower bound)
//   -DCLightBShadow=0|1          group B casts shadows
//   -DCLightBGi=0|1              group B lights the Lumen scene (indirect scale 1 or 0)
//   -DCLightBRadius=<cm>  -DCLightBLumens=<lm>  -DCLightBEvery=<n>
//   -DCLightAShadowMax=<n>       only the first n group-A fixtures cast shadows (-1 = all)
//   -DCLightAGi=0|1  -DCLightARadius=<cm>  -DCLightALumens=<lm>  -DCLightAEvery=<n>
//
// `Every` keeps one lamp in n and brightens what is left by n, so "fewer but brighter" is a
// number rather than a re-export of the art.
namespace
{
	struct FDCLightTuning
	{
		bool bBuildB = true;
		int32 ShadowB = -1;              // -1 = leave the actor's own flag alone
		int32 GiB = -1;
		float RadiusB = -1.0f;
		float LumensB = -1.0f;
		int32 EveryB = 1;

		int32 ShadowAMax = -1;           // -1 = every group-A fixture casts
		int32 GiA = -1;
		float RadiusA = -1.0f;
		float LumensA = -1.0f;
		int32 EveryA = 1;

		FString Describe() const
		{
			return FString::Printf(
				TEXT("B %s shadow=%s gi=%s radius=%s lumens=%s every=%d | "
					"A shadowmax=%s gi=%s radius=%s lumens=%s every=%d"),
				bBuildB ? TEXT("on") : TEXT("NOT BUILT"),
				ShadowB < 0 ? TEXT("-") : (ShadowB ? TEXT("1") : TEXT("0")),
				GiB < 0 ? TEXT("-") : (GiB ? TEXT("1") : TEXT("0")),
				RadiusB < 0.0f ? TEXT("-") : *FString::Printf(TEXT("%.0f"), RadiusB),
				LumensB < 0.0f ? TEXT("-") : *FString::Printf(TEXT("%.0f"), LumensB),
				EveryB,
				ShadowAMax < 0 ? TEXT("all") : *FString::Printf(TEXT("%d"), ShadowAMax),
				GiA < 0 ? TEXT("-") : (GiA ? TEXT("1") : TEXT("0")),
				RadiusA < 0.0f ? TEXT("-") : *FString::Printf(TEXT("%.0f"), RadiusA),
				LumensA < 0.0f ? TEXT("-") : *FString::Printf(TEXT("%.0f"), LumensA),
				EveryA);
		}
	};

	const FDCLightTuning& LightTuning()
	{
		static FDCLightTuning Tuning;
		static bool bParsed = false;
		if (!bParsed)
		{
			bParsed = true;
			const TCHAR* Cmd = FCommandLine::Get();
			Tuning.bBuildB = !FParse::Param(Cmd, TEXT("DCLightBOff"));
			FParse::Value(Cmd, TEXT("DCLightBShadow="), Tuning.ShadowB);
			FParse::Value(Cmd, TEXT("DCLightBGi="), Tuning.GiB);
			FParse::Value(Cmd, TEXT("DCLightBRadius="), Tuning.RadiusB);
			FParse::Value(Cmd, TEXT("DCLightBLumens="), Tuning.LumensB);
			FParse::Value(Cmd, TEXT("DCLightBEvery="), Tuning.EveryB);
			FParse::Value(Cmd, TEXT("DCLightAShadowMax="), Tuning.ShadowAMax);
			FParse::Value(Cmd, TEXT("DCLightAGi="), Tuning.GiA);
			FParse::Value(Cmd, TEXT("DCLightARadius="), Tuning.RadiusA);
			FParse::Value(Cmd, TEXT("DCLightALumens="), Tuning.LumensA);
			FParse::Value(Cmd, TEXT("DCLightAEvery="), Tuning.EveryA);
			Tuning.EveryA = FMath::Max(Tuning.EveryA, 1);
			Tuning.EveryB = FMath::Max(Tuning.EveryB, 1);
			DC_LOG(Log, TEXT("LIGHTS tuning: %s"), *Tuning.Describe());
		}
		return Tuning;
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

	const FDCLightTuning& Tuning = LightTuning();

	TArray<FName> SocketNames = ShellComp->GetAllSocketNames();
	SocketNames.Sort([](const FName& A, const FName& B) { return A.LexicalLess(B); });

	// Count first, so "fewer but brighter" conserves the light in the room: keeping one
	// socket in Every out of six is a sixfold brightening, not an Every-fold one, and the
	// two only agree when Every happens to divide the count.
	int32 TotalA = 0;
	int32 TotalB = 0;
	for (const FName& SocketName : SocketNames)
	{
		FString Name = SocketName.ToString();
		Name.RemoveFromStart(TEXT("SOCKET_"), ESearchCase::CaseSensitive);
		TotalA += Name.StartsWith(TEXT("LightA_"), ESearchCase::CaseSensitive) ? 1 : 0;
		TotalB += Name.StartsWith(TEXT("LightB_"), ESearchCase::CaseSensitive) ? 1 : 0;
	}
	const int32 EveryA = Tuning.EveryA > 1 ? Tuning.EveryA : FMath::Max(LightAKeepEvery, 1);
	const int32 EveryB = Tuning.EveryB > 1 ? Tuning.EveryB : FMath::Max(LightBKeepEvery, 1);
	const int32 KeptA = FMath::Max((TotalA + EveryA - 1) / EveryA, 1);
	const int32 KeptB = FMath::Max((TotalB + EveryB - 1) / EveryB, 1);
	const float BoostA = TotalA > 0 ? float(TotalA) / float(KeptA) : 1.0f;
	const float BoostB = TotalB > 0 ? float(TotalB) / float(KeptB) : 1.0f;
	BuiltBoostA = BoostA;
	BuiltBoostB = BoostB;

	int32 SeenA = 0;
	int32 SeenB = 0;
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
		if (bGroupB && !Tuning.bBuildB)
		{
			continue;
		}

		const int32 Every = bGroupA ? EveryA : EveryB;
		const int32 Index = bGroupA ? SeenA++ : SeenB++;
		if (Every > 1 && (Index % Every) != 0)
		{
			continue;
		}

		const float Lumens = (bGroupA
			? (Tuning.LumensA >= 0.0f ? Tuning.LumensA : LightAIntensity) * BoostA
			: (Tuning.LumensB >= 0.0f ? Tuning.LumensB : LightBIntensity) * BoostB);
		const float Radius = bGroupA
			? (Tuning.RadiusA >= 0.0f ? Tuning.RadiusA : LightARadius)
			: (Tuning.RadiusB >= 0.0f ? Tuning.RadiusB : LightBRadius);

		// Group A casts unless the tuning caps how many of them do; group B follows its own
		// flag. One shadow-caster per piece is a real option: it is the ceiling fixture that
		// makes the room read as a room, and the others only add to the same answer.
		bool bShadows = bGroupA ? bLightsCastShadows : bLightBCastsShadows;
		if (bGroupA && Tuning.ShadowAMax >= 0)
		{
			bShadows = bShadows && LightsA.Num() < Tuning.ShadowAMax;
		}
		if (bGroupB && Tuning.ShadowB >= 0)
		{
			bShadows = Tuning.ShadowB != 0;
		}
		const bool bGi = bGroupA
			? (Tuning.GiA >= 0 ? Tuning.GiA != 0 : bLightAAffectsGi)
			: (Tuning.GiB >= 0 ? Tuning.GiB != 0 : bLightBAffectsGi);

		UPointLightComponent* Light = NewObject<UPointLightComponent>(this, FName(*(FString(TEXT("PL_")) + Name)));
		Light->SetMobility(EComponentMobility::Movable);
		Light->SetupAttachment(ShellComp, SocketName);

		// Plain bitfields on ULightComponentBase with no setter of their own, so they are set
		// before the component is registered and the proxy is built from them.
		Light->bAffectGlobalIllumination = bGi;
		Light->bAffectReflection = bGi;
		Light->bAffectTranslucentLighting = bGi;
		Light->bCastVolumetricShadow = false;

		Light->RegisterComponent();

		// Lumens, not candelas: the defaults above are the numbers a real fitting is sold in,
		// and UPointLightComponent's own default unit is candelas, so say so explicitly.
		Light->SetIntensityUnits(ELightUnits::Lumens);
		Light->SetIntensity(Lumens);
		Light->SetLightColor(LightColor);
		Light->SetAttenuationRadius(Radius);
		Light->SetSourceRadius(LightSourceRadius);
		Light->SetCastShadows(bShadows);

		// **This** is the Lumen switch, and it is a float rather than a flag: a local light
		// with an indirect scale of zero is skipped by the Lumen scene's direct lighting pass
		// altogether (LumenSceneDirectLighting.cpp), which is where most of the cost of a
		// roomful of small lamps actually goes. Its direct contribution - the thing a visitor
		// sees when they press the switch - is untouched.
		Light->SetIndirectLightingIntensity(bGi ? 1.0f : 0.0f);
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
		TEXT("lightsA=%d(%s %.0flm r%.0f) lightsB=%d(%s %.0flm r%.0f) shadowsA=%s shadowsB=%s ")
		TEXT("giA=%s giB=%s sockets=%d ")
		TEXT("bounds=%.0fx%.0fx%.0f cm door_local=(%.0f,%.0f,%.0f) door_open=%d screen_index=%d ")
		TEXT("sign_local=(%.0f,%.0f,%.0f) sign_out=(%.2f,%.2f,%.2f) ")
		TEXT("brand=(%.2f,%.2f,%.2f) emblem=%s screen_img=%s"),
		*ContentId.ToString(), *ContentVersion.ToString(),
		ShellMesh ? *ShellMesh->GetName() : TEXT("none"), ContentUnitScale,
		DoorComp ? 1 : 0, ScreenComp ? 1 : 0, SignComp ? 1 : 0,
		SwitchComps.Num(),
		LightsA.Num(), bLightAOn ? TEXT("on") : TEXT("off"), LightAIntensity * BuiltBoostA,
		LightARadius,
		LightsB.Num(), bLightBOn ? TEXT("on") : TEXT("off"), LightBIntensity * BuiltBoostB,
		LightBRadius,
		bLightsCastShadows ? TEXT("yes") : TEXT("no"),
		bLightBCastsShadows ? TEXT("yes") : TEXT("no"),
		bLightAAffectsGi ? TEXT("yes") : TEXT("no"),
		bLightBAffectsGi ? TEXT("yes") : TEXT("no"),
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
