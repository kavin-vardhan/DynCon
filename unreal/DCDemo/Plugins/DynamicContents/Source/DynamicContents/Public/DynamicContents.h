// DynamicContents runtime module.

#pragma once

#include "CoreMinimal.h"
#include "Logging/LogMacros.h"
#include "Modules/ModuleManager.h"

/** Every step of the dynamic-content path logs here, so one grep tells the whole story. */
DYNAMICCONTENTS_API DECLARE_LOG_CATEGORY_EXTERN(LogDC, Log, All);

/** Milliseconds since an FPlatformTime::Seconds() stamp, for the timings in the log. */
DYNAMICCONTENTS_API float DCElapsedMs(double StartSeconds);
