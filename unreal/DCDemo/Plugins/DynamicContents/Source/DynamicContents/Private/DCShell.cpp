#include "DCShell.h"

#include "DCContentActor.h"
#include "DCInteractor.h"
#include "DCSlot.h"
#include "DCSubsystem.h"
#include "DynamicContents.h"

#include "Components/ActorComponent.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/LocalPlayer.h"
#include "Engine/Texture2D.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformTime.h"
#include "HttpModule.h"
#include "ImageUtils.h"
#include "InputAction.h"
#include "InputCoreTypes.h"
#include "InputMappingContext.h"
#include "Interfaces/IHttpResponse.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
	/** How long the black fade takes either side of a level load, and how long it is held. */
	constexpr float DCFadeSeconds = 0.5f;

	/** Black, with the line on it, before the load actually starts. Long enough that a
	 *  visitor reads the words and that a screenshot of them lands. */
	constexpr float DCFadeHoldSeconds = 0.9f;

	/** Above every other mapping context, because a menu eats the button. */
	constexpr int32 DCShellContextPriority = 20;

	/** The scripted run gives up on any one step after this. */
	constexpr float DCUiStepTimeout = 120.0f;
}

const TCHAR* DCShellModeName(EDCShellMode Mode)
{
	switch (Mode)
	{
	case EDCShellMode::Attract: return TEXT("ATTRACT");
	case EDCShellMode::Title:   return TEXT("TITLE");
	case EDCShellMode::Playing: return TEXT("PLAYING");
	case EDCShellMode::Paused:  return TEXT("PAUSED");
	case EDCShellMode::Boot:
	default:                    return TEXT("BOOT");
	}
}

UDCShell* UDCShell::Get(const UObject* WorldContext)
{
	if (WorldContext == nullptr || GEngine == nullptr)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContext,
		EGetWorldErrorMode::ReturnNull);
	UGameInstance* Instance = World ? World->GetGameInstance() : nullptr;
	return Instance ? Instance->GetSubsystem<UDCShell>() : nullptr;
}

void UDCShell::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	UiStarted = FPlatformTime::Seconds();
}

// ===================================================================== start

void UDCShell::Start()
{
	if (bStarted)
	{
		return;
	}
	bStarted = true;

	const TCHAR* Cmd = FCommandLine::Get();

	// On by default, and off whenever something else already owns the camera and the pawn.
	// Every test written before brief 018 passes one of those, so every one of them behaves
	// exactly as it did; the booth's start script passes none of them and gets the shell.
	bEnabled = !FParse::Param(Cmd, TEXT("DCPreview"))
		&& !FParse::Param(Cmd, TEXT("DCTour"))
		&& !FCString::Strifind(Cmd, TEXT("-DCTour="))
		&& !FCString::Strifind(Cmd, TEXT("-DCTourFor="))
		&& !FParse::Param(Cmd, TEXT("DCStateTest"))
		&& !FCString::Strifind(Cmd, TEXT("-DCStateTest="))
		&& !FParse::Param(Cmd, TEXT("DCAutoShot"))
		&& !FCString::Strifind(Cmd, TEXT("-DCShotDir="));
	if (FParse::Param(Cmd, TEXT("DCShell")))
	{
		bEnabled = true;
	}
	if (FParse::Param(Cmd, TEXT("DCNoShell")))
	{
		bEnabled = false;
	}

	FParse::Value(Cmd, TEXT("DCIdleAttract="), IdleTimeoutSeconds);
	FParse::Value(Cmd, TEXT("DCAttractDwell="), AttractDwellSeconds);
	AttractDwellSeconds = FMath::Max(AttractDwellSeconds, 1.0f);
	bXray = FParse::Param(Cmd, TEXT("DCXray"));

	FString MapA = TEXT("/Game/Maps/GameA");
	FString MapB = TEXT("/Game/Maps/GameB");
	FString Value;
	if (FParse::Value(Cmd, TEXT("DCMapA="), Value, false) && !Value.IsEmpty())
	{
		MapA = Value.TrimQuotes();
	}
	if (FParse::Value(Cmd, TEXT("DCMapB="), Value, false) && !Value.IsEmpty())
	{
		MapB = Value.TrimQuotes();
	}

	// No titles anywhere: a card says "Game A" and nothing else (the demo's no-names
	// rule), in English and nothing else (decided 2026-11-02). The picture on it is the
	// developer's own plan view of the map, which the slot-map tool captured and registered
	// with the platform.
	Cards.Reset();
	FDCGameCard A;
	A.Id = TEXT("A");
	A.Label = TEXT("Game A");
	A.MapPackage = MapA;
	Cards.Add(A);
	FDCGameCard B;
	B.Id = TEXT("B");
	B.Label = TEXT("Game B");
	B.MapPackage = MapB;
	Cards.Add(B);

	// Read straight off the command line rather than out of UDCSubsystem: this runs from
	// InitGame, which is before the game mode has started the subsystem, and asking it
	// then would get the default instead of what -DCGame= says.
	CurrentGame = TEXT("A");
	if (FParse::Value(Cmd, TEXT("DCGame="), Value, false) && !Value.IsEmpty())
	{
		CurrentGame = Value.TrimQuotes();
	}
	CardIndex = FMath::Max(0, Cards.IndexOfByPredicate(
		[this](const FDCGameCard& C) { return C.Id == CurrentGame; }));

	bUiTest = FParse::Param(Cmd, TEXT("DCUiTest"));
	if (FParse::Value(Cmd, TEXT("DCUiTest="), Value, false) && !Value.IsEmpty())
	{
		bUiTest = true;
		UiReportPath = FPaths::ConvertRelativePathToFull(Value.TrimQuotes());
	}
	if (bUiTest)
	{
		bEnabled = true;
		if (UiReportPath.IsEmpty())
		{
			UiReportPath = FPaths::ConvertRelativePathToFull(
				FPaths::ProjectSavedDir() / TEXT("dc_ui_test.json"));
		}
		IFileManager::Get().Delete(*UiReportPath, false, true, true);
	}

	FString StartIn = TEXT("attract");
	FParse::Value(Cmd, TEXT("DCStartIn="), StartIn, false);
	StartIn = StartIn.TrimQuotes().ToLower();

	DC_LOG(Log, TEXT("SHELL %s   start=%s  game=%s  maps A=%s B=%s  idle->attract %.0f s  "
		"attract dwell %.0f s  xray=%s  ui-test=%s"),
		bEnabled ? TEXT("on") : TEXT("off (a scripted run owns the camera)"),
		*StartIn, *CurrentGame, *MapA, *MapB, IdleTimeoutSeconds, AttractDwellSeconds,
		bXray ? TEXT("on") : TEXT("off"), bUiTest ? TEXT("yes") : TEXT("no"));

	if (!bEnabled)
	{
		Mode = EDCShellMode::Playing;        // the old behaviour: a Player, from the first frame
		return;
	}

	if (StartIn == TEXT("game"))
	{
		SetMode(EDCShellMode::Playing, TEXT("-DCStartIn=game"));
	}
	else if (StartIn == TEXT("title"))
	{
		SetMode(EDCShellMode::Title, TEXT("-DCStartIn=title"));
	}
	else
	{
		SetMode(EDCShellMode::Attract, TEXT("boot"));
	}
	// The card pictures are fetched from NotifyWorldReady, not here: the backend address
	// is the subsystem's, and the subsystem has not read the command line yet either.
}

