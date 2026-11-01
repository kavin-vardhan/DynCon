// What the booth's left-hand screen does when nobody is inside a game yet: the attract loop,
// the title menu, the pause menu, and the one thing in this demo that really is a loading
// screen - switching from Game A to Game B.
//
// Plan v6 §3: "One packaged build, two maps. The Player picks a game from a title menu and
// can switch from the pause menu... Switching between the two games is a normal level load,
// because it is switching games. The promise being shown is that **content** changes never
// need one."
//
// So this class draws the line between the two kinds of change, and the status strip is the
// witness: `restarts: 0` and `content loading screens: 0` carry across a switch, because a
// switch is neither. The number of game switches is counted too, and shown only in the X-ray
// - putting it on the strip next to the two zeroes would invite the reading that it is one
// of them.
//
// It is a **game instance** subsystem, which is the whole trick: a level load destroys the
// world, the game mode, the HUD, the Player and every slot, and leaves the game instance
// alone. So the mode, the X-ray flag, the idle clock, the switch count, the pack cache, the
// mounted packs, the uptime and `UDCStateStore`'s record of what the Player did all live
// through a switch, and A -> B -> A finds A1 exactly as it was left.
//
// Command line (all optional):
//   -DCShell / -DCNoShell        force the shell on / off. It is on by default and off
//                                whenever a scripted run owns the camera (-DCTour,
//                                -DCStateTest, -DCPreview, -DCShotDir / -DCAutoShot), so
//                                every test written before brief 018 behaves as it did.
//   -DCStartIn=attract|title|game   where a run begins (default attract)
//   -DCIdleAttract=<seconds>     untouched player pad -> attract (default 90)
//   -DCMapA=<package path>  -DCMapB=<package path>
//   -DCAttractDwell=<seconds>    how long the attract camera lingers on one slot (default 14)
//   -DCXray                      start with the X-ray overlay on
//   -DCUiTest[=<path>]           brief 018's scripted menu run; writes its report there

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Subsystems/GameInstanceSubsystem.h"

#include "DCShell.generated.h"

class ADCSlot;
class UTexture2D;

/** Where the left-hand screen is. */
UENUM()
enum class EDCShellMode : uint8
{
	/** Before the first decision - one frame, at most. */
	Boot,
	/** Nobody is playing: the camera drifts over the map and lingers on each slot. */
	Attract,
	/** The two game cards. */
	Title,
	/** Somebody is playing. */
	Playing,
	/** Somebody is playing and the pause menu is up. The world keeps running. */
	Paused
};

DYNAMICCONTENTS_API const TCHAR* DCShellModeName(EDCShellMode Mode);

/** One card on the title menu. No titles, by CLAUDE.md rule 3: "Game A" and "ゲーム A". */
USTRUCT()
struct FDCGameCard
{
	GENERATED_BODY()

	UPROPERTY() FString Id;
	UPROPERTY() FString LabelEn;
	UPROPERTY() FString LabelJp;
	UPROPERTY() FString MapPackage;

	/** The plan view the developer's own slot-map tool captured and registered, fetched back
	 *  from the platform (`GET /games/<id>/map`). Null until it arrives, or for good if the
	 *  game was never registered - the card then draws as a plain tinted panel. */
	UPROPERTY() TObjectPtr<UTexture2D> Art;

	UPROPERTY() bool bArtRequested = false;
};

/** What the pause menu offers. */
UENUM()
enum class EDCPauseItem : uint8
{
	Resume,
	SwitchGame,
	Xray,
	MAX_None
};

