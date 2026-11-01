// The slot-map tool: the developer's half of the plugin (demo plan v6 §6).
//
// A game developer ships a map with fixed dynamic slots in it. Before the platform can sell
// those slots, it has to know what and where they are, and a brand has to be able to *see*
// the spot it is bidding on. That is this tool, and it is the third actor in the story: the
// game developer registers the game, its slots and the rule for each slot.
//
// For the level that is open it:
//
//   1. takes a straight-down **orthographic, lit** capture of the playable area and saves
//      it as a PNG (2048 px on the long side);
//   2. finds every ADCSlot and records its id, size class and class limits, rating rule,
//      pre-fetch radius and world position;
//   3. works out each slot's **pixel position** on that capture, from the capture camera's
//      own transform - so the portal's pin lands where the slot is;
//   4. takes an **eye-level thumbnail** per slot (1.7 m, framed on the slot, 16:9) with the
//      slot's current content hidden - the portal must show the empty spot, never somebody
//      else's building;
//   5. POSTs the image, the thumbnails and the JSON to `POST /games/register`.
//
// Three ways in, all the same code:
//
//   * the menu entry  Tools -> "Register this game with Dynamic Contents..."
//   * the commandlet  -run=DynamicContentsEditor.DCRegisterGameCommandlet
//   * editor Python   unreal.DCSlotMapTool.register_current_level(options)
//
// The last two need **-AllowCommandletRendering** on the command line: a commandlet runs
// with rendering switched off unless it is asked for, and without it there is no scene to
// capture. The tool says so rather than writing a black PNG.

#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"

#include "DCSlotMapTool.generated.h"

/** What to capture and where to send it. Every field has a working default. */
USTRUCT(BlueprintType)
struct FDCSlotMapOptions
{
	GENERATED_BODY()

	/** "A" / "B". Empty = taken from the level name (GameA -> A). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	FString Game;

	/** Where the backend is. Empty, or bPostToBackend false, writes the files and stops. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	FString Backend = TEXT("http://127.0.0.1:8700");

	/** Where the PNGs and the JSON go. Empty = <project>/Saved/DCSlotMap/<game>/. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	FString OutDir;

	/** The map capture's long side, pixels. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	int32 MapLongSidePixels = 2048;

	/** A thumbnail's width, pixels; the height is this at 16:9. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	int32 ThumbWidthPixels = 960;

	/** Eye level for a thumbnail, metres. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	float EyeHeightM = 1.7f;

	/** Horizontal field of view of a thumbnail, degrees. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	float ThumbFovDegrees = 70.0f;

	/** How much air to leave round the playable area on the map capture. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	float MarginFraction = 0.03f;

	/** Height the map capture is taken from, metres above the tallest thing in the level. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	float MapCameraClearanceM = 120.0f;

	/**
	 * Leave the sky atmosphere on for the map capture. A straight-down capture never has the
	 * sky in frame, so this only decides whether the atmosphere's aerial perspective tints
	 * the ground - off is flatter, on matches the game. The height fog is always off.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	bool bMapAtmosphere = true;

	/**
	 * How much ambient fill to add while capturing, as a fraction of the map's own sun.
	 *
	 * It is not decoration. This project's ambient light is Lumen, Lumen's scene is built by
	 * the main renderer, and a headless editor has no main renderer - so without a fill
	 * every surface the sun does not reach comes out pure black. 0 turns it off.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	float FillFraction = 0.60f;

	/** Exposure compensation, stops. The captures adapt their own exposure; this nudges it. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	float ExposureBias = 0.6f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	bool bPostToBackend = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "DC|SlotMap")
	float HttpTimeoutSeconds = 120.0f;
};

/** One slot, as the tool measured it. */
USTRUCT(BlueprintType)
struct FDCSlotMapSlot
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FString Id;

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FString SizeClass;

	/** Normalised position on the map capture, 0..1 from the top-left. */
	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FVector2D Px = FVector2D::ZeroVector;

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FString ThumbFile;
};

/** What the run did. `bOk` false always comes with a sentence in `Message`. */
USTRUCT(BlueprintType)
struct FDCSlotMapResult
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	bool bOk = false;

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FString Message;

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FString Game;

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FString MapPackage;

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FString MapImagePath;

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FString JsonPath;

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FIntPoint MapImageSize = FIntPoint::ZeroValue;

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	TArray<FDCSlotMapSlot> Slots;

	/** 0 when nothing was posted. */
	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	int32 PostStatus = 0;

	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FString PostResponse;

	/** Every line the tool logged, so a headless run has its own report. */
	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	TArray<FString> Log;

	/** One line for a human. */
	UPROPERTY(BlueprintReadOnly, Category = "DC|SlotMap")
	FString Summary;
};

UCLASS()
class UDCSlotMapTool : public UObject
{
	GENERATED_BODY()

public:
	/**
	 * Run the whole tool on the level that is currently open in the editor.
	 *
	 * Safe to call from a commandlet, from Python and from the menu: it spawns nothing into
	 * the level (the capture component is outered to the world and transient), saves no
	 * asset, and never marks a package dirty.
	 */
	UFUNCTION(BlueprintCallable, Category = "DynamicContents")
	static FDCSlotMapResult RegisterCurrentLevel(const FDCSlotMapOptions& Options);

	/** The tag the map builder puts on the invisible walls round the playable area. */
	static const FName PlayableAreaTag;
};
