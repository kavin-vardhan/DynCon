#include "DCContentActor.h"

#include "DynamicContents.h"

#include "Components/PointLightComponent.h"
#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/Texture2D.h"
#include "HAL/PlatformTime.h"
#include "Materials/MaterialInstanceDynamic.h"

namespace
{
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
			UE_LOG(LogDC, Warning, TEXT("  brand: no material to instance for slot %s on %s"),
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
	PrimaryActorTick.bCanEverTick = false;

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
		UE_LOG(LogDC, Warning, TEXT("  part %s: no socket '%s' on the shell, placing at the origin"),
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
		Light->SetIntensity(bGroupA ? LightAIntensity : LightBIntensity);
		Light->SetLightColor(LightColor);
		Light->SetAttenuationRadius(LightRadius);
		Light->SetCastShadows(false);
		AddInstanceComponent(Light);

		(bGroupA ? LightsA : LightsB).Add(Light);
	}
}

void ADCContentActor::Rebuild()
{
	const double Start = FPlatformTime::Seconds();

	if (ShellMesh == nullptr)
	{
		UE_LOG(LogDC, Error, TEXT("BUILD FAIL  %s_%s has no ShellMesh"),
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

	ApplyBrand();
	ApplyState();

	UE_LOG(LogDC, Log, TEXT("BUILD ok     %s in %.1f ms"), *DescribeBuild(), DCElapsedMs(Start));
}

void ADCContentActor::ApplyBrand()
{
	SetBrandOn(ShellComp, SlotBrandAccent, BrandColor, nullptr, nullptr, /*bWholeSlotIsBrand=*/true);
	SetBrandOn(SignComp, SlotSign, BrandColor, EmblemTexture, nullptr);
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

	if (DoorComp)
	{
		const float Yaw = bDoorOpen ? (DoorOpenSign >= 0 ? DoorOpenDegrees : -DoorOpenDegrees) : 0.0f;
		DoorComp->SetRelativeRotation(FRotator(0.0f, Yaw, 0.0f));
	}
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

	return FString::Printf(
		TEXT("%s_%s  shell=%s unit_scale=%.0f door=%d screen=%d sign=%d switches=%d ")
		TEXT("lightsA=%d lightsB=%d sockets=%d bounds=%.0fx%.0fx%.0f cm door_local=(%.0f,%.0f,%.0f) ")
		TEXT("brand=(%.2f,%.2f,%.2f) emblem=%s screen_img=%s"),
		*ContentId.ToString(), *ContentVersion.ToString(),
		ShellMesh ? *ShellMesh->GetName() : TEXT("none"), ContentUnitScale,
		DoorComp ? 1 : 0, ScreenComp ? 1 : 0, SignComp ? 1 : 0,
		SwitchComps.Num(), LightsA.Num(), LightsB.Num(),
		ShellComp ? ShellComp->GetAllSocketNames().Num() : 0,
		Size.X, Size.Y, Size.Z,
		DoorLocal.X, DoorLocal.Y, DoorLocal.Z,
		BrandColor.R, BrandColor.G, BrandColor.B,
		EmblemTexture ? *EmblemTexture->GetName() : TEXT("none"),
		ScreenImage ? *ScreenImage->GetName() : TEXT("none"));
}

FBox ADCContentActor::GetBuiltBounds() const
{
	return GetComponentsBoundingBox(true);
}
