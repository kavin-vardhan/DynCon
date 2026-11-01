#include "DCStatusHud.h"

#include "DCInteractor.h"
#include "DCSlot.h"
#include "DCSubsystem.h"
#include "DynamicContents.h"

#include "CanvasItem.h"
#include "CanvasTypes.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

namespace
{
	constexpr float DCMargin = 18.0f;
	constexpr float DCPadding = 12.0f;

	/** How far in from the edge a clamped marker sits. */
	constexpr float DCEdgeMargin = 64.0f;

	/** Half-width of the marker's diamond, before the UI scale. */
	constexpr float DCDiamond = 13.0f;
}

ADCStatusHud::ADCStatusHud()
{
	PrimaryActorTick.bCanEverTick = false;
}

void ADCStatusHud::BeginPlay()
{
	Super::BeginPlay();

	const TCHAR* Cmd = FCommandLine::Get();
	float Scale = 0.0f;
	if (FParse::Value(Cmd, TEXT("DCUiScale="), Scale) && Scale > 0.1f)
	{
		UiScale = Scale;
	}
	// -DCNoStrip used to turn the whole HUD off. It now turns off only the instrumentation:
	// the prompt and the marker belong to the game the Player is playing, and a capture made
	// without the strip should still show them.
	bStrip = !FParse::Param(Cmd, TEXT("DCNoStrip"));
	bMarker = !FParse::Param(Cmd, TEXT("DCNoMarker"));
	bPreview = FParse::Param(Cmd, TEXT("DCPreview"));
	if (bPreview)
	{
		// The preview window is not a game anybody is playing: no instrumentation, no
		// prompt, no marker - one small caption (brief 017 / plan v6 §7).
		bStrip = false;
		bMarker = false;
	}
	DC_LOG(Log, TEXT("HUD status strip %s, waypoint marker %s, preview caption %s, scale %.2f"),
		bStrip ? TEXT("on") : TEXT("off"), bMarker ? TEXT("on") : TEXT("off"),
		bPreview ? TEXT("on") : TEXT("off"), UiScale);
}

void ADCStatusHud::DrawPanel(float X, float Y, float W, float H, const FLinearColor& Fill)
{
	// The three-argument tile uses the engine's default white texture, so the panel needs no
	// asset of its own.
	FCanvasTileItem Panel(FVector2D(X, Y), FVector2D(W, H), Fill);
	Panel.BlendMode = SE_BLEND_Translucent;
	Canvas->DrawItem(Panel);
}

bool ADCStatusHud::ProjectToScreen(const FVector& World, FVector2D& Out, bool& bOffScreen) const
{
	if (Canvas == nullptr)
	{
		return false;
	}
	const FVector Projected = Canvas->Project(World, /*bClampToZeroPlane=*/false);
	const float W = static_cast<float>(Canvas->SizeX);
	const float H = static_cast<float>(Canvas->SizeY);
	const float Edge = DCEdgeMargin * UiScale;

	FVector2D Screen(Projected.X, Projected.Y);
	bOffScreen = false;

	if (Projected.Z <= 0.0f)
	{
		// Behind the camera: Project's answer is meaningless, so mirror it through the middle
		// of the screen and push it to the bottom. The marker then points back the way the
		// Player came, which is where the thing is.
		Screen.X = W - Screen.X;
		Screen.Y = H - Edge;
		bOffScreen = true;
	}
	if (Screen.X < Edge || Screen.X > W - Edge || Screen.Y < Edge || Screen.Y > H - Edge)
	{
		bOffScreen = true;
	}
	Out.X = FMath::Clamp(Screen.X, Edge, W - Edge);
	Out.Y = FMath::Clamp(Screen.Y, Edge, H - Edge);
	return true;
}

void ADCStatusHud::DrawHUD()
{
	Super::DrawHUD();

	if (Canvas == nullptr || GEngine == nullptr)
	{
		return;
	}
	if (bPreview)
	{
		DrawPreviewCaption();
		return;
	}
	if (bStrip)
	{
		DrawStrip();
	}
	if (bMarker)
	{
		DrawMarkers();
	}
	DrawPrompt();
}

// ------------------------------------------------------------------- the preview caption

