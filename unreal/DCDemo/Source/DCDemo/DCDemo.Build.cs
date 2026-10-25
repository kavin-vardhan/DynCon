// Copyright Epic Games, Inc. All Rights Reserved.

using System;
using System.Collections.Generic;
using System.IO;
using UnrealBuildTool;

public class DCDemo : ModuleRules
{
	/// <summary>
	/// Workaround for the monolithic game link on this PC (brief 004).
	///
	/// UE 5.7.4's precompiled engine libraries were built with MSVC 14.44, whose STL calls
	/// vectorised helpers (__std_mismatch_4, __std_minmax_element_d/f, __std_max_element_f,
	/// __std_search_1/2, __std_find_first_of_trivial_pos_1) that older CRT libraries do not
	/// contain. This PC only has 14.36, 14.38 and 14.42; UnrealBuildTool bans 14.40-14.43 and
	/// rejects anything below 14.38, so it compiles with 14.38 - and the game executable then
	/// fails to link with unresolved __std_* symbols. (The editor links fine: it links against
	/// the engine's DLL import libraries, not its static objects.)
	///
	/// Adding the newest installed msvcprt.lib ahead of 14.38's resolves the symbols it has.
	/// It is a stopgap: the real fix is installing MSVC 14.44.35207 from the Visual Studio
	/// installer, after which this whole block can go.
	/// </summary>
	private void AddNewerMsvcStlForMonolithicLink()
	{
		if (Target.Platform != UnrealTargetPlatform.Win64 || Target.Type == TargetType.Editor)
		{
			return;
		}

		string[] Roots =
		{
			@"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC",
			@"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC",
			@"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC",
			@"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC",
		};

		string Best = null;
		Version BestVersion = new Version(14, 39);
		foreach (string Root in Roots)
		{
			if (!Directory.Exists(Root))
			{
				continue;
			}
			foreach (string Dir in Directory.GetDirectories(Root))
			{
				Version Parsed;
				if (!Version.TryParse(Path.GetFileName(Dir), out Parsed) || Parsed <= BestVersion)
				{
					continue;
				}
				string Lib = Path.Combine(Dir, "lib", "x64", "msvcprt.lib");
				if (File.Exists(Lib))
				{
					Best = Lib;
					BestVersion = Parsed;
				}
			}
		}

		if (Best != null)
		{
			PublicAdditionalLibraries.Add(Best);
			System.Console.WriteLine("DCDemo: adding {0} so the monolithic link finds the newer STL helpers", Best);
		}
	}

	/// <summary>
	/// Second half of the toolchain workaround, and the subtle one.
	///
	/// The game is linked with -NoLiveCoding, which keeps Module.LiveCoding out of the link
	/// (it is the only module that needs __std_search_1/2, which no CRT on this PC has). But
	/// that switch also sets WITH_LIVE_CODING=0, and through WITH_RELOAD that *removes
	/// members* from the UObject registration structs (FClassReloadVersionInfo and friends in
	/// UObjectBase.h). The precompiled engine was built with live coding on, so its
	/// CoreUObject reads those structs at the larger size: the first packaged build crashed
	/// with an access violation in ProcessNewlyLoadedUObjects before it reached a frame.
	///
	/// Defining it back to 1 for our own modules makes our registration tables the shape the
	/// engine expects, while the module itself stays out of the link. Remove together with
	/// -NoLiveCoding once MSVC 14.44.35207 is installed.
	/// </summary>
	private void KeepLiveCodingAbiOfPrecompiledEngine()
	{
		// Only for the configurations where the engine itself was precompiled with live
		// coding on: UnrealBuildTool turns it off by default for Shipping and Test, so those
		// configurations already agree with the engine and must be left alone.
		bool bEngineHasLiveCoding = Target.Platform == UnrealTargetPlatform.Win64
			&& Target.Type != TargetType.Editor
			&& Target.Configuration != UnrealTargetConfiguration.Shipping
			&& Target.Configuration != UnrealTargetConfiguration.Test;

		if (bEngineHasLiveCoding)
		{
			PublicDefinitions.Add("WITH_LIVE_CODING=1");
		}
	}

	public DCDemo(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		AddNewerMsvcStlForMonolithicLink();
		KeepLiveCodingAbiOfPrecompiledEngine();

		// StateTreeModule and GameplayStateTreeModule are gone with the two template variants
		// that used them (see the comment on AddNewerMsvcStlForMonolithicLink: StateTreeModule
		// drags TraceAnalysis into every non-Shipping desktop build, and TraceAnalysis is the
		// one module whose missing STL helper no installed CRT on this PC provides).
		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"EnhancedInput",
			"AIModule",
			"UMG",
			"Slate"
		});

		PrivateDependencyModuleNames.AddRange(new string[] { });

		PublicIncludePaths.AddRange(new string[] {
			"DCDemo",
			"DCDemo/Variant_Platforming",
			"DCDemo/Variant_Platforming/Animation"
		});

		// Uncomment if you are using Slate UI
		// PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore" });

		// Uncomment if you are using online features
		// PrivateDependencyModuleNames.Add("OnlineSubsystem");

		// To include OnlineSubsystemSteam, add it to the plugins section in your uproject file with the Enabled attribute set to true
	}
}