void UDCShell::FetchCardArt(FDCGameCard& Card)
{
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (Subsystem == nullptr || Card.bArtRequested)
	{
		return;
	}
	Card.bArtRequested = true;

	// The developer's own picture of the developer's own map, coming back from the platform
	// it was registered with. It is the same PNG the portal's slot map draws, so the card and
	// the brand's map are the same thing, and nothing had to be authored twice.
	const FString Url = Subsystem->GetBackendUrl() + TEXT("/games/") + Card.Id + TEXT("/map");
	const FString Id = Card.Id;

	TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Request = FHttpModule::Get().CreateRequest();
	Request->SetURL(Url);
	Request->SetVerb(TEXT("GET"));
	Request->SetTimeout(15.0f);

	TWeakObjectPtr<UDCShell> Weak(this);
	Request->OnProcessRequestComplete().BindLambda(
		[Weak, Id](FHttpRequestPtr, FHttpResponsePtr Response, bool bOk)
		{
			UDCShell* Self = Weak.Get();
			if (Self == nullptr)
			{
				return;
			}
			if (!bOk || !Response.IsValid() || Response->GetResponseCode() != 200)
			{
				// Let the title menu ask again: a card with no picture on it is the one
				// part of the booth's front end a visitor is looking straight at.
				for (FDCGameCard& Card : Self->Cards)
				{
					if (Card.Id == Id)
					{
						Card.bArtRequested = false;
					}
				}
				DC_LOG(Warning, TEXT("TITLE  no card picture for game %s (ok=%s code=%d) - a "
					"plain panel for now; it will ask again"), *Id, bOk ? TEXT("y") : TEXT("n"),
					Response.IsValid() ? Response->GetResponseCode() : 0);
				return;
			}
			const TArray<uint8>& Bytes = Response->GetContent();
			UTexture2D* Texture = FImageUtils::ImportBufferAsTexture2D(Bytes);
			if (Texture == nullptr)
			{
				DC_LOG(Warning, TEXT("TITLE  game %s's card picture would not decode (%d B)"),
					*Id, Bytes.Num());
				return;
			}
			Texture->AddToRoot();            // nothing else owns it until the card does
			for (FDCGameCard& Card : Self->Cards)
			{
				if (Card.Id == Id)
				{
					Card.Art = Texture;
					Texture->RemoveFromRoot();     // the card owns it now
					DC_LOG(Log, TEXT("TITLE  game %s's card picture: %d x %d"), *Id,
						Texture->GetSizeX(), Texture->GetSizeY());
					break;
				}
			}
		});
	Request->ProcessRequest();
}

// ===================================================================== the modes

void UDCShell::SetMode(EDCShellMode New, const FString& Why)
{
	if (Mode == New)
	{
		return;
	}
	const EDCShellMode Was = Mode;
	Mode = New;
	IdleSeconds = 0.0f;
	InputLockSeconds = 0.22f;
	DC_LOG(Log, TEXT("SHELL %s -> %s   (%s)"), DCShellModeName(Was), DCShellModeName(New), *Why);
}

void UDCShell::EnterAttract(const FString& Why)
{
	if (!bEnabled)
	{
		return;
	}
	AttractElapsed = 0.0f;
	AttractIndex = 0;
	bAttractOverview = true;
	SetMode(EDCShellMode::Attract, Why);
}

void UDCShell::EnterTitle(const FString& Why)
{
	if (!bEnabled)
	{
		return;
	}
	CardIndex = FMath::Max(0, Cards.IndexOfByPredicate(
		[this](const FDCGameCard& C) { return C.Id == CurrentGame; }));
	for (FDCGameCard& Card : Cards)
	{
		if (Card.Art == nullptr)
		{
			FetchCardArt(Card);              // a no-op once it has one, or one is in flight
		}
	}
	SetMode(EDCShellMode::Title, Why);
}

void UDCShell::OpenPause()
{
	if (!bEnabled || Mode != EDCShellMode::Playing)
	{
		return;
	}
	PauseIndex = 0;
	SetMode(EDCShellMode::Paused, TEXT("Start on the player pad"));
}

void UDCShell::ClosePause()
{
	if (Mode == EDCShellMode::Paused)
	{
		SetMode(EDCShellMode::Playing, TEXT("resume"));
	}
}

void UDCShell::SetXray(bool bOn, const FString& Why)
{
	if (bXray == bOn)
	{
		return;
	}
	bXray = bOn;
	DC_LOG(Log, TEXT("XRAY  %s   (%s)"), bOn ? TEXT("on") : TEXT("off"), *Why);
}

FString UDCShell::GetOtherGame() const
{
	for (const FDCGameCard& Card : Cards)
	{
		if (Card.Id != CurrentGame)
		{
			return Card.Id;
		}
	}
	return CurrentGame;
}

FString UDCShell::GameLabel(const FString& GameId) const
{
	for (const FDCGameCard& Card : Cards)
	{
		if (Card.Id == GameId)
		{
			return Card.Label;
		}
	}
	return FString::Printf(TEXT("Game %s"), *GameId);
}

// ===================================================================== starting a game

