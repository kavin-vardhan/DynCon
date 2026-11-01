#include "DCRegisterGameCommandlet.h"

#include "DCSlotMapTool.h"

#include "FileHelpers.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"

DEFINE_LOG_CATEGORY_STATIC(LogDCRegisterGame, Log, All);

UDCRegisterGameCommandlet::UDCRegisterGameCommandlet()
{
	IsClient = true;         // leaving this true is what keeps rendering possible at all
	IsEditor = true;
	IsServer = false;
	LogToConsole = true;
	ShowErrorCount = true;
}

int32 UDCRegisterGameCommandlet::Main(const FString& Params)
{
	FString MapPackage;
	FParse::Value(*Params, TEXT("map="), MapPackage);

	FDCSlotMapOptions Options;
	FParse::Value(*Params, TEXT("game="), Options.Game);
	FParse::Value(*Params, TEXT("backend="), Options.Backend);
	FParse::Value(*Params, TEXT("out="), Options.OutDir);
	FParse::Value(*Params, TEXT("mappixels="), Options.MapLongSidePixels);
	FParse::Value(*Params, TEXT("thumbwidth="), Options.ThumbWidthPixels);
	FParse::Value(*Params, TEXT("eyeheight="), Options.EyeHeightM);
	if (FParse::Param(*Params, TEXT("nopost")))
	{
		Options.bPostToBackend = false;
	}
	if (FParse::Param(*Params, TEXT("noatmosphere")))
	{
		Options.bMapAtmosphere = false;
	}

	if (!MapPackage.IsEmpty())
	{
		FString Filename;
		if (!FPackageName::TryConvertLongPackageNameToFilename(
			MapPackage, Filename, FPackageName::GetMapPackageExtension()))
		{
			UE_LOG(LogDCRegisterGame, Error,
				TEXT("%s is not a package path this project knows (try /Game/Maps/GameA)"),
				*MapPackage);
			return 1;
		}
		UE_LOG(LogDCRegisterGame, Display, TEXT("loading %s"), *Filename);
		if (!FEditorFileUtils::LoadMap(Filename, /*LoadAsTemplate=*/false, /*bShowProgress=*/false))
		{
			UE_LOG(LogDCRegisterGame, Error, TEXT("could not load %s"), *Filename);
			return 1;
		}
	}

	const FDCSlotMapResult Result = UDCSlotMapTool::RegisterCurrentLevel(Options);
	for (const FString& Line : Result.Log)
	{
		UE_LOG(LogDCRegisterGame, Display, TEXT("%s"), *Line);
	}
	if (!Result.bOk)
	{
		UE_LOG(LogDCRegisterGame, Error, TEXT("%s"), *Result.Message);
		return 1;
	}
	return 0;
}
