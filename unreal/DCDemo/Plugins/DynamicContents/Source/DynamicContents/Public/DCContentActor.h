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
	 * Metres to centimetres. The art is authored in metres and its FBX carries metre-scale
	 * vertex data; because the parts are imported in their own local space (each part's pivot
	 * on its socket) the FBX importer's uniform scale is discarded, so the conversion happens
	 * here instead - on the shell, which every part and light hangs off, so sockets, parts and
	 * collision all scale together. Set back to 1 once the Blender export writes centimetres.
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

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|State")
	bool bLightAOn = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|State")
	bool bLightBOn = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|State")
	bool bDoorOpen = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Door")
	float DoorOpenDegrees = 90.0f;

	/** +1 or -1: which way the leaf swings about the hinge (from the piece's manifest). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Door")
	int32 DoorOpenSign = 1;

	// ------------------------------------------------------------------ lights

	/** Lumens (point lights use inverse-square falloff by default). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	float LightAIntensity = 3000.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	float LightBIntensity = 900.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Lights")
	float LightRadius = 700.0f;

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
