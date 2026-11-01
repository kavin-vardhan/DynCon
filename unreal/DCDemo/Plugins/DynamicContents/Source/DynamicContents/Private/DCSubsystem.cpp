#include "DCSubsystem.h"

#include "DCContentActor.h"
#include "DCCrypto.h"
#include "DCInteractor.h"
#include "DCPackMounter.h"
#include "DCShell.h"
#include "DCSlot.h"
#include "DCStateStore.h"
#include "DynamicContents.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/Texture2D.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "HttpModule.h"
#include "Interfaces/IHttpResponse.h"
#include "Misc/CommandLine.h"
#include "Misc/DateTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/Archive.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/UObjectGlobals.h"

namespace
{
	/** Where the base game keeps the eight emblems (unreal\Tools\import_content.py). */
	const TCHAR* DCEmblemFolder = TEXT("/Game/DCCore/Emblems/T_Emblem_");

	/** …and the screen image set (unreal\Tools\core_extras.py). 1-based on disk. */
	const TCHAR* DCScreenPrefix = TEXT("/Game/DCCore/Screens/T_DC_Screen_");

	/** Nobody is going to cycle past this many; it only stops a runaway loop. */
	constexpr int32 DCMaxScreenImages = 16;

	/** Keep the status file's history bounded; a booth day is a long run. */
	constexpr int32 DCMaxActivations = 400;
	constexpr int32 DCMaxFallbacks = 200;

	/** The X-ray's lifecycle log and frame-time graph (brief 018). */
	constexpr int32 DCMaxLifecycle = 24;
	constexpr float DCGraphSeconds = 10.0f;
	constexpr int32 DCMaxGraphSamples = 2400;     // 10 s at 240 fps, with room to spare

	FString UtcNowIso()
	{
		return FDateTime::UtcNow().ToIso8601();
	}

	TSharedPtr<FJsonObject> ParseJsonObject(const FString& Text)
	{
		TSharedPtr<FJsonObject> Root;
		const TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Root))
		{
			return nullptr;
		}
		return Root;
	}

	/** "00:01:23" from seconds - what the uptime stamp on the status strip shows. */
	FString HoursMinutesSeconds(double Seconds)
	{
		const int32 Whole = FMath::Max(static_cast<int32>(Seconds), 0);
		return FString::Printf(TEXT("%02d:%02d:%02d"), Whole / 3600, (Whole / 60) % 60, Whole % 60);
	}
}

// ===================================================================== lifetime

UDCSubsystem* UDCSubsystem::Get(const UObject* WorldContext)
{
	if (WorldContext == nullptr || GEngine == nullptr)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull);
	if (World == nullptr)
	{
		return nullptr;
	}
	UGameInstance* Instance = World->GetGameInstance();
	return Instance ? Instance->GetSubsystem<UDCSubsystem>() : nullptr;
}

void UDCSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	StartSeconds = FPlatformTime::Seconds();
}

void UDCSubsystem::Deinitialize()
{
	if (TickerHandle.IsValid())
	{
		FTSTicker::GetCoreTicker().RemoveTicker(TickerHandle);
		TickerHandle.Reset();
	}

	// Nothing may be left in flight: a packaged run that ends with an HTTP callback still
	// queued is a crash on shutdown waiting to happen.
	for (TPair<FString, TSharedPtr<FDCSlotJob>>& Pair : Jobs)
	{
		if (Pair.Value.IsValid())
		{
			Pair.Value->bCancelled = true;
			if (Pair.Value->InFlight.IsValid())
			{
				Pair.Value->InFlight->CancelRequest();
			}
		}
	}
	Jobs.Empty();
	Super::Deinitialize();
}

const TCHAR* UDCSubsystem::GetBuildConfigName()
{
#if UE_BUILD_DEBUG
	return TEXT("Debug");
#elif UE_BUILD_DEVELOPMENT
	return TEXT("Development");
#elif UE_BUILD_TEST
	return TEXT("Test");
#else
	return TEXT("Shipping");
#endif
}

double UDCSubsystem::GetUptimeSeconds() const
{
	return FPlatformTime::Seconds() - StartSeconds;
}

void UDCSubsystem::SetBackendStatus(const FString& Status)
{
	if (BackendStatus != Status)
	{
		BackendStatus = Status;
		DC_LOG(Log, TEXT("BACKEND %s"), *Status);
	}
}

// ===================================================================== start

void UDCSubsystem::ParseCommandLine()
{
	const TCHAR* Cmd = FCommandLine::Get();

	FString Value;
	if (FParse::Value(Cmd, TEXT("DCBackend="), Value, false) && !Value.IsEmpty())
	{
		BackendUrl = Value.TrimQuotes();
	}
	BackendUrl.RemoveFromEnd(TEXT("/"));

	if (FParse::Value(Cmd, TEXT("DCRegion="), Value, false) && !Value.IsEmpty())
	{
		Region = Value.TrimQuotes();
	}
	if (FParse::Value(Cmd, TEXT("DCGame="), Value, false) && !Value.IsEmpty())
	{
		Game = Value.TrimQuotes();
	}
	if (FParse::Value(Cmd, TEXT("DCStatusFile="), Value, false) && !Value.IsEmpty())
	{
		StatusFilePath = FPaths::ConvertRelativePathToFull(Value.TrimQuotes());
		IFileManager::Get().MakeDirectory(*FPaths::GetPath(StatusFilePath), true);
	}

	FString CacheDir = FPaths::ProjectSavedDir() / TEXT("DCPacks");
	if (FParse::Value(Cmd, TEXT("DCCacheDir="), Value, false) && !Value.IsEmpty())
	{
		CacheDir = Value.TrimQuotes();
	}

	int32 Number = 0;
	if (FParse::Value(Cmd, TEXT("DCRangeBytes="), Number))
	{
		RangeBytes = Number;             // 0 = fetch each file in one request, no Range header
	}
	float Seconds = 0.0f;
	if (FParse::Value(Cmd, TEXT("DCRetryBase="), Seconds) && Seconds > 0.0f)
	{
		RetryBaseSeconds = Seconds;
	}
	if (FParse::Value(Cmd, TEXT("DCPollInterval="), Seconds) && Seconds > 0.0f)
	{
		PollIntervalSeconds = Seconds;
	}

	bFollowPreviewRegion = FParse::Param(Cmd, TEXT("DCFollowRegion"));
	bPreview = FParse::Param(Cmd, TEXT("DCPreview"));
	bNoLiveFlip = FParse::Param(Cmd, TEXT("DCNoFlip"));

	Cache.Configure(CacheDir, 8);
}

void UDCSubsystem::Start()
{
	if (bStarted)
	{
		return;
	}
	bStarted = true;

	ParseCommandLine();

	bCryptoOk = FDCCrypto::IsAvailable(CryptoApi);
	DC_LOG(Log, TEXT("CRYPTO %s   %s"), bCryptoOk ? TEXT("ok") : TEXT("UNAVAILABLE"), *CryptoApi);

	DC_LOG(Log, TEXT("DC client starting: build=%s  backend=%s  game=%s  region=%s  "
		"follow-preview-region=%s  preview=%s  range=%d B  cache=%s"),
		GetBuildConfigName(), *BackendUrl, *Game, *Region,
		bFollowPreviewRegion ? TEXT("yes") : TEXT("no"),
		bPreview ? TEXT("yes - this copy is the region preview window") : TEXT("no"),
		RangeBytes, *Cache.GetRoot());
	if (bPreview)
	{
		// The preview is not a player. It has a camera within 30 m of content for minutes
		// at a time, so every slot it frames would post `view` telemetry and the brand's
		// report would count views nobody had - and a mount from a machine nobody is
		// playing is what the portal's push-update screen reads as "the game swapped it".
		DC_LOG(Log, TEXT("TELEMETRY off: this copy is the preview window, not a player"));
	}

	SetBackendStatus(TEXT("waiting for the backend"));

	TickerHandle = FTSTicker::GetCoreTicker().AddTicker(
		FTickerDelegate::CreateUObject(this, &UDCSubsystem::Tick));

	FetchClientConfig();
}

// ===================================================================== slots

void UDCSubsystem::RegisterSlot(ADCSlot* Slot)
{
	if (Slot == nullptr)
	{
		return;
	}
	Slots.RemoveAll([](const TWeakObjectPtr<ADCSlot>& Weak) { return !Weak.IsValid(); });
	Slots.AddUnique(Slot);
	Slots.Sort([](const TWeakObjectPtr<ADCSlot>& A, const TWeakObjectPtr<ADCSlot>& B)
	{
		const int32 OrderA = A.IsValid() ? A->FillOrder : MAX_int32;
		const int32 OrderB = B.IsValid() ? B->FillOrder : MAX_int32;
		return OrderA < OrderB;
	});

	// A slot that registers after the first poll must not wait a whole interval for its turn:
	// the game mode's BeginPlay and the slots' BeginPlay are not in a guaranteed order.
	LastPollSeconds = 0.0;

	const FVector Limits = Slot->GetClassLimits();
	DC_LOG(Log, TEXT("SLOT registered '%s' class=%s limits=%.0fx%.0fx%.0f cm at %s"),
		*Slot->SlotId.ToString(), *Slot->GetSizeClassName(), Limits.X, Limits.Y, Limits.Z,
		*Slot->GetActorLocation().ToCompactString());
}

