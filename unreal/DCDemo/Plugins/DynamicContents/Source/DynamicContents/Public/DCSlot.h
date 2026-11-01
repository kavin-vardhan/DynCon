// A dynamic slot: the fixed, shipped-with-the-map place where content appears, and the state
// machine that runs its life.
//
// The states are the ones in the slot-lifecycle figure, in that order:
//
//   IDLE -> RESOLVING -> DOWNLOADING -> VERIFYING -> MOUNTING -> ACTIVE
//
// with two side exits:
//
//   SWAP PENDING  the next piece is downloaded, verified and mounted, but the Player is
//                 standing inside this slot's bounds box, so nothing changes under their
//                 feet; it is applied the moment they step out.
//   ERROR /       something failed. Whatever is on screen stays on screen (the default, in
//   FALLBACK      the normal case) and the slot tries again with a growing backoff. The
//                 visitor is never shown an error - demo plan v6 §15.
//
// UDCSubsystem drives the transitions (it owns the HTTP, the cache and the mounting); this
// actor owns the state, the bounds box, the spawn and what is on screen.

#pragma once

#include "CoreMinimal.h"
#include "DCManifest.h"
#include "GameFramework/Actor.h"
#include "Templates/SubclassOf.h"

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

/** The slot lifecycle, exactly as the figure. */
UENUM(BlueprintType)
enum class EDCSlotState : uint8
{
	Idle,
	Resolving,
	Downloading,
	Verifying,
	Mounting,
	Active,
	SwapPending,
	Error,
	Fallback
};

/** "IDLE" / "DOWNLOADING" / ... - what the log and the status strip print. */
DYNAMICCONTENTS_API const TCHAR* DCSlotStateName(EDCSlotState State);

/**
 * One dynamic slot.
 *
 * The slot id, the size class and the bounds box are shipped with the map; everything else
 * arrives at runtime.
 */
UCLASS(Blueprintable)
class DYNAMICCONTENTS_API ADCSlot : public AActor
{
	GENERATED_BODY()

public:
	ADCSlot();

	// ---------------------------------------------------------------- shipped with the map

	/** A1 / A2 / A3 / B1 / B2 in the demo; slot_s / slot_l / slot_t in the spike map. */
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

	/**
	 * How near the Player has to be for this slot to be worth pre-fetching, centimetres.
	 * Overwritten from GET /client-config's prefetch_radius_m when the backend answers.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	float PrefetchRadius = 6000.0f;

	// ---------------------------------------------------------------- geometry questions

	/** Transform content should be spawned at. */
	UFUNCTION(BlueprintCallable, Category = "DC|Slot")
	FTransform GetContentTransform() const;

	/** Class limits in centimetres, from the size class. */
	UFUNCTION(BlueprintCallable, Category = "DC|Slot")
	FVector GetClassLimits() const;

	/** "S" / "L" / "T" - the name the art's manifests and the server use. */
	UFUNCTION(BlueprintCallable, Category = "DC|Slot")
	FString GetSizeClassName() const;

	/** True when a world-space point is inside the bounds box. */
	UFUNCTION(BlueprintCallable, Category = "DC|Slot")
	bool IsPointInsideBounds(const FVector& WorldPoint) const;

	/** Middle of whatever is on screen, or of the bounds box when nothing is. */
	UFUNCTION(BlueprintCallable, Category = "DC|Slot")
	FVector GetContentCentre() const;

	// ---------------------------------------------------------------- lifecycle

	EDCSlotState GetState() const { return State; }
	double GetSecondsInState() const;

	/** What /changes says belongs here (empty before the first poll). */
	const FString& GetWantedAllocKey() const { return WantedAllocKey; }

	/** What is actually on screen. */
	const FString& GetActiveAllocKey() const { return ActiveAllocKey; }
	const FDCManifest& GetActiveManifest() const { return ActiveManifest; }

	bool HasContent() const { return Content.IsValid(); }
	bool IsPlayerInside() const { return bPlayerInside; }

	const FString& GetLastError() const { return LastError; }
	int32 GetAttempts() const { return Attempts; }

	/** "content1 v1 #E23D3D star" / "nothing yet" - for the status strip. */
	FString DescribeShowing() const;

	/** One line for the log and the status file. */
	FString DescribeState() const;

	// ---- called by UDCSubsystem -------------------------------------------------------

	void SetWantedAllocKey(const FString& Key) { WantedAllocKey = Key; }
	void SetState(EDCSlotState NewState);

	/** FALLBACK: keep (or re-spawn) what is up, remember why, and arm the backoff. */
	void EnterFallback(const FString& Reason, double NowSeconds, float BaseDelaySeconds, float MaxDelaySeconds);

	/** True when the backoff has run out and the slot should be tried again. */
	bool IsRetryDue(double NowSeconds) const;

	void ClearRetry() { Attempts = 0; RetryAtSeconds = 0.0; }

	/**
	 * The pack is mounted and the class is loaded: either put it on screen now, or hold it as
	 * SWAP PENDING because the Player is inside the bounds box. Returns true when it went on
	 * screen.
	 */
	bool ApplyOrHold(UClass* ContentClass, const FDCManifest& Manifest, FString& OutError);

	/** Spawn the held piece if the Player has left. Returns true when it went on screen. */
	bool ApplyPendingIfClear(FString& OutError);

	void DespawnContent();

	/** Seconds this slot's content has been on screen, within 30 m and in front of the camera. */
	float GetViewSeconds() const { return ViewSeconds; }
	bool HasReportedView() const { return bViewReported; }
	void MarkViewReported() { bViewReported = true; }

	/** Wall-clock UTC of the moment the piece that is up now went on screen. */
	const FDateTime& GetActiveSince() const { return ActiveSinceUtc; }

	float GetLastSpawnMs() const { return LastSpawnMs; }

	virtual void OnConstruction(const FTransform& Transform) override;
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void Tick(float DeltaSeconds) override;

protected:
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	TObjectPtr<USceneComponent> Anchor;

	/** The class limit box, i.e. the volume content must fit inside - and the "inside the
	 *  slot" test the swap waits on. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "DC|Slot")
	TObjectPtr<UBoxComponent> LimitsBox;

private:
	bool SpawnFromClass(UClass* ContentClass, const FDCManifest& Manifest, FString& OutError);
	void UpdatePlayerInside();
	void UpdateViewSeconds(float DeltaSeconds);

	EDCSlotState State = EDCSlotState::Idle;
	double StateEnteredSeconds = 0.0;

	FString WantedAllocKey;
	FString ActiveAllocKey;
	FDCManifest ActiveManifest;

	/** Ready and waiting for the Player to step out of the bounds box. */
	FDCManifest PendingManifest;
	bool bHasPending = false;

	UPROPERTY(Transient)
	TSubclassOf<AActor> PendingClass;

	TWeakObjectPtr<AActor> Content;

	FString LastError;
	int32 Attempts = 0;
	double RetryAtSeconds = 0.0;

	bool bPlayerInside = false;
	float ViewSeconds = 0.0f;
	bool bViewReported = false;
	float LastSpawnMs = 0.0f;
	FDateTime ActiveSinceUtc = FDateTime::MinValue();
};
