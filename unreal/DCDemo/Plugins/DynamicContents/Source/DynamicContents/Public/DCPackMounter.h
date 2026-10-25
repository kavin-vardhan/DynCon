// Runtime mounting of a content pack: one .pak (plus, with IoStore on, a sibling .utoc/.ucas).

#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"

#include "DCPackMounter.generated.h"

/** What happened when we tried to mount one pack. Everything here goes into the LogDC line. */
USTRUCT(BlueprintType)
struct FDCMountResult
{
	GENERATED_BODY()

	/** True only if the pak *and* its IoStore container (when there is one) mounted. */
	UPROPERTY(BlueprintReadOnly, Category = "DC")
	bool bMounted = false;

	/** Which API did it: "FCoreDelegates::MountPak" or "FPakPlatformFile::Mount". */
	UPROPERTY(BlueprintReadOnly, Category = "DC")
	FString Api;

	UPROPERTY(BlueprintReadOnly, Category = "DC")
	FString PakPath;

	/** The pak's own mount point, i.e. where its files appear in the virtual file system. */
	UPROPERTY(BlueprintReadOnly, Category = "DC")
	FString MountPoint;

	UPROPERTY(BlueprintReadOnly, Category = "DC")
	FString Error;

	UPROPERTY(BlueprintReadOnly, Category = "DC")
	float Milliseconds = 0.0f;

	/** Files listed in the pak index (small when IoStore is on - the assets live in the .ucas). */
	UPROPERTY(BlueprintReadOnly, Category = "DC")
	int32 PakFileCount = 0;

	UPROPERTY(BlueprintReadOnly, Category = "DC")
	int64 PakBytes = 0;

	UPROPERTY(BlueprintReadOnly, Category = "DC")
	int64 UtocBytes = 0;

	UPROPERTY(BlueprintReadOnly, Category = "DC")
	int64 UcasBytes = 0;

	UPROPERTY(BlueprintReadOnly, Category = "DC")
	bool bHasIoStoreContainer = false;

	/**
	 * Whether the pack's shaders were picked up. A pack carries its own component of the
	 * game's shader library, and the library only binds new components when it is asked to
	 * open again - without this the pack's material instances fall back to the default
	 * material and the content renders as grey checks.
	 */
	UPROPERTY(BlueprintReadOnly, Category = "DC")
	bool bShaderLibraryOpened = false;

	UPROPERTY(BlueprintReadOnly, Category = "DC")
	float ShaderLibraryMilliseconds = 0.0f;
};

/**
 * Mounts and unmounts content packs at runtime.
 *
 * A pack directory holds exactly one `*.pak`; when the project is packaged with IoStore (the
 * 5.7 default) the actual assets are in the sibling `.ucas`, indexed by the `.utoc`, and the
 * `.pak` carries whatever was left out of the container. FPakPlatformFile::Mount mounts both
 * halves - it looks for the `.utoc` next to the `.pak` itself - so one call is enough; see
 * Engine\Source\Runtime\PakFile\Private\IPlatformFilePak.cpp (FPakPlatformFile::Mount).
 */
UCLASS()
class DYNAMICCONTENTS_API UDCPackMounter : public UObject
{
	GENERATED_BODY()

public:
	/** Mounts the single *.pak found in PackDir. */
	static FDCMountResult MountPackDir(const FString& PackDir);

	/** Mounts one pak by full path. */
	static FDCMountResult Mount(const FString& PakPath);

	static bool Unmount(const FString& PakPath);

	/** How many entries of the pak index to write to the log after a successful mount. */
	static constexpr int32 LoggedPakEntries = 12;
};
