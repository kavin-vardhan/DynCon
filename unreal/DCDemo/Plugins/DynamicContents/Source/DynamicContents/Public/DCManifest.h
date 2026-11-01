// What the backend says belongs in a slot, once the signature has been checked and the
// payload parsed: see server\README.md ("Verifying a manifest") and specs\server_spec_v1.md §4.
//
// /resolve answers with an *envelope*:
//
//     { "signed_payload": "{\"alloc_key\":\"…\",…}", "signature": "<base64>",
//       "signature_alg": "RS256-canonical-json-v1" }
//
// The signature is RS256 over the exact UTF-8 bytes of the signed_payload *string*, so a
// client verifies bytes first and only then parses them - it never has to reproduce the
// server's canonical JSON to check a signature. FDCManifest::FromJson parses what is inside.

#pragma once

#include "CoreMinimal.h"

class FJsonObject;

/** One file of a pack: what it is called, how big it is, its hash, and a signed link to it. */
struct DYNAMICCONTENTS_API FDCPackFile
{
	FString Name;
	int64 Size = 0;
	FString Sha256;

	/** Relative to the backend address: "/files/<pack>/<name>?exp=…&sig=…". */
	FString Url;
};

/**
 * A brand is a colour and an emblem, and nothing else. It is a runtime input - never baked
 * into a pack - which is what lets one piece of geometry be "yours" in one region and a
 * rival's in another.
 */
struct DYNAMICCONTENTS_API FDCBrand
{
	bool bValid = false;
	FString ColourHex;
	FString Emblem;

	/** The colour the material wants: the hex is sRGB, the parameter is linear. */
	FLinearColor ToLinearColour() const;

	/** "#E23D3D star" or "no-brand" - the words the log and the status strip use. */
	FString Describe() const;
};

/** The parsed, verified manifest for one slot. */
struct DYNAMICCONTENTS_API FDCManifest
{
	// ---- which slot, and the key that says "this is still what belongs here"
	FString Slot;
	FString Game;
	FString Region;
	FString AllocKey;
	bool bIsDefault = false;

	// ---- what to show
	FString Piece;
	FString Version;
	FString SizeClass;
	FString ClassPath;
	int32 StateSchemaVersion = 1;
	TArray<FString> StateSchema;

	// ---- where to get it
	FString PackId;
	int64 PackTotalBytes = 0;
	TArray<FDCPackFile> Files;

	// ---- who it belongs to and why it is here
	FDCBrand Brand;
	FString ShowingKind;        // visitor | rival | default
	FString ShowingSource;      // alloc:<id> | rotation:<k> | rival-after:<id>
	FString ShowingEndsAt;
	FString ShowingReason;

	/** Which demo time block this is, and the lot it was won in (empty when nobody bid). */
	int32 ShowingBlock = -1;
	FString ShowingLot;

	FString ServerTime;
	FString ValidUntil;

	/**
	 * The RS256 over these exact bytes checked out. Set by UDCSubsystem the moment it does,
	 * so the X-ray can say "signature OK" and mean it rather than mean "the server said so".
	 */
	bool bSignatureVerified = false;

	/** Enough to act on: a slot, a key, a class path and at least one file. */
	bool IsValid() const;

	/** "content1 v1 brand #E23D3D star (visitor)" - one phrase for a log line. */
	FString Describe() const;

	/** Total declared size of every file. */
	int64 TotalFileBytes() const;

	static bool FromJson(const TSharedPtr<FJsonObject>& Payload, FDCManifest& Out, FString& OutError);
};
