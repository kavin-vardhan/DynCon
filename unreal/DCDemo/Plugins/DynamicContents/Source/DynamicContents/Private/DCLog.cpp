#include "DCLog.h"

#include "HAL/FileManager.h"
#include "HAL/PlatformTime.h"
#include "Misc/CommandLine.h"
#include "Misc/DateTime.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/Archive.h"

DEFINE_LOG_CATEGORY(LogDC);

float DCElapsedMs(double StartSeconds)
{
	return static_cast<float>((FPlatformTime::Seconds() - StartSeconds) * 1000.0);
}

FDCFileLog& FDCFileLog::Get()
{
	static FDCFileLog Instance;
	return Instance;
}

void FDCFileLog::OpenIfNeeded()
{
	if (bTriedToOpen)
	{
		return;
	}
	bTriedToOpen = true;

	FString Wanted;
	if (!FParse::Value(FCommandLine::Get(), TEXT("DCLogFile="), Wanted, false) || Wanted.IsEmpty())
	{
		Wanted = FPaths::ProjectSavedDir() / TEXT("DCLogs")
			/ FString::Printf(TEXT("dc_%s.log"), *FDateTime::Now().ToString(TEXT("%Y%m%d_%H%M%S")));
	}
	Wanted = FPaths::ConvertRelativePathToFull(Wanted.TrimQuotes());

	IFileManager::Get().MakeDirectory(*FPaths::GetPath(Wanted), true);

	// FILEWRITE_AllowRead so the run can be tailed while it is still going.
	File.Reset(IFileManager::Get().CreateFileWriter(*Wanted, FILEWRITE_AllowRead));
	if (File.IsValid())
	{
		Path = Wanted;
		const FString Header = FString::Printf(
			TEXT("# DynamicContents log  started=%s  file=%s\n"),
			*FDateTime::Now().ToString(), *Path);
		auto Utf8 = StringCast<UTF8CHAR>(*Header);
		File->Serialize(const_cast<UTF8CHAR*>(Utf8.Get()), Utf8.Length() * sizeof(UTF8CHAR));
		File->Flush();
	}
}

void FDCFileLog::Write(const TCHAR* Verbosity, const FString& Line)
{
	FScopeLock Guard(&Lock);

	OpenIfNeeded();
	if (!File.IsValid())
	{
		return;
	}

	const FString Text = FString::Printf(TEXT("[%s][%-7s] %s\n"),
		*FDateTime::Now().ToString(TEXT("%H:%M:%S.%s")), Verbosity, *Line);

	// UTF-8 on purpose: the report files this project writes are read by PowerShell and by
	// Python, and both default to UTF-8 here.
	auto Utf8 = StringCast<UTF8CHAR>(*Text);
	File->Serialize(const_cast<UTF8CHAR*>(Utf8.Get()), Utf8.Length() * sizeof(UTF8CHAR));
	File->Flush();

	++LineCount;
}
