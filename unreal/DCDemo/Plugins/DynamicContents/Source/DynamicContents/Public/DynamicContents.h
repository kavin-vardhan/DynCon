// DynamicContents runtime module.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

// LogDC, DCElapsedMs and DC_LOG live here: every call site in the plugin logs through DC_LOG
// so the evidence lands in Saved\DCLogs\ as well as in UE_LOG, which Shipping compiles out.
#include "DCLog.h"
