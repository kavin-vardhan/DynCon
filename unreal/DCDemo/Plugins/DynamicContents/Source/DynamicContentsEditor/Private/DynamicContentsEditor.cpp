#include "DynamicContentsEditor.h"

#include "DCSlotMapTool.h"

#include "Misc/MessageDialog.h"
#include "Modules/ModuleManager.h"
#include "ToolMenus.h"

#define LOCTEXT_NAMESPACE "DynamicContentsEditor"

namespace
{
	/**
	 * The button. It runs the tool with its defaults - which means the backend at
	 * 127.0.0.1:8700, the game taken from the level's name, and the files under
	 * Saved/DCSlotMap/<game>/ - and then says what happened, including the paths, so a
	 * developer who pressed it by mistake knows exactly what moved.
	 */
	void OnRegisterThisGame()
	{
		FDCSlotMapOptions Options;
		const FDCSlotMapResult Result = UDCSlotMapTool::RegisterCurrentLevel(Options);

		FString Text = Result.Summary;
		if (!Result.MapImagePath.IsEmpty())
		{
			Text += TEXT("\n\n") + Result.MapImagePath;
		}
		if (!Result.bOk && !Result.Message.IsEmpty())
		{
			Text += TEXT("\n\n") + Result.Message;
		}
		if (!Result.PostResponse.IsEmpty())
		{
			Text += TEXT("\n\n") + Result.PostResponse.Left(600);
		}

		FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(Text),
			Result.bOk ? LOCTEXT("DCRegisteredTitle", "Registered with Dynamic Contents")
			           : LOCTEXT("DCRegisterFailedTitle", "Dynamic Contents: nothing was registered"));
	}

	void RegisterMenus()
	{
		FToolMenuOwnerScoped OwnerScoped(FName(TEXT("DynamicContentsEditor")));

		UToolMenu* Menu = UToolMenus::Get()->ExtendMenu(TEXT("LevelEditor.MainMenu.Tools"));
		if (Menu == nullptr)
		{
			return;
		}
		FToolMenuSection& Section = Menu->FindOrAddSection(
			FName(TEXT("DynamicContents")), LOCTEXT("DCSection", "Dynamic Contents"));
		Section.AddMenuEntry(
			FName(TEXT("DCRegisterThisGame")),
			LOCTEXT("DCRegisterLabel", "Register this game with Dynamic Contents…"),
			LOCTEXT("DCRegisterTip",
				"Capture this level's slot map and a thumbnail of every slot, and upload them "
				"to the Dynamic Contents backend."),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateStatic(&OnRegisterThisGame)));
	}
}

void FDynamicContentsEditorModule::StartupModule()
{
	UToolMenus::RegisterStartupCallback(
		FSimpleMulticastDelegate::FDelegate::CreateStatic(&RegisterMenus));
}

void FDynamicContentsEditorModule::ShutdownModule()
{
	UToolMenus::UnRegisterStartupCallback(this);
	UToolMenus::UnregisterOwner(FName(TEXT("DynamicContentsEditor")));
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FDynamicContentsEditorModule, DynamicContentsEditor)