void UDCShell::StartGame(const FString& GameId, const FString& Why)
{
	if (!bEnabled)
	{
		return;
	}
	if (GameId == CurrentGame)
	{
		// Already standing in this map: the Player walks in, and nothing is loaded. That is
		// the point of saying it out loud - picking the game that is up is not a level load.
		DC_LOG(Log, TEXT("SHELL game %s is already loaded - spawning the Player, no level "
			"load (%s)"), *GameId, *Why);
		SetMode(EDCShellMode::Playing, Why);
		return;
	}
	BeginSwitch(GameId, Why);
}

void UDCShell::BeginSwitch(const FString& GameId, const FString& Why)
{
	const FDCGameCard* Card = Cards.FindByPredicate(
		[&GameId](const FDCGameCard& C) { return C.Id == GameId; });
	if (Card == nullptr)
	{
		DC_LOG(Warning, TEXT("SHELL there is no game %s in this build"), *GameId);
		return;
	}

	PendingGame = GameId;
	PendingMap = Card->MapPackage;
	bSwitching = true;
	FadeDirection = 1;
	FadeText = FString::Printf(TEXT("Loading %s"), *Card->Label);

	DC_LOG(Log, TEXT("SWITCH game %s -> %s (%s): fading to black, then a level load. This is "
		"a **game** switch - plan v6 Â§3 allows it a loading screen; a **content** change "
		"never gets one, and the strip's two zeroes do not move."),
		*CurrentGame, *GameId, *Why);
}

void UDCShell::FinishSwitch()
{
	UWorld* World = GetGameInstance() ? GetGameInstance()->GetWorld() : nullptr;
	if (World == nullptr || PendingMap.IsEmpty())
	{
		bSwitching = false;
		FadeDirection = -1;
		return;
	}

	// The client has to be asking about the game it is about to be in before the new map's
	// slots register, or the first poll of the new world asks about the old game's slots.
	if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		Subsystem->SetGame(PendingGame, TEXT("the Player switched game"));
	}
	++GameSwitches;
	CurrentGame = PendingGame;
	CardIndex = FMath::Max(0, Cards.IndexOfByPredicate(
		[this](const FDCGameCard& C) { return C.Id == CurrentGame; }));

	DC_LOG(Log, TEXT("SWITCH loading %s (switch #%d). The game instance - and with it the "
		"pack cache, the mounted packs, the saved state, the uptime and this shell - lives "
		"through it."), *PendingMap, GameSwitches);

	const FString Map = PendingMap;
	PendingMap.Reset();
	PendingGame.Reset();

	// The map's own GameMode Override is what picks ADCRuntimeGameMode up, exactly as
	// -DCMap= does out of the default map a Shipping build always starts in.
	UGameplayStatics::OpenLevel(World, FName(*Map), true,
		TEXT("game=/Script/DynamicContents.DCRuntimeGameMode"));
}

void UDCShell::NotifyWorldReady(const FString& MapName)
{
	if (!bEnabled)
	{
		return;
	}
	// The backend address is known by now (the game mode starts the subsystem just before
	// this), so this is the first moment the card pictures can be asked for.
	for (FDCGameCard& Card : Cards)
	{
		FetchCardArt(Card);
	}
	if (bSwitching)
	{
		// The new world is up. Fade back in and put the Player straight into it: a visitor
		// who chose "switch game" has already made their choice.
		bSwitching = false;
		bTravelling = false;
		FadeAlpha = 1.0f;
		FadeDirection = -1;
		SetMode(EDCShellMode::Playing, TEXT("the other game finished loading"));
		DC_LOG(Log, TEXT("SWITCH %s is up"), *MapName);
	}
}

// ===================================================================== the pad

void UDCShell::AnyButton(const TCHAR* What)
{
	if (!bEnabled)
	{
		return;
	}
	IdleSeconds = 0.0f;                      // always, lock or no lock
	if (InputLockSeconds > 0.0f)
	{
		return;
	}
	if (Mode == EDCShellMode::Attract && !bSwitching)
	{
		DC_LOG(Log, TEXT("SHELL %s on the player pad - leaving the attract loop"), What);
		EnterTitle(TEXT("a button on the player pad"));
	}
}

void UDCShell::NavVertical(int32 Delta)
{
	if (!bEnabled || Delta == 0 || InputLockSeconds > 0.0f)
	{
		return;
	}
	if (Mode == EDCShellMode::Paused)
	{
		const int32 Count = static_cast<int32>(EDCPauseItem::MAX_None);
		PauseIndex = (PauseIndex + Delta + Count) % Count;
	}
}

void UDCShell::NavHorizontal(int32 Delta)
{
	if (!bEnabled || Delta == 0 || Cards.Num() == 0 || InputLockSeconds > 0.0f)
	{
		return;
	}
	if (Mode == EDCShellMode::Title)
	{
		CardIndex = (CardIndex + Delta + Cards.Num()) % Cards.Num();
	}
}

void UDCShell::Confirm()
{
	if (!bEnabled || bSwitching || InputLockSeconds > 0.0f)
	{
		return;
	}
	if (Mode == EDCShellMode::Title)
	{
		if (Cards.IsValidIndex(CardIndex))
		{
			StartGame(Cards[CardIndex].Id, TEXT("picked on the title menu"));
		}
		return;
	}
	if (Mode == EDCShellMode::Paused)
	{
		switch (static_cast<EDCPauseItem>(PauseIndex))
		{
		case EDCPauseItem::Resume:
			ClosePause();
			return;
		case EDCPauseItem::SwitchGame:
			BeginSwitch(GetOtherGame(), TEXT("switch game, from the pause menu"));
			return;
		case EDCPauseItem::Xray:
			SetXray(!bXray, TEXT("the pause menu"));
			return;
		default:
			return;
		}
	}
}

void UDCShell::Cancel()
{
	if (!bEnabled || InputLockSeconds > 0.0f)
	{
		return;
	}
	if (Mode == EDCShellMode::Paused)
	{
		ClosePause();
	}
	else if (Mode == EDCShellMode::Title)
	{
		// Backing out of the title menu goes back to the loop, not to nothing.
		EnterAttract(TEXT("backed out of the title menu"));
	}
}