void UDCSubsystem::UnregisterSlot(ADCSlot* Slot)
{
	Slots.RemoveAll([Slot](const TWeakObjectPtr<ADCSlot>& Weak)
	{
		return !Weak.IsValid() || Weak.Get() == Slot;
	});
	if (Slot != nullptr)
	{
		FinishJob(Slot->SlotId.ToString());
	}
}

TArray<ADCSlot*> UDCSubsystem::GetSlots() const
{
	TArray<ADCSlot*> Out;
	for (const TWeakObjectPtr<ADCSlot>& Weak : Slots)
	{
		if (ADCSlot* Slot = Weak.Get())
		{
			Out.Add(Slot);
		}
	}
	return Out;
}

UTexture2D* UDCSubsystem::GetEmblemTexture(const FString& Emblem)
{
	if (Emblem.IsEmpty())
	{
		return nullptr;
	}
	if (const TObjectPtr<UTexture2D>* Found = Emblems.Find(Emblem))
	{
		return Found->Get();
	}

	const FString Path = FString(DCEmblemFolder) + Emblem;
	UTexture2D* Texture = LoadObject<UTexture2D>(nullptr, *Path);
	if (Texture == nullptr)
	{
		DC_LOG(Warning, TEXT("BRAND  no emblem texture at %s - the sign keeps the pack's own"), *Path);
	}
	Emblems.Add(Emblem, Texture);
	return Texture;
}

int32 UDCSubsystem::GetScreenImageCount()
{
	if (!bScreenImagesLoaded)
	{
		bScreenImagesLoaded = true;
		// Counted by loading until one is missing, rather than by a number written down
		// twice: adding a fifth image to the set is then a build step and nothing else.
		for (int32 Index = 1; Index <= DCMaxScreenImages; ++Index)
		{
			const FString Path = FString::Printf(TEXT("%s%d"), DCScreenPrefix, Index);
			UTexture2D* Texture = LoadObject<UTexture2D>(nullptr, *Path);
			if (Texture == nullptr)
			{
				break;
			}
			ScreenImages.Add(Texture);
		}
		if (ScreenImages.Num() == 0)
		{
			DC_LOG(Warning, TEXT("SCREENS no image set at %s1 - every screen keeps the image "
				"its pack was built with"), DCScreenPrefix);
		}
		else
		{
			DC_LOG(Log, TEXT("SCREENS %d image(s) in the base game's set"), ScreenImages.Num());
		}
	}
	return ScreenImages.Num();
}

UTexture2D* UDCSubsystem::GetScreenImage(int32 Index)
{
	const int32 Count = GetScreenImageCount();
	if (Count <= 0 || Index < 1 || Index > Count)
	{
		return nullptr;
	}
	return ScreenImages[Index - 1].Get();
}

// ===================================================================== HTTP plumbing

FString UDCSubsystem::AbsoluteUrl(const FString& PathOrUrl) const
{
	if (PathOrUrl.StartsWith(TEXT("http://")) || PathOrUrl.StartsWith(TEXT("https://")))
	{
		return PathOrUrl;
	}
	return BackendUrl + (PathOrUrl.StartsWith(TEXT("/")) ? PathOrUrl : TEXT("/") + PathOrUrl);
}

FHttpRequestRef UDCSubsystem::MakeRequest(const FString& PathOrUrl, const FString& Verb) const
{
	FHttpRequestRef Request = FHttpModule::Get().CreateRequest();
	Request->SetURL(AbsoluteUrl(PathOrUrl));
	Request->SetVerb(Verb);
	Request->SetHeader(TEXT("Accept"), TEXT("application/json"));
	Request->SetTimeout(30.0f);
	return Request;
}

// ===================================================================== client-config

void UDCSubsystem::FetchClientConfig()
{
	if (bConfigInFlight)
	{
		return;
	}
	bConfigInFlight = true;
	++ConfigAttempts;

	FHttpRequestRef Request = MakeRequest(TEXT("/client-config"), TEXT("GET"));
	TWeakObjectPtr<UDCSubsystem> Weak(this);
	Request->OnProcessRequestComplete().BindLambda(
		[Weak](FHttpRequestPtr, FHttpResponsePtr Response, bool bOk)
		{
			if (UDCSubsystem* Self = Weak.Get())
			{
				Self->OnClientConfig(Response, bOk);
			}
		});
	Request->ProcessRequest();
}

void UDCSubsystem::OnClientConfig(FHttpResponsePtr Response, bool bOk)
{
	bConfigInFlight = false;

	if (!bOk || !Response.IsValid() || Response->GetResponseCode() != 200)
	{
		const int32 Code = Response.IsValid() ? Response->GetResponseCode() : 0;
		SetBackendStatus(FString::Printf(TEXT("GET /client-config did not answer (%d) - retrying"), Code));
		NextConfigAttemptSeconds = FPlatformTime::Seconds()
			+ FMath::Min(RetryBaseSeconds * ConfigAttempts, RetryMaxSeconds);
		return;
	}

	const TSharedPtr<FJsonObject> Root = ParseJsonObject(Response->GetContentAsString());
	if (!Root.IsValid())
	{
		SetBackendStatus(TEXT("GET /client-config was not JSON - retrying"));
		NextConfigAttemptSeconds = FPlatformTime::Seconds() + RetryBaseSeconds;
		return;
	}

	Root->TryGetStringField(TEXT("public_key_pem"), PublicKeyPem);

	double Interval = 0.0;
	if (Root->TryGetNumberField(TEXT("poll_interval_s"), Interval) && Interval > 0.05)
	{
		PollIntervalSeconds = static_cast<float>(Interval);
	}
	double Keep = 0.0;
	if (Root->TryGetNumberField(TEXT("cache_packs"), Keep) && Keep >= 1.0)
	{
		Cache.SetKeepPacks(static_cast<int32>(Keep));
	}
	double RadiusM = 0.0;
	if (Root->TryGetNumberField(TEXT("prefetch_radius_m"), RadiusM) && RadiusM > 0.0)
	{
		for (ADCSlot* Slot : GetSlots())
		{
			Slot->PrefetchRadius = static_cast<float>(RadiusM) * 100.0f;
		}
	}

	// A booth reset bumps the generation and lists the visitor packs every client has to
	// forget, so the next visitor gets a real download instead of a cache hit.
	double Generation = 0.0;
	Root->TryGetNumberField(TEXT("reset_generation"), Generation);
	ResetGeneration = static_cast<int32>(Generation);

	const FString KeyHead = PublicKeyPem.Left(40).Replace(TEXT("\n"), TEXT(""));
	DC_LOG(Log, TEXT("CONFIG ok  poll=%.2f s  cache=%d packs  key=%d chars '%s…'  reset_generation=%d"),
		PollIntervalSeconds, Cache.GetKeepPacks(), PublicKeyPem.Len(), *KeyHead, ResetGeneration);

	SetBackendStatus(PublicKeyPem.IsEmpty()
		? TEXT("the backend sent no public key - nothing will be mounted")
		: TEXT("ok"));

	LastPollSeconds = 0.0;      // poll straight away
}

// ===================================================================== the loop

bool UDCSubsystem::Tick(float DeltaSeconds)
{
	if (!bStarted)
	{
		return true;
	}
	const double Now = FPlatformTime::Seconds();

	if (PublicKeyPem.IsEmpty())
	{
		if (!bConfigInFlight && Now >= NextConfigAttemptSeconds)
		{
			FetchClientConfig();
		}
		return true;
	}

	if (Now - LastPollSeconds >= PollIntervalSeconds)
	{
		LastPollSeconds = Now;
		Poll();
		// The preview window asks this whether or not it is following the region: the same
		// answer carries the slot it should be looking at, and the labels for its caption.
		if (bFollowPreviewRegion || bPreview)
		{
			PollPreviewRegion();
		}
	}

	// A slot in FALLBACK keeps what it has and tries again when its backoff runs out.
	for (ADCSlot* Slot : GetSlots())
	{
		if (Slot->GetState() == EDCSlotState::Fallback && Slot->IsRetryDue(Now)
			&& !Jobs.Contains(Slot->SlotId.ToString()) && !Slot->GetWantedAllocKey().IsEmpty())
		{
			DC_LOG(Log, TEXT("SLOT %s  backoff is up, trying again"), *Slot->SlotId.ToString());
			StartJob(Slot, Slot->GetWantedAllocKey());
		}
	}

	FlushTelemetry(false);

	// Four times a second is enough for a watching script to see every state the lifecycle
	// goes through, and it costs one small file write.
	if (Now - LastStatusSeconds >= 0.25)
	{
		LastStatusSeconds = Now;
		WriteStatusFile();
	}
	return true;
}

