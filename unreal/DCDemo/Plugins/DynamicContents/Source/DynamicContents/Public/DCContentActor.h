// The actor a content pack spawns: shell + parts wired to the shell's sockets, brand on top.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "DCContentActor.generated.h"

class UPointLightComponent;
class UStaticMesh;
class UStaticMeshComponent;
class UTexture2D;

/**
 * One piece of walk-in content.
 *
 * The geometry, the material instances and the socket names all come out of the pack; the
 * brand (a colour plus an emblem) and the screen image are runtime inputs, never baked - so
 * the same pack can be "yours" or a rival's. Every piece-version in the demo is a Blueprint
 * child of this class (BP_DC_<id>_<v>), built by unreal\Tools\import_content.py, which sets
 * the mesh and brand properties below on the Blueprint's defaults.
 *
 * The parts are built in BeginPlay from the shell's sockets: SOCKET_Door, SOCKET_SwitchA/B,
 * SOCKET_Screen, SOCKET_Sign, SOCKET_LightA_*, SOCKET_LightB_* (the FBX importer drops the
 * "SOCKET_" prefix, so both spellings are accepted).
 */
UCLASS(Blueprintable)
class DYNAMICCONTENTS_API ADCContentActor : public AActor
{
	GENERATED_BODY()

public:
	ADCContentActor();

	// ------------------------------------------------------------------ what this piece is

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Content")
	FName ContentId;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Content")
	FName ContentVersion;

	/** State-preservation schema the piece speaks (1 = lights A/B, door, screen index). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Content")
	int32 StateSchemaVersion = 1;

	// ------------------------------------------------------------------ geometry

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Meshes")
	TObjectPtr<UStaticMesh> ShellMesh;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Meshes")
	TObjectPtr<UStaticMesh> DoorMesh;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Meshes")
	TObjectPtr<UStaticMesh> SwitchMesh;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Meshes")
	TObjectPtr<UStaticMesh> ScreenMesh;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Meshes")
	TObjectPtr<UStaticMesh> SignMesh;

	/**
	 * Parts sit on the shell's sockets. The pieces are exported with each part's origin on
	 * its socket, so this reproduces the Blender layout; turn it off if a pack was imported
	 * with vertices baked into absolute positions, in which case the parts are already placed.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Meshes")
	bool bAttachPartsAtSockets = true;

	/**
	 * Always 1: the art's FBX is written in centimetres (dc_kit.FBX_UNIT_SCALE), so a piece
	 * imports at true size and nothing scales it at spawn. Kept as a visible property, and
	 * printed by DescribeBuild, because a pack built before that change would need 100 here -
	 * and a piece that is suddenly 100x too small or too large is then one number to check.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Meshes")
	float ContentUnitScale = 1.0f;

	// ------------------------------------------------------------------ brand (runtime input)

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Brand")
	FLinearColor BrandColor = FLinearColor(0.08f, 0.62f, 0.60f);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Brand")
	TObjectPtr<UTexture2D> EmblemTexture;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Brand")
	TObjectPtr<UTexture2D> ScreenImage;

	// ------------------------------------------------------------------ state (schema 1)

	/** Group A is the ceiling fixtures: on by default, they are what lights the interior. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|State")
	bool bLightAOn = true;

	/**
	 * Group B is the wall lamps - including the ones on the facade. Off by default: with them
	 * on, a small building's own facade is the nearest surface to half a dozen lamps and
	 * blows out. A visitor turning them on at the switches is the point of the group.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|State")
	bool bLightBOn = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|State")
	bool bDoorOpen = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Door")
	float DoorOpenDegrees = 90.0f;

	/** +1 or -1: which way the leaf swings about the hinge (from the piece's manifest). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Door")
	int32 DoorOpenSign = 1;

	// ------------------------------------------------------------------ lights
	//
	// These are room fixtures in a 6-14 m building, not stadium lights. The numbers below are
	// lumens, the unit a real fitting is sold in: a bright domestic ceiling light is about
	// 1200 lm and a wall lamp about 300. The attenuation radius is deliberately shorter than
	// the building is wide, so a fixture lights its own corner and not the whole piece. Only
	// group A casts shadows; see the two flags below for why.

	/** Ceiling fixtures, lumens. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	float LightAIntensity = 1200.0f;

	/** Wall lamps, lumens. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	float LightBIntensity = 320.0f;

	/** Attenuation radius of a group-A fixture, centimetres. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	float LightARadius = 600.0f;

	/** Attenuation radius of a group-B lamp, centimetres. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	float LightBRadius = 320.0f;

	/** Emitter size, centimetres: a little softness, and it keeps the falloff off a singularity. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	float LightSourceRadius = 8.0f;

	/**
	 * Group A casts shadows: without them the ceiling fixtures shine straight through the
	 * walls and wash the facade out, which is the whole reason they were turned on.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	bool bLightsCastShadows = true;

	/**
	 * Group B does not. The wall lamps are 320 lm with a 3.2 m reach - too weak to leak
	 * through a wall and be noticed - but there are more of them than of group A and a
	 * visitor turning them on used to be visible in the **worst 1 % frame time** rather than
	 * on screen. Shadowless is the trade: nobody can see the difference in the picture.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	bool bLightBCastsShadows = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	FLinearColor LightColor = FLinearColor(1.0f, 0.90f, 0.73f);

	// ------------------------------------------------------------------ build

	/** Builds shell, parts and lights. Called from BeginPlay; safe to call again. */
	UFUNCTION(BlueprintCallable, Category = "DC")
	void Rebuild();

