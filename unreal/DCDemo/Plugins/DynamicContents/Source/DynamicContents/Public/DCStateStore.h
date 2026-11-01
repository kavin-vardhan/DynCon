// What the Player did inside a piece of content, kept across a replacement.
//
// This is the patent's "post-deployment replacement without interrupting the player" promise
// in its smallest honest form (demo plan v6 §9, "State kept across an update"): a small record
// keyed by **slot + content id + schema version**, saved when a piece is unloaded and restored
// when any version of the same content is spawned into the same slot.
//
// Three rules, and they are the whole class:
//
//   * the key does **not** contain the version, because the point is that version 2 of the
//     same content picks up where version 1 left off;
//   * it does contain the slot, because the same content in another slot is another building;
//   * a record whose schema version does not match the piece being spawned is **discarded**,
//     never applied and never crashed on. v1 and v2 of everything in this demo share schema 1,
//     so the discard path is exercised by a test rather than by the demo - which is exactly
//     why it has to be written down.
//
// It lives on the game instance, so it survives a slot's content being destroyed and respawned
// as many times as the booth wants, and a booth reset clears it (UDCSubsystem does that when
// the server's reset generation changes).

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"

#include "DCStateStore.generated.h"

/**
 * Schema 1: the lights, the door and which image is on the screen.
 *
 * The names are the manifest's own `state_schema` list
 * (`light_a_on`, `light_b_on`, `door_open`, `screen_image_index`), so what the pack declares
 * and what the client keeps are the same four things.
 */
struct DYNAMICCONTENTS_API FDCContentState
{
	bool bLightAOn = true;
	bool bLightBOn = false;
	bool bDoorOpen = false;

	/** 1-based, into the base game's screen image set. 0 means "whatever the pack had". */
	int32 ScreenIndex = 1;

	bool operator==(const FDCContentState& Other) const
	{
		return bLightAOn == Other.bLightAOn && bLightBOn == Other.bLightBOn
			&& bDoorOpen == Other.bDoorOpen && ScreenIndex == Other.ScreenIndex;
	}
	bool operator!=(const FDCContentState& Other) const { return !(*this == Other); }

	/** "lights A on, B off, door closed, screen 1" - what the log and the report print. */
	FString Describe() const;
};

UCLASS()
class DYNAMICCONTENTS_API UDCStateStore : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	/** The store for whatever world this object is in, or nullptr. */
	static UDCStateStore* Get(const UObject* WorldContext);

	/** Keep what the Player did. Called the moment before a piece is destroyed. */
	void Save(const FString& SlotId, const FString& ContentId, int32 SchemaVersion,
		const FDCContentState& State);

	/**
	 * What the Player left in this slot, if it was this content and this schema.
	 *
	 * False means "nothing to restore" - either nothing was saved, or the saved record speaks
	 * a different schema, in which case it is thrown away here and now. The caller spawns the
	 * piece with its own defaults and carries on; nothing about a schema change is an error
	 * the visitor should ever see.
	 */
	bool Restore(const FString& SlotId, const FString& ContentId, int32 SchemaVersion,
		FDCContentState& OutState);

	/** True when there is a record for this slot and content, whatever its schema. */
	bool Has(const FString& SlotId, const FString& ContentId) const;

	/** A booth reset: the next visitor starts with nothing of the last one's. */
	void Clear(const FString& Why);

	int32 Num() const { return Entries.Num(); }

	/** One line per record, for the status file and the end-of-run report. */
	TArray<FString> DescribeAll() const;

	virtual void Deinitialize() override;

private:
	struct FEntry
	{
		int32 SchemaVersion = 1;
		FDCContentState State;
		FString SavedUtc;
		int32 Saves = 0;
		int32 Restores = 0;
	};

	static FString KeyFor(const FString& SlotId, const FString& ContentId);

	TMap<FString, FEntry> Entries;
};
