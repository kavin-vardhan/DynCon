// A dynamic slot: the fixed, shipped-with-the-map place where content appears.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "DCSlot.generated.h"

class UBoxComponent;

/** Slot size classes from content_assets_spec_v1 section 2 (metres there, centimetres here). */
UENUM(BlueprintType)
enum class EDCSizeClass : uint8
{
	/** small: 7 x 7 x 5 m */
	S,
	/** large: 14 x 14 x 9 m */
	L,
	/** large and tall: 14 x 14 x 20 m */
	T
};

/**
 * One dynamic slot. For the pack round-trip spike this is just an anchor with a bounds box
 * and the yaw that turns a piece's front (-Y in Blender, +Y once imported) towards the
 * approach; the full slot lifecycle (IDLE -> RESOLVING -> ... -> ACTIVE) comes later.
 */
UCLASS(Blueprintable)
class DYNAMICCONTENTS_API ADCSlot : public AActor
{
	GENERATED_BODY()

public:
	ADCSlot();

	/** A1 / A2 / A3 / B1 / B2 in the demo; slot1 / slot2 in the spike map. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	FName SlotId;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	EDCSizeClass SizeClass = EDCSizeClass::S;

	/** Order the spike fills slots in: lowest first. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	int32 FillOrder = 0;

	/**
	 * Yaw added to the slot's rotation when content is spawned, so the piece's door faces the
	 * approach. Content comes out of Blender facing -Y and arrives in UE facing +Y, so -90
	 * turns the front onto the slot's +X.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	float ContentYawOffset = -90.0f;

	/** Where to put the camera to look at this slot's content, along the slot's -X. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	float ViewDistance = 1800.0f;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	float ViewHeight = 420.0f;

	/** Transform content should be spawned at. */
	UFUNCTION(BlueprintCallable, Category = "DC|Slot")
	FTransform GetContentTransform() const;

	/** Class limits in centimetres, from the size class. */
	UFUNCTION(BlueprintCallable, Category = "DC|Slot")
	FVector GetClassLimits() const;

	virtual void OnConstruction(const FTransform& Transform) override;

protected:
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	TObjectPtr<USceneComponent> Anchor;

	/** The class limit box, i.e. the volume content must fit inside. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	TObjectPtr<UBoxComponent> LimitsBox;
};