void ADCStatusHud::DrawPreviewCaption()
{
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (Subsystem == nullptr || Canvas == nullptr)
	{
		return;
	}
	UFont* Font = GEngine->GetMediumFont();
	if (Font == nullptr)
	{
		Font = GEngine->GetSmallFont();
	}
	if (Font == nullptr)
	{
		return;
	}

	// The server's own words for the region, Japanese over English, exactly as the portal
	// does it. Until the first GET /preview/region answers there is only the region id,
	// which is the honest thing to show rather than a guess at a name.
	const FString Label = Subsystem->GetRegionLabel().IsEmpty()
		? Subsystem->GetRegion() : Subsystem->GetRegionLabel();
	const FString Jp = Subsystem->GetRegionLabelJp();

	// "a player in India" - which region this copy plays as, and nothing else. No ad and no
	// money language ever reaches a game screen (plan v6 §3), and this is a game screen.
	const FString Line1 = Jp.IsEmpty() ? FString() : FString::Printf(TEXT("%sのプレイヤー"), *Jp);
	const FString Line2 = FString::Printf(TEXT("a player in %s"), *Label);

	const float Scale = UiScale * 0.85f;
	float W1 = 0.0f;
	float H1 = 0.0f;
	float W2 = 0.0f;
	float H2 = 0.0f;
	if (!Line1.IsEmpty())
	{
		Canvas->TextSize(Font, Line1, W1, H1, Scale, Scale);
	}
	Canvas->TextSize(Font, Line2, W2, H2, Scale * 0.8f, Scale * 0.8f);

	const float Pad = 9.0f * UiScale;
	const float BoxW = FMath::Max(W1, W2) + Pad * 2.0f;
	const float BoxH = H1 + H2 + Pad * 2.0f;
	const float X = DCMargin;
	const float Y = static_cast<float>(Canvas->SizeY) - BoxH - DCMargin;

	DrawPanel(X, Y, BoxW, BoxH, PanelColour);

	float TextY = Y + Pad;
	if (!Line1.IsEmpty())
	{
		FCanvasTextItem Top(FVector2D(X + Pad, TextY), FText::FromString(Line1), Font,
			FLinearColor::White);
		Top.Scale = FVector2D(Scale, Scale);
		Top.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
		Canvas->DrawItem(Top);
		TextY += H1;
	}
	FCanvasTextItem Bottom(FVector2D(X + Pad, TextY), FText::FromString(Line2), Font,
		MarkerColour);
	Bottom.Scale = FVector2D(Scale * 0.8f, Scale * 0.8f);
	Bottom.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
	Canvas->DrawItem(Bottom);
}

// --------------------------------------------------------------------------- the strip

void ADCStatusHud::DrawStrip()
{
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	TArray<FString> Lines;
	if (Subsystem != nullptr)
	{
		Lines = Subsystem->GetStatusLines();
	}
	else
	{
		Lines.Add(FString::Printf(TEXT("build %s  ·  no DC client in this run"),
			UDCSubsystem::GetBuildConfigName()));
	}
	if (Lines.Num() == 0)
	{
		return;
	}

	UFont* Font = GEngine->GetMediumFont();
	if (Font == nullptr)
	{
		Font = GEngine->GetSmallFont();
	}
	if (Font == nullptr)
	{
		return;
	}

	// Measure first, so the panel is exactly as wide as the longest line.
	float Width = 0.0f;
	float LineHeight = 0.0f;
	for (const FString& Line : Lines)
	{
		float W = 0.0f;
		float H = 0.0f;
		Canvas->TextSize(Font, Line, W, H, UiScale, UiScale);
		Width = FMath::Max(Width, W);
		LineHeight = FMath::Max(LineHeight, H);
	}
	const float Height = LineHeight * Lines.Num();

	DrawPanel(DCMargin, DCMargin, Width + DCPadding * 2.0f, Height + DCPadding * 2.0f,
		PanelColour);

	float Y = DCMargin + DCPadding;
	for (int32 Index = 0; Index < Lines.Num(); ++Index)
	{
		// The first two lines are the build/uptime header; the slot lines below are dimmer so
		// the eye finds the one that just changed.
		const FLinearColor Colour = Index < 2 ? FLinearColor(1.0f, 1.0f, 1.0f, 1.0f)
			: FLinearColor(0.80f, 0.90f, 1.0f, 1.0f);
		FCanvasTextItem Item(FVector2D(DCMargin + DCPadding, Y), FText::FromString(Lines[Index]),
			Font, Colour);
		Item.Scale = FVector2D(UiScale, UiScale);
		Item.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
		Canvas->DrawItem(Item);
		Y += LineHeight;
	}
}

// --------------------------------------------------------------------------- the marker