void UDCShell::PauseButton()
{
	if (!bEnabled || InputLockSeconds > 0.0f)
	{
		return;
	}
	if (Mode == EDCShellMode::Playing)
	{
		OpenPause();
	}
	else if (Mode == EDCShellMode::Paused)
	{
		ClosePause();
	}
	else if (Mode == EDCShellMode::Attract)
	{
		EnterTitle(TEXT("Start on the player pad"));
	}
}

void UDCShell::XrayButton()
{
	if (!bEnabled || InputLockSeconds > 0.0f)
	{
		return;
	}
	SetXray(!bXray, TEXT("View / Back on the player pad"));
}

// ===================================================================== per frame

void UDCShell::TickShell(float DeltaSeconds)
{
	if (!bEnabled)
	{
		return;
	}
	InputLockSeconds = FMath::Max(0.0f, InputLockSeconds - DeltaSeconds);

	// ---- the fade, and the level load in the middle of it
	if (bSwitching && !bTravelling)
	{
		FadeAlpha = FMath::Min(1.0f, FadeAlpha + DeltaSeconds / DCFadeSeconds);
		if (FadeAlpha >= 1.0f)
		{
			// Hold full black with the line on it: long enough for a visitor to read it, and
			// long enough for a screenshot of it to land before the world is torn down.
			FadeDirection = 0;
			FadeHeldSeconds += DeltaSeconds;
			if (bUiTest && !UiShots.Contains(TEXT("05_loading")) && FadeHeldSeconds > 0.2f)
			{
				if (OnShot.IsBound() && OnShot.Execute(TEXT("05_loading")))
				{
					UiShots.Add(TEXT("05_loading"));
				}
			}
			if (FadeHeldSeconds >= DCFadeHoldSeconds)
			{
				FadeHeldSeconds = 0.0f;
				bTravelling = true;          // OpenLevel travels at the end of the frame,
				FinishSwitch();              // and this tick runs again before it does
				return;
			}
		}
		return;                              // nothing else moves while the screen is black
	}
	if (bTravelling)
	{
		return;
	}
	if (FadeDirection < 0)
	{
		FadeAlpha = FMath::Max(0.0f, FadeAlpha - DeltaSeconds / DCFadeSeconds);
		if (FadeAlpha <= 0.0f)
		{
			FadeDirection = 0;
		}
	}

	// ---- the idle clock. Plan v6 Â§4 step 0: 90 s of an untouched player pad and the booth
	// goes back to the loop. The attract loop itself cannot time out of anything.
	if (Mode == EDCShellMode::Playing || Mode == EDCShellMode::Paused
		|| Mode == EDCShellMode::Title)
	{
		IdleSeconds += DeltaSeconds;
		if (IdleTimeoutSeconds > 0.0f && IdleSeconds >= IdleTimeoutSeconds && !bSwitching)
		{
			DC_LOG(Log, TEXT("SHELL the player pad has been untouched for %.0f s"), IdleSeconds);
			EnterAttract(TEXT("the player pad went quiet"));
		}
	}

	// ---- the attract camera's rota (the camera itself is the game mode's)
	if (Mode == EDCShellMode::Attract && !bSwitching)
	{
		AttractElapsed += DeltaSeconds;
	}

	if (bUiTest)
	{
		TickUiTest(DeltaSeconds);
	}
}

ADCSlot* UDCShell::AttractFocusSlot(const TArray<ADCSlot*>& Slots)
{
	if (Slots.Num() == 0)
	{
		bAttractOverview = true;
		return nullptr;
	}

	// One leg of the map from above, then every slot in turn, then round again. The camera
	// is a visitor walking the map without a body: it is in front of whatever is standing
	// there *now*, so when a block rolls over or a rival takes a slot the loop shows it.
	const int32 Legs = Slots.Num() + 1;
	if (AttractElapsed >= AttractDwellSeconds)
	{
		AttractElapsed = 0.0f;
		AttractIndex = (AttractIndex + 1) % Legs;
	}
	bAttractOverview = AttractIndex == 0;
	if (bAttractOverview)
	{
		return nullptr;
	}
	return Slots[FMath::Clamp(AttractIndex - 1, 0, Slots.Num() - 1)];
}

// ===================================================================== the scripted run
//
// Brief 018's exit test, in the game, because half of it is on the other side of a level
// load: boot -> attract -> a button -> the title menu -> Game B -> walk to B1 -> pause ->
// X-ray -> switch to Game A -> walk into A1 and change what is inside it -> switch to B and
// back -> A1 is as it was left -> the idle timeout -> attract.
//
// It presses what a visitor presses: every step below calls the same Confirm / NavHorizontal
// / PauseButton / AnyButton that `UDCShellInput` binds the pad and the keyboard to. What it
// does **not** simulate is the pad driver itself; `-DCUiTest` is a test hook, not a fake
// gamepad, and the report says so.

namespace
{
	enum class EDCUiStep : uint8
	{
		WaitForContent,
		ShotAttract,
		PressAnyButton,
		ShotTitle,
		PickGameB,
		WaitGameB,
		WalkToB1,
		PauseForXray,
		XrayOn,
		ShotXrayMenu,
		ResumeFromPause,
		ShotXrayWorld,
		PauseToSwitchA,
		SwitchToA,
		WaitGameA,
		WalkToA1Door,
		OpenA1Door,
		WalkIntoA1,
		LightsOnInA1,
		WalkToScreenInA1,
		ScreenOnInA1,
		ShotA1Set,
		PauseToSwitchB,
		SwitchToB,
		WaitGameB2,
		PauseToSwitchBackA,
		SwitchBackToA,
		WaitGameA2,
		WalkBackToA1,
		CheckKeptState,
		ShotA1Back,
		WaitForIdle,
		ShotAttractAgain,
		Done
	};

