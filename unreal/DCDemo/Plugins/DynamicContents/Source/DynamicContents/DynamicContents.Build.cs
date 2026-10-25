using UnrealBuildTool;

public class DynamicContents : ModuleRules
{
	public DynamicContents(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine"
		});

		PrivateDependencyModuleNames.AddRange(new string[] {
			// Runtime pak + IoStore container mounting (FPakPlatformFile).
			"PakFile",
			"Projects",
			"RenderCore"
		});

		// Same reason as in DCDemo.Build.cs (KeepLiveCodingAbiOfPrecompiledEngine): the game
		// is linked with -NoLiveCoding to keep Module.LiveCoding out, so every module we
		// compile ourselves has to keep the UObject registration structs at the size the
		// precompiled engine reads them at. Goes away with MSVC 14.44.35207.
		// Shipping and Test already agree with the engine (live coding is off there by
		// default), so they are left alone.
		if (Target.Platform == UnrealTargetPlatform.Win64
			&& Target.Type != TargetType.Editor
			&& Target.Configuration != UnrealTargetConfiguration.Shipping
			&& Target.Configuration != UnrealTargetConfiguration.Test)
		{
			PublicDefinitions.Add("WITH_LIVE_CODING=1");
		}
	}
}
