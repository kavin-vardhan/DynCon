// The pack round-trip spike driver (unreal_spec_v1 section 2): mount a pack from disk, load
// the Blueprint it contains, spawn it at a slot, screenshot, then do it again for the next
// pack - all in one run of the packaged game, which does not contain either pack.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"

#include "DCSpikeGameMode.generated.h"

class ACameraActor;
class ADCSlot;

/** One "a pack arrives" step: where the pack is, and what to spawn out of it. */
struct FDCSpikeStep
{
	FString PackDir;
	FString ClassPath;
};

UCLASS()
class DYNAMICCONTENTS_API ADCSpikeGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	ADCSpikeGameMode();

	virtual void BeginPlay() override;

private:
	/** -DCSpikeMount="<dir>[;<class path>][+<dir>[;<class path>]]" */
	void ParseCommandLine();

	void Begin();
	void RunStep();
	void TakeShot();
	void Finish();

	void PointCameraAt(const ADCSlot& Slot);

	TArray<FDCSpikeStep> Steps;
	int32 StepIndex = 0;

	TArray<TWeakObjectPtr<ADCSlot>> Slots;
	TWeakObjectPtr<ACameraActor> Camera;

	/** Where the screenshots and the result file go. */
	FString ShotDir;

	/** One line per step, written to spike_result.txt at the end. */
	TArray<FString> Report;

	FTimerHandle Timer;
	double RunStart = 0.0;
};
