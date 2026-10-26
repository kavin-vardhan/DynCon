#include "DCPackMounter.h"

#include "DynamicContents.h"

#include "GenericPlatform/GenericPlatformFile.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformFileManager.h"
#include "HAL/PlatformTime.h"
#include "IPlatformFilePak.h"
#include "Misc/App.h"
#include "Misc/CoreDelegates.h"
#include "Misc/Paths.h"
#include "ShaderCodeLibrary.h"

namespace
{
	/** Read order for content packs. Above the base game's paks, so a pack always wins. */
	constexpr int32 DCPackOrder = 10;

	/** Writes the first few entries of a mounted pak's index to the log. */
	class FDCPakIndexLogger : public IPlatformFile::FDirectoryVisitor
	{
	public:
		int32 Logged = 0;
		int32 Total = 0;

		virtual bool Visit(const TCHAR* FilenameOrDirectory, bool bIsDirectory) override
		{
			if (bIsDirectory)
			{
				return true;
			}
			++Total;
			if (Logged < UDCPackMounter::LoggedPakEntries)
			{
				++Logged;
				DC_LOG(Log, TEXT("    pak entry: %s"), FilenameOrDirectory);
			}
			return true;
		}
	};
}

FDCMountResult UDCPackMounter::MountPackDir(const FString& PackDir)
{
	FDCMountResult Result;

	const FString Dir = FPaths::ConvertRelativePathToFull(PackDir);
	TArray<FString> Paks;
	IFileManager::Get().FindFiles(Paks, *(Dir / TEXT("*.pak")), true, false);

	if (Paks.Num() != 1)
	{
		Result.Error = FString::Printf(TEXT("expected exactly one *.pak in '%s', found %d"), *Dir, Paks.Num());
		DC_LOG(Error, TEXT("MOUNT FAIL  %s"), *Result.Error);
		return Result;
	}

	return Mount(Dir / Paks[0]);
}

FDCMountResult UDCPackMounter::Mount(const FString& InPakPath)
{
	FDCMountResult Result;
	Result.PakPath = FPaths::ConvertRelativePathToFull(InPakPath);

	const FString UtocPath = FPaths::ChangeExtension(Result.PakPath, TEXT(".utoc"));
	const FString UcasPath = FPaths::ChangeExtension(Result.PakPath, TEXT(".ucas"));

	Result.PakBytes  = IFileManager::Get().FileSize(*Result.PakPath);
	Result.UtocBytes = IFileManager::Get().FileSize(*UtocPath);
	Result.UcasBytes = IFileManager::Get().FileSize(*UcasPath);
	Result.bHasIoStoreContainer = Result.UtocBytes > 0;

	if (Result.PakBytes < 0)
	{
		Result.Error = FString::Printf(TEXT("no such pak: %s"), *Result.PakPath);
		DC_LOG(Error, TEXT("MOUNT FAIL  %s"), *Result.Error);
		return Result;
	}

	DC_LOG(Log, TEXT("MOUNT begin  pak=%s (%lld B)  utoc=%lld B  ucas=%lld B"),
		*FPaths::GetCleanFilename(Result.PakPath), Result.PakBytes, Result.UtocBytes, Result.UcasBytes);

	const double Start = FPlatformTime::Seconds();

	// 1. The documented route: the pak system's own mounting delegate, bound by
	//    FPakPlatformFile when it is the active platform file. It mounts the pak and, when
	//    there is one, the sibling IoStore container, and hands back the mounted pak.
	IPakFile* Mounted = nullptr;
	if (FCoreDelegates::MountPak.IsBound())
	{
		Mounted = FCoreDelegates::MountPak.Execute(Result.PakPath, DCPackOrder);
		if (Mounted != nullptr)
		{
			Result.bMounted = true;
			Result.Api = TEXT("FCoreDelegates::MountPak");
		}
	}
	else
	{
		DC_LOG(Warning, TEXT("MOUNT  FCoreDelegates::MountPak is not bound (no pak platform file?)"));
	}

	// 2. Fallback: go straight at FPakPlatformFile. Same code underneath, but it works even
	//    if nothing bound the delegate.
	if (!Result.bMounted)
	{
		FPakPlatformFile* PakPlatformFile =
			static_cast<FPakPlatformFile*>(FPlatformFileManager::Get().FindPlatformFile(FPakPlatformFile::GetTypeName()));

		if (PakPlatformFile == nullptr)
		{
			Result.Error = TEXT("FPakPlatformFile is not in the platform file chain (unpacked build?)");
		}
		else if (PakPlatformFile->Mount(*Result.PakPath, DCPackOrder))
		{
			Result.bMounted = true;
			Result.Api = TEXT("FPakPlatformFile::Mount");
		}
		else
		{
			Result.Error = TEXT("FPakPlatformFile::Mount returned false (see LogPakFile lines above)");
		}
	}

	Result.Milliseconds = DCElapsedMs(Start);

	if (Mounted != nullptr)
	{
		Result.MountPoint = Mounted->PakGetMountPoint();
		Result.PakFileCount = Mounted->GetNumFiles();

		FDCPakIndexLogger Logger;
		Mounted->PakVisitPrunedFilenames(Logger);
	}

	if (Result.bMounted)
	{
		// The pak system has just told the shader code library about the new chunk; asking
		// the library to open again is what makes it bind that chunk's shaders. Without it
		// the pack's material instances have no shaders and fall back to the default
		// material, so the content renders as grey checks.
		const double ShaderStart = FPlatformTime::Seconds();
		Result.bShaderLibraryOpened = FShaderCodeLibrary::OpenLibrary(
			FApp::GetProjectName(), FPaths::ProjectContentDir());
		Result.ShaderLibraryMilliseconds = DCElapsedMs(ShaderStart);
		DC_LOG(Log, TEXT("SHADERS %s   library '%s' reopened in %.1f ms"),
			Result.bShaderLibraryOpened ? TEXT("ok") : TEXT("(no new components)"),
			FApp::GetProjectName(), Result.ShaderLibraryMilliseconds);
	}

	if (Result.bMounted)
	{
		DC_LOG(Log, TEXT("MOUNT ok     %s via %s in %.1f ms  mountpoint='%s'  pak index entries=%d  iostore=%s"),
			*FPaths::GetCleanFilename(Result.PakPath), *Result.Api, Result.Milliseconds,
			*Result.MountPoint, Result.PakFileCount, Result.bHasIoStoreContainer ? TEXT("yes") : TEXT("no"));
	}
	else
	{
		DC_LOG(Error, TEXT("MOUNT FAIL   %s after %.1f ms: %s"),
			*FPaths::GetCleanFilename(Result.PakPath), Result.Milliseconds, *Result.Error);
	}

	return Result;
}

bool UDCPackMounter::Unmount(const FString& PakPath)
{
	const FString Full = FPaths::ConvertRelativePathToFull(PakPath);

	if (FCoreDelegates::OnUnmountPak.IsBound())
	{
		const bool bOk = FCoreDelegates::OnUnmountPak.Execute(Full);
		DC_LOG(Log, TEXT("UNMOUNT %s  %s"), bOk ? TEXT("ok") : TEXT("FAIL"), *FPaths::GetCleanFilename(Full));
		return bOk;
	}

	DC_LOG(Warning, TEXT("UNMOUNT  no unmount delegate bound"));
	return false;
}
