#include "DCSlotMapTool.h"

#include "DCContentActor.h"
#include "DCSlot.h"

#include "AssetCompilingManager.h"
#include "CollisionQueryParams.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SkyLightComponent.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "Engine/HitResult.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "HttpManager.h"
#include "HttpModule.h"
#include "ImageCore.h"
#include "ImageUtils.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Misc/App.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"
#include "RenderingThread.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "ShaderCompiler.h"

DEFINE_LOG_CATEGORY_STATIC(LogDCSlotMap, Log, All);

const FName UDCSlotMapTool::PlayableAreaTag(TEXT("DCPlayableArea"));

namespace
{
	constexpr double CM_PER_M = 100.0;

	/** Nothing in a level that is taller than this is scenery worth clearing - it is a sky
	 *  dome or a mistake, and it must not push the map camera into orbit. */
	constexpr double MaxSensibleHeightCm = 10000.0;    // 100 m

	/** A primitive wider than this is the map's big ground plane, not the playable area. */
	constexpr double OversizedPrimitiveCm = 40000.0;   // 400 m

	struct FRunLog
	{
		TArray<FString> Lines;

		void Add(const FString& Line)
		{
			Lines.Add(Line);
			UE_LOG(LogDCSlotMap, Display, TEXT("%s"), *Line);
		}

		void Warn(const FString& Line)
		{
			Lines.Add(TEXT("WARNING ") + Line);
			UE_LOG(LogDCSlotMap, Warning, TEXT("%s"), *Line);
		}
	};

	FDCSlotMapResult Fail(FRunLog& Log, const FString& Sentence)
	{
		Log.Warn(Sentence);
		FDCSlotMapResult Out;
		Out.bOk = false;
		Out.Message = Sentence;
		Out.Summary = TEXT("slot-map tool FAILED: ") + Sentence;
		Out.Log = Log.Lines;
		return Out;
	}

	UWorld* EditorWorld()
	{
		return GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	}

	/** "A" out of "/Game/Maps/GameA"; falls back to the first letter of a slot id. */
	FString GuessGameId(const UWorld* World, const TArray<ADCSlot*>& Slots)
	{
		FString Name = World ? World->GetMapName() : FString();
		Name.RemoveFromStart(TEXT("UEDPIE_0_"));
		if (Name.StartsWith(TEXT("Game"), ESearchCase::CaseSensitive) && Name.Len() > 4)
		{
			return Name.RightChop(4);
		}
		if (Slots.Num() > 0)
		{
			const FString Id = Slots[0]->SlotId.ToString();
			if (Id.Len() > 0)
			{
				return Id.Left(1);
			}
		}
		return FString();
	}

	/**
	 * The rectangle to capture, in centimetres.
	 *
	 * First choice is the actors the map builder tagged `DCPlayableArea` - the invisible
	 * walls round the part of the level the Player can reach. That is the honest answer to
	 * "the playable area", and it is one tag rather than a guess.
	 *
	 * A level that knows nothing about this plugin has no such tag, so the fallback is the
	 * union of every visible primitive that is not absurdly large - which throws away the
	 * map's 600 m ground plane and its water, and keeps the buildings and the paving.
	 */
	bool FindPlayableRect(UWorld* World, FBox2D& OutRect, double& OutTopZ, FString& OutHow)
	{
		FBox Tagged(ForceInit);
		FBox Visible(ForceInit);
		int32 TaggedCount = 0;

		for (TActorIterator<AActor> It(World); It; ++It)
		{
			AActor* Actor = *It;
			if (Actor == nullptr || !Actor->IsValidLowLevelFast())
			{
				continue;
			}
			FVector Origin, Extent;
			Actor->GetActorBounds(/*bOnlyCollidingComponents=*/false, Origin, Extent);
			if (Extent.IsNearlyZero())
			{
				continue;
			}
			const FBox Box(Origin - Extent, Origin + Extent);

			if (Actor->ActorHasTag(UDCSlotMapTool::PlayableAreaTag))
			{
				Tagged += Box;
				++TaggedCount;
			}
			if (Extent.X * 2.0 < OversizedPrimitiveCm && Extent.Y * 2.0 < OversizedPrimitiveCm)
			{
				Visible += Box;
			}
		}

		const FBox& Use = (TaggedCount > 0) ? Tagged : Visible;
		if (!Use.IsValid)
		{
			return false;
		}
		OutHow = (TaggedCount > 0)
			? FString::Printf(TEXT("%d actor(s) tagged %s"), TaggedCount,
				*UDCSlotMapTool::PlayableAreaTag.ToString())
			: TEXT("every visible primitive under 400 m across (no DCPlayableArea tag in this level)");

		OutRect = FBox2D(FVector2D(Use.Min.X, Use.Min.Y), FVector2D(Use.Max.X, Use.Max.Y));
		OutTopZ = FMath::Min(Use.Max.Z, MaxSensibleHeightCm);
		return true;
	}

	UTextureRenderTarget2D* MakeRenderTarget(int32 Width, int32 Height)
	{
		UTextureRenderTarget2D* RT = NewObject<UTextureRenderTarget2D>(
			GetTransientPackage(), NAME_None, RF_Transient);
		RT->RenderTargetFormat = ETextureRenderTargetFormat::RTF_RGBA8_SRGB;
		RT->ClearColor = FLinearColor::Black;
		RT->bAutoGenerateMips = false;
		RT->bGPUSharedFlag = false;
		RT->TargetGamma = 0.0f;                    // 0 = use the device default
		RT->InitAutoFormat(Width, Height);
		RT->UpdateResourceImmediate(true);
		return RT;
	}

	void SetFlag(TArray<FEngineShowFlagsSetting>& Flags, const TCHAR* Name, bool bEnabled)
	{
		FEngineShowFlagsSetting Setting;
		Setting.ShowFlagName = Name;
		Setting.Enabled = bEnabled;
		Flags.Add(Setting);
	}

