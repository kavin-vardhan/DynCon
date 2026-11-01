#include "DCInteractor.h"

#include "DCShell.h"
#include "DCSlot.h"
#include "DCSubsystem.h"
#include "DynamicContents.h"

#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "Engine/Engine.h"
#include "Engine/LocalPlayer.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "InputAction.h"
#include "InputCoreTypes.h"
#include "InputMappingContext.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

namespace
{
	/** The action asset unreal\Tools\core_extras.py builds. A soft path: the plugin owns no
	 *  content of its own. The mapping context is built below instead of loaded - see
	 *  BindInput for why the keys cannot come from an asset built by editor Python. */
	const TCHAR* DCDefaultUseAction = TEXT("/Game/Input/Actions/IA_DCUse.IA_DCUse");

	/** Above everything the template adds, so "use" is never eaten by a movement mapping. */
	constexpr int32 DCContextPriority = 10;

	/**
	 * How much being off to one side counts against a thing when two are in reach.
	 *
	 * The two light switches are 38 cm apart on the same wall, so distance alone cannot tell
	 * them apart from a metre and a half away - but the angle between them from there is about
	 * 14 degrees, which is plenty. Score = distance x (1 + k(1 - cos)) therefore picks the one
	 * the Player is looking at, which is the one they think they are about to press.
	 */
	constexpr float DCAimWeight = 3.0f;

	/** Anything more than this far off the middle of the screen is not being looked at. */
	constexpr float DCAimMinCos = 0.25f;
}

UDCInteractor::UDCInteractor()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickInterval = 0.0f;
	bWantsInitializeComponent = false;
}

UDCInteractor* UDCInteractor::EnsureOn(APawn* Pawn)
{
	if (Pawn == nullptr)
	{
		return nullptr;
	}
	if (UDCInteractor* Existing = Pawn->FindComponentByClass<UDCInteractor>())
	{
		Existing->BindInput();
		return Existing;
	}
	UDCInteractor* Made = NewObject<UDCInteractor>(Pawn, TEXT("DCInteractor"));
	Made->RegisterComponent();
	Pawn->AddInstanceComponent(Made);
	return Made;
}

UDCInteractor* UDCInteractor::Find(const UObject* WorldContext)
{
	if (WorldContext == nullptr || GEngine == nullptr)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContext,
		EGetWorldErrorMode::ReturnNull);
	const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	return Pawn ? Pawn->FindComponentByClass<UDCInteractor>() : nullptr;
}

void UDCInteractor::BeginPlay()
{
	Super::BeginPlay();

	const TCHAR* Cmd = FCommandLine::Get();
	bEnabled = !FParse::Param(Cmd, TEXT("DCNoInteract"));
	float Value = 0.0f;
	if (FParse::Value(Cmd, TEXT("DCInteractReach="), Value) && Value > 10.0f)
	{
		Reach = Value;
	}

	BindInput();
}