void UDCSubsystem::Poll()
{
	if (bPollInFlight)
	{
		return;
	}
	bPollInFlight = true;
	++PollCount;

	// `preview=1` keeps the second copy of the game out of the platform's idea of which
	// game the booth is playing: it is a picture of somewhere else, usually of the same
	// map as another region, and the portal's "playing at this booth" badge follows the
	// screen a visitor is actually standing in front of.
	const FString Path = FString::Printf(TEXT("/changes?game=%s&region=%s%s"), *Game, *Region,
		bPreview ? TEXT("&preview=1") : TEXT(""));
	FHttpRequestRef Request = MakeRequest(Path, TEXT("GET"));
	TWeakObjectPtr<UDCSubsystem> Weak(this);
	Request->OnProcessRequestComplete().BindLambda(
		[Weak](FHttpRequestPtr, FHttpResponsePtr Response, bool bOk)
		{
			if (UDCSubsystem* Self = Weak.Get())
			{
				Self->OnChanges(Response, bOk);
			}
		});
	Request->ProcessRequest();
}

void UDCSubsystem::OnChanges(FHttpResponsePtr Response, bool bOk)
{
	bPollInFlight = false;

	if (!bOk || !Response.IsValid() || Response->GetResponseCode() != 200)
	{
		const int32 Code = Response.IsValid() ? Response->GetResponseCode() : 0;
		SetBackendStatus(FString::Printf(TEXT("GET /changes did not answer (%d)"), Code));
		return;
	}

	const TSharedPtr<FJsonObject> Root = ParseJsonObject(Response->GetContentAsString());
	if (!Root.IsValid())
	{
		SetBackendStatus(TEXT("GET /changes was not JSON"));
		return;
	}
	SetBackendStatus(TEXT("ok"));

	// A reset at the booth: forget the visitor's packs, then re-resolve everything.
	double Generation = 0.0;
	Root->TryGetNumberField(TEXT("reset_generation"), Generation);
	if (static_cast<int32>(Generation) != ResetGeneration)
	{
		const bool bFirstPoll = ResetGeneration < 0;
		ResetGeneration = static_cast<int32>(Generation);
		FString Reason;
		Root->TryGetStringField(TEXT("reset_reason"), Reason);
		TArray<FString> Purge;
		const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
		if (Root->TryGetArrayField(TEXT("purge_packs"), List) && List)
		{
			for (const TSharedPtr<FJsonValue>& Entry : *List)
			{
				FString PackId;
				if (Entry.IsValid() && Entry->TryGetString(PackId))
				{
					Purge.Add(PackId);
				}
			}
		}
		DC_LOG(Log, TEXT("RESET generation %d (%s): purging %d visitor pack(s) from the cache"),
			ResetGeneration, Reason.IsEmpty() ? TEXT("?") : *Reason, Purge.Num());
		// Never delete the bytes of a pack that is mounted; the LRU gets those later.
		Purge.RemoveAll([this](const FString& PackId) { return MountedPackIds.Contains(PackId); });
		Cache.Purge(Purge);
		// A reset wipes the visitor's saved state too (plan v6 §9): the next visitor must not
		// walk into the last one's lights.
		if (UDCStateStore* Store = UDCStateStore::Get(this))
		{
			Store->Clear(FString::Printf(TEXT("booth reset, generation %d"), ResetGeneration));
		}
		for (ADCSlot* Slot : GetSlots())
		{
			Slot->SetWantedAllocKey(FString());
		}

		// Only the **staff** reset clears the booth's own screen down. The portal's
		// sixty-second idle timer fires when the *brand* seat has gone quiet, and the two
		// seats can be two different visitors (plan v6 §2): an idle reset that dropped the
		// Player into the attract loop would take the game away from somebody who is still
		// playing it. The first poll of a run is not a reset at all - it is only this copy
		// learning what the generation already is.
		if (!bFirstPoll && !bPreview && Reason != TEXT("idle"))
		{
			if (UDCShell* Shell = UDCShell::Get(this))
			{
				Shell->EnterAttract(TEXT("the staff reset combo"));
			}
		}
	}

	ApplyLiveFlip(Root);

	const TSharedPtr<FJsonObject>* SlotMap = nullptr;
	if (!Root->TryGetObjectField(TEXT("slots"), SlotMap) || !SlotMap)
	{
		return;
	}

	for (ADCSlot* Slot : GetSlots())
	{
		const FString Id = Slot->SlotId.ToString();
		FString Key;
		if (!(*SlotMap)->TryGetStringField(Id, Key) || Key.IsEmpty())
		{
			continue;                     // this map's slot is not one this game registered
		}
		if (Key == Slot->GetWantedAllocKey())
		{
			continue;                     // stable: nothing to do, which is the common case
		}

		++ChangeCount;
		DC_LOG(Log, TEXT("CHANGES slot %s  alloc_key %s -> %s"), *Id,
			Slot->GetWantedAllocKey().IsEmpty() ? TEXT("(none)") : *Slot->GetWantedAllocKey(), *Key);
		Slot->SetWantedAllocKey(Key);
		Slot->ClearRetry();
		StartJob(Slot, Key);
	}

	WriteStatusFile();
}

void UDCSubsystem::ApplyLiveFlip(const TSharedPtr<FJsonObject>& Changes)
{
	// The fallback for tour step 7 (plan v6 §11). If the booth cannot afford a second copy
	// of the game, the portal flips the **main** game to another region for twenty seconds
	// instead: the slot swaps in front of the Player, and swaps back. It is the same
	// promise shown a different way, and it needs no second window.
	//
	// The preview window ignores it: it already *is* another region, and flipping it would
	// make the two screens show the same thing, which is the opposite of the point.
	if (bPreview || bNoLiveFlip)
	{
		return;
	}

	const TSharedPtr<FJsonObject>* Flip = nullptr;
	const bool bHasFlip = Changes->TryGetObjectField(TEXT("live_flip"), Flip)
		&& Flip != nullptr && Flip->IsValid();

	if (bHasFlip)
	{
		FString To;
		(*Flip)->TryGetStringField(TEXT("region"), To);
		if (To.IsEmpty() || To == Region)
		{
			return;
		}
		if (FlipBackTo.IsEmpty())
		{
			// Remember what this copy really is, from the command line rather than from
			// the server's idea of it: this is where it has to end up.
			FlipBackTo = Region;
		}
		double Left = 0.0;
		(*Flip)->TryGetNumberField(TEXT("seconds_left"), Left);
		DC_LOG(Log, TEXT("FLIP  the portal is flipping this copy to %s for %.0f s "
			"(back to %s)"), *To, Left, *FlipBackTo);
		SetRegion(To, TEXT("the portal's live flip"));
	}
	else if (!FlipBackTo.IsEmpty())
	{
		const FString Back = FlipBackTo;
		FlipBackTo.Reset();
		DC_LOG(Log, TEXT("FLIP  over - back to %s"), *Back);
		SetRegion(Back, TEXT("the live flip ended"));
	}
}

void UDCSubsystem::PollPreviewRegion()
{
	if (bPreviewRegionInFlight)
	{
		return;
	}
	bPreviewRegionInFlight = true;

	FHttpRequestRef Request = MakeRequest(TEXT("/preview/region"), TEXT("GET"));
	TWeakObjectPtr<UDCSubsystem> Weak(this);
	Request->OnProcessRequestComplete().BindLambda(
		[Weak](FHttpRequestPtr, FHttpResponsePtr Response, bool bOk)
		{
			if (UDCSubsystem* Self = Weak.Get())
			{
				Self->OnPreviewRegion(Response, bOk);
			}
		});
	Request->ProcessRequest();
}

void UDCSubsystem::OnPreviewRegion(FHttpResponsePtr Response, bool bOk)
{
	bPreviewRegionInFlight = false;
	if (!bOk || !Response.IsValid() || Response->GetResponseCode() != 200)
	{
		return;
	}
	const TSharedPtr<FJsonObject> Root = ParseJsonObject(Response->GetContentAsString());
	if (!Root.IsValid())
	{
		return;
	}

	FString NewRegion;
	if (Root->TryGetStringField(TEXT("region"), NewRegion) && !NewRegion.IsEmpty()
		&& bFollowPreviewRegion)
	{
		SetRegion(NewRegion, TEXT("the portal moved this copy's region"));
	}
	// The labels are of whatever region the answer is about. Only read them when this copy
	// is actually playing as that region, so the caption can never name somebody else's.
	if (NewRegion == Region)
	{
		Root->TryGetStringField(TEXT("label"), RegionLabel);
		Root->TryGetStringField(TEXT("label_jp"), RegionLabelJp);
	}

	const TSharedPtr<FJsonObject>* Focus = nullptr;
	if (Root->TryGetObjectField(TEXT("focus"), Focus) && Focus != nullptr)
	{
		FString NewGame;
		FString NewSlot;
		FString NewReason;
		(*Focus)->TryGetStringField(TEXT("game"), NewGame);
		(*Focus)->TryGetStringField(TEXT("slot"), NewSlot);
		(*Focus)->TryGetStringField(TEXT("reason"), NewReason);
		if (NewSlot != FocusSlot || NewGame != FocusGame)
		{
			DC_LOG(Log, TEXT("PREVIEW focus %s/%s -> %s/%s   (%s)"),
				FocusGame.IsEmpty() ? TEXT("-") : *FocusGame,
				FocusSlot.IsEmpty() ? TEXT("-") : *FocusSlot,
				*NewGame, *NewSlot, *NewReason);
		}
		FocusGame = NewGame;
		FocusSlot = NewSlot;
		FocusReason = NewReason;
	}
}