	/**
	 * A capture component, outered to the world and transient: it is never part of the level,
	 * so the tool cannot dirty a package or leave anything behind.
	 *
	 * `bPlanView` is the difference between the two kinds of picture this tool takes.
	 *
	 * A **thumbnail** has to look like the game, so it keeps the fog, the sky and **Lumen**.
	 * Lumen is not optional: this project's ambient light *is* Lumen (`unreal\README.md`,
	 * "Detail Tracing"), and the first run of this tool turned it off for determinism and
	 * produced pictures whose every shadow was pure black - Game B's low afternoon sun made
	 * a near-black photograph of a perfectly well-lit promenade.
	 *
	 * The **plan view** cannot have Lumen whatever we would like: Lumen does not support an
	 * orthographic projection. So it goes the other way and turns the cast shadows off as
	 * well, which is what an architectural site plan looks like anyway - evenly lit, every
	 * roof and every path legible, nothing hidden under a black blob. The fog goes with
	 * them; the sky is never in a straight-down frame to begin with.
	 *
	 * Both turn TemporalAA and auto-exposure off: TemporalAA wants a frame history that one
	 * capture does not have, and a pinned exposure is what makes two runs of the tool agree.
	 */
	USceneCaptureComponent2D* MakeCapture(UWorld* World, UTextureRenderTarget2D* RT,
		const TArray<AActor*>& Hidden, bool bPlanView, bool bAtmosphere, float ExposureBias)
	{
		USceneCaptureComponent2D* Capture = NewObject<USceneCaptureComponent2D>(
			World, NAME_None, RF_Transient);

		Capture->TextureTarget = RT;
		Capture->CaptureSource = ESceneCaptureSource::SCS_FinalColorLDR;
		Capture->PrimitiveRenderMode = ESceneCapturePrimitiveRenderMode::PRM_RenderScenePrimitives;
		Capture->bCaptureEveryFrame = false;
		Capture->bCaptureOnMovement = false;
		// Not an optimisation to turn off: without a persisted rendering state the capture
		// has no view state, and without a view state Lumen - which is this project's
		// ambient light - does not run at all. That is what makes every shadow black.
		Capture->bAlwaysPersistRenderingState = true;
		Capture->bConsiderUnrenderedOpaquePixelAsFullyTranslucent = false;

		for (AActor* Actor : Hidden)
		{
			Capture->HiddenActors.Add(Actor);
		}

		TArray<FEngineShowFlagsSetting> Flags;
		SetFlag(Flags, TEXT("TemporalAA"), false);
		SetFlag(Flags, TEXT("MotionBlur"), false);
		SetFlag(Flags, TEXT("DepthOfField"), false);
		SetFlag(Flags, TEXT("Vignette"), false);
		SetFlag(Flags, TEXT("LocalExposure"), false);
		SetFlag(Flags, TEXT("Fog"), !bPlanView);
		SetFlag(Flags, TEXT("VolumetricFog"), false);
		SetFlag(Flags, TEXT("Atmosphere"), bAtmosphere);
		SetFlag(Flags, TEXT("Cloud"), !bPlanView);
		if (bPlanView)
		{
			SetFlag(Flags, TEXT("DynamicShadows"), false);
			SetFlag(Flags, TEXT("LumenGlobalIllumination"), false);
			SetFlag(Flags, TEXT("LumenReflections"), false);
			SetFlag(Flags, TEXT("ScreenSpaceReflections"), false);
			SetFlag(Flags, TEXT("Bloom"), false);
			// And **no specular at all** on a site plan. The water is a roughness-0.04
			// surface, which is a mirror; from straight above with every other reflection
			// method already off, the one that was left - the reflection environment, i.e.
			// the sky light's cubemap - was all it had to reflect, and a mirror pointed at
			// the sky is white. Game B's first registered capture had a white sea, and
			// because that white sea is half the frame the histogram exposure then pulled
			// everything else down until the roofs were black. Turning both off gives the
			// water its own colour back and the rest of the picture its exposure back.
			SetFlag(Flags, TEXT("ReflectionEnvironment"), false);
			SetFlag(Flags, TEXT("Specular"), false);
		}
		Capture->SetShowFlagSettings(Flags);

		// Exposure: let it adapt, but instantly.
		//
		// Pinning it instead sounds like the deterministic choice and is the wrong one -
		// Game A is a midday plaza and Game B a low afternoon over water, and one fixed
		// exposure blows out the first and blacks out the second. Adaptation is what makes
		// the two games' pictures comparable. It is made repeatable by winding the
		// adaptation speed right up, so it settles inside the warm-up captures rather than
		// drifting over however many frames the tool happens to take.
		Capture->PostProcessSettings.bOverride_AutoExposureMethod = true;
		Capture->PostProcessSettings.AutoExposureMethod = EAutoExposureMethod::AEM_Histogram;
		Capture->PostProcessSettings.bOverride_AutoExposureSpeedUp = true;
		Capture->PostProcessSettings.AutoExposureSpeedUp = 100.0f;
		Capture->PostProcessSettings.bOverride_AutoExposureSpeedDown = true;
		Capture->PostProcessSettings.AutoExposureSpeedDown = 100.0f;
		Capture->PostProcessSettings.bOverride_AutoExposureBias = true;
		Capture->PostProcessSettings.AutoExposureBias = ExposureBias;
		Capture->PostProcessSettings.bOverride_MotionBlurAmount = true;
		Capture->PostProcessSettings.MotionBlurAmount = 0.0f;

		Capture->RegisterComponentWithWorld(World);
		return Capture;
	}

	/**
	 * Take the shot and write it. Several times on purpose: the first captures warm the
	 * scene up (shadow maps, the sky light's irradiance, primitive visibility) and let
	 * Lumen's screen probes settle - it accumulates over frames and one frame of it is a
	 * speckled picture - and the last one is the one that is kept.
	 */
	constexpr int32 WarmUpCaptures = 4;

