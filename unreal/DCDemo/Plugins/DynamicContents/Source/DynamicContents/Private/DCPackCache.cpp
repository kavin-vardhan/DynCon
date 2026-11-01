#include "DCPackCache.h"

#include "DynamicContents.h"

#include "HAL/FileManager.h"
#include "Misc/DateTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

void FDCPackCache::Configure(const FString& InRoot, int32 InKeepPacks)
{
	Root = FPaths::ConvertRelativePathToFull(InRoot);
	KeepPacks = FMath::Max(InKeepPacks, 1);
	IFileManager::Get().MakeDirectory(*Root, true);
	DC_LOG(Log, TEXT("CACHE at %s  keep=%d packs  (%d already there, %lld B)"),
		*Root, KeepPacks, CountPacks(), TotalBytes());
}

void FDCPackCache::SetKeepPacks(int32 InKeepPacks)
{
	KeepPacks = FMath::Max(InKeepPacks, 1);
}

FString FDCPackCache::DirFor(const FString& PackId) const
{
	// A pack id is the server's own "pk_<hex>", but take the leaf of it anyway: a cache path
	// is the one place a string off the network becomes a file path.
	const FString Dir = Root / FPaths::GetCleanFilename(PackId);
	IFileManager::Get().MakeDirectory(*Dir, true);
	return Dir;
}

void FDCPackCache::Touch(const FString& PackId) const
{
	const FString Stamp = DirFor(PackId) / StampName();
	FFileHelper::SaveStringToFile(FDateTime::UtcNow().ToIso8601(), *Stamp);
}

TArray<FString> FDCPackCache::Purge(const TArray<FString>& PackIds)
{
	TArray<FString> Gone;
	for (const FString& PackId : PackIds)
	{
		const FString Dir = Root / FPaths::GetCleanFilename(PackId);
		if (IFileManager::Get().DirectoryExists(*Dir))
		{
			IFileManager::Get().DeleteDirectory(*Dir, false, true);
			Gone.Add(PackId);
		}
	}
	if (Gone.Num() > 0)
	{
		DC_LOG(Log, TEXT("CACHE purged %d pack(s): %s"), Gone.Num(), *FString::Join(Gone, TEXT(" ")));
	}
	return Gone;
}

namespace
{
	struct FDCCacheEntry
	{
		FString PackId;
		FDateTime Used;
	};

	void CollectPacks(const FString& Root, TArray<FDCCacheEntry>& Out)
	{
		TArray<FString> Dirs;
		IFileManager::Get().FindFiles(Dirs, *(Root / TEXT("*")), false, true);
		for (const FString& Name : Dirs)
		{
			FDCCacheEntry Entry;
			Entry.PackId = Name;
			// The stamp's own write time is the "last used"; a pack with no stamp (one that
			// was interrupted mid-download) sorts oldest and goes first.
			const FString Stamp = Root / Name / TEXT(".used");
			Entry.Used = IFileManager::Get().FileExists(*Stamp)
				? IFileManager::Get().GetTimeStamp(*Stamp)
				: FDateTime::MinValue();
			Out.Add(MoveTemp(Entry));
		}
	}
}

TArray<FString> FDCPackCache::Evict(const TSet<FString>& Protect)
{
	TArray<FDCCacheEntry> Entries;
	CollectPacks(Root, Entries);

	TArray<FString> Dropped;
	if (Entries.Num() <= KeepPacks)
	{
		return Dropped;
	}

	Entries.Sort([](const FDCCacheEntry& A, const FDCCacheEntry& B) { return A.Used < B.Used; });

	int32 Remaining = Entries.Num();
	for (const FDCCacheEntry& Entry : Entries)
	{
		if (Remaining <= KeepPacks)
		{
			break;
		}
		if (Protect.Contains(Entry.PackId))
		{
			continue;
		}
		IFileManager::Get().DeleteDirectory(*(Root / Entry.PackId), false, true);
		Dropped.Add(Entry.PackId);
		--Remaining;
	}

	if (Dropped.Num() > 0)
	{
		DC_LOG(Log, TEXT("CACHE evicted %d pack(s) to keep %d: %s"),
			Dropped.Num(), KeepPacks, *FString::Join(Dropped, TEXT(" ")));
	}
	return Dropped;
}

int32 FDCPackCache::CountPacks() const
{
	TArray<FString> Dirs;
	IFileManager::Get().FindFiles(Dirs, *(Root / TEXT("*")), false, true);
	return Dirs.Num();
}

int64 FDCPackCache::TotalBytes() const
{
	TArray<FString> Files;
	IFileManager::Get().FindFilesRecursive(Files, *Root, TEXT("*"), true, false);
	int64 Total = 0;
	for (const FString& File : Files)
	{
		const int64 Size = IFileManager::Get().FileSize(*File);
		if (Size > 0)
		{
			Total += Size;
		}
	}
	return Total;
}