void UDCSubsystem::SetRegion(const FString& NewRegion, const FString& Why)
{
	if (NewRegion == Region)
	{
		return;
	}
	DC_LOG(Log, TEXT("REGION %s -> %s   (%s)"), *Region, *NewRegion, *Why);
	Region = NewRegion;

	// Every slot has to be asked again: the same slot in another region is different content.
	for (ADCSlot* Slot : GetSlots())
	{
		Slot->SetWantedAllocKey(FString());
		Slot->ClearRetry();
	}
	LastPollSeconds = 0.0;
}

// ===================================================================== one slot's pipeline

bool UDCSubsystem::IsJobStale(const TSharedPtr<FDCSlotJob>& Job) const
{
	if (!Job.IsValid() || Job->bCancelled)
	{
		return true;
	}
	const ADCSlot* Slot = Job->Slot.Get();
	if (Slot == nullptr)
	{
		return true;
	}
	return Slot->GetWantedAllocKey() != Job->AllocKey;
}

void UDCSubsystem::StartJob(ADCSlot* Slot, const FString& AllocKey)
{
	if (Slot == nullptr || AllocKey.IsEmpty())
	{
		return;
	}
	const FString Id = Slot->SlotId.ToString();

	// One job per slot: a key that changes mid-download abandons the one in flight.
	if (TSharedPtr<FDCSlotJob>* Existing = Jobs.Find(Id))
	{
		if (Existing->IsValid())
		{
			(*Existing)->bCancelled = true;
			if ((*Existing)->InFlight.IsValid())
			{
				(*Existing)->InFlight->CancelRequest();
			}
		}
		Jobs.Remove(Id);
	}

	TSharedPtr<FDCSlotJob> Job = MakeShared<FDCSlotJob>();
	Job->Slot = Slot;
	Job->SlotId = Id;
	Job->AllocKey = AllocKey;
	Job->StartedSeconds = FPlatformTime::Seconds();
	Jobs.Add(Id, Job);

	StartResolve(Job);
}

void UDCSubsystem::FinishJob(const FString& SlotId)
{
	Jobs.Remove(SlotId);
}

void UDCSubsystem::StartResolve(TSharedPtr<FDCSlotJob> Job)
{
	ADCSlot* Slot = Job->Slot.Get();
	if (Slot == nullptr)
	{
		return;
	}
	Slot->SetState(EDCSlotState::Resolving);

	const FString Path = FString::Printf(TEXT("/resolve?game=%s&slot=%s&region=%s"),
		*Game, *Job->SlotId, *Region);
	FHttpRequestRef Request = MakeRequest(Path, TEXT("GET"));
	Job->InFlight = Request;
	Job->ResolveMs = FPlatformTime::Seconds();        // start stamp; turned into ms below

	TWeakObjectPtr<UDCSubsystem> Weak(this);
	Request->OnProcessRequestComplete().BindLambda(
		[Weak, Job](FHttpRequestPtr, FHttpResponsePtr Response, bool bOk)
		{
			if (UDCSubsystem* Self = Weak.Get())
			{
				Self->OnResolved(Job, Response, bOk);
			}
		});
	Request->ProcessRequest();
}

void UDCSubsystem::OnResolved(TSharedPtr<FDCSlotJob> Job, FHttpResponsePtr Response, bool bOk)
{
	Job->InFlight = nullptr;
	if (IsJobStale(Job))
	{
		DC_LOG(Log, TEXT("SLOT %s  resolve abandoned: the allocation moved on"), *Job->SlotId);
		FinishJob(Job->SlotId);
		return;
	}
	Job->ResolveMs = (FPlatformTime::Seconds() - Job->ResolveMs) * 1000.0;

	if (!bOk || !Response.IsValid() || Response->GetResponseCode() != 200)
	{
		const int32 Code = Response.IsValid() ? Response->GetResponseCode() : 0;
		FailJob(Job, FString::Printf(TEXT("GET /resolve answered %d"), Code));
		return;
	}

	// The envelope: verify the exact bytes the server signed, then parse them. Nothing from
	// inside the payload is believed - or even read - until the signature is good.
	const TSharedPtr<FJsonObject> Envelope = ParseJsonObject(Response->GetContentAsString());
	if (!Envelope.IsValid())
	{
		FailJob(Job, TEXT("the resolve answer was not JSON"));
		return;
	}

	FString SignedPayload;
	FString Signature;
	FString Algorithm;
	Envelope->TryGetStringField(TEXT("signature"), Signature);
	Envelope->TryGetStringField(TEXT("signature_alg"), Algorithm);
	if (!Envelope->TryGetStringField(TEXT("signed_payload"), SignedPayload) || SignedPayload.IsEmpty())
	{
		FailJob(Job, TEXT("the resolve answer carried no signed_payload"));
		return;
	}
	if (Signature.IsEmpty())
	{
		FailJob(Job, TEXT("the resolve answer carried no signature"));
		return;
	}

	// The signature is over the UTF-8 bytes of the string, so convert and do not touch.
	const FTCHARToUTF8 Utf8(*SignedPayload);
	TArray<uint8> PayloadBytes;
	PayloadBytes.Append(reinterpret_cast<const uint8*>(Utf8.Get()), Utf8.Length());

	const double VerifyStart = FPlatformTime::Seconds();
	FString CryptoError;
	if (!FDCCrypto::VerifyRs256(PublicKeyPem, PayloadBytes, Signature, CryptoError))
	{
		FailJob(Job, FString::Printf(TEXT("manifest signature: %s"), *CryptoError));
		return;
	}
	const double SignatureMs = (FPlatformTime::Seconds() - VerifyStart) * 1000.0;

	FString ParseError;
	const TSharedPtr<FJsonObject> Payload = ParseJsonObject(SignedPayload);
	if (!FDCManifest::FromJson(Payload, Job->Manifest, ParseError))
	{
		FailJob(Job, FString::Printf(TEXT("manifest: %s"), *ParseError));
		return;
	}

	if (Job->Manifest.AllocKey != Job->AllocKey)
	{
		// Not an error: /changes and /resolve are two requests and the world can move between
		// them. Follow the manifest and let the next poll settle it.
		DC_LOG(Log, TEXT("SLOT %s  resolve came back with key %s, not %s - following the manifest"),
			*Job->SlotId, *Job->Manifest.AllocKey, *Job->AllocKey);
		Job->AllocKey = Job->Manifest.AllocKey;
		if (ADCSlot* Slot = Job->Slot.Get())
		{
			Slot->SetWantedAllocKey(Job->Manifest.AllocKey);
		}
	}

	DC_LOG(Log, TEXT("RESOLVE ok slot %s  %s  alg=%s signature ok in %.2f ms (resolve %.0f ms)  "
		"pack=%s %lld B in %d file(s)  class=%s  source=%s"),
		*Job->SlotId, *Job->Manifest.Describe(), *Algorithm, SignatureMs, Job->ResolveMs,
		*Job->Manifest.PackId, Job->Manifest.TotalFileBytes(), Job->Manifest.Files.Num(),
		*Job->Manifest.ClassPath, *Job->Manifest.ShowingSource);
	Job->Manifest.bSignatureVerified = true;
	NoteLifecycle(Job->SlotId, TEXT("resolve"), static_cast<float>(Job->ResolveMs),
		FString::Printf(TEXT("%s %s, signature ok"), *Job->Manifest.Piece,
			*Job->Manifest.Version));

	StartDownloads(Job);
}

void UDCSubsystem::StartDownloads(TSharedPtr<FDCSlotJob> Job)
{
	ADCSlot* Slot = Job->Slot.Get();
	if (Slot == nullptr)
	{
		return;
	}

	// Two slots can want the SAME pack at the same moment - a region's large rival is in
	// both of that game's large slots, so the attract rotation does it every block, and the
	// portal's live flip does it the instant it fires. The cache is one folder per pack, so
	// two jobs downloading it at once write over each other's bytes and both fail their
	// SHA-256. (Brief 017 found this: A1 and A2 both resolved to rival2 on a cold cache and
	// A1 came back with "sha256 mismatch on pakchunk110-Windows.ucas".)
	//
	// So the second one waits instead: it keeps what is on screen, falls back with the
	// ordinary backoff, and when it tries again the pack is in the cache and costs nothing.
	FString FetchedBy;
	for (const TPair<FString, TSharedPtr<FDCSlotJob>>& Other : Jobs)
	{
		if (Other.Value == Job || !Other.Value.IsValid() || Other.Value->bCancelled)
		{
			continue;
		}
		if (Other.Value->Manifest.PackId == Job->Manifest.PackId
			&& Other.Value->DownloadStartSeconds > 0.0)
		{
			FetchedBy = Other.Value->SlotId;
			break;
		}
	}
	if (!FetchedBy.IsEmpty())
	{
		// Outside the loop: FailJob removes this job from the very map being iterated.
		FailJob(Job, FString::Printf(
			TEXT("slot %s is already fetching pack %s - waiting for it"),
			*FetchedBy, *Job->Manifest.PackId));
		return;
	}

	Slot->SetState(EDCSlotState::Downloading);

	Job->CacheDir = Cache.DirFor(Job->Manifest.PackId);
	Job->FileIndex = 0;
	Job->FileHave = 0;
	Job->DownloadStartSeconds = FPlatformTime::Seconds();

	NextFile(Job);
}