	bool CaptureToPng(USceneCaptureComponent2D* Capture, UTextureRenderTarget2D* RT,
		const FString& Path, FRunLog& Log)
	{
		USkyLightComponent::UpdateSkyCaptureContents(Capture->GetWorld());
		for (int32 Pass = 0; Pass < WarmUpCaptures; ++Pass)
		{
			Capture->CaptureScene();
			FlushRenderingCommands();
		}

		FImage Image;
		if (!FImageUtils::GetRenderTargetImage(RT, Image))
		{
			Log.Warn(FString::Printf(TEXT("could not read the render target back for %s"), *Path));
			return false;
		}

		// FinalColorLDR leaves alpha at whatever the scene wrote, which for an opaque shot is
		// usually zero - and a PNG with a zero alpha channel is an invisible picture. Flatten
		// it to BGRA8 and force every pixel opaque.
		Image.ChangeFormat(ERawImageFormat::BGRA8, EGammaSpace::sRGB);
		for (FColor& Pixel : Image.AsBGRA8())
		{
			Pixel.A = 255;
		}

		if (!FImageUtils::SaveImageByExtension(*Path, Image))
		{
			Log.Warn(FString::Printf(TEXT("could not write %s"), *Path));
			return false;
		}
		const int64 Bytes = IFileManager::Get().FileSize(*Path);
		Log.Add(FString::Printf(TEXT("wrote %s  (%d x %d, %lld B)"), *Path,
			Image.SizeX, Image.SizeY, Bytes));
		return true;
	}

	/**
	 * Ground height under a point - somewhere a visitor could actually be standing.
	 *
	 * "Could be standing" is the point of the height window: Game B's B1 faces out over the
	 * water, and the first version of this walked the thumbnail camera off the quay and
	 * photographed the promenade from below the waterline. Ground that is more than
	 * `MaxDropCm` away from the slot's own level is not ground a visitor walks on, so the
	 * caller steps in closer and asks again.
	 */
	bool GroundHeightAt(UWorld* World, const FVector2D& Where, double SlotZ, double MaxDropCm,
		double& OutZ)
	{
		const FVector Start(Where.X, Where.Y, SlotZ + 2000.0);
		const FVector End(Where.X, Where.Y, SlotZ - 6000.0);
		FHitResult Hit;
		FCollisionQueryParams Params(FName(TEXT("DCSlotMapGround")), /*bTraceComplex=*/true);
		if (!World->LineTraceSingleByChannel(Hit, Start, End, ECC_WorldStatic, Params))
		{
			return false;
		}
		if (FMath::Abs(Hit.ImpactPoint.Z - SlotZ) > MaxDropCm)
		{
			return false;
		}
		OutZ = Hit.ImpactPoint.Z;
		return true;
	}

	/**
	 * The capture's own ambient light, for as long as the tool is running.
	 *
	 * This project's ambient light is **Lumen** (`unreal\README.md`, "Detail Tracing"), and
	 * Lumen cannot run here. Its scene is built and maintained by the main renderer over
	 * successive frames, and a headless editor has no main renderer - there is no viewport,
	 * so there is no frame for it to live in. A scene capture on its own therefore gets
	 * direct light and nothing else, and every surface the sun does not reach comes out
	 * **pure black**. That is not a subtle loss: Game B's low afternoon sun left a
	 * near-black photograph of a perfectly well-lit promenade, and the sky light does not
	 * fix it either (its real-time capture belongs to the same missing frame).
	 *
	 * So the tool lights its own subject, the way a product-shot rig does: three shadowless
	 * directional lights sized against the map's own sun - one straight down, one from
	 * behind the sun to fill the shadow side, one across - in a cool sky tint. They exist
	 * only while the captures are being taken and are destroyed afterwards; nothing is
	 * saved, and the game's own lighting is untouched.
	 */
	struct FScopedCaptureFill
	{
		TArray<UDirectionalLightComponent*> Lights;

		FScopedCaptureFill(UWorld* World, float Fraction, FRunLog& Log)
		{
			if (Fraction <= 0.0f)
			{
				return;
			}

			// Size the fill against whatever the map calls its sun, so a bright midday
			// plaza and a dim waterfront evening each get a fill in proportion.
			float SunIntensity = 0.0f;
			float SunYaw = 0.0f;
			for (TActorIterator<AActor> It(World); It; ++It)
			{
				UDirectionalLightComponent* Sun =
					It->FindComponentByClass<UDirectionalLightComponent>();
				if (Sun != nullptr && Sun->Intensity > SunIntensity)
				{
					SunIntensity = Sun->Intensity;
					SunYaw = Sun->GetComponentRotation().Yaw;
				}
			}
			const float Base = (SunIntensity > 0.0f ? SunIntensity : 4.0f) * Fraction;
			const FLinearColor SkyTint(0.80f, 0.87f, 1.0f);

			const TPair<FRotator, float> Rig[] = {
				{ FRotator(-89.0f, 0.0f, 0.0f),            0.50f },   // the sky overhead
				{ FRotator(-20.0f, SunYaw + 180.0f, 0.0f), 0.30f },   // into the shadow side
				{ FRotator(-20.0f, SunYaw + 90.0f, 0.0f),  0.20f },   // and across it
			};
			for (const TPair<FRotator, float>& Entry : Rig)
			{
				UDirectionalLightComponent* Light = NewObject<UDirectionalLightComponent>(
					World, NAME_None, RF_Transient);
				Light->SetMobility(EComponentMobility::Movable);
				Light->SetIntensity(Base * Entry.Value);
				Light->SetLightColor(SkyTint);
				Light->SetCastShadows(false);
				Light->bAtmosphereSunLight = false;      // it must not move the sky about
				Light->bEnableLightShaftOcclusion = false;
				Light->SetWorldRotation(Entry.Key);
				Light->RegisterComponentWithWorld(World);
				Lights.Add(Light);
			}
			Log.Add(FString::Printf(
				TEXT("capture fill: 3 shadowless lights totalling %.2f lux against a %.2f lux "
					"sun (Lumen cannot run in a headless editor)"), Base, SunIntensity));
		}