UCLASS()
class DYNAMICCONTENTS_API UDCShell : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	static UDCShell* Get(const UObject* WorldContext);

	virtual void Initialize(FSubsystemCollectionBase& Collection) override;

	/** Reads the command line once. Safe to call from every map's BeginPlay. */
	void Start();
	bool IsEnabled() const { return bEnabled; }

	// ---------------------------------------------------------------- where we are

	EDCShellMode GetMode() const { return Mode; }
	bool IsPlayerWanted() const { return Mode == EDCShellMode::Playing || Mode == EDCShellMode::Paused; }
	bool IsMenuUp() const { return Mode == EDCShellMode::Title || Mode == EDCShellMode::Paused; }

	void EnterAttract(const FString& Why);
	void EnterTitle(const FString& Why);
	void ClosePause();
	void OpenPause();

	/** The title menu's choice. Reloads only when it is the other map. */
	void StartGame(const FString& GameId, const FString& Why);

	bool IsXray() const { return bXray; }
	void SetXray(bool bOn, const FString& Why);

	// ---------------------------------------------------------------- the pad

	/** Every one of these is what the pad's Enhanced Input binding calls, and what the
	 *  scripted run calls. There is one path, so a test presses what a visitor presses. */
	void NavVertical(int32 Delta);
	void NavHorizontal(int32 Delta);
	void Confirm();
	void Cancel();
	void PauseButton();
	void XrayButton();

	/** Any button at all: what leaves the attract loop, and what resets the idle clock. */
	void AnyButton(const TCHAR* What);

	// ---------------------------------------------------------------- per frame

	/** Called by ADCRuntimeGameMode::Tick. Idle clock, the fade, and the scripted run. */
	void TickShell(float DeltaSeconds);

	/** The game mode says "this world is mine now": which map, and whether it is a switch. */
	void NotifyWorldReady(const FString& MapName);

	// ---------------------------------------------------------------- what the HUD draws

	const TArray<FDCGameCard>& GetCards() const { return Cards; }
	int32 GetCardIndex() const { return CardIndex; }
	int32 GetPauseIndex() const { return PauseIndex; }

	/** 0 = clear, 1 = black. Covers the level load at both ends. */
	float GetFadeAlpha() const { return FadeAlpha; }
	const FString& GetFadeJp() const { return FadeJp; }
	const FString& GetFadeEn() const { return FadeEn; }

	/** Seconds of untouched pad before the attract loop takes over, and how many are left. */
	float GetIdleTimeout() const { return IdleTimeoutSeconds; }
	float GetIdleSeconds() const { return IdleSeconds; }

	const FString& GetCurrentGame() const { return CurrentGame; }
	int32 GetGameSwitchCount() const { return GameSwitches; }

	/** The other game, for "Switch game" - two games, so there is exactly one. */
	FString GetOtherGame() const;

	/** The label pair for a game id, for anything that has to name one. */
	void GetGameLabels(const FString& GameId, FString& OutJp, FString& OutEn) const;

	// ---------------------------------------------------------------- the attract camera

	/** Which slot the attract camera should be framing now; it moves on by itself. */
	ADCSlot* AttractFocusSlot(const TArray<ADCSlot*>& Slots);

	/** True while the attract camera should be showing the whole map rather than a slot. */
	bool IsAttractOverview() const { return bAttractOverview; }

	// ---------------------------------------------------------------- the scripted run

	bool IsUiTest() const { return bUiTest; }

	/** The game mode hands these over: it owns the pawn, the camera and the shutter. */
	DECLARE_DELEGATE_RetVal_OneParam(bool, FDCUiShot, const FString& /*label*/);
	FDCUiShot OnShot;

	DECLARE_DELEGATE_RetVal_OneParam(bool, FDCUiWalk, const FString& /*slot*/);
	FDCUiWalk OnWalkToSlot;

	DECLARE_DELEGATE_RetVal_OneParam(bool, FDCUiUse, int32 /*EDCInteraction*/);
	FDCUiUse OnUse;