	const TCHAR* UiStepName(EDCUiStep Step)
	{
		switch (Step)
		{
		case EDCUiStep::WaitForContent:    return TEXT("wait for the backend to fill the slots");
		case EDCUiStep::ShotAttract:       return TEXT("attract");
		case EDCUiStep::PressAnyButton:    return TEXT("a button on the player pad");
		case EDCUiStep::ShotTitle:         return TEXT("the title menu");
		case EDCUiStep::PickGameB:         return TEXT("pick Game B");
		case EDCUiStep::WaitGameB:         return TEXT("Game B is up");
		case EDCUiStep::WalkToB1:          return TEXT("walk to B1");
		case EDCUiStep::PauseForXray:      return TEXT("pause");
		case EDCUiStep::XrayOn:            return TEXT("X-ray on");
		case EDCUiStep::ShotXrayMenu:      return TEXT("the X-ray with the pause menu");
		case EDCUiStep::ResumeFromPause:   return TEXT("resume");
		case EDCUiStep::ShotXrayWorld:     return TEXT("the X-ray from third person");
		case EDCUiStep::PauseToSwitchA:    return TEXT("pause again");
		case EDCUiStep::SwitchToA:         return TEXT("switch to Game A");
		case EDCUiStep::WaitGameA:         return TEXT("Game A is up");
		case EDCUiStep::WalkToA1Door:      return TEXT("walk to A1's door");
		case EDCUiStep::OpenA1Door:        return TEXT("open A1's door");
		case EDCUiStep::WalkIntoA1:        return TEXT("walk into A1");
		case EDCUiStep::LightsOnInA1:      return TEXT("lights B on in A1");
		case EDCUiStep::WalkToScreenInA1:  return TEXT("walk across to A1's screen");
		case EDCUiStep::ScreenOnInA1:      return TEXT("the screen on in A1");
		case EDCUiStep::ShotA1Set:         return TEXT("A1 as the Player leaves it");
		case EDCUiStep::PauseToSwitchB:    return TEXT("pause");
		case EDCUiStep::SwitchToB:         return TEXT("switch to Game B");
		case EDCUiStep::WaitGameB2:        return TEXT("Game B is up again");
		case EDCUiStep::PauseToSwitchBackA: return TEXT("pause");
		case EDCUiStep::SwitchBackToA:     return TEXT("switch back to Game A");
		case EDCUiStep::WaitGameA2:        return TEXT("Game A is up again");
		case EDCUiStep::WalkBackToA1:      return TEXT("walk back into A1");
		case EDCUiStep::CheckKeptState:    return TEXT("A1 is as it was left");
		case EDCUiStep::ShotA1Back:        return TEXT("A1 on the way back");
		case EDCUiStep::WaitForIdle:       return TEXT("the idle timeout");
		case EDCUiStep::ShotAttractAgain:  return TEXT("attract again");
		case EDCUiStep::Done:
		default:                           return TEXT("done");
		}
	}

	/** What the Player leaves behind in A1, and what has to come back. */
	constexpr bool DCUiWantLightB = true;
	constexpr int32 DCUiWantScreen = 3;
}

void UDCShell::UiStep(const TCHAR* What)
{
	const double Now = FPlatformTime::Seconds();
	UiLog.Add(FString::Printf(TEXT("%6.1f s  step %2d  %s"), Now - UiStarted, UiStepIndex, What));
	DC_LOG(Log, TEXT("UITEST step %d: %s"), UiStepIndex, What);
	++UiStepIndex;
	UiStepStarted = Now;
}

void UDCShell::UiFail(const FString& Why)
{
	UiProblems.Add(Why);
	DC_LOG(Error, TEXT("UITEST %s"), *Why);
}

