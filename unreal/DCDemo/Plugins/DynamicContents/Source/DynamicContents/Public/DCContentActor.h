// The actor a content pack spawns: shell + parts wired to the shell's sockets, brand on top.

#pragma once

#include "CoreMinimal.h"
#include "DCStateStore.h"
#include "GameFramework/Actor.h"

#include "DCContentActor.generated.h"

class UPointLightComponent;
class UStaticMesh;
class UStaticMeshComponent;
class UTexture2D;

/** The things a Player can use inside a piece. Schema 1, i.e. all of them. */
UENUM(BlueprintType)
enum class EDCInteraction : uint8
{
	None,
	/** The door leaf: open / close, swinging inward on its hinge. */
	Door,
	/** Switch A: the ceiling fixtures. */
	LightA,
	/** Switch B: the wall lamps. */
	LightB,
	/** The display screen: the next image in the base game's set. */
	Screen
};

DYNAMICCONTENTS_API const TCHAR* DCInteractionName(EDCInteraction Kind);

/**
 * One thing to use, where it is, and the words that go next to it.
 *
 * Deliberately not a USTRUCT: nothing in the demo needs it in Blueprint, and keeping it plain
 * keeps the prompt text out of any asset.
 */
struct DYNAMICCONTENTS_API FDCInteractionPoint
{
	EDCInteraction Kind = EDCInteraction::None;

	/** Where the prompt is drawn, in the world. */
	FVector Location = FVector::ZeroVector;

	/** "Open the door" / "Lights A - off" - plain, neutral words. Never a brand or a price. */
	FString Prompt;

	/** Where a Player has to stand to use it (the scripted tests walk to this). */
	FVector StandPoint = FVector::ZeroVector;
};

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

	/**
	 * Which image is on the screen, 1-based, into the base game's set
	 * (`UDCSubsystem::GetScreenImage`). 0 or a number the set does not have leaves the pack's
	 * own default image alone, which is what the spike's runs and any pack built before the
	 * set existed get.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|State")
	int32 ScreenIndex = 1;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Door")
	float DoorOpenDegrees = 90.0f;

	/**
	 * +1 or -1: which way the leaf swings about the hinge (from the piece's manifest).
	 *
	 * Every piece in this demo declares `"swings": "inward"` with `open_sign` +1 in Blender,
	 * and `import_content.py` negates it on the way into the engine because Blender -> UE is a
	 * mirror in Y. So the leaf really does swing into the room - which is what makes it safe
	 * to stand in front of a door and open it.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Door")
	int32 DoorOpenSign = 1;

	/** Degrees a second the leaf swings. 90 degrees in about half a second. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|Door")
	float DoorSwingSpeed = 190.0f;

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

	/** Pushes bLightAOn / bLightBOn / bDoorOpen / ScreenIndex onto the components, at once. */
	UFUNCTION(BlueprintCallable, Category = "DC")
	void ApplyState();

	// ------------------------------------------------------------------ interaction

	/**
	 * Everything a Player can use on this piece, with where the prompt goes and where to
	 * stand. Empty for a piece with no door, no switches and no screen - the developer's
	 * default placeholder is exactly that, and nothing may assume otherwise.
	 */
	void GetInteractionPoints(TArray<FDCInteractionPoint>& Out) const;

	/** One of them by kind, or false when this piece does not have it. */
	bool GetInteractionPoint(EDCInteraction Kind, FDCInteractionPoint& Out) const;

	/**
	 * Use it: the door swings, a switch toggles its group, the screen moves to the next
	 * image. Returns false when the piece has no such thing.
	 *
	 * This is the *only* way any of them changes at runtime - the key press, the pad button
	 * and the scripted exit test all come through here, so what a visitor does at the booth
	 * is what the test did.
	 */
	bool Interact(EDCInteraction Kind);

	/** The four things schema 1 keeps. */
	FDCContentState GetContentState() const;

	/** Put a kept record back. `bInstant` skips the door's swing (it is a restore, not a use). */
	void ApplyContentState(const FDCContentState& State, bool bInstant = true);

	/** True while the door is still swinging. */
	bool IsDoorMoving() const;

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
	virtual void Tick(float DeltaSeconds) override;

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

	/** The yaw the leaf should be at for the current bDoorOpen. */
	float WantedDoorYaw() const;

	/** Pushes DoorYaw onto the leaf. */
	void ApplyDoorYaw();

	/** Puts the set's image for ScreenIndex on the screen, if the base game has one. */
	void ApplyScreenImage();

	/** Where a Player stands to use something: Extra centimetres out from the piece's middle. */
	FVector StandPointFor(const FVector& Where, float Extra, bool bOutward) const;

	bool bBuilt = false;

	/** Where the leaf actually is, which is not where it is going while it swings. */
	float DoorYaw = 0.0f;

	/** The screen image this piece last put up, so ApplyState does not re-set it every call. */
	int32 AppliedScreenIndex = -1;
};
