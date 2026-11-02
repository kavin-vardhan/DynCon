// Logging for the dynamic-content path, in a form that survives a Shipping build.
//
// Shipping compiles UE_LOG out, and until MSVC 14.44 is installed on this PC a Development
// game cannot be linked at all, so every piece of evidence this project produces has to
// come from somewhere other than the engine log. DC_LOG writes the same line twice: once
// through UE_LOG (so an editor or Development run still reads normally) and once into a
// plain text file under Saved\DCLogs\, which exists in every configuration.

#pragma once

#include "CoreMinimal.h"
#include "HAL/CriticalSection.h"
#include "Logging/LogMacros.h"
#include "Modules/ModuleManager.h"

/** Every step of the dynamic-content path logs here, so one grep tells the whole story. */
DYNAMICCONTENTS_API DECLARE_LOG_CATEGORY_EXTERN(LogDC, Log, All);

/** Milliseconds since an FPlatformTime::Seconds() stamp, for the timings in the log. */
DYNAMICCONTENTS_API float DCElapsedMs(double StartSeconds);

/**
 * The file half of DC_LOG: one text file per run of the game, appended to line by line and
 * flushed every time, so the evidence is on disk even if the process is killed.
 *
 * Path: <project saved dir>\DCLogs\dc_<yyyymmdd_hhmmss>.log, or whatever -DCLogFile= says.
 * A packaged build's "project saved dir" is <build>\DCDemo\Saved\, so the logs land next to
 * the build and the runner script can pick them up.
 */
class DYNAMICCONTENTS_API FDCFileLog
{
public:
	static FDCFileLog& Get();

	/** Appends one line, with a timestamp and the verbosity it was logged at. */
	void Write(const TCHAR* Verbosity, const FString& Line);

	/** Where this run is writing. Empty if the file could not be opened. */
	const FString& GetPath() const { return Path; }

	/** How many lines have gone in so far - a cheap "did anything log at all" check. */
	int32 GetLineCount() const { return LineCount; }

private:
	FDCFileLog() = default;

	void OpenIfNeeded();

	FCriticalSection Lock;
	TUniquePtr<class FArchive> File;
	FString Path;
	int32 LineCount = 0;
	bool bTriedToOpen = false;
};

/**
 * DC_LOG(Log, TEXT("mounted %s in %.1f ms"), *Name, Ms);
 *
 * Verbosity is an ELogVerbosity name (Log / Warning / Error), exactly as for UE_LOG. The
 * format string is always present, so no ##__VA_ARGS__ trick is needed and the macro behaves
 * the same under both MSVC preprocessors.
 */
#define DC_LOG(Verbosity, ...) \
	do { \
		const FString DCLogLine_ = FString::Printf(__VA_ARGS__); \
		UE_LOG(LogDC, Verbosity, TEXT("%s"), *DCLogLine_); \
		FDCFileLog::Get().Write(TEXT(#Verbosity), DCLogLine_); \
	} while (0)