void UDCShell::TickUiTest(float DeltaSeconds)
{
	if (bUiDone)
	{
		return;
	}
	if (UiWait > 0.0f)
	{
		UiWait -= DeltaSeconds;
		return;
	}
	if (bSwitching)
	{
		return;                              // the fade and the load run themselves
	}

	const double Now = FPlatformTime::Seconds();
	if (UiStepStarted <= 0.0)
	{
		UiStepStarted = Now;
		UiStarted = Now;
	}
	const EDCUiStep Step = static_cast<EDCUiStep>(FMath::Min<int32>(UiStepIndex,
		static_cast<int32>(EDCUiStep::Done)));

	// The scripted run holds the idle clock down until the step that is *about* the idle
	// clock. Otherwise the shortened timeout the runner passes (so the last step takes
	// seconds rather than a minute and a half) would fire in the middle of a walk.
	if (Step != EDCUiStep::WaitForIdle)
	{
		IdleSeconds = 0.0f;
	}

	if (Step != EDCUiStep::Done && Now - UiStepStarted > DCUiStepTimeout)
	{
		UiFail(FString::Printf(TEXT("step %d (%s) never finished - giving up on it"),
			UiStepIndex, UiStepName(Step)));
		UiStep(UiStepName(Step));
		return;
	}

	UWorld* World = GetGameInstance() ? GetGameInstance()->GetWorld() : nullptr;
	UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (World == nullptr || Subsystem == nullptr)
	{
		return;
	}

	auto SlotNamed = [Subsystem](const TCHAR* Id) -> ADCSlot*
	{
		for (ADCSlot* Slot : Subsystem->GetSlots())
		{
			if (Slot->SlotId.ToString() == Id)
			{
				return Slot;
			}
		}
		return nullptr;
	};
	auto EverySlotFull = [Subsystem]() -> bool
	{
		const TArray<ADCSlot*> Slots = Subsystem->GetSlots();
		if (Slots.Num() == 0)
		{
			return false;
		}
		for (const ADCSlot* Slot : Slots)
		{
			if (!Slot->HasContent())
			{
				return false;
			}
		}
		return true;
	};
	auto Shot = [this](const TCHAR* Label) -> bool
	{
		if (!OnShot.IsBound())
		{
			return true;
		}
		if (OnShot.Execute(Label))
		{
			UiShots.Add(Label);
			return true;
		}
		return false;
	};

	switch (Step)
	{
	case EDCUiStep::WaitForContent:
		if (EverySlotFull() && Mode == EDCShellMode::Attract && Now - UiStarted > 14.0)
		{
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::ShotAttract:
		if (Mode != EDCShellMode::Attract)
		{
			UiFail(TEXT("the booth did not boot into the attract loop"));
		}
		Shot(TEXT("01_attract"));
		UiWait = 1.0f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::PressAnyButton:
		AnyButton(TEXT("the scripted run"));
		if (Mode != EDCShellMode::Title)
		{
			UiFail(TEXT("a button on the player pad did not open the title menu"));
		}
		UiWait = 0.8f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::ShotTitle:
		Shot(TEXT("02_title"));
		UiWait = 0.8f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::PickGameB:
	{
		int32 Guard = 0;
		while (Cards.IsValidIndex(CardIndex) && Cards[CardIndex].Id != TEXT("B") && Guard++ < 4)
		{
			NavHorizontal(1);
		}
		if (!Cards.IsValidIndex(CardIndex) || Cards[CardIndex].Id != TEXT("B"))
		{
			UiFail(TEXT("the title menu's cursor would not land on Game B"));
		}
		Confirm();
		UiStep(UiStepName(Step));
		return;
	}

	case EDCUiStep::WaitGameB:
		if (CurrentGame == TEXT("B") && Mode == EDCShellMode::Playing && FadeAlpha <= 0.01f
			&& EverySlotFull())
		{
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::WalkToB1:
		if (!OnWalkToSlot.IsBound() || OnWalkToSlot.Execute(TEXT("B1:door")))
		{
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::PauseForXray:
		PauseButton();
		if (Mode != EDCShellMode::Paused)
		{
			UiFail(TEXT("Start did not open the pause menu"));
		}
		UiWait = 0.6f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::XrayOn:
		PauseIndex = static_cast<int32>(EDCPauseItem::Xray);
		Confirm();
		if (!bXray)
		{
			UiFail(TEXT("the pause menu's X-ray item did not turn it on"));
		}
		UiWait = 1.0f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::ShotXrayMenu:
		Shot(TEXT("03_xray_pause"));
		UiWait = 1.0f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::ResumeFromPause:
		PauseIndex = static_cast<int32>(EDCPauseItem::Resume);
		Confirm();
		UiWait = 1.2f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::ShotXrayWorld:
		Shot(TEXT("04_xray_world"));
		UiWait = 1.0f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::PauseToSwitchA:
		PauseButton();
		UiWait = 0.6f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::SwitchToA:
		PauseIndex = static_cast<int32>(EDCPauseItem::SwitchGame);
		Confirm();
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::WaitGameA:
		if (CurrentGame == TEXT("A") && Mode == EDCShellMode::Playing && FadeAlpha <= 0.01f
			&& EverySlotFull())
		{
			if (!UiShots.Contains(TEXT("05_loading")))
			{
				UiFail(TEXT("no picture of the loading line was taken"));
			}
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::WalkToA1Door:
		if (!OnWalkToSlot.IsBound() || OnWalkToSlot.Execute(TEXT("A1:door")))
		{
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::OpenA1Door:
	{
		ADCSlot* Slot = SlotNamed(TEXT("A1"));
		const ADCContentActor* Built = Slot
			? Cast<ADCContentActor>(Slot->GetContentActor()) : nullptr;
		if (Built != nullptr && !Built->bDoorOpen && OnUse.IsBound())
		{
			// Keep pressing until it takes. A door that did not open is not a small
			// failure: the next step walks through where it would have been, gets stuck
			// on a closed leaf, and every step after it fails for the wrong reason.
			OnUse.Execute(static_cast<int32>(EDCInteraction::Door));
			UiWait = 0.6f;
			return;
		}
		if (Built == nullptr || !Built->bDoorOpen)
		{
			UiFail(TEXT("A1's door would not open"));
		}
		UiWait = 1.0f;                       // let the leaf finish its swing
		UiStep(UiStepName(Step));
		return;
	}

	case EDCUiStep::WalkIntoA1:
		if (!OnWalkToSlot.IsBound() || OnWalkToSlot.Execute(TEXT("A1:inside")))
		{
			UiWait = 1.2f;
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::LightsOnInA1:
	{
		ADCSlot* Slot = SlotNamed(TEXT("A1"));
		ADCContentActor* Built = Slot ? Cast<ADCContentActor>(Slot->GetContentActor()) : nullptr;
		if (Built != nullptr && Built->bLightBOn != DCUiWantLightB && OnUse.IsBound())
		{
			OnUse.Execute(static_cast<int32>(EDCInteraction::LightB));
			UiWait = 0.5f;
			return;                          // try again next tick until it took
		}
		if (Built == nullptr || Built->bLightBOn != DCUiWantLightB)
		{
			UiFail(TEXT("the wall-lamp switch in A1 would not go on"));
		}
		UiStep(UiStepName(Step));
		return;
	}

	case EDCUiStep::WalkToScreenInA1:
		// The interactor's five-metre reach is deliberately short of the screen on the far
		// wall (DCInteractor.h): "walk across to the screen" is a walk, not a lean. So the
		// scripted run walks it, exactly as the state exit test does.
		if (!OnWalkToSlot.IsBound() || OnWalkToSlot.Execute(TEXT("A1:screen")))
		{
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::ScreenOnInA1:
	{
		ADCSlot* Slot = SlotNamed(TEXT("A1"));
		ADCContentActor* Built = Slot ? Cast<ADCContentActor>(Slot->GetContentActor()) : nullptr;
		if (Built != nullptr && Built->ScreenIndex != DCUiWantScreen && OnUse.IsBound())
		{
			OnUse.Execute(static_cast<int32>(EDCInteraction::Screen));
			UiWait = 0.4f;
			return;
		}
		if (Built == nullptr || Built->ScreenIndex != DCUiWantScreen)
		{
			UiFail(TEXT("the screen in A1 would not reach image 3"));
		}
		UiStep(UiStepName(Step));
		return;
	}

	case EDCUiStep::ShotA1Set:
		Shot(TEXT("06_a1_as_left"));
		UiWait = 1.0f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::PauseToSwitchB:
	case EDCUiStep::PauseToSwitchBackA:
		PauseButton();
		UiWait = 0.5f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::SwitchToB:
	case EDCUiStep::SwitchBackToA:
		PauseIndex = static_cast<int32>(EDCPauseItem::SwitchGame);
		Confirm();
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::WaitGameB2:
		if (CurrentGame == TEXT("B") && Mode == EDCShellMode::Playing && FadeAlpha <= 0.01f)
		{
			UiWait = 2.0f;
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::WaitGameA2:
		if (CurrentGame == TEXT("A") && Mode == EDCShellMode::Playing && FadeAlpha <= 0.01f
			&& EverySlotFull())
		{
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::WalkBackToA1:
		if (!OnWalkToSlot.IsBound() || OnWalkToSlot.Execute(TEXT("A1:inside")))
		{
			UiWait = 1.5f;              // let the camera settle before the shutter
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::CheckKeptState:
	{
		ADCSlot* Slot = SlotNamed(TEXT("A1"));
		const ADCContentActor* Built = Slot
			? Cast<ADCContentActor>(Slot->GetContentActor()) : nullptr;
		if (Built == nullptr)
		{
			UiFail(TEXT("there is nothing in A1 after coming back"));
		}
		else
		{
			UiLog.Add(FString::Printf(TEXT("        A1 came back as: %s"),
				*Built->GetContentState().Describe()));
			if (Built->bLightBOn != DCUiWantLightB)
			{
				UiFail(TEXT("A1's wall lamps are not as the Player left them"));
			}
			if (Built->ScreenIndex != DCUiWantScreen)
			{
				UiFail(FString::Printf(
					TEXT("A1's screen came back on image %d, not %d"),
					Built->ScreenIndex, DCUiWantScreen));
			}
			if (!Built->bDoorOpen)
			{
				UiFail(TEXT("A1's door is not as the Player left it"));
			}
		}
		UiStep(UiStepName(Step));
		return;
	}

	case EDCUiStep::ShotA1Back:
		Shot(TEXT("07_a1_as_found"));
		UiWait = 1.0f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::WaitForIdle:
		if (Mode == EDCShellMode::Attract)
		{
			UiWait = 3.0f;
			UiStep(UiStepName(Step));
		}
		return;

	case EDCUiStep::ShotAttractAgain:
		Shot(TEXT("08_attract_again"));
		UiWait = 1.0f;
		UiStep(UiStepName(Step));
		return;

	case EDCUiStep::Done:
	default:
		bUiDone = true;
		WriteUiReport();
		return;
	}
}

void UDCShell::WriteUiReport()
{
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);

	FString Text;
	const TSharedRef<TJsonWriter<TCHAR>> W = TJsonWriterFactory<TCHAR>::Create(&Text);
	W->WriteObjectStart();
	W->WriteValue(TEXT("ok"), UiProblems.Num() == 0);
	W->WriteValue(TEXT("seconds"), FPlatformTime::Seconds() - UiStarted);
	W->WriteValue(TEXT("game_switches"), GameSwitches);
	W->WriteValue(TEXT("mode"), DCShellModeName(Mode));
	W->WriteValue(TEXT("xray"), bXray);
	if (Subsystem != nullptr)
	{
		W->WriteValue(TEXT("uptime_s"), Subsystem->GetUptimeSeconds());
		W->WriteValue(TEXT("restarts"), Subsystem->GetRestartCount());
		W->WriteValue(TEXT("content_loading_screens"), Subsystem->GetLoadingScreenCount());
		W->WriteValue(TEXT("packs_mounted"), Subsystem->GetMountedPackCount());
		W->WriteArrayStart(TEXT("strip"));
		for (const FString& Line : Subsystem->GetStatusLines())
		{
			W->WriteValue(Line);
		}
		W->WriteArrayEnd();
	}
	W->WriteArrayStart(TEXT("steps"));
	for (const FString& Line : UiLog)
	{
		W->WriteValue(Line);
	}
	W->WriteArrayEnd();
	W->WriteArrayStart(TEXT("shots"));
	for (const FString& Line : UiShots)
	{
		W->WriteValue(Line);
	}
	W->WriteArrayEnd();
	W->WriteArrayStart(TEXT("problems"));
	for (const FString& Line : UiProblems)
	{
		W->WriteValue(Line);
	}
	W->WriteArrayEnd();
	W->WriteObjectEnd();
	W->Close();

	FFileHelper::SaveStringToFile(Text, *UiReportPath,
		FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	DC_LOG(Log, TEXT("UITEST wrote %s - %d problem(s), %d shot(s), %d switch(es)"),
		*UiReportPath, UiProblems.Num(), UiShots.Num(), GameSwitches);
}

// =====================================================================================
// the pad and the emergency keyboard

UDCShellInput::UDCShellInput()
{
	PrimaryComponentTick.bCanEverTick = false;
}

UDCShellInput* UDCShellInput::EnsureOn(APlayerController* PC)
{
	if (PC == nullptr)
	{
		return nullptr;
	}
	if (UDCShellInput* Existing = PC->FindComponentByClass<UDCShellInput>())
	{
		Existing->BindInput();
		return Existing;
	}
	UDCShellInput* Made = NewObject<UDCShellInput>(PC, TEXT("DCShellInput"));
	Made->RegisterComponent();
	PC->AddInstanceComponent(Made);
	return Made;
}

void UDCShellInput::BeginPlay()
{
	Super::BeginPlay();
	BindInput();
}

UInputAction* UDCShellInput::MakeAction(const TCHAR* Name)
{
	UInputAction* Action = NewObject<UInputAction>(this, Name);
	Action->ValueType = EInputActionValueType::Boolean;
	Actions.Add(Action);
	return Action;
}

void UDCShellInput::BindInput()
{
	if (bBound)
	{
		return;
	}
	APlayerController* PC = Cast<APlayerController>(GetOwner());
	if (PC == nullptr || PC->GetLocalPlayer() == nullptr)
	{
		return;                              // the local player arrives a frame later
	}
	Controller = PC;

	// Built in code, not loaded: an input action with nothing on it but a name is not worth
	// an asset, FKey's KeyName is private so the editor's Python cannot build one anyway
	// (DCInteractor.h), and the keys belong next to the handler that answers them.
	Context = NewObject<UInputMappingContext>(this, TEXT("DCShellContext"));

	UInputAction* Up = MakeAction(TEXT("DCNavUp"));
	UInputAction* Down = MakeAction(TEXT("DCNavDown"));
	UInputAction* Left = MakeAction(TEXT("DCNavLeft"));
	UInputAction* Right = MakeAction(TEXT("DCNavRight"));
	UInputAction* Ok = MakeAction(TEXT("DCConfirm"));
	UInputAction* Back = MakeAction(TEXT("DCCancel"));
	UInputAction* Pause = MakeAction(TEXT("DCPause"));
	UInputAction* Xray = MakeAction(TEXT("DCXray"));
	UInputAction* Any = MakeAction(TEXT("DCAnyButton"));

	// The stick stands in for the d-pad, the way the pad helper does it for the portal.
	Context->MapKey(Up, EKeys::Gamepad_DPad_Up);
	Context->MapKey(Up, EKeys::Gamepad_LeftStick_Up);
	Context->MapKey(Up, EKeys::Up);
	Context->MapKey(Down, EKeys::Gamepad_DPad_Down);
	Context->MapKey(Down, EKeys::Gamepad_LeftStick_Down);
	Context->MapKey(Down, EKeys::Down);
	Context->MapKey(Left, EKeys::Gamepad_DPad_Left);
	Context->MapKey(Left, EKeys::Gamepad_LeftStick_Left);
	Context->MapKey(Left, EKeys::Left);
	Context->MapKey(Right, EKeys::Gamepad_DPad_Right);
	Context->MapKey(Right, EKeys::Gamepad_LeftStick_Right);
	Context->MapKey(Right, EKeys::Right);

	// The bottom face button is Cross on a DualShock and A on an Xbox pad: the one a visitor
	// presses without being told which it is. It is also the "use" button - the interactor
	// only answers it when something is in reach, and a menu is up or it is not.
	Context->MapKey(Ok, EKeys::Gamepad_FaceButton_Bottom);
	Context->MapKey(Ok, EKeys::Enter);
	Context->MapKey(Back, EKeys::Gamepad_FaceButton_Right);
	Context->MapKey(Pause, EKeys::Gamepad_Special_Right);        // Start / Options
	Context->MapKey(Pause, EKeys::Escape);
	Context->MapKey(Xray, EKeys::Gamepad_Special_Left);          // View / Share / Back
	Context->MapKey(Xray, EKeys::F2);

	// "Any button on the player pad" leaves the attract loop. Everything a thumb can land on
	// except the two triggers, which are axes and would fire on a resting finger.
	const FKey AnyKeys[] = {
		EKeys::Gamepad_FaceButton_Bottom, EKeys::Gamepad_FaceButton_Right,
		EKeys::Gamepad_FaceButton_Left, EKeys::Gamepad_FaceButton_Top,
		EKeys::Gamepad_Special_Left, EKeys::Gamepad_Special_Right,
		EKeys::Gamepad_LeftShoulder, EKeys::Gamepad_RightShoulder,
		EKeys::Gamepad_LeftThumbstick, EKeys::Gamepad_RightThumbstick,
		EKeys::Gamepad_DPad_Up, EKeys::Gamepad_DPad_Down,
		EKeys::Gamepad_DPad_Left, EKeys::Gamepad_DPad_Right,
		EKeys::Gamepad_LeftStick_Up, EKeys::Gamepad_LeftStick_Down,
		EKeys::Gamepad_LeftStick_Left, EKeys::Gamepad_LeftStick_Right,
		EKeys::Enter, EKeys::SpaceBar, EKeys::Escape,
		EKeys::Up, EKeys::Down, EKeys::Left, EKeys::Right };
	for (const FKey& Key : AnyKeys)
	{
		Context->MapKey(Any, Key);
	}

	if (UEnhancedInputLocalPlayerSubsystem* Input =
		ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
	{
		Input->AddMappingContext(Context, DCShellContextPriority);
	}
	else
	{
		DC_LOG(Warning, TEXT("SHELL no Enhanced Input subsystem - the menus will not answer "
			"the pad"));
	}

	InputComp = NewObject<UEnhancedInputComponent>(PC, TEXT("DCShellInputComp"));
	InputComp->RegisterComponent();
	InputComp->BindAction(Up, ETriggerEvent::Started, this, &UDCShellInput::OnUp);
	InputComp->BindAction(Down, ETriggerEvent::Started, this, &UDCShellInput::OnDown);
	InputComp->BindAction(Left, ETriggerEvent::Started, this, &UDCShellInput::OnLeft);
	InputComp->BindAction(Right, ETriggerEvent::Started, this, &UDCShellInput::OnRight);
	InputComp->BindAction(Ok, ETriggerEvent::Started, this, &UDCShellInput::OnConfirm);
	InputComp->BindAction(Back, ETriggerEvent::Started, this, &UDCShellInput::OnCancel);
	InputComp->BindAction(Pause, ETriggerEvent::Started, this, &UDCShellInput::OnPause);
	InputComp->BindAction(Xray, ETriggerEvent::Started, this, &UDCShellInput::OnXray);
	InputComp->BindAction(Any, ETriggerEvent::Started, this, &UDCShellInput::OnAnyButton);
	PC->PushInputComponent(InputComp);

	bBound = true;
	DC_LOG(Log, TEXT("SHELL pad and keyboard bound (priority %d): d-pad / stick, the bottom and right face buttons, Start and View; arrows, Enter, Esc, F2"
		"Start, View; arrows, Enter, Esc, F2"), DCShellContextPriority);
}

void UDCShellInput::EndPlay(const EEndPlayReason::Type Reason)
{
	if (APlayerController* PC = Controller.Get())
	{
		if (InputComp != nullptr)
		{
			PC->PopInputComponent(InputComp);
		}
		if (Context != nullptr && PC->GetLocalPlayer() != nullptr)
		{
			if (UEnhancedInputLocalPlayerSubsystem* Input =
				ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
			{
				Input->RemoveMappingContext(Context);
			}
		}
	}
	InputComp = nullptr;
	Super::EndPlay(Reason);
}

void UDCShellInput::OnUp()      { if (UDCShell* S = UDCShell::Get(this)) { S->NavVertical(-1); } }
void UDCShellInput::OnDown()    { if (UDCShell* S = UDCShell::Get(this)) { S->NavVertical(+1); } }
void UDCShellInput::OnLeft()    { if (UDCShell* S = UDCShell::Get(this)) { S->NavHorizontal(-1); } }
void UDCShellInput::OnRight()   { if (UDCShell* S = UDCShell::Get(this)) { S->NavHorizontal(+1); } }
void UDCShellInput::OnConfirm() { if (UDCShell* S = UDCShell::Get(this)) { S->Confirm(); } }
void UDCShellInput::OnCancel()  { if (UDCShell* S = UDCShell::Get(this)) { S->Cancel(); } }
void UDCShellInput::OnPause()   { if (UDCShell* S = UDCShell::Get(this)) { S->PauseButton(); } }
void UDCShellInput::OnXray()    { if (UDCShell* S = UDCShell::Get(this)) { S->XrayButton(); } }

void UDCShellInput::OnAnyButton()
{
	if (UDCShell* S = UDCShell::Get(this))
	{
		S->AnyButton(TEXT("a button"));
	}
}
