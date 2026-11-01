// The game copy's own pack cache: one folder per pack, least-recently-used eviction.
//
// Lives under the project's Saved folder (`Saved\DCPacks\` by default, `-DCCacheDir=` to put
// it elsewhere) so a second copy of the same build - the region preview window of plan v6
// §11 - gets its own cache without any other change. A reset at the booth sends a purge list
// down through GET /changes, which is how "every visitor sees a real download" is kept true
// while the rival and default packs stay cached.

#pragma once

#include "CoreMinimal.h"

class DYNAMICCONTENTS_API FDCPackCache
{
public:
	void Configure(const FString& InRoot, int32 InKeepPacks);

	const FString& GetRoot() const { return Root; }
	int32 GetKeepPacks() const { return KeepPacks; }
	void SetKeepPacks(int32 InKeepPacks);

	/** The folder this pack's files live in, created if it is not there yet. */
	FString DirFor(const FString& PackId) const;

	/** Marks a pack as used now; the stamp is what the LRU sorts on. */
	void Touch(const FString& PackId) const;

	/** Deletes these packs outright (the booth reset's purge list). Returns what went. */
	TArray<FString> Purge(const TArray<FString>& PackIds);

	/**
	 * Drops least-recently-used packs until only KeepPacks are left. Packs in Protect are
	 * never dropped - deleting the files of a pack that is mounted would pull the content out
	 * from under the piece that is on screen.
	 */
	TArray<FString> Evict(const TSet<FString>& Protect);

	/** How many pack folders are in the cache. */
	int32 CountPacks() const;

	/** Total bytes in the cache. */
	int64 TotalBytes() const;

private:
	FString Root;
	int32 KeepPacks = 8;

	static const TCHAR* StampName() { return TEXT(".used"); }
};