private:
	void FetchCardArt(FDCGameCard& Card);
	void BeginSwitch(const FString& GameId, const FString& Why);
	void FinishSwitch();
	void SetMode(EDCShellMode New, const FString& Why);
	void TickUiTest(float DeltaSeconds);
	void UiStep(const TCHAR* What);
	void UiFail(const FString& Why);
	void WriteUiReport();

	bool bEnabled = false;
	bool bStarted = false;

	EDCShellMode Mode = EDCShellMode::Boot;
	bool bXray = false;

	UPROPERTY(Transient)
	TArray<FDCGameCard> Cards;

	int32 CardIndex = 0;
	int32 PauseIndex = 0;

	FString CurrentGame;
	int32 GameSwitches = 0;

	float IdleSeconds = 0.0f;
	float IdleTimeoutSeconds = 90.0f;

	/** The black fade either side of a level load. */
	float FadeAlpha = 0.0f;
	int32 FadeDirection = 0;             // -1 fading in (to clear), +1 fading out (to black)
	float FadeHeldSeconds = 0.0f;
	FString FadeJp;
	FString FadeEn;
	FString PendingGame;
	FString PendingMap;
	bool bSwitching = false;

	/** OpenLevel has been asked for; travel happens at the end of the frame. Without this
	 *  the hold would come round again next tick and ask for a second one. */
	bool bTravelling = false;

	/**
	 * A fifth of a second after any change of screen, during which a button does nothing.
	 *
	 * One press of ✕ fires two of this component's actions - "any button", which leaves
	 * the attract loop, and "confirm", which picks a card - and Enhanced Input does not
	 * promise which order they run in. Without this, the one press that was meant to open
	 * the title menu could also choose a game off it. It doubles as the debounce a booth
	 * needs anyway.
	 */
	float InputLockSeconds = 0.0f;

	/** The attract camera's rota. */
	float AttractDwellSeconds = 14.0f;
	float AttractElapsed = 0.0f;
	int32 AttractIndex = 0;
	bool bAttractOverview = true;

	// ---- the scripted run (brief 018's exit test)
	bool bUiTest = false;
	FString UiReportPath;
	int32 UiStepIndex = 0;
	double UiStepStarted = 0.0;
	double UiStarted = 0.0;
	float UiWait = 0.0f;
	bool bUiDone = false;
	TArray<FString> UiLog;
	TArray<FString> UiShots;
	TArray<FString> UiProblems;
};

// =====================================================================================

/**
 * The pad and the emergency keyboard, bound to the shell.
 *
 * A component on the **player controller**, not on the pawn: in the attract loop and on the
 * title menu there is no pawn at all, and the menus still have to answer the pad. Everything
 * is Enhanced Input for the reason in DCInteractor.h - a Shipping build with the Enhanced
 * Input plugin on processes no legacy key bindings whatsoever - and the actions are built in
 * code rather than loaded, because a UInputAction with nothing on it but a name is not worth
 * an asset and the keys belong next to the handler that answers them.
 *
 * Plan v6 §3 and §11: the menus are driven from **the player pad**; the keyboard under the
 * table is the emergency fallback and gets arrows, Enter and Esc.
 */
UCLASS(ClassGroup = (DynamicContents))
class DYNAMICCONTENTS_API UDCShellInput : public UActorComponent
{
	GENERATED_BODY()

public:
	UDCShellInput();

	/** Put one on this controller if it has not got one, and bind it. */
	static UDCShellInput* EnsureOn(class APlayerController* PC);

	void BindInput();

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
	UFUNCTION() void OnUp();
	UFUNCTION() void OnDown();
	UFUNCTION() void OnLeft();
	UFUNCTION() void OnRight();
	UFUNCTION() void OnConfirm();
	UFUNCTION() void OnCancel();
	UFUNCTION() void OnPause();
	UFUNCTION() void OnXray();
	UFUNCTION() void OnAnyButton();

	class UInputAction* MakeAction(const TCHAR* Name);

	UPROPERTY(Transient) TObjectPtr<class UEnhancedInputComponent> InputComp;
	UPROPERTY(Transient) TObjectPtr<class UInputMappingContext> Context;
	UPROPERTY(Transient) TArray<TObjectPtr<class UInputAction>> Actions;

	TWeakObjectPtr<APlayerController> Controller;
	bool bBound = false;
};