void UDCSubsystem::NextFile(TSharedPtr<FDCSlotJob> Job)
{
	if (IsJobStale(Job))
	{
		DC_LOG(Log, TEXT("SLOT %s  download abandoned: the allocation moved on"), *Job->SlotId);
		FinishJob(Job->SlotId);
		return;
	}

	while (Job->Manifest.Files.IsValidIndex(Job->FileIndex))
	{
		const FDCPackFile& File = Job->Manifest.Files[Job->FileIndex];
		const FString Final = Job->CacheDir / File.Name;
		const int64 Have = IFileManager::Get().FileSize(*Final);
		if (Have == File.Size)
		{
			// The right number of bytes are already here. VERIFYING hashes it either way, so
			// a cached file that has gone bad is still caught - it just costs no download.
			++Job->CachedFiles;
			++Job->FileIndex;
			continue;
		}
		if (Have >= 0)
		{
			IFileManager::Get().Delete(*Final, false, true, true);
		}
		Job->FileHave = FMath::Max<int64>(IFileManager::Get().FileSize(*PartPathFor(Final)), 0);
		if (Job->FileHave > File.Size)
		{
			IFileManager::Get().Delete(*PartPathFor(Final), false, true, true);
			Job->FileHave = 0;
		}
		if (Job->FileHave > 0)
		{
			++Job->Resumes;
			DC_LOG(Log, TEXT("  resuming %s at %lld/%lld B"), *File.Name, Job->FileHave, File.Size);
		}
		RequestRange(Job);
		return;
	}

	Job->DownloadMs = (FPlatformTime::Seconds() - Job->DownloadStartSeconds) * 1000.0;
	DC_LOG(Log, TEXT("DOWNLOAD ok slot %s  %lld B over the network in %.0f ms  "
		"(%d file(s) already cached, %d range request(s), %d resume(s))"),
		*Job->SlotId, Job->NetworkBytes, Job->DownloadMs, Job->CachedFiles,
		Job->RangeRequests, Job->Resumes);
	NoteLifecycle(Job->SlotId, TEXT("download"), static_cast<float>(Job->DownloadMs),
		FString::Printf(TEXT("%lld B, %d cached"), Job->NetworkBytes, Job->CachedFiles));

	VerifyPack(Job);
}

void UDCSubsystem::RequestRange(TSharedPtr<FDCSlotJob> Job)
{
	const FDCPackFile& File = Job->Manifest.Files[Job->FileIndex];

	FHttpRequestRef Request = MakeRequest(File.Url, TEXT("GET"));
	Request->SetHeader(TEXT("Accept"), TEXT("application/octet-stream"));

	// Every request is a byte range, so resuming is the normal path and not a special case:
	// a dropped connection leaves the .part file at a clean boundary and the next attempt
	// carries on from exactly there. -DCRangeBytes=0 asks for whole files instead.
	if (RangeBytes > 0)
	{
		const int64 Last = FMath::Min<int64>(Job->FileHave + RangeBytes - 1, File.Size - 1);
		Request->SetHeader(TEXT("Range"), FString::Printf(TEXT("bytes=%lld-%lld"), Job->FileHave, Last));
	}
	else if (Job->FileHave > 0)
	{
		Request->SetHeader(TEXT("Range"), FString::Printf(TEXT("bytes=%lld-"), Job->FileHave));
	}
	++Job->RangeRequests;

	Job->InFlight = Request;
	TWeakObjectPtr<UDCSubsystem> Weak(this);
	Request->OnProcessRequestComplete().BindLambda(
		[Weak, Job](FHttpRequestPtr, FHttpResponsePtr Response, bool bOk)
		{
			if (UDCSubsystem* Self = Weak.Get())
			{
				Self->OnRange(Job, Response, bOk);
			}
		});
	Request->ProcessRequest();
}

void UDCSubsystem::OnRange(TSharedPtr<FDCSlotJob> Job, FHttpResponsePtr Response, bool bOk)
{
	Job->InFlight = nullptr;
	if (IsJobStale(Job))
	{
		FinishJob(Job->SlotId);
		return;
	}

	const FDCPackFile& File = Job->Manifest.Files[Job->FileIndex];
	const FString Final = Job->CacheDir / File.Name;
	const FString Part = PartPathFor(Final);

	const int32 Code = Response.IsValid() ? Response->GetResponseCode() : 0;
	if (!bOk || !Response.IsValid() || (Code != 200 && Code != 206))
	{
		FailJob(Job, FString::Printf(TEXT("%s came back %d"), *File.Name, Code));
		return;
	}

	const TArray<uint8>& Body = Response->GetContent();
	if (Body.Num() == 0)
	{
		FailJob(Job, FString::Printf(TEXT("%s sent no bytes at offset %lld"), *File.Name, Job->FileHave));
		return;
	}

	// A plain 200 means the server ignored the range and sent the lot, so start again.
	const bool bAppend = (Code == 206) && Job->FileHave > 0;
	if (!bAppend)
	{
		IFileManager::Get().Delete(*Part, false, true, true);
		Job->FileHave = 0;
	}

	const uint32 WriteFlags = bAppend ? static_cast<uint32>(FILEWRITE_Append) : 0u;
	TUniquePtr<FArchive> Writer(IFileManager::Get().CreateFileWriter(*Part, WriteFlags));
	if (!Writer.IsValid())
	{
		FailJob(Job, FString::Printf(TEXT("cannot write %s"), *Part));
		return;
	}
	Writer->Serialize(const_cast<uint8*>(Body.GetData()), Body.Num());
	Writer->Close();

	Job->FileHave += Body.Num();
	Job->NetworkBytes += Body.Num();

	if (Job->FileHave < File.Size)
	{
		RequestRange(Job);
		return;
	}

	if (!IFileManager::Get().Move(*Final, *Part, true, true))
	{
		FailJob(Job, FString::Printf(TEXT("cannot rename %s into place"), *File.Name));
		return;
	}
	++Job->FileIndex;
	Job->FileHave = 0;
	NextFile(Job);
}

void UDCSubsystem::VerifyPack(TSharedPtr<FDCSlotJob> Job)
{
	ADCSlot* Slot = Job->Slot.Get();
	if (Slot == nullptr)
	{
		FinishJob(Job->SlotId);
		return;
	}
	Slot->SetState(EDCSlotState::Verifying);

	const double Start = FPlatformTime::Seconds();
	for (const FDCPackFile& File : Job->Manifest.Files)
	{
		const FString Path = Job->CacheDir / File.Name;
		FString Hex;
		FString Error;
		if (!FDCCrypto::Sha256OfFile(Path, Hex, Error))
		{
			FailJob(Job, FString::Printf(TEXT("SHA-256 of %s: %s"), *File.Name, *Error));
			return;
		}
		if (!Hex.Equals(File.Sha256, ESearchCase::IgnoreCase))
		{
			// Throw the bad bytes away so the retry is a real download, not a cache hit.
			IFileManager::Get().Delete(*Path, false, true, true);
			FailJob(Job, FString::Printf(TEXT("sha256 mismatch on %s"), *File.Name));
			return;
		}
	}
	Job->VerifyMs = (FPlatformTime::Seconds() - Start) * 1000.0;

	DC_LOG(Log, TEXT("VERIFY ok  slot %s  %d file(s), SHA-256 each, in %.1f ms"),
		*Job->SlotId, Job->Manifest.Files.Num(), Job->VerifyMs);
	NoteLifecycle(Job->SlotId, TEXT("verify"), static_cast<float>(Job->VerifyMs),
		FString::Printf(TEXT("%d file(s) hashed"), Job->Manifest.Files.Num()));

	MountAndSpawn(Job);
}

bool UDCSubsystem::EnsurePackMounted(const FString& PackDir, double& OutMountMs, FString& OutError)
{
	TArray<FString> Paks;
	IFileManager::Get().FindFiles(Paks, *(PackDir / TEXT("*.pak")), true, false);
	if (Paks.Num() != 1)
	{
		OutError = FString::Printf(TEXT("expected one *.pak in the pack, found %d"), Paks.Num());
		return false;
	}
	const FString PakPath = FPaths::ConvertRelativePathToFull(PackDir / Paks[0]);

	if (MountedPaks.Contains(PakPath))
	{
		OutMountMs = 0.0;
		return true;                      // already mounted: a pack is mounted once per run
	}

	const FDCMountResult Result = UDCPackMounter::Mount(PakPath);
	OutMountMs = Result.Milliseconds;
	if (!Result.bMounted)
	{
		OutError = Result.Error;
		return false;
	}
	MountedPaks.Add(PakPath);
	return true;
}