	/** Pushes BrandColor / EmblemTexture / ScreenImage into the material instances. */
	UFUNCTION(BlueprintCallable, Category = "DC")
	void ApplyBrand();

	/** Pushes bLightAOn / bLightBOn / bDoorOpen onto the components. */
	UFUNCTION(BlueprintCallable, Category = "DC")
	void ApplyState();

	/** One line for the log: what got built. */
	UFUNCTION(BlueprintCallable, Category = "DC")
	FString DescribeBuild() const;

	/** World-space bounds of everything built, for the slot fit check. */
	UFUNCTION(BlueprintCallable, Category = "DC")
	FBox GetBuiltBounds() const;

	/**
	 * World transform of one of the shell's sockets, by base name ("Inside", "Sign", ...).
	 * How the spike puts its camera inside a piece without knowing anything about the piece.
	 */
	UFUNCTION(BlueprintCallable, Category = "DC")
	bool GetSocketWorldTransform(const FString& SocketBaseName, FTransform& OutTransform) const;

	/** World location of the screen, for something inside the piece to look at. NaN-free. */
	UFUNCTION(BlueprintCallable, Category = "DC")
	bool GetScreenWorldLocation(FVector& OutLocation) const;

	virtual void BeginPlay() override;

protected:
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC")
	TObjectPtr<USceneComponent> Anchor;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC")
	TObjectPtr<UStaticMeshComponent> ShellComp;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC")
	TObjectPtr<UStaticMeshComponent> DoorComp;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC")
	TObjectPtr<UStaticMeshComponent> ScreenComp;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC")
	TObjectPtr<UStaticMeshComponent> SignComp;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC")
	TArray<TObjectPtr<UStaticMeshComponent>> SwitchComps;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC")
	TArray<TObjectPtr<UPointLightComponent>> LightsA;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC")
	TArray<TObjectPtr<UPointLightComponent>> LightsB;

private:
	/** Socket name as imported: tries "Name" then "SOCKET_Name". NAME_None if neither. */
	FName ResolveSocket(const FString& BaseName) const;

	UStaticMeshComponent* AddPart(UStaticMesh* Mesh, const FString& Name, const FString& SocketBaseName);

	void AddLights();

	bool bBuilt = false;
};
