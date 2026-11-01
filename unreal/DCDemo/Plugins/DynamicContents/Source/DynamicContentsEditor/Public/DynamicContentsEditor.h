// The editor half of the plugin. Nothing in this module exists in the game.
//
// It adds one menu entry - Tools -> "Register this game with Dynamic Contents..." - which
// runs UDCSlotMapTool on the level that is open. The same tool is reachable from a
// commandlet and from editor Python, which is how it runs headless for both maps.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleInterface.h"

class FDynamicContentsEditorModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};
