// The headless entry to the slot-map tool: one map per run.
//
//   "<engine>\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" ^
//     "unreal\DCDemo\DCDemo.uproject" ^
//     -run=DynamicContentsEditor.DCRegisterGameCommandlet ^
//     -map=/Game/Maps/GameA -game=A -backend=http://127.0.0.1:8700 ^
//     -AllowCommandletRendering -unattended -nosplash
//
// **-AllowCommandletRendering is not optional.** A commandlet runs with rendering switched
// off unless it is asked for, and the tool's whole job is to render two kinds of picture.
//
// For both maps in one editor session - which is a minute of start-up cheaper - use
// `unreal\Tools\register_games.py` instead; it calls the same UDCSlotMapTool.

#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"

#include "DCRegisterGameCommandlet.generated.h"

UCLASS()
class UDCRegisterGameCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UDCRegisterGameCommandlet();

	virtual int32 Main(const FString& Params) override;
};