void UDCInteractor::BindInput()
{
	if (bBound || !bEnabled)
	{
		return;
	}

	APawn* Pawn = Cast<APawn>(GetOwner());
	APlayerController* PC = Pawn ? Cast<APlayerController>(Pawn->GetController()) : nullptr;
	if (PC == nullptr)
	{
		return;                          // not possessed yet; ADCRuntimeGameMode calls again
	}
	Controller = PC;

	const TCHAR* Cmd = FCommandLine::Get();
	FString ActionPath = DCDefaultUseAction;
	FString ContextPath;
	FString Override;
	if (FParse::Value(Cmd, TEXT("DCUseAction="), Override, false) && !Override.IsEmpty())
	{
		ActionPath = Override.TrimQuotes();
	}
	if (FParse::Value(Cmd, TEXT("DCInteractContext="), Override, false) && !Override.IsEmpty())
	{
		ContextPath = Override.TrimQuotes();
	}

	UseAction = Cast<UInputAction>(FSoftObjectPath(ActionPath).TryLoad());
	if (UseAction == nullptr)
	{
		DC_LOG(Warning, TEXT("INTERACT %s would not load - nothing is bound, the prompt still "
			"draws"), *ActionPath);
		bBound = true;                   // do not try every frame
		return;
	}

	// The mapping context is **built here, not loaded**, unless a project names one.
	//
	// FKey's KeyName is a private UPROPERTY, so the editor's Python cannot construct an FKey
	// at all - unreal.Key("E") is "call() takes at most 0 arguments" - and
	// UInputMappingContext::MapKey needs one. Rather than hand-author an asset nobody can
	// rebuild, the two keys live here, next to the binding that answers them.
	FString KeyWords;
	if (!ContextPath.IsEmpty())
	{
		Context = Cast<UInputMappingContext>(FSoftObjectPath(ContextPath).TryLoad());
		KeyWords = ContextPath;
	}
	if (Context == nullptr)
	{
		Context = NewObject<UInputMappingContext>(this, TEXT("DCInteractContext"));
		// Keyboard, and the pad's bottom face button - A on an Xbox pad, Cross on a
		// DualShock: the button a visitor presses without being told which it is.
		Context->MapKey(UseAction, EKeys::E);
		Context->MapKey(UseAction, EKeys::Gamepad_FaceButton_Bottom);
		KeyWords = TEXT("built in code: E, Gamepad_FaceButton_Bottom");
	}
	if (UEnhancedInputLocalPlayerSubsystem* Input =
		ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
	{
		Input->AddMappingContext(Context, DCContextPriority);
	}
	else
	{
		DC_LOG(Warning, TEXT("INTERACT no Enhanced Input subsystem on this local player - "
			"the button will do nothing"));
	}

	// Our own component on the controller's input stack, rather than the pawn's: the pawn's
	// belongs to the game module's Blueprint and this plugin must not need to touch it.
	InputComp = NewObject<UEnhancedInputComponent>(PC, TEXT("DCInteractInput"));
	InputComp->RegisterComponent();
	InputComp->BindAction(UseAction, ETriggerEvent::Started, this, &UDCInteractor::OnUsePressed);
	PC->PushInputComponent(InputComp);

	bBound = true;
	DC_LOG(Log, TEXT("INTERACT bound %s (%s, priority %d), reach %.0f cm"),
		*UseAction->GetName(), *KeyWords, DCContextPriority, Reach);
}

void UDCInteractor::EndPlay(const EEndPlayReason::Type Reason)
{
	if (APlayerController* PC = Controller.Get())
	{
		if (InputComp != nullptr)
		{
			PC->PopInputComponent(InputComp);
		}
		if (Context != nullptr)
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

// --------------------------------------------------------------------------- what is in reach

void UDCInteractor::UpdateTarget()
{
	Target = FDCInteractorTarget();
	if (!bEnabled)
	{
		return;
	}

	// The title and pause menus answer the same button this does (✕ / A), so while one of
	// them is up there is nothing in reach: a visitor choosing "switch game" must not also
	// open the door they happen to be standing at.
	if (const UDCShell* Shell = UDCShell::Get(this))
	{
		if (Shell->IsMenuUp())
		{
			return;
		}
	}

	const APawn* Pawn = Cast<APawn>(GetOwner());
	const UWorld* World = GetWorld();
	const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (Pawn == nullptr || PC == nullptr)
	{
		return;
	}

	// The Player's own position decides what is in reach; where they are looking only breaks
	// a tie. A third-person camera is several metres behind the character, so measuring reach
	// from the camera would put the whole room out of it.
	const FVector Here = Pawn->GetActorLocation();
	FVector Eye;
	FRotator Look;
	PC->GetPlayerViewPoint(Eye, Look);
	const FVector Forward = Look.Vector();

	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (Subsystem == nullptr)
	{
		return;
	}

	float BestScore = TNumericLimits<float>::Max();
	TArray<FDCInteractionPoint> Points;
	for (ADCSlot* Slot : Subsystem->GetSlots())
	{
		ADCContentActor* Content = Cast<ADCContentActor>(Slot->GetContentActor());
		if (Content == nullptr)
		{
			continue;
		}
		Content->GetInteractionPoints(Points);
		for (const FDCInteractionPoint& Point : Points)
		{
			const float Distance = FVector::Dist(Here, Point.Location);
			if (Distance > Reach)
			{
				continue;
			}
			FVector ToPoint = Point.Location - Eye;
			const float Length = ToPoint.Size();
			const float Cos = Length > KINDA_SMALL_NUMBER
				? static_cast<float>(FVector::DotProduct(Forward, ToPoint / Length)) : 1.0f;
			if (Cos < DCAimMinCos)
			{
				continue;
			}
			const float Score = Distance * (1.0f + DCAimWeight * (1.0f - Cos));
			if (Score < BestScore)
			{
				BestScore = Score;
				Target.Slot = Slot;
				Target.Content = Content;
				Target.Kind = Point.Kind;
				Target.Location = Point.Location;
				Target.Prompt = Point.Prompt;
				Target.Distance = Distance;
			}
		}
	}
}

void UDCInteractor::TickComponent(float DeltaSeconds, ELevelTick TickType,
	FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaSeconds, TickType, ThisTickFunction);

	if (!bBound)
	{
		BindInput();
	}
	UpdateTarget();
}

// --------------------------------------------------------------------------- using

bool UDCInteractor::Perform(ADCSlot* Slot, ADCContentActor* Content, EDCInteraction Kind)
{
	if (Content == nullptr || !Content->Interact(Kind))
	{
		return false;
	}

	const int32 Index = static_cast<int32>(Kind);
	if (Index >= 0 && Index < UE_ARRAY_COUNT(Uses))
	{
		++Uses[Index];
	}
	++TotalUses;

	// Every use is an interaction event (plan v6 §9). The slot and the allocation key are what
	// turns it into "this campaign's content was used", which is what the report counts.
	if (UDCSubsystem* Subsystem = UDCSubsystem::Get(this))
	{
		Subsystem->QueueTelemetry(TEXT("interaction"),
			Slot ? Slot->SlotId.ToString() : FString(),
			Slot ? Slot->GetActiveAllocKey() : FString(), 1.0);
	}
	return true;
}

bool UDCInteractor::TryUse()
{
	UpdateTarget();
	if (!Target.IsValid())
	{
		return false;
	}
	return Perform(Target.Slot.Get(), Target.Content.Get(), Target.Kind);
}

bool UDCInteractor::TryUseKind(EDCInteraction Kind)
{
	UpdateTarget();

	// Did the prompt already have it? That is the only part of the human path a scripted run
	// cannot otherwise exercise, so it is counted rather than assumed.
	++PromptChecked;
	if (Target.IsValid() && Target.Kind == Kind)
	{
		++PromptAgreed;
		return Perform(Target.Slot.Get(), Target.Content.Get(), Kind);
	}

	const APawn* Pawn = Cast<APawn>(GetOwner());
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (Pawn == nullptr || Subsystem == nullptr)
	{
		return false;
	}
	const FVector Here = Pawn->GetActorLocation();

	ADCSlot* BestSlot = nullptr;
	ADCContentActor* BestContent = nullptr;
	float BestDistance = Reach;
	FDCInteractionPoint Point;
	for (ADCSlot* Slot : Subsystem->GetSlots())
	{
		ADCContentActor* Content = Cast<ADCContentActor>(Slot->GetContentActor());
		if (Content == nullptr || !Content->GetInteractionPoint(Kind, Point))
		{
			continue;
		}
		const float Distance = FVector::Dist(Here, Point.Location);
		if (Distance <= BestDistance)
		{
			BestDistance = Distance;
			BestSlot = Slot;
			BestContent = Content;
		}
	}
	if (BestContent == nullptr)
	{
		DC_LOG(Warning, TEXT("USE   %s is not in reach (%.0f cm)"), DCInteractionName(Kind), Reach);
		return false;
	}
	return Perform(BestSlot, BestContent, Kind);
}

void UDCInteractor::OnUsePressed()
{
	TryUse();
}

int32 UDCInteractor::GetUseCount(EDCInteraction Kind) const
{
	const int32 Index = static_cast<int32>(Kind);
	return (Index >= 0 && Index < UE_ARRAY_COUNT(Uses)) ? Uses[Index] : 0;
}

bool UDCInteractor::GetStandPoint(const ADCSlot* Slot, EDCInteraction Kind, FVector& Out)
{
	const ADCContentActor* Content = Slot
		? Cast<ADCContentActor>(Slot->GetContentActor()) : nullptr;
	FDCInteractionPoint Point;
	if (Content == nullptr || !Content->GetInteractionPoint(Kind, Point))
	{
		return false;
	}
	Out = Point.StandPoint;
	return true;
}