		~FScopedCaptureFill()
		{
			for (UDirectionalLightComponent* Light : Lights)
			{
				Light->UnregisterComponent();
				Light->DestroyComponent();
			}
		}
	};

	/**
	 * Make the sky light's irradiance real, even in a commandlet.
	 *
	 * A movable sky light with **Real Time Capture** never fills its irradiance in here: the
	 * real-time capture is part of the main renderer's frame, and a scene capture is not
	 * that frame. Left alone, every shadow in the picture comes out **pure black** - which
	 * is exactly what this tool's first run produced, and Game B's low afternoon sun made
	 * a near-black thumbnail of a perfectly well-lit promenade.
	 *
	 * Turning real-time capture off and asking for one explicit recapture takes the ordinary
	 * path, which `UpdateSkyCaptureContents` does render. The flag goes back afterwards, so
	 * the level is exactly as it was.
	 */
	struct FScopedSkyLightCapture
	{
		TArray<USkyLightComponent*> Restored;

		FScopedSkyLightCapture(UWorld* World, FRunLog& Log)
		{
			for (TActorIterator<AActor> It(World); It; ++It)
			{
				USkyLightComponent* Sky = It->FindComponentByClass<USkyLightComponent>();
				if (Sky == nullptr)
				{
					continue;
				}
				if (Sky->IsRealTimeCaptureEnabled())
				{
					Sky->SetRealTimeCaptureEnabled(false);
					Restored.Add(Sky);
				}
				Sky->RecaptureSky();
			}
			if (Restored.Num() > 0)
			{
				Log.Add(FString::Printf(
					TEXT("sky light: %d real-time capture(s) turned into one explicit "
						"recapture for the duration of the tool"), Restored.Num()));
			}
			USkyLightComponent::UpdateSkyCaptureContents(World);
			FlushRenderingCommands();
		}

		~FScopedSkyLightCapture()
		{
			for (USkyLightComponent* Sky : Restored)
			{
				Sky->SetRealTimeCaptureEnabled(true);
			}
		}
	};

	FString JsonToString(const TSharedRef<FJsonObject>& Object)
	{
		FString Out;
		TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
			TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Object, Writer);
		return Out;
	}

	TSharedRef<FJsonObject> Vec3Json(const FVector& V, double Scale)
	{
		TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
		O->SetNumberField(TEXT("x"), V.X / Scale);
		O->SetNumberField(TEXT("y"), V.Y / Scale);
		O->SetNumberField(TEXT("z"), V.Z / Scale);
		return O;
	}

	void AppendUtf8(TArray<uint8>& Body, const FString& Text)
	{
		const FTCHARToUTF8 Converted(*Text);
		Body.Append(reinterpret_cast<const uint8*>(Converted.Get()), Converted.Length());
	}

	/** One multipart/form-data body: the JSON, the map image, one thumbnail per slot. */
	void BuildMultipart(const FString& Boundary, const FString& Json,
		const FString& MapFileName, const TArray<uint8>& MapBytes,
		const TArray<TPair<FString, TArray<uint8>>>& Thumbs, TArray<uint8>& Body)
	{
		AppendUtf8(Body, FString::Printf(
			TEXT("--%s\r\nContent-Disposition: form-data; name=\"data\"\r\n")
			TEXT("Content-Type: application/json; charset=utf-8\r\n\r\n"), *Boundary));
		AppendUtf8(Body, Json);
		AppendUtf8(Body, TEXT("\r\n"));

		AppendUtf8(Body, FString::Printf(
			TEXT("--%s\r\nContent-Disposition: form-data; name=\"map_image\"; filename=\"%s\"\r\n")
			TEXT("Content-Type: image/png\r\n\r\n"), *Boundary, *MapFileName));
		Body.Append(MapBytes);
		AppendUtf8(Body, TEXT("\r\n"));

		for (const TPair<FString, TArray<uint8>>& Thumb : Thumbs)
		{
			AppendUtf8(Body, FString::Printf(
				TEXT("--%s\r\nContent-Disposition: form-data; name=\"thumbs\"; filename=\"%s\"\r\n")
				TEXT("Content-Type: image/png\r\n\r\n"), *Boundary, *Thumb.Key));
			Body.Append(Thumb.Value);
			AppendUtf8(Body, TEXT("\r\n"));
		}

		AppendUtf8(Body, FString::Printf(TEXT("--%s--\r\n"), *Boundary));
	}

	/**
	 * POST it, and wait. The HTTP module is asynchronous and a commandlet has no engine loop
	 * ticking it, so the manager is ticked by hand until the request lands - which is also
	 * harmless in the editor, where it is being ticked anyway.
	 */
	bool PostMultipart(const FString& Url, const FString& Json, const FString& MapFileName,
		const TArray<uint8>& MapBytes,
		const TArray<TPair<FString, TArray<uint8>>>& Thumbs,
		float TimeoutSeconds, int32& OutStatus, FString& OutResponse, FRunLog& Log)
	{
		const FString Boundary = TEXT("----DCSlotMap") + FGuid::NewGuid().ToString(EGuidFormats::Digits);
		TArray<uint8> Body;
		BuildMultipart(Boundary, Json, MapFileName, MapBytes, Thumbs, Body);

		FHttpRequestRef Request = FHttpModule::Get().CreateRequest();
		Request->SetURL(Url);
		Request->SetVerb(TEXT("POST"));
		Request->SetHeader(TEXT("Content-Type"),
			FString::Printf(TEXT("multipart/form-data; boundary=%s"), *Boundary));
		Request->SetHeader(TEXT("Accept"), TEXT("application/json"));
		Request->SetTimeout(TimeoutSeconds);
		Request->SetContent(Body);

		bool bDone = false;
		bool bConnected = false;
		int32 Status = 0;
		FString Response;
		Request->OnProcessRequestComplete().BindLambda(
			[&bDone, &bConnected, &Status, &Response]
			(FHttpRequestPtr, FHttpResponsePtr Reply, bool bSucceeded)
			{
				bConnected = bSucceeded && Reply.IsValid();
				if (bConnected)
				{
					Status = Reply->GetResponseCode();
					Response = Reply->GetContentAsString();
				}
				bDone = true;
			});

		Log.Add(FString::Printf(TEXT("POST %s  (%d B of multipart, %d thumbnail(s))"),
			*Url, Body.Num(), Thumbs.Num()));
		if (!Request->ProcessRequest())
		{
			Log.Warn(TEXT("the HTTP request would not start"));
			return false;
		}

		const double Deadline = FPlatformTime::Seconds() + TimeoutSeconds + 5.0;
		while (!bDone && FPlatformTime::Seconds() < Deadline)
		{
			FHttpModule::Get().GetHttpManager().Tick(0.05f);
			FPlatformProcess::Sleep(0.02f);
		}
		if (!bDone)
		{
			Request->CancelRequest();
			Log.Warn(FString::Printf(TEXT("%s never answered in %.0f s"), *Url, TimeoutSeconds));
			return false;
		}
		if (!bConnected)
		{
			Log.Warn(FString::Printf(TEXT("could not reach %s at all - is the server up?"), *Url));
			return false;
		}

		OutStatus = Status;
		OutResponse = Response;
		Log.Add(FString::Printf(TEXT("  -> %d  %s"), Status,
			*Response.Left(400).Replace(TEXT("\n"), TEXT(" "))));
		return Status >= 200 && Status < 300;
	}
}