void UDCSubsystem::MountAndSpawn(TSharedPtr<FDCSlotJob> Job)
{
	ADCSlot* Slot = Job->Slot.Get();
	if (Slot == nullptr)
	{
		FinishJob(Job->SlotId);
		return;
	}
	Slot->SetState(EDCSlotState::Mounting);

	FString Error;
	if (!EnsurePackMounted(Job->CacheDir, Job->MountMs, Error))
	{
		FailJob(Job, FString::Printf(TEXT("mount: %s"), *Error));
		return;
	}
	MountedPackIds.Add(Job->Manifest.PackId);
	Cache.Touch(Job->Manifest.PackId);

	const double LoadStart = FPlatformTime::Seconds();
	UClass* ContentClass = StaticLoadClass(AActor::StaticClass(), nullptr,
		*Job->Manifest.ClassPath, nullptr, LOAD_None, nullptr);
	Job->LoadMs = (FPlatformTime::Seconds() - LoadStart) * 1000.0;
	if (ContentClass == nullptr)
	{
		FailJob(Job, FString::Printf(TEXT("the pack mounted but %s would not load"),
			*Job->Manifest.ClassPath));
		return;
	}

	DC_LOG(Log, TEXT("MOUNT ok   slot %s  pack %s in %.1f ms, class loaded in %.1f ms"),
		*Job->SlotId, *Job->Manifest.PackId, Job->MountMs, Job->LoadMs);
	NoteLifecycle(Job->SlotId, TEXT("mount"),
		static_cast<float>(Job->MountMs + Job->LoadMs), Job->Manifest.PackId);

	const bool bOnScreen = Slot->ApplyOrHold(ContentClass, Job->Manifest, Error);
	if (!bOnScreen && !Error.IsEmpty())
	{
		FailJob(Job, Error);
		return;
	}

	if (bOnScreen)
	{
		FActivation Record;
		Record.Seq = ++EventSeq;
		Record.SlotId = Job->SlotId;
		Record.Piece = Job->Manifest.Piece;
		Record.Version = Job->Manifest.Version;
		Record.AllocKey = Job->Manifest.AllocKey;
		Record.BrandColour = Job->Manifest.Brand.bValid ? Job->Manifest.Brand.ColourHex : FString();
		Record.BrandEmblem = Job->Manifest.Brand.bValid ? Job->Manifest.Brand.Emblem : FString();
		Record.Kind = Job->Manifest.ShowingKind;
		Record.Source = Job->Manifest.ShowingSource;
		Record.PackId = Job->Manifest.PackId;
		Record.VisibleUtc = Slot->GetActiveSince().ToIso8601();
		Record.ResolveMs = Job->ResolveMs;
		Record.DownloadMs = Job->DownloadMs;
		Record.VerifyMs = Job->VerifyMs;
		Record.MountMs = Job->MountMs;
		Record.LoadMs = Job->LoadMs;
		Record.SpawnMs = Slot->GetLastSpawnMs();
		Record.TotalMs = (FPlatformTime::Seconds() - Job->StartedSeconds) * 1000.0;
		Record.NetworkBytes = Job->NetworkBytes;
		Record.CachedFiles = Job->CachedFiles;
		Record.RangeRequests = Job->RangeRequests;
		Activations.Add(Record);
		if (Activations.Num() > DCMaxActivations)
		{
			Activations.RemoveAt(0, Activations.Num() - DCMaxActivations);
		}

		DC_LOG(Log, TEXT("ACTIVE #%d  slot %s  %s   resolve %.0f + download %.0f + verify %.0f + "
			"mount %.0f + load %.0f + spawn %.1f = %.0f ms total"),
			Record.Seq, *Record.SlotId, *Job->Manifest.Describe(), Record.ResolveMs,
			Record.DownloadMs, Record.VerifyMs, Record.MountMs, Record.LoadMs, Record.SpawnMs,
			Record.TotalMs);

		NoteLifecycle(Job->SlotId, TEXT("spawn"), static_cast<float>(Record.SpawnMs),
			FString::Printf(TEXT("%s %s"), *Job->Manifest.Piece, *Job->Manifest.Version));

		QueueTelemetry(TEXT("mount"), Job->SlotId, Job->Manifest.AllocKey, 1.0);

		// Keep the cache down to its limit, but never touch a pack that is on screen.
		TSet<FString> Protect;
		for (const ADCSlot* Each : GetSlots())
		{
			if (Each->HasContent())
			{
				Protect.Add(Each->GetActiveManifest().PackId);
			}
		}
		Protect.Append(MountedPackIds);
		Cache.Evict(Protect);

		OnSlotActive.Broadcast(Slot, Job->Manifest);
	}

	FinishJob(Job->SlotId);
	WriteStatusFile();
}

void UDCSubsystem::FailJob(TSharedPtr<FDCSlotJob> Job, const FString& Reason)
{
	ADCSlot* Slot = Job->Slot.Get();
	FinishJob(Job->SlotId);

	FFallbackNote Note;
	Note.Seq = ++EventSeq;
	Note.SlotId = Job->SlotId;
	Note.Reason = Reason;
	Note.Utc = UtcNowIso();
	Fallbacks.Add(Note);
	if (Fallbacks.Num() > DCMaxFallbacks)
	{
		Fallbacks.RemoveAt(0, Fallbacks.Num() - DCMaxFallbacks);
	}
	NoteLifecycle(Job->SlotId, TEXT("fallback"), 0.0f, Reason);

	if (Slot != nullptr)
	{
		Slot->EnterFallback(Reason, FPlatformTime::Seconds(), RetryBaseSeconds, RetryMaxSeconds);
		OnSlotFallback.Broadcast(Slot, Reason);
	}
	WriteStatusFile();
}

// ===================================================================== telemetry

void UDCSubsystem::QueueTelemetry(const FString& Type, const FString& SlotId,
	const FString& AllocKey, double Value)
{
	if (bPreview)
	{
		// Plan v6 §9 counts a view, a visit, a dwell or an interaction of the **Player**.
		// This copy is a camera on the brand's screen: nobody is playing it, so nothing it
		// sees is a view and nothing it mounts is a swap the portal should believe.
		++TelemetryDropped;
		return;
	}

	// The attract camera is not a player either, and it is parked in front of a piece of
	// content for a quarter of a minute at a time - so every slot it lingers on would post
	// a `view` nobody saw. Same rule as the preview window, one difference: a **mount** is
	// still posted, because this machine really is the booth's game and the portal's
	// push-update screen is right to believe it.
	if (Type != TEXT("mount") && !IsPlayerPresent())
	{
		++TelemetryDropped;
		return;
	}

	FDCTelemetryEvent Event;
	Event.Type = Type;
	Event.SlotId = SlotId;
	Event.AllocKey = AllocKey;
	Event.Value = Value;
	Event.TimestampUtc = UtcNowIso();
	Telemetry.Add(Event);

	DC_LOG(Log, TEXT("TELEMETRY queued %s slot=%s key=%s value=%.1f (%d waiting)"),
		*Type, *SlotId, *AllocKey, Value, Telemetry.Num());

	if (Telemetry.Num() >= TelemetryBatchSize)
	{
		FlushTelemetry(true);
	}
}

float UDCSubsystem::GetFrameGraphSeconds()
{
	return DCGraphSeconds;
}

void UDCSubsystem::NoteLifecycle(const FString& SlotId, const TCHAR* Phase, float Ms,
	const FString& Note)
{
	const double Now = FPlatformTime::Seconds();

	FDCLifecycleNote Entry;
	Entry.Seconds = Now;
	Entry.SlotId = SlotId;
	Entry.Phase = Phase;
	Entry.Ms = Ms;
	Entry.Note = Note;
	Lifecycle.Add(Entry);
	while (Lifecycle.Num() > DCMaxLifecycle)
	{
		Lifecycle.RemoveAt(0, 1, EAllowShrinking::No);
	}

	// Only the three that change what is on screen get a tick on the graph: those are the
	// moments somebody watching is being invited to look for a spike.
	const FString Which(Phase);
	if (Which == TEXT("mount") || Which == TEXT("spawn") || Which == TEXT("unload"))
	{
		FDCFrameMark Mark;
		Mark.Seconds = Now;
		Mark.Phase = Which;
		Mark.SlotId = SlotId;
		GraphMarks.Add(Mark);
	}
}

bool UDCSubsystem::GetViewerLocation(FVector& Out) const
{
	const UGameInstance* Instance = GetGameInstance();
	const UWorld* World = Instance ? Instance->GetWorld() : nullptr;
	const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (PC == nullptr)
	{
		return false;
	}
	if (const APawn* Pawn = PC->GetPawn())
	{
		Out = Pawn->GetActorLocation();
		return true;
	}
	// No pawn: the attract camera, or the preview window. Both of them are an eye in the
	// world, and the pre-fetch rings are drawn from wherever that eye is.
	FVector Eye;
	FRotator Look;
	PC->GetPlayerViewPoint(Eye, Look);
	Out = Eye;
	return true;
}

