// The Player's side of "each piece of content has a few plain interactable things"
// (demo plan v6 §3): what is in reach, what the prompt says, and what pressing the button does.
//
// It is a component on the Player's pawn, added at runtime by ADCRuntimeGameMode, and it is
// entirely inside the plugin: a project that drops this plugin in gets working interaction
// without a line of its own Blueprint. The input is Enhanced Input, because a Shipping build
// with Enhanced Input on **does not process legacy key bindings at all**
// (UEnhancedPlayerInput::EvaluateInputComponentDelegates only looks at enhanced components,
// and debug key bindings are compiled out of Shipping) - so the component loads an input
// action and a mapping context by soft path, pushes its own UEnhancedInputComponent onto the
// player controller's input stack, and binds there.
//
// The keys themselves are **not** an asset: FKey's KeyName is a private UPROPERTY, so the
// editor's Python cannot build one, so the mapping context is made here at runtime with
// EKeys::E and EKeys::Gamepad_FaceButton_Bottom on it. Which is the better place for them
// anyway - the keys sit next to the binding that answers them.
//
// Command line:
//   -DCUseAction=<asset path>        the input action          (default /Game/Input/Actions/IA_DCUse)
//   -DCInteractContext=<asset path>  use this mapping context instead of the built-in keys
//   -DCInteractReach=<cm>            how near counts as in reach
//   -DCNoInteract                    no prompt and no binding at all

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "DCContentActor.h"
#include "UObject/SoftObjectPath.h"

#include "DCInteractor.generated.h"

class ADCSlot;
class APlayerController;
class UEnhancedInputComponent;
class UInputAction;
class UInputMappingContext;

/** What the Player could use right now, if anything. */
struct DYNAMICCONTENTS_API FDCInteractorTarget
{
	TWeakObjectPtr<ADCSlot> Slot;
	TWeakObjectPtr<ADCContentActor> Content;
	EDCInteraction Kind = EDCInteraction::None;
	FVector Location = FVector::ZeroVector;
	FString Prompt;
	float Distance = 0.0f;

	bool IsValid() const { return Kind != EDCInteraction::None && Content.IsValid(); }
};

UCLASS(ClassGroup = (DynamicContents), meta = (BlueprintSpawnableComponent))
class DYNAMICCONTENTS_API UDCInteractor : public UActorComponent
{
	GENERATED_BODY()

public:
	UDCInteractor();

	/** Put one on this pawn if it has not got one, and wire its input up. Returns it. */
	static UDCInteractor* EnsureOn(APawn* Pawn);

	/** The interactor on whatever pawn the first local player is driving, or nullptr. */
	static UDCInteractor* Find(const UObject* WorldContext);

	/** Loads the input assets and pushes an input component onto the controller's stack. */
	void BindInput();

	/** What the prompt is showing. ADCStatusHud draws it; a test reads it. */
	const FDCInteractorTarget& GetTarget() const { return Target; }

	/** "E / pad A" - what the prompt tells the Player to press. */
	const FString& GetKeyHint() const { return KeyHint; }

	/**
	 * Use whatever the prompt is showing. This is what the key and the pad button call.
	 * Returns false when nothing is in reach.
	 */
	UFUNCTION(BlueprintCallable, Category = "DynamicContents")
	bool TryUse();

	/** What the input action is bound to: Enhanced Input wants a void handler. */
	UFUNCTION()
	void OnUsePressed();

	/**
	 * Use one named thing, if it is in reach - the scripted exit test's door.
	 *
	 * It is not a short cut round the Player's path: the same reach test applies, the same
	 * ADCContentActor::Interact does the work, and the same interaction event is posted. What
	 * it skips is only *which of two things 38 cm apart the prompt happened to pick*, which
	 * is a matter of where a human's head is pointing and has nothing to prove.
	 */
	bool TryUseKind(EDCInteraction Kind);

	/** How many uses this component has made, by kind - the run report prints it. */
	int32 GetUseCount(EDCInteraction Kind) const;
	int32 GetTotalUses() const { return TotalUses; }

	/**
	 * How many times the prompt was already showing the thing TryUseKind went on to use.
	 * That is how a scripted run still says something about the *human* path.
	 */
	int32 GetPromptAgreed() const { return PromptAgreed; }
	int32 GetPromptChecked() const { return PromptChecked; }

	float GetReach() const { return Reach; }
	bool IsEnabled() const { return bEnabled; }

	/** Where to stand to use one thing on the content in a slot. False when there is none. */
	static bool GetStandPoint(const ADCSlot* Slot, EDCInteraction Kind, FVector& Out);

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void TickComponent(float DeltaSeconds, ELevelTick TickType,
		FActorComponentTickFunction* ThisTickFunction) override;

private:
	void UpdateTarget();
	bool Perform(ADCSlot* Slot, ADCContentActor* Content, EDCInteraction Kind);

	UPROPERTY(Transient)
	TObjectPtr<UEnhancedInputComponent> InputComp;

	UPROPERTY(Transient)
	TObjectPtr<UInputAction> UseAction;

	UPROPERTY(Transient)
	TObjectPtr<UInputMappingContext> Context;

	TWeakObjectPtr<APlayerController> Controller;

	FDCInteractorTarget Target;
	FString KeyHint = TEXT("E / pad A");
	/**
	 * 5 m. The place to stand to use a door is 2 m clear of the front of the piece, on its
	 * centre line, and the door itself is a metre or so off that line - and the walk that gets
	 * there accepts 1.1 m of slack. So a Player plainly standing at a door can be 4.3 m from
	 * the leaf. Inside, 5 m reaches both switches from the doorway and still leaves the screen
	 * on the far wall (7.5 m) out of it, which is what makes "walk across to the screen" a
	 * walk rather than a lean.
	 */
	float Reach = 500.0f;
	bool bEnabled = true;
	bool bBound = false;

	/** One counter per EDCInteraction, indexed by the enum itself. */
	int32 Uses[5] = { 0, 0, 0, 0, 0 };
	int32 TotalUses = 0;
	int32 PromptAgreed = 0;
	int32 PromptChecked = 0;
};
