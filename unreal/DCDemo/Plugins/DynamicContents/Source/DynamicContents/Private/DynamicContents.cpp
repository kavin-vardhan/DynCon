#include "DynamicContents.h"

#include "HAL/PlatformTime.h"

DEFINE_LOG_CATEGORY(LogDC);

float DCElapsedMs(double StartSeconds)
{
	return static_cast<float>((FPlatformTime::Seconds() - StartSeconds) * 1000.0);
}

IMPLEMENT_MODULE(FDefaultModuleImpl, DynamicContents);