FDCSlotMapResult UDCSlotMapTool::RegisterCurrentLevel(const FDCSlotMapOptions& Options)
{
	FRunLog Log;
	const double Started = FPlatformTime::Seconds();

	UWorld* World = EditorWorld();
	if (World == nullptr)
	{
		return Fail(Log, TEXT("there is no editor world - open a level first"));
	}
	if (!FApp::CanEverRender())
	{
		return Fail(Log, TEXT("this process cannot render, so there is nothing to capture. "
			"A commandlet needs -AllowCommandletRendering on the command line."));
	}

	// ---------------------------------------------------------------- the slots

	TArray<ADCSlot*> Slots;
	TArray<AActor*> Hidden;
	for (TActorIterator<ADCSlot> It(World); It; ++It)
	{
		Slots.Add(*It);
	}
	if (Slots.Num() == 0)
	{
		return Fail(Log, FString::Printf(
			TEXT("%s has no ADCSlot actors in it - there is nothing to register"),
			*World->GetMapName()));
	}
	Slots.Sort([](const ADCSlot& A, const ADCSlot& B)
	{
		if (A.FillOrder != B.FillOrder)
		{
			return A.FillOrder < B.FillOrder;
		}
		return A.SlotId.ToString() < B.SlotId.ToString();
	});

	// Whatever happens to be standing in a slot right now is hidden in every capture: the
	// portal has to show the brand the empty spot it is bidding on, not somebody else's
	// building. In the shipped maps there is nothing to hide (the content arrives from the
	// backend at runtime), but a developer's own level may well have a placeholder in it.
	for (TActorIterator<ADCContentActor> It(World); It; ++It)
	{
		Hidden.Add(*It);
	}
	for (ADCSlot* Slot : Slots)
	{
		TArray<AActor*> Attached;
		Slot->GetAttachedActors(Attached, /*bResetArray=*/true, /*bRecursivelyIncludeAttachedActors=*/true);
		for (AActor* Child : Attached)
		{
			Hidden.AddUnique(Child);
		}
	}

	const FString Game = Options.Game.IsEmpty() ? GuessGameId(World, Slots) : Options.Game;
	if (Game.IsEmpty())
	{
		return Fail(Log, TEXT("could not work out which game this level belongs to - pass Game"));
	}

	const FString MapPackage = World->PersistentLevel && World->PersistentLevel->GetOutermost()
		? World->PersistentLevel->GetOutermost()->GetName()
		: World->GetMapName();

	Log.Add(FString::Printf(TEXT("slot-map tool: game %s, level %s, %d slot(s): %s"),
		*Game, *MapPackage, Slots.Num(),
		*FString::JoinBy(Slots, TEXT(" "), [](const ADCSlot* S) { return S->SlotId.ToString(); })));
	if (Hidden.Num() > 0)
	{
		Log.Add(FString::Printf(TEXT("hiding %d actor(s) of content for every capture"), Hidden.Num()));
	}

	// ---------------------------------------------------------------- where to write

	FString OutDir = Options.OutDir;
	if (OutDir.IsEmpty())
	{
		OutDir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("DCSlotMap"), Game);
	}
	OutDir = FPaths::ConvertRelativePathToFull(OutDir);
	if (!IFileManager::Get().DirectoryExists(*OutDir)
		&& !IFileManager::Get().MakeDirectory(*OutDir, /*Tree=*/true))
	{
		return Fail(Log, FString::Printf(TEXT("could not make %s"), *OutDir));
	}

	// ---------------------------------------------------------------- let the editor finish

	// A capture of a level whose meshes are still building, or whose shaders are still
	// compiling, is a picture of grey default materials. Both of these block until the
	// editor has genuinely finished, which is the difference between a tool and a race.
	FAssetCompilingManager::Get().FinishAllCompilation();
	if (GShaderCompilingManager != nullptr)
	{
		GShaderCompilingManager->FinishAllCompilation();
	}
	World->UpdateWorldComponents(/*bRerunConstructionScripts=*/true, /*bCurrentLevelOnly=*/false);
	World->SendAllEndOfFrameUpdates();

	// Without these two every shadow in every picture is pure black - see the comments on
	// them. Both undo themselves when the tool returns.
	FScopedSkyLightCapture SkyLight(World, Log);
	FScopedCaptureFill Fill(World, Options.FillFraction, Log);

	// ---------------------------------------------------------------- the map capture

	FBox2D Rect(ForceInit);
	double TopZ = 0.0;
	FString RectHow;
	if (!FindPlayableRect(World, Rect, TopZ, RectHow))
	{
		return Fail(Log, TEXT("could not measure the playable area - the level looks empty"));
	}

	const FVector2D Centre = Rect.GetCenter();
	FVector2D Size = Rect.GetSize() * (1.0 + FMath::Max(0.0f, Options.MarginFraction));
	Size.X = FMath::Max(Size.X, 100.0);
	Size.Y = FMath::Max(Size.Y, 100.0);

	// The longer world axis becomes the image's horizontal, so the capture is landscape
	// whichever way round the level was built. Yaw -90 puts world +X to the right and world
	// +Y down the image; yaw 0 puts world +Y right and world +X up. Either way the pixel
	// positions below come out of the camera's own transform, not out of this choice.
	const bool bXIsLong = Size.X >= Size.Y;
	const double LongCm = bXIsLong ? Size.X : Size.Y;
	const double ShortCm = bXIsLong ? Size.Y : Size.X;
	const float CaptureYaw = bXIsLong ? -90.0f : 0.0f;

	const int32 MapWidth = FMath::Clamp(Options.MapLongSidePixels, 256, 8192);
	int32 MapHeight = FMath::RoundToInt(MapWidth * (ShortCm / LongCm));
	MapHeight = FMath::Clamp(MapHeight - (MapHeight % 2), 128, 8192);

	const double CameraZ = TopZ + FMath::Max(10.0f, Options.MapCameraClearanceM) * CM_PER_M;
	const FVector CameraLoc(Centre.X, Centre.Y, CameraZ);
	const FRotator CameraRot(-90.0f, CaptureYaw, 0.0f);
	const FTransform CameraXform(CameraRot, CameraLoc);

	const double HalfWidthCm = LongCm * 0.5;
	const double HalfHeightCm = HalfWidthCm * (double(MapHeight) / double(MapWidth));

	Log.Add(FString::Printf(
		TEXT("playable area from %s: %.1f x %.1f m centred (%.1f, %.1f) m, top %.1f m"),
		*RectHow, Rect.GetSize().X / CM_PER_M, Rect.GetSize().Y / CM_PER_M,
		Centre.X / CM_PER_M, Centre.Y / CM_PER_M, TopZ / CM_PER_M));
	Log.Add(FString::Printf(
		TEXT("map capture: orthographic %d x %d px, %.1f x %.1f m of world, camera %.0f m up, yaw %.0f"),
		MapWidth, MapHeight, LongCm / CM_PER_M, HalfHeightCm * 2.0 / CM_PER_M,
		CameraZ / CM_PER_M, CaptureYaw));

	const FString MapFileName = Game + TEXT(".png");
	const FString MapImagePath = FPaths::Combine(OutDir, MapFileName);
	{
		UTextureRenderTarget2D* RT = MakeRenderTarget(MapWidth, MapHeight);
		USceneCaptureComponent2D* Capture = MakeCapture(World, RT, Hidden, /*bPlanView=*/true,
			Options.bMapAtmosphere, Options.MapExposureBias);
		Capture->ProjectionType = ECameraProjectionMode::Orthographic;
		Capture->OrthoWidth = LongCm;
		// Explicitly off: the automatic planes are worked out from the distance to the
		// component's *owner*, and this component has no owner, so they would be computed
		// around a distance of zero and clip the level away.
		Capture->bAutoCalculateOrthoPlanes = false;
		Capture->bUpdateOrthoPlanes = false;
		Capture->SetWorldLocationAndRotation(CameraLoc, CameraRot);

		const bool bWrote = CaptureToPng(Capture, RT, MapImagePath, Log);
		Capture->UnregisterComponent();
		Capture->DestroyComponent();
		if (!bWrote)
		{
			return Fail(Log, FString::Printf(TEXT("the map capture failed for game %s"), *Game));
		}
	}

	// ---------------------------------------------------------------- the slots and the thumbnails

	const int32 ThumbWidth = FMath::Clamp(Options.ThumbWidthPixels, 128, 4096);
	int32 ThumbHeight = FMath::RoundToInt(ThumbWidth * 9.0 / 16.0);
	ThumbHeight -= ThumbHeight % 2;
	const float ThumbFov = FMath::Clamp(Options.ThumbFovDegrees, 20.0f, 140.0f);
	const double TanHalfH = FMath::Tan(FMath::DegreesToRadians(ThumbFov) * 0.5);

	TArray<TSharedPtr<FJsonValue>> SlotsJson;
	TArray<TPair<FString, TArray<uint8>>> ThumbFiles;
	FDCSlotMapResult Result;

	for (ADCSlot* Slot : Slots)
	{
		const FString Id = Slot->SlotId.ToString();
		const FVector Where = Slot->GetActorLocation();
		const FVector Limits = Slot->GetClassLimits();

		// Pixel position: straight out of the capture camera's own transform, so it cannot
		// drift away from the picture it is a position on.
		const FVector Local = CameraXform.InverseTransformPosition(Where);
		const double U = 0.5 + Local.Y / (2.0 * HalfWidthCm);
		const double V = 0.5 - Local.Z / (2.0 * HalfHeightCm);
		if (U < 0.0 || U > 1.0 || V < 0.0 || V > 1.0)
		{
			Log.Warn(FString::Printf(
				TEXT("slot %s lands at (%.3f, %.3f) - outside the capture; the playable area "
					"does not contain it"), *Id, U, V));
		}

		// How far back to stand, worked out from the lens rather than from a round number
		// times the footprint, so a 7 m slot and a 14 m one both come out framed: far
		// enough that the class footprint fits across the frame with a little air round it.
		//
		// The camera then looks at a quarter of the way up the slot's volume, not at the
		// middle of it. At eye level a flat pad is nearly edge-on, so aiming at the middle
		// of a 9 m box tips the horizon down to the bottom of the frame and hands the
		// portal a photograph of the sky. A low aim puts the ground - which is what is for
		// sale - across two thirds of the picture, with room above it for what will stand
		// there. A T slot's 20 m therefore does not all fit, and does not need to: the
		// slot card says "20 m tall" in words.
		const double ShowHeight = FMath::Min<double>(Limits.Z, 1000.0);
		const double NeedAcross = FMath::Max(Limits.X, Limits.Y) * 0.5 * 1.15 / TanHalfH;
		double Distance = FMath::Max(800.0, NeedAcross);

		// The camera stands where a visitor would: out along the slot's +X, which is the
		// direction the content's door faces. If there is no ground a visitor could be
		// standing on there - Game B's B1 faces out over the water - it steps in until
		// there is.
		const FVector Forward = Slot->GetActorForwardVector();
		double GroundZ = Where.Z;
		bool bFoundGround = false;
		for (int32 Attempt = 0; Attempt < 8; ++Attempt)
		{
			const FVector Candidate = Where + Forward * Distance;
			if (GroundHeightAt(World, FVector2D(Candidate.X, Candidate.Y), Where.Z,
				/*MaxDropCm=*/1000.0, GroundZ))
			{
				bFoundGround = true;
				break;
			}
			Distance *= 0.85;
		}
		if (!bFoundGround)
		{
			GroundZ = Where.Z;
			Log.Warn(FString::Printf(
				TEXT("no ground under the thumbnail camera for %s - standing it at the slot's "
					"own height"), *Id));
		}

		const FVector Stand = Where + Forward * Distance;
		const FVector EyeLoc(Stand.X, Stand.Y, GroundZ + Options.EyeHeightM * CM_PER_M);
		const FVector Aim(Where.X, Where.Y, Where.Z + ShowHeight * 0.25);
		const FRotator EyeRot = (Aim - EyeLoc).Rotation();

		const FString ThumbFileName = FString::Printf(TEXT("%s_%s.png"), *Game, *Id);
		const FString ThumbPath = FPaths::Combine(OutDir, ThumbFileName);
		{
			UTextureRenderTarget2D* RT = MakeRenderTarget(ThumbWidth, ThumbHeight);
			USceneCaptureComponent2D* Capture = MakeCapture(World, RT, Hidden,
				/*bPlanView=*/false, /*bAtmosphere=*/true, Options.ExposureBias);
			Capture->ProjectionType = ECameraProjectionMode::Perspective;
			Capture->FOVAngle = ThumbFov;
			Capture->SetWorldLocationAndRotation(EyeLoc, EyeRot);

			const bool bWrote = CaptureToPng(Capture, RT, ThumbPath, Log);
			Capture->UnregisterComponent();
			Capture->DestroyComponent();
			if (!bWrote)
			{
				return Fail(Log, FString::Printf(TEXT("the thumbnail capture failed for %s"), *Id));
			}
		}

		TArray<uint8> ThumbBytes;
		if (!FFileHelper::LoadFileToArray(ThumbBytes, *ThumbPath))
		{
			return Fail(Log, FString::Printf(TEXT("could not read %s back"), *ThumbPath));
		}
		ThumbFiles.Emplace(ThumbFileName, MoveTemp(ThumbBytes));

		Log.Add(FString::Printf(
			TEXT("slot %-3s %s  px (%.4f, %.4f)  world (%.1f, %.1f, %.1f) m  rating %s  "
				"pre-fetch %.0f m  eye %.1f m at %.1f m out"),
			*Id, *Slot->GetSizeClassName(), U, V,
			Where.X / CM_PER_M, Where.Y / CM_PER_M, Where.Z / CM_PER_M,
			*Slot->RatingRule.ToString(), Slot->PrefetchRadius / CM_PER_M,
			Options.EyeHeightM, Distance / CM_PER_M));

		// ---- the JSON for this slot
		TSharedRef<FJsonObject> J = MakeShared<FJsonObject>();
		J->SetStringField(TEXT("id"), Id);
		J->SetStringField(TEXT("size_class"), Slot->GetSizeClassName());

		TSharedRef<FJsonObject> LimitsJson = MakeShared<FJsonObject>();
		LimitsJson->SetNumberField(TEXT("x"), Limits.X / CM_PER_M);
		LimitsJson->SetNumberField(TEXT("y"), Limits.Y / CM_PER_M);
		LimitsJson->SetNumberField(TEXT("z"), Limits.Z / CM_PER_M);
		J->SetObjectField(TEXT("limits_m"), LimitsJson);

		J->SetStringField(TEXT("rating_rule"), Slot->RatingRule.ToString());
		J->SetNumberField(TEXT("prefetch_radius_m"), Slot->PrefetchRadius / CM_PER_M);
		J->SetObjectField(TEXT("world_m"), Vec3Json(Where, CM_PER_M));
		J->SetNumberField(TEXT("facing_deg"), Slot->GetActorRotation().Yaw);
		J->SetNumberField(TEXT("fill_order"), Slot->FillOrder);

		TSharedRef<FJsonObject> PxJson = MakeShared<FJsonObject>();
		PxJson->SetNumberField(TEXT("x"), FMath::RoundToDouble(U * 10000.0) / 10000.0);
		PxJson->SetNumberField(TEXT("y"), FMath::RoundToDouble(V * 10000.0) / 10000.0);
		J->SetObjectField(TEXT("px"), PxJson);

		TSharedRef<FJsonObject> ThumbJson = MakeShared<FJsonObject>();
		ThumbJson->SetStringField(TEXT("file"), ThumbFileName);
		ThumbJson->SetNumberField(TEXT("width"), ThumbWidth);
		ThumbJson->SetNumberField(TEXT("height"), ThumbHeight);
		ThumbJson->SetNumberField(TEXT("fov_deg"), ThumbFov);
		ThumbJson->SetNumberField(TEXT("eye_height_m"), Options.EyeHeightM);
		ThumbJson->SetNumberField(TEXT("stand_off_m"), Distance / CM_PER_M);
		ThumbJson->SetObjectField(TEXT("camera_m"), Vec3Json(EyeLoc, CM_PER_M));
		ThumbJson->SetObjectField(TEXT("aim_m"), Vec3Json(Aim, CM_PER_M));
		ThumbJson->SetBoolField(TEXT("content_hidden"), true);
		J->SetObjectField(TEXT("thumb"), ThumbJson);

		SlotsJson.Add(MakeShared<FJsonValueObject>(J));

		FDCSlotMapSlot Row;
		Row.Id = Id;
		Row.SizeClass = Slot->GetSizeClassName();
		Row.Px = FVector2D(U, V);
		Row.ThumbFile = ThumbFileName;
		Result.Slots.Add(Row);
	}

	// ---------------------------------------------------------------- the registration JSON

	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetNumberField(TEXT("schema_version"), 1);
	Root->SetStringField(TEXT("game"), Game);
	Root->SetStringField(TEXT("map"), MapPackage);
	Root->SetStringField(TEXT("captured_utc"), FDateTime::UtcNow().ToIso8601());
	Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
	Root->SetStringField(TEXT("tool"), TEXT("DynamicContentsEditor.DCSlotMapTool"));

	TSharedRef<FJsonObject> ImageJson = MakeShared<FJsonObject>();
	ImageJson->SetStringField(TEXT("file"), MapFileName);
	ImageJson->SetNumberField(TEXT("width"), MapWidth);
	ImageJson->SetNumberField(TEXT("height"), MapHeight);
	Root->SetObjectField(TEXT("image"), ImageJson);

	TSharedRef<FJsonObject> WorldJson = MakeShared<FJsonObject>();
	WorldJson->SetStringField(TEXT("playable_area_from"), RectHow);
	WorldJson->SetStringField(TEXT("projection"), TEXT("orthographic"));
	WorldJson->SetNumberField(TEXT("width_m"), HalfWidthCm * 2.0 / CM_PER_M);
	WorldJson->SetNumberField(TEXT("height_m"), HalfHeightCm * 2.0 / CM_PER_M);
	WorldJson->SetObjectField(TEXT("camera_m"), Vec3Json(CameraLoc, CM_PER_M));
	WorldJson->SetNumberField(TEXT("camera_yaw_deg"), CaptureYaw);
	TSharedRef<FJsonObject> RectJson = MakeShared<FJsonObject>();
	RectJson->SetNumberField(TEXT("min_x"), Rect.Min.X / CM_PER_M);
	RectJson->SetNumberField(TEXT("min_y"), Rect.Min.Y / CM_PER_M);
	RectJson->SetNumberField(TEXT("max_x"), Rect.Max.X / CM_PER_M);
	RectJson->SetNumberField(TEXT("max_y"), Rect.Max.Y / CM_PER_M);
	WorldJson->SetObjectField(TEXT("measured_rect_m"), RectJson);
	Root->SetObjectField(TEXT("world"), WorldJson);

	Root->SetArrayField(TEXT("slots"), SlotsJson);

	const FString Json = JsonToString(Root);
	const FString JsonPath = FPaths::Combine(OutDir, Game + TEXT(".slots.json"));
	if (!FFileHelper::SaveStringToFile(Json, *JsonPath,
		FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
	{
		return Fail(Log, FString::Printf(TEXT("could not write %s"), *JsonPath));
	}
	Log.Add(FString::Printf(TEXT("wrote %s"), *JsonPath));

	// ---------------------------------------------------------------- send it

	Result.bOk = true;
	Result.Game = Game;
	Result.MapPackage = MapPackage;
	Result.MapImagePath = MapImagePath;
	Result.JsonPath = JsonPath;
	Result.MapImageSize = FIntPoint(MapWidth, MapHeight);

	if (Options.bPostToBackend && !Options.Backend.IsEmpty())
	{
		TArray<uint8> MapBytes;
		if (!FFileHelper::LoadFileToArray(MapBytes, *MapImagePath))
		{
			return Fail(Log, FString::Printf(TEXT("could not read %s back"), *MapImagePath));
		}
		FString Url = Options.Backend;
		Url.RemoveFromEnd(TEXT("/"));
		Url += TEXT("/games/register");

		int32 Status = 0;
		FString Response;
		const bool bPosted = PostMultipart(Url, Json, MapFileName, MapBytes, ThumbFiles,
			Options.HttpTimeoutSeconds, Status, Response, Log);
		Result.PostStatus = Status;
		Result.PostResponse = Response;
		if (!bPosted)
		{
			Result.bOk = false;
			Result.Message = FString::Printf(
				TEXT("the captures are on disk in %s, but the backend did not accept them "
					"(status %d)"), *OutDir, Status);
		}
	}
	else
	{
		Log.Add(TEXT("not posting: the files are on disk for someone else to send"));
	}

	const double Seconds = FPlatformTime::Seconds() - Started;
	Result.Summary = FString::Printf(
		TEXT("game %s: %d slot(s), map %d x %d px, %d thumbnail(s), %s, %.1f s"),
		*Game, Result.Slots.Num(), MapWidth, MapHeight, ThumbFiles.Num(),
		Result.PostStatus == 0 ? TEXT("not posted")
			: *FString::Printf(TEXT("POST -> %d"), Result.PostStatus),
		Seconds);
	if (Result.Message.IsEmpty())
	{
		Result.Message = Result.Summary;
	}
	Log.Add(Result.Summary);
	Result.Log = Log.Lines;
	return Result;
}
