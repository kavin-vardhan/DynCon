// The pack round-trip driver (unreal_spec_v1 section 2): mount a pack from disk, load the
// Blueprint it contains, spawn it at a slot of a fitting size class, photograph it from
// outside and from inside, take it away again, and do the same for the next pack - all in one
// run of the packaged game, which contains none of them.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"

#include "DCSpikeGameMode.generated.h"

class ACameraActor;
class ADCContentActor;
class ADCSlot;

/** One "a pack arrives" step: where the pack is, what to spawn out of it, and how big it is. */
USTRUCT()
struct FDCSpikeStep
{
	GENERATED_BODY()

	FString PackDir;
	FString ClassPath;

	/** "S" / "L" / "T": which size class of slot this piece needs. Empty = first free slot. */
	FString SizeClass;
};

UCLASS()
class DYNAMICCONTENTS_API ADCSpikeGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	ADCSpikeGameMode();

	virtual void BeginPlay() override;

private:
	/**
	 * -DCMap=<package path>: travel there instead of running the spike.
	 *
	 * A Shipping build ignores a map named on the command line, so every run of the packaged
	 * game starts in GameDefaultMap - which is this map. Travelling out of it is a client
	 * travel, which is not gated, and it is how the runtime client's own map is reached.
	 * Returns true when it has started a travel and this game mode should do nothing else.
	 */
	bool RedirectToRequestedMap();

	/** -DCSpikeMount="<dir>[;<class path>[;<size class>]][+ ...]" */
	void ParseCommandLine();

	/**
	 * -DCCvars="r.Name=Value,r.Other=Value"
	 *
	 * A Shipping build has no console and ignores a user Engine.ini (writing one into the
	 * packaged build's Saved\Config\ does not set the variable - it stops the build rendering
	 * at all), so this is the only way to try a renderer setting without re-packaging. It is
	 * also how the booth PC will be tuned.
	 */
	void ApplyCvarOverrides();

	void Begin();

	/** mount -> load -> spawn, then line the outside shot up. */
	void RunStep();
	void TakeOutsideShot();
	void MoveCameraInside();
	void TakeInsideShot();
	void EndStep();
	void Finish();

	/**
	 * Three-quarter view from outside, framed on the piece that is actually there.
	 * Zoom < 1 moves in for a close-up (the second shot of a piece with no interior).
	 */
	void PointCameraOutside(const ADCSlot& Slot, const AActor* Content, float Zoom = 1.0f);

	/** Standing at SOCKET_Inside, looking at the screen. */
	bool PointCameraInside(const ADCContentActor& Content);

	ADCSlot* PickSlot(const FString& SizeClass) const;

	void SetCameraFov(float Degrees);

	void RequestShot(const TCHAR* Suffix);

	TArray<FDCSpikeStep> Steps;
	int32 StepIndex = 0;

	TArray<TWeakObjectPtr<ADCSlot>> Slots;
	TWeakObjectPtr<ACameraActor> Camera;

	/** The piece the current step spawned; destroyed before the next step starts. */
	TWeakObjectPtr<AActor> Spawned;

	/** Where the screenshots and the result file go. */
	FString ShotDir;

	/** One line per step, written to spike_result.txt at the end. */
	TArray<FString> Report;

	/** Shot file names for the step in progress, for the report line. */
	TArray<FString> StepShots;

	FTimerHandle Timer;
	double RunStart = 0.0;
	int32 StepsOk = 0;
};