void ADCStatusHud::DrawMarkers()
{
	const UDCSubsystem* Subsystem = UDCSubsystem::Get(this);
	if (Subsystem == nullptr)
	{
		return;
	}
	UFont* Font = GEngine->GetSmallFont();
	const APlayerController* PC = GetOwningPlayerController();
	const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	if (Pawn == nullptr)
	{
		return;
	}

	for (const ADCSlot* Slot : Subsystem->GetSlots())
	{
		if (!Slot->IsWaypointActive())
		{
			continue;
		}
		const FVector Where = Slot->GetWaypointLocation();
		FVector2D Screen;
		bool bOffScreen = false;
		if (!ProjectToScreen(Where, Screen, bOffScreen))
		{
			continue;
		}

		const float R = DCDiamond * UiScale;
		const FLinearColor Ink = MarkerColour;

		// A diamond outline, four lines. Deliberately small, deliberately a shape and not a
		// word: nothing on the Player's screen is allowed to be an advertisement, and a
		// wordless marker cannot become one in another language either.
		const FVector2D Top(Screen.X, Screen.Y - R);
		const FVector2D Right(Screen.X + R, Screen.Y);
		const FVector2D Bottom(Screen.X, Screen.Y + R);
		const FVector2D Left(Screen.X - R, Screen.Y);
		const FVector2D Corners[4] = { Top, Right, Bottom, Left };
		for (int32 i = 0; i < 4; ++i)
		{
			FCanvasLineItem Line(Corners[i], Corners[(i + 1) % 4]);
			Line.SetColor(Ink);
			Line.LineThickness = 2.0f * UiScale;
			Canvas->DrawItem(Line);
		}
		if (!bOffScreen)
		{
			// A stalk down to the ground, so the diamond reads as "there", not "over there".
			FCanvasLineItem Stalk(Bottom, FVector2D(Screen.X, Screen.Y + R * 2.2f));
			Stalk.SetColor(FLinearColor(Ink.R, Ink.G, Ink.B, 0.55f));
			Stalk.LineThickness = 2.0f * UiScale;
			Canvas->DrawItem(Stalk);
		}

		if (Font != nullptr)
		{
			const float Metres = FVector::Dist(Pawn->GetActorLocation(), Where) / 100.0f;
			const FString Label = FString::Printf(TEXT("%s  %.0f m"), *Slot->SlotId.ToString(),
				Metres);
			float TW = 0.0f;
			float TH = 0.0f;
			Canvas->TextSize(Font, Label, TW, TH, UiScale, UiScale);
			FCanvasTextItem Text(FVector2D(Screen.X - TW * 0.5f, Screen.Y - R - TH - 2.0f),
				FText::FromString(Label), Font, Ink);
			Text.Scale = FVector2D(UiScale, UiScale);
			Text.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
			Canvas->DrawItem(Text);
		}
	}
}

// --------------------------------------------------------------------------- the prompt

void ADCStatusHud::DrawPrompt()
{
	const UDCInteractor* Interactor = UDCInteractor::Find(this);
	if (Interactor == nullptr || !Interactor->IsEnabled())
	{
		return;
	}
	const FDCInteractorTarget& Target = Interactor->GetTarget();
	if (!Target.IsValid())
	{
		return;
	}
	UFont* Font = GEngine->GetMediumFont();
	if (Font == nullptr)
	{
		Font = GEngine->GetSmallFont();
	}
	if (Font == nullptr)
	{
		return;
	}

	FVector2D Screen;
	bool bOffScreen = false;
	if (!ProjectToScreen(Target.Location, Screen, bOffScreen) || bOffScreen)
	{
		return;                       // in reach but not in frame: there is nothing to label
	}

	const FString Line = Target.Prompt;
	const FString Key = Interactor->GetKeyHint();
	float W1 = 0.0f;
	float H1 = 0.0f;
	float W2 = 0.0f;
	float H2 = 0.0f;
	Canvas->TextSize(Font, Line, W1, H1, UiScale, UiScale);
	Canvas->TextSize(Font, Key, W2, H2, UiScale * 0.8f, UiScale * 0.8f);

	const float Pad = 10.0f * UiScale;
	const float BoxW = FMath::Max(W1, W2) + Pad * 2.0f;
	const float BoxH = H1 + H2 + Pad * 2.0f;
	const float X = Screen.X - BoxW * 0.5f;
	const float Y = Screen.Y - BoxH - 18.0f * UiScale;

	DrawPanel(X, Y, BoxW, BoxH, FLinearColor(0.02f, 0.03f, 0.04f, 0.70f));

	FCanvasTextItem What(FVector2D(X + (BoxW - W1) * 0.5f, Y + Pad), FText::FromString(Line),
		Font, FLinearColor::White);
	What.Scale = FVector2D(UiScale, UiScale);
	What.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
	Canvas->DrawItem(What);

	FCanvasTextItem Hint(FVector2D(X + (BoxW - W2) * 0.5f, Y + Pad + H1),
		FText::FromString(Key), Font, MarkerColour);
	Hint.Scale = FVector2D(UiScale * 0.8f, UiScale * 0.8f);
	Hint.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
	Canvas->DrawItem(Hint);
}
