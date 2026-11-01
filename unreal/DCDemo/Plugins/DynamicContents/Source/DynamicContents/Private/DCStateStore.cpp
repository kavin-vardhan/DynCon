#include "DCStateStore.h"

#include "DynamicContents.h"

#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "Misc/DateTime.h"

FString FDCContentState::Describe() const
{
	return FString::Printf(TEXT("lights A %s / B %s, door %s, screen %d"),
		bLightAOn ? TEXT("on") : TEXT("off"),
		bLightBOn ? TEXT("on") : TEXT("off"),
		bDoorOpen ? TEXT("open") : TEXT("closed"),
		ScreenIndex);
}

UDCStateStore* UDCStateStore::Get(const UObject* WorldContext)
{
	if (WorldContext == nullptr || GEngine == nullptr)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContext,
		EGetWorldErrorMode::ReturnNull);
	if (World == nullptr)
	{
		return nullptr;
	}
	UGameInstance* Instance = World->GetGameInstance();
	return Instance ? Instance->GetSubsystem<UDCStateStore>() : nullptr;
}

FString UDCStateStore::KeyFor(const FString& SlotId, const FString& ContentId)
{
	// No version in the key: that is the whole point. The schema version is checked on the
	// way out instead, so a record that cannot be applied can be reported rather than missed.
	return SlotId + TEXT("|") + ContentId;
}

void UDCStateStore::Save(const FString& SlotId, const FString& ContentId, int32 SchemaVersion,
	const FDCContentState& State)
{
	if (SlotId.IsEmpty() || ContentId.IsEmpty())
	{
		return;
	}
	const FString Key = KeyFor(SlotId, ContentId);
	FEntry& Entry = Entries.FindOrAdd(Key);
	const bool bChanged = Entry.Saves == 0 || Entry.State != State
		|| Entry.SchemaVersion != SchemaVersion;
	Entry.SchemaVersion = SchemaVersion;
	Entry.State = State;
	Entry.SavedUtc = FDateTime::UtcNow().ToIso8601();
	++Entry.Saves;

	DC_LOG(Log, TEXT("STATE save    %s schema %d: %s%s"), *Key, SchemaVersion,
		*State.Describe(), bChanged ? TEXT("") : TEXT("  (unchanged)"));
}

bool UDCStateStore::Restore(const FString& SlotId, const FString& ContentId,
	int32 SchemaVersion, FDCContentState& OutState)
{
	if (SlotId.IsEmpty() || ContentId.IsEmpty())
	{
		return false;
	}
	const FString Key = KeyFor(SlotId, ContentId);
	FEntry* Entry = Entries.Find(Key);
	if (Entry == nullptr)
	{
		DC_LOG(Log, TEXT("STATE restore %s: nothing kept, the piece keeps its own defaults"), *Key);
		return false;
	}
	if (Entry->SchemaVersion != SchemaVersion)
	{
		// Discard, never apply and never crash: the two records are not about the same four
		// things, and half-applying one would be worse than starting clean.
		DC_LOG(Warning, TEXT("STATE restore %s: kept schema %d, this piece speaks schema %d "
			"- discarding the record, the piece keeps its own defaults"),
			*Key, Entry->SchemaVersion, SchemaVersion);
		Entries.Remove(Key);
		return false;
	}

	OutState = Entry->State;
	++Entry->Restores;
	DC_LOG(Log, TEXT("STATE restore %s schema %d: %s  (saved %s)"), *Key, SchemaVersion,
		*OutState.Describe(), *Entry->SavedUtc);
	return true;
}

bool UDCStateStore::Has(const FString& SlotId, const FString& ContentId) const
{
	return Entries.Contains(KeyFor(SlotId, ContentId));
}

void UDCStateStore::Clear(const FString& Why)
{
	if (Entries.Num() == 0)
	{
		return;
	}
	DC_LOG(Log, TEXT("STATE clear   %d record(s): %s"), Entries.Num(), *Why);
	Entries.Empty();
}

TArray<FString> UDCStateStore::DescribeAll() const
{
	TArray<FString> Keys;
	Entries.GetKeys(Keys);
	Keys.Sort([](const FString& A, const FString& B) { return A < B; });

	TArray<FString> Lines;
	for (const FString& Key : Keys)
	{
		const FEntry& Entry = Entries[Key];
		Lines.Add(FString::Printf(TEXT("%s  schema %d  %s  (saved %d, restored %d)"),
			*Key, Entry.SchemaVersion, *Entry.State.Describe(), Entry.Saves, Entry.Restores));
	}
	return Lines;
}

void UDCStateStore::Deinitialize()
{
	Entries.Empty();
	Super::Deinitialize();
}