bool UDCSubsystem::IsPlayerPresent() const
{
	if (bPreview)
	{
		return false;
	}
	const UGameInstance* Instance = GetGameInstance();
	const UWorld* World = Instance ? Instance->GetWorld() : nullptr;
	const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	return PC != nullptr && PC->GetPawn() != nullptr;
}

void UDCSubsystem::SetGame(const FString& NewGame, const FString& Why)
{
	if (NewGame.IsEmpty() || NewGame == Game)
	{
		return;
	}
	DC_LOG(Log, TEXT("GAME  %s -> %s   (%s)"), *Game, *NewGame, *Why);
	Game = NewGame;
	for (ADCSlot* Slot : GetSlots())
	{
		Slot->SetWantedAllocKey(FString());
		Slot->ClearRetry();
	}
	LastPollSeconds = 0.0;
}

void UDCSubsystem::NoteFrame(float Ms)
{
	if (Ms <= 0.0f)
	{
		return;
	}

	// The rolling window the X-ray's graph draws. Trimmed from the front, never sorted.
	const double Now = FPlatformTime::Seconds();
	FDCFrameSample Sample;
	Sample.Seconds = Now;
	Sample.Ms = Ms;
	Graph.Add(Sample);
	int32 Drop = 0;
	while (Drop < Graph.Num() && Now - Graph[Drop].Seconds > DCGraphSeconds)
	{
		++Drop;
	}
	if (Drop > 0)
	{
		Graph.RemoveAt(0, Drop, EAllowShrinking::No);
	}
	if (Graph.Num() > DCMaxGraphSamples)
	{
		Graph.RemoveAt(0, Graph.Num() - DCMaxGraphSamples, EAllowShrinking::No);
	}
	Drop = 0;
	while (Drop < GraphMarks.Num() && Now - GraphMarks[Drop].Seconds > DCGraphSeconds)
	{
		++Drop;
	}
	if (Drop > 0)
	{
		GraphMarks.RemoveAt(0, Drop, EAllowShrinking::No);
	}
	++Frames.Frames;
	Frames.SumMs += Ms;
	Frames.WorstMs = FMath::Max(Frames.WorstMs, Ms);
	// Three buckets rather than a histogram, because a watching script wants to difference
	// them: "no frame over 25 ms while the preview window was on screen" is the pass line
	// of plan v6 §11, and that is a subtraction of two readings of Over25.
	Frames.Over16 += Ms > 16.0f ? 1 : 0;
	Frames.Over25 += Ms > 25.0f ? 1 : 0;
	Frames.Over33 += Ms > 33.0f ? 1 : 0;
	if (FrameSamples.Num() < 240000)
	{
		FrameSamples.Add(Ms);
	}
}

FDCFrameStats UDCSubsystem::GetFrameStats()
{
	// The percentiles need the samples sorted, and the status file is written four times a
	// second: sorting ten minutes of frames that often would itself cost frame time, in the
	// one run whose whole purpose is to measure frame time. So they are recomputed at most
	// once every five seconds, which is far fresher than anything reads them.
	const double Now = FPlatformTime::Seconds();
	if (FrameSamples.Num() > 0
		&& (PercentileFrames != FrameSamples.Num() && Now - LastPercentileSeconds >= 5.0))
	{
		LastPercentileSeconds = Now;
		PercentileFrames = FrameSamples.Num();
		TArray<float> Sorted = FrameSamples;
		Sorted.Sort();
		Frames.MedianMs = Sorted[Sorted.Num() / 2];
		Frames.Worst1PercentMs = Sorted[FMath::Clamp(FMath::FloorToInt(Sorted.Num() * 0.99f),
			0, Sorted.Num() - 1)];
	}
	Frames.AverageMs = Frames.Frames > 0
		? static_cast<float>(Frames.SumMs / Frames.Frames) : 0.0f;
	return Frames;
}

void UDCSubsystem::FlushTelemetry(bool bForce)
{
	if (bTelemetryInFlight || Telemetry.Num() == 0)
	{
		return;
	}
	const double Now = FPlatformTime::Seconds();
	if (!bForce && Now - LastTelemetrySeconds < TelemetryFlushSeconds)
	{
		return;
	}
	LastTelemetrySeconds = Now;

	FString Body;
	const TSharedRef<TJsonWriter<TCHAR>> Writer = TJsonWriterFactory<TCHAR>::Create(&Body);
	Writer->WriteArrayStart();
	for (const FDCTelemetryEvent& Event : Telemetry)
	{
		Writer->WriteObjectStart();
		Writer->WriteValue(TEXT("game"), Game);
		Writer->WriteValue(TEXT("region"), Region);
		Writer->WriteValue(TEXT("slot"), Event.SlotId);
		Writer->WriteValue(TEXT("alloc_key"), Event.AllocKey);
		Writer->WriteValue(TEXT("type"), Event.Type);
		Writer->WriteValue(TEXT("value"), Event.Value);
		Writer->WriteValue(TEXT("ts"), Event.TimestampUtc);
		Writer->WriteObjectEnd();
	}
	Writer->WriteArrayEnd();
	Writer->Close();

	const int32 Count = Telemetry.Num();
	Telemetry.Reset();
	bTelemetryInFlight = true;

	FHttpRequestRef Request = MakeRequest(TEXT("/telemetry"), TEXT("POST"));
	Request->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
	Request->SetContentAsString(Body);

	TWeakObjectPtr<UDCSubsystem> Weak(this);
	Request->OnProcessRequestComplete().BindLambda(
		[Weak, Count](FHttpRequestPtr, FHttpResponsePtr Response, bool bOk)
		{
			UDCSubsystem* Self = Weak.Get();
			if (Self == nullptr)
			{
				return;
			}
			Self->bTelemetryInFlight = false;
			const int32 Code = Response.IsValid() ? Response->GetResponseCode() : 0;
			if (bOk && Code == 200)
			{
				Self->TelemetrySent += Count;
				DC_LOG(Log, TEXT("TELEMETRY posted %d event(s)  (%d this run)"), Count, Self->TelemetrySent);
			}
			else
			{
				DC_LOG(Warning, TEXT("TELEMETRY POST /telemetry answered %d - %d event(s) dropped"),
					Code, Count);
			}
		});
	Request->ProcessRequest();
}

// ===================================================================== status

void UDCSubsystem::NoteShot(int32 ActivationSeq, const FString& ShotFile)
{
	// By sequence number, never by slot: two pictures of the same slot can be in the queue at
	// once (the attract rotation fills a slot, then an allocation replaces it), and matching
	// by slot would hang each picture on the wrong activation.
	for (FActivation& Record : Activations)
	{
		if (Record.Seq == ActivationSeq)
		{
			Record.Shot = ShotFile;
			break;
		}
	}
	WriteStatusFile();
}

TArray<FString> UDCSubsystem::GetStatusLines() const
{
	TArray<FString> Lines;
	Lines.Add(FString::Printf(
		TEXT("build %s  ·  uptime %s  ·  restarts: %d  ·  content loading screens: %d"),
		GetBuildConfigName(), *HoursMinutesSeconds(GetUptimeSeconds()),
		GetRestartCount(), GetLoadingScreenCount()));
	Lines.Add(FString::Printf(
		TEXT("backend %s  game %s  region %s  ·  %s  ·  polls %d  changes %d  packs mounted %d"),
		*BackendUrl, *Game, *Region, *BackendStatus, PollCount, ChangeCount, MountedPaks.Num()));

	for (const TWeakObjectPtr<ADCSlot>& Weak : Slots)
	{
		if (const ADCSlot* Slot = Weak.Get())
		{
			Lines.Add(Slot->DescribeState());
		}
	}
	return Lines;
}

