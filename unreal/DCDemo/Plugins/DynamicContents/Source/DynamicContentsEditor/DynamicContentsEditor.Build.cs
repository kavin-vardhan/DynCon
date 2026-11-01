using UnrealBuildTool;

/// <summary>
/// The developer's half of the plugin (demo plan v6 section 6): the slot-map tool.
///
/// It is an **Editor** module, so none of this is compiled into the game. That matters for
/// more than tidiness: the tool spawns scene captures and talks to the backend with a
/// developer's credentials, and the shipped game must contain neither.
/// </summary>
public class DynamicContentsEditor : ModuleRules
{
	public DynamicContentsEditor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",

			// ADCSlot and ADCContentActor: the tool reads what the map already declares.
			"DynamicContents"
		});

		PrivateDependencyModuleNames.AddRange(new string[] {
			// GEditor, the editor world, loading a map by package path.
			"UnrealEd",

			// The menu entry under Tools.
			"ToolMenus",
			"Slate",
			"SlateCore",

			// The captures: render targets, flushing the render thread, and writing a PNG
			// (FImageUtils lives in Engine, FImage in ImageCore).
			"RenderCore",
			"ImageCore",

			// POST /games/register, and the JSON that goes with it.
			"HTTP",
			"Json"
		});
	}
}
