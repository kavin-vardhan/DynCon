#include "DCSlot.h"

#include "Components/BoxComponent.h"
#include "Components/SceneComponent.h"

ADCSlot::ADCSlot()
{
	PrimaryActorTick.bCanEverTick = false;

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

FTransform ADCSlot::GetContentTransform() const
{
	FTransform Out = GetActorTransform();
	FRotator Rot = Out.Rotator();
	Rot.Yaw += ContentYawOffset;
	Out.SetRotation(Rot.Quaternion());
	Out.SetScale3D(FVector(1.0f));
	return Out;
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