void UDCSubsystem::WriteStatusFile()
{
	if (StatusFilePath.IsEmpty())
	{
		return;
	}

	FString Text;
	const TSharedRef<TJsonWriter<TCHAR>> W = TJsonWriterFactory<TCHAR>::Create(&Text);
	W->WriteObjectStart();
	W->WriteValue(TEXT("build"), GetBuildConfigName());
	// The archived build's DCDemo.exe is a launcher that starts the real executable, so a
	// script that started the game does not have the pid of the process that owns the
	// window. This is how a test (and the booth's watchdog) finds it.
	W->WriteValue(TEXT("pid"), static_cast<int32>(FPlatformProcess::GetCurrentProcessId()));
	W->WriteValue(TEXT("now_utc"), UtcNowIso());
	W->WriteValue(TEXT("uptime_s"), GetUptimeSeconds());
	W->WriteValue(TEXT("restarts"), GetRestartCount());
	W->WriteValue(TEXT("content_loading_screens"), GetLoadingScreenCount());
	W->WriteValue(TEXT("backend"), BackendUrl);
	W->WriteValue(TEXT("backend_status"), BackendStatus);
	W->WriteValue(TEXT("game"), Game);
	W->WriteValue(TEXT("region"), Region);
	W->WriteValue(TEXT("poll_interval_s"), PollIntervalSeconds);
	W->WriteValue(TEXT("polls"), PollCount);
	W->WriteValue(TEXT("changes"), ChangeCount);
	W->WriteValue(TEXT("packs_mounted"), MountedPaks.Num());
	W->WriteValue(TEXT("cache_dir"), Cache.GetRoot());
	W->WriteValue(TEXT("cache_packs"), Cache.CountPacks());
	W->WriteValue(TEXT("crypto"), CryptoApi);
	W->WriteValue(TEXT("telemetry_sent"), TelemetrySent);
	W->WriteValue(TEXT("telemetry_dropped"), TelemetryDropped);
	W->WriteValue(TEXT("preview"), bPreview);
	// Non-empty only while the portal's live flip has this copy playing as another region.
	W->WriteValue(TEXT("live_flip_back_to"), FlipBackTo);
	if (bPreview)
	{
		W->WriteValue(TEXT("region_label"), RegionLabel);
		W->WriteValue(TEXT("region_label_jp"), RegionLabelJp);
		W->WriteObjectStart(TEXT("focus"));
		W->WriteValue(TEXT("game"), FocusGame);
		W->WriteValue(TEXT("slot"), FocusSlot);
		W->WriteValue(TEXT("reason"), FocusReason);
		W->WriteObjectEnd();
	}

	// Frame times, the same samples the tour report uses. The counters are cumulative, so
	// a watching script can difference two readings and get the average and the number of
	// frames over 25 ms in any window it cares about - "while the preview window was up".
	const FDCFrameStats Stats = GetFrameStats();
	W->WriteObjectStart(TEXT("frame_ms"));
	W->WriteValue(TEXT("frames"), Stats.Frames);
	W->WriteValue(TEXT("sum_ms"), Stats.SumMs);
	W->WriteValue(TEXT("average"), Stats.AverageMs);
	W->WriteValue(TEXT("median"), Stats.MedianMs);
	W->WriteValue(TEXT("worst_1_percent"), Stats.Worst1PercentMs);
	W->WriteValue(TEXT("worst"), Stats.WorstMs);
	W->WriteValue(TEXT("over_16ms"), Stats.Over16);
	W->WriteValue(TEXT("over_25ms"), Stats.Over25);
	W->WriteValue(TEXT("over_33ms"), Stats.Over33);
	W->WriteObjectEnd();

	W->WriteObjectStart(TEXT("slots"));
	for (const TWeakObjectPtr<ADCSlot>& Weak : Slots)
	{
		const ADCSlot* Slot = Weak.Get();
		if (Slot == nullptr)
		{
			continue;
		}
		W->WriteObjectStart(Slot->SlotId.ToString());
		W->WriteValue(TEXT("state"), DCSlotStateName(Slot->GetState()));
		W->WriteValue(TEXT("size_class"), Slot->GetSizeClassName());
		W->WriteValue(TEXT("wanted_alloc_key"), Slot->GetWantedAllocKey());
		W->WriteValue(TEXT("alloc_key"), Slot->GetActiveAllocKey());
		W->WriteValue(TEXT("piece"), Slot->GetActiveManifest().Piece);
		W->WriteValue(TEXT("version"), Slot->GetActiveManifest().Version);
		W->WriteValue(TEXT("brand"), Slot->GetActiveManifest().Brand.bValid
			? Slot->GetActiveManifest().Brand.ColourHex : FString());
		W->WriteValue(TEXT("emblem"), Slot->GetActiveManifest().Brand.bValid
			? Slot->GetActiveManifest().Brand.Emblem : FString());
		W->WriteValue(TEXT("kind"), Slot->GetActiveManifest().ShowingKind);
		W->WriteValue(TEXT("has_content"), Slot->HasContent());
		W->WriteValue(TEXT("player_inside"), Slot->IsPlayerInside());
		W->WriteValue(TEXT("last_error"), Slot->GetLastError());
		W->WriteValue(TEXT("attempts"), Slot->GetAttempts());
		W->WriteValue(TEXT("active_since_utc"), Slot->HasContent()
			? Slot->GetActiveSince().ToIso8601() : FString());
		W->WriteValue(TEXT("visits"), Slot->GetVisitCount());
		W->WriteValue(TEXT("dwell_s"), Slot->GetTotalDwellSeconds() + Slot->GetDwellSeconds());
		W->WriteValue(TEXT("waypoint"), Slot->IsWaypointActive());

		// What the Player has done inside whatever is standing here - the thing a swap has to
		// carry over, written out four times a second so a test can watch it happen.
		FDCContentState State;
		if (Slot->GetContentState(State))
		{
			W->WriteObjectStart(TEXT("content_state"));
			W->WriteValue(TEXT("light_a_on"), State.bLightAOn);
			W->WriteValue(TEXT("light_b_on"), State.bLightBOn);
			W->WriteValue(TEXT("door_open"), State.bDoorOpen);
			W->WriteValue(TEXT("screen_image_index"), State.ScreenIndex);
			W->WriteValue(TEXT("schema"), Slot->GetActiveManifest().StateSchemaVersion);
			W->WriteObjectEnd();
		}
		W->WriteObjectEnd();
	}
	W->WriteObjectEnd();

	W->WriteArrayStart(TEXT("activations"));
	for (const FActivation& A : Activations)
	{
		W->WriteObjectStart();
		W->WriteValue(TEXT("seq"), A.Seq);
		W->WriteValue(TEXT("slot"), A.SlotId);
		W->WriteValue(TEXT("piece"), A.Piece);
		W->WriteValue(TEXT("version"), A.Version);
		W->WriteValue(TEXT("alloc_key"), A.AllocKey);
		W->WriteValue(TEXT("brand"), A.BrandColour);
		W->WriteValue(TEXT("emblem"), A.BrandEmblem);
		W->WriteValue(TEXT("kind"), A.Kind);
		W->WriteValue(TEXT("source"), A.Source);
		W->WriteValue(TEXT("pack_id"), A.PackId);
		W->WriteValue(TEXT("visible_utc"), A.VisibleUtc);
		W->WriteValue(TEXT("shot"), A.Shot);
		W->WriteValue(TEXT("resolve_ms"), A.ResolveMs);
		W->WriteValue(TEXT("download_ms"), A.DownloadMs);
		W->WriteValue(TEXT("verify_ms"), A.VerifyMs);
		W->WriteValue(TEXT("mount_ms"), A.MountMs);
		W->WriteValue(TEXT("load_ms"), A.LoadMs);
		W->WriteValue(TEXT("spawn_ms"), A.SpawnMs);
		W->WriteValue(TEXT("total_ms"), A.TotalMs);
		W->WriteValue(TEXT("network_bytes"), static_cast<double>(A.NetworkBytes));
		W->WriteValue(TEXT("cached_files"), A.CachedFiles);
		W->WriteValue(TEXT("range_requests"), A.RangeRequests);
		W->WriteObjectEnd();
	}
	W->WriteArrayEnd();

	W->WriteArrayStart(TEXT("fallbacks"));
	for (const FFallbackNote& F : Fallbacks)
	{
		W->WriteObjectStart();
		W->WriteValue(TEXT("seq"), F.Seq);
		W->WriteValue(TEXT("slot"), F.SlotId);
		W->WriteValue(TEXT("reason"), F.Reason);
		W->WriteValue(TEXT("utc"), F.Utc);
		W->WriteObjectEnd();
	}
	W->WriteArrayEnd();

	W->WriteArrayStart(TEXT("state_store"));
	if (const UDCStateStore* Store = UDCStateStore::Get(this))
	{
		for (const FString& Line : Store->DescribeAll())
		{
			W->WriteValue(Line);
		}
	}
	W->WriteArrayEnd();

	if (const UDCInteractor* Interactor = UDCInteractor::Find(this))
	{
		W->WriteObjectStart(TEXT("interaction"));
		W->WriteValue(TEXT("uses"), Interactor->GetTotalUses());
		W->WriteValue(TEXT("door"), Interactor->GetUseCount(EDCInteraction::Door));
		W->WriteValue(TEXT("light_a"), Interactor->GetUseCount(EDCInteraction::LightA));
		W->WriteValue(TEXT("light_b"), Interactor->GetUseCount(EDCInteraction::LightB));
		W->WriteValue(TEXT("screen"), Interactor->GetUseCount(EDCInteraction::Screen));
		W->WriteValue(TEXT("prompt_agreed"), Interactor->GetPromptAgreed());
		W->WriteValue(TEXT("prompt_checked"), Interactor->GetPromptChecked());
		W->WriteValue(TEXT("prompt"), Interactor->GetTarget().IsValid()
			? Interactor->GetTarget().Prompt : FString());
		W->WriteObjectEnd();
	}

	W->WriteObjectEnd();
	W->Close();

	// Written aside and moved into place, so a script that is watching the file never reads
	// half of one.
	const FString Temp = StatusFilePath + TEXT(".tmp");
	if (FFileHelper::SaveStringToFile(Text, *Temp, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
	{
		IFileManager::Get().Move(*StatusFilePath, *Temp, true, true);
	}
}
