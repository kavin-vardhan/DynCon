#include "DCStatusHud.h"

#include "DCInteractor.h"
#include "DCShell.h"
#include "DCSlot.h"
#include "DCSubsystem.h"
#include "DCXray.h"
#include "DynamicContents.h"

#include "CanvasItem.h"
#include "CanvasTypes.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Engine/Texture2D.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "TextureResource.h"

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

	// **Never over the strip** (brief 018, from 016's report). A slot behind the Player
	// clamps the marker to the edge, and the top-left edge is where the one piece of
	// instrumentation the whole demo turns on is drawn. So if the clamped marker - with the
	// room its diamond and its label need above it - lands inside the strip's box, it is
	// pushed to whichever side of the strip is nearer. The unclamped case is untouched: a
	// marker over a slot that is genuinely up there is where it should be.
	if (StripBottom > 0.0f && bOffScreen)
	{
		const float Room = (DCDiamond * 2.6f + 16.0f) * UiScale;
		if (Out.X < StripRight + Room && Out.Y < StripBottom + Room)
		{
			if (StripRight + Room < W - Edge && Out.X > Edge * 1.5f)
			{
				Out.X = StripRight + Room;    // out to the right of it
			}
			else
			{
				Out.Y = StripBottom + Room;   // or down below it
			}
			// Logged once per run, because a run whose pictures happen not to catch the
			// marker in that corner would otherwise say nothing about whether this works.
			if (!bLoggedStripClamp)
			{
				bLoggedStripClamp = true;
				DC_LOG(Log, TEXT("HUD   a waypoint marker clamped into the status strip's "
					"corner and was pushed clear of it (strip %0.fx%.0f, marker now "
					"%.0f,%.0f)"), StripRight, StripBottom, Out.X, Out.Y);
			}
		}
	}
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
	StripBottom = 0.0f;
	StripRight = 0.0f;
	if (bStrip)
	{
		DrawStrip();
	}

	const UDCShell* Shell = UDCShell::Get(this);

	// The X-ray goes under the game's own UI and over the world: it is instrumentation
	// about the world, and the prompt and the marker are the game.
	if (Shell != nullptr && Shell->IsXray())
	{
		FDCXray::Draw(Canvas, UDCSubsystem::Get(this), UiScale, StripBottom);
	}
	if (bMarker)
	{
		DrawMarkers();
	}
	DrawPrompt();

	if (Shell != nullptr && Shell->IsEnabled())
	{
		switch (Shell->GetMode())
		{
		case EDCShellMode::Attract: DrawAttract(); break;
		case EDCShellMode::Title:   DrawTitle();   break;
		case EDCShellMode::Paused:  DrawPause();   break;
		default: break;
		}
		DrawFade();
	}
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
	StripBottom = DCMargin + Height + DCPadding * 2.0f;
	StripRight = DCMargin + Width + DCPadding * 2.0f;

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

// ================================================================= the shell's screens
//
// Plan v6 §3 and §4 step 0. Every line here is Japanese over English, because every line a
// visitor reads is; the only things that are not are the slot ids and the button faces,
// which are the same in both languages.

float ADCStatusHud::DrawBilingual(float CentreX, float Y, const FString& Jp, const FString& En,
	const FLinearColor& Colour, float Scale)
{
	UFont* Font = GEngine->GetMediumFont();
	if (Font == nullptr || Canvas == nullptr)
	{
		return 0.0f;
	}
	float W1 = 0.0f;
	float H1 = 0.0f;
	float W2 = 0.0f;
	float H2 = 0.0f;
	const float Small = Scale * 0.74f;
	Canvas->TextSize(Font, Jp, W1, H1, Scale, Scale);
	Canvas->TextSize(Font, En, W2, H2, Small, Small);

	if (!Jp.IsEmpty())
	{
		FCanvasTextItem Top(FVector2D(CentreX - W1 * 0.5f, Y), FText::FromString(Jp), Font,
			Colour);
		Top.Scale = FVector2D(Scale, Scale);
		Top.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.9f));
		Canvas->DrawItem(Top);
	}
	if (!En.IsEmpty())
	{
		FCanvasTextItem Bottom(FVector2D(CentreX - W2 * 0.5f, Y + H1),
			FText::FromString(En), Font, Colour);
		Bottom.Scale = FVector2D(Small, Small);
		Bottom.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.9f));
		Canvas->DrawItem(Bottom);
	}
	return H1 + H2;
}

void ADCStatusHud::DrawAttract()
{
	// The attract loop is the map, and the map is the point. The only thing drawn over it
	// is the one sentence that says how to stop watching and start playing.
	const float W = static_cast<float>(Canvas->SizeX);
	const float H = static_cast<float>(Canvas->SizeY);
	const float Scale = UiScale * 1.05f;

	UFont* Font = GEngine->GetMediumFont();
	float TW = 0.0f;
	float TH = 0.0f;
	const FString Jp = TEXT("どれかのボタンでスタート");
	Canvas->TextSize(Font, Jp, TW, TH, Scale, Scale);

	const float BoxW = FMath::Max(TW + 70.0f * UiScale, 340.0f * UiScale);
	const float BoxH = TH * 1.95f + 24.0f * UiScale;
	const float X = (W - BoxW) * 0.5f;

	// Above the X-ray's frame-time graph when that is up, and at the bottom of the screen
	// when it is not: they are both bottom-centre and the one line a visitor has to read
	// does not share a box with a chart.
	const UDCShell* Shell = UDCShell::Get(this);
	const float Lift = (Shell != nullptr && Shell->IsXray()) ? H * 0.23f : 0.0f;
	const float Y = H - BoxH - 56.0f * UiScale - Lift;
	DrawPanel(X, Y, BoxW, BoxH, FLinearColor(0.02f, 0.03f, 0.05f, 0.62f));
	DrawBilingual(W * 0.5f, Y + 12.0f * UiScale, Jp, TEXT("Press any button to start"),
		FLinearColor::White, Scale);
}

void ADCStatusHud::DrawTitle()
{
	const UDCShell* Shell = UDCShell::Get(this);
	if (Shell == nullptr)
	{
		return;
	}
	const TArray<FDCGameCard>& Cards = Shell->GetCards();
	if (Cards.Num() == 0)
	{
		return;
	}

	const float W = static_cast<float>(Canvas->SizeX);
	const float H = static_cast<float>(Canvas->SizeY);

	// The map keeps playing behind it, dimmed: a visitor walking up sees a game, not a form.
	DrawPanel(0.0f, 0.0f, W, H, FLinearColor(0.01f, 0.02f, 0.04f, 0.72f));

	DrawBilingual(W * 0.5f, H * 0.11f, TEXT("ゲームを選ぶ"), TEXT("Choose a game"),
		FLinearColor::White, UiScale * 1.5f);

	// Two 16:9 cards side by side, as big as they fit.
	const float Gap = 40.0f * UiScale;
	const float CardW = FMath::Min((W - Gap * (Cards.Num() + 1)) / Cards.Num(), W * 0.40f);
	const float CardH = CardW * 9.0f / 16.0f;
	const float Total = CardW * Cards.Num() + Gap * (Cards.Num() - 1);
	const float Top = H * 0.30f;
	float X = (W - Total) * 0.5f;

	for (int32 i = 0; i < Cards.Num(); ++i)
	{
		const FDCGameCard& Card = Cards[i];
		const bool bPicked = i == Shell->GetCardIndex();
		const float Grow = bPicked ? 10.0f * UiScale : 0.0f;
		const float CX = X - Grow;
		const float CY = Top - Grow;
		const float CW = CardW + Grow * 2.0f;
		const float CH = CardH + Grow * 2.0f;

		// The border first, so the picture sits inside it.
		DrawPanel(CX - 4.0f * UiScale, CY - 4.0f * UiScale, CW + 8.0f * UiScale,
			CH + 8.0f * UiScale, bPicked ? FLinearColor(0.60f, 0.86f, 1.0f, 0.95f)
				: FLinearColor(0.35f, 0.42f, 0.52f, 0.75f));

		if (Card.Art != nullptr && Card.Art->GetResource() != nullptr)
		{
			// The developer's own plan view of the map, registered with the platform and
			// fetched back - the same picture the portal's slot map draws.
			FCanvasTileItem Tile(FVector2D(CX, CY), Card.Art->GetResource(),
				FVector2D(CW, CH), bPicked ? FLinearColor::White
					: FLinearColor(0.68f, 0.72f, 0.78f, 1.0f));
			Tile.BlendMode = SE_BLEND_Opaque;
			Canvas->DrawItem(Tile);
		}
		else
		{
			// No registration on this server: a plain panel, warm for the first game and
			// cool for the second, so the two still read as two different places.
			DrawPanel(CX, CY, CW, CH, i == 0 ? FLinearColor(0.20f, 0.15f, 0.10f, 1.0f)
				: FLinearColor(0.09f, 0.14f, 0.20f, 1.0f));
		}

		DrawBilingual(CX + CW * 0.5f, CY + CH + 16.0f * UiScale, Card.LabelJp, Card.LabelEn,
			bPicked ? FLinearColor::White : FLinearColor(0.70f, 0.76f, 0.84f, 1.0f),
			UiScale * 1.25f);

		X += CardW + Gap;
	}

	DrawBilingual(W * 0.5f, H * 0.88f, TEXT("←→ で選び、✕ で決定"),
		TEXT("Left / right to choose, X to start"), MarkerColour, UiScale);
}

void ADCStatusHud::DrawPause()
{
	const UDCShell* Shell = UDCShell::Get(this);
	if (Shell == nullptr)
	{
		return;
	}
	const float W = static_cast<float>(Canvas->SizeX);
	const float H = static_cast<float>(Canvas->SizeY);

	// Only a dim, not a blackout: the world behind the menu is still running, and that is
	// worth seeing - a block can roll over while the menu is up and the slot behind it will
	// swap. Nothing here stops the game.
	DrawPanel(0.0f, 0.0f, W, H, FLinearColor(0.01f, 0.02f, 0.04f, 0.52f));

	FString OtherJp;
	FString OtherEn;
	Shell->GetGameLabels(Shell->GetOtherGame(), OtherJp, OtherEn);

	const FString ItemsJp[3] = {
		TEXT("再開"),
		FString::Printf(TEXT("%s に切り替え"), *OtherJp),
		FString::Printf(TEXT("X 線ビュー：%s"), Shell->IsXray() ? TEXT("オン") : TEXT("オフ")) };
	const FString ItemsEn[3] = {
		TEXT("Resume"),
		FString::Printf(TEXT("Switch to %s"), *OtherEn),
		FString::Printf(TEXT("X-ray view: %s"), Shell->IsXray() ? TEXT("on") : TEXT("off")) };

	const float BoxW = FMath::Min(W * 0.46f, 760.0f * UiScale);
	const float RowH = 78.0f * UiScale;
	const float BoxH = RowH * 3.0f + 96.0f * UiScale;
	const float X = (W - BoxW) * 0.5f;
	const float Y = (H - BoxH) * 0.5f;
	DrawPanel(X, Y, BoxW, BoxH, FLinearColor(0.02f, 0.03f, 0.05f, 0.88f));

	DrawBilingual(W * 0.5f, Y + 18.0f * UiScale, TEXT("ポーズ"), TEXT("Paused"),
		FLinearColor::White, UiScale * 1.2f);

	for (int32 i = 0; i < 3; ++i)
	{
		const bool bPicked = i == Shell->GetPauseIndex();
		const float RowY = Y + 86.0f * UiScale + RowH * i;
		if (bPicked)
		{
			DrawPanel(X + 16.0f * UiScale, RowY - 6.0f * UiScale, BoxW - 32.0f * UiScale,
				RowH - 8.0f * UiScale, FLinearColor(0.16f, 0.30f, 0.42f, 0.92f));
		}
		DrawBilingual(W * 0.5f, RowY, ItemsJp[i], ItemsEn[i],
			bPicked ? FLinearColor::White : FLinearColor(0.70f, 0.76f, 0.84f, 1.0f),
			UiScale * 1.05f);
	}
}

void ADCStatusHud::DrawFade()
{
	const UDCShell* Shell = UDCShell::Get(this);
	if (Shell == nullptr)
	{
		return;
	}
	const float Alpha = Shell->GetFadeAlpha();
	if (Alpha <= 0.002f)
	{
		return;
	}
	const float W = static_cast<float>(Canvas->SizeX);
	const float H = static_cast<float>(Canvas->SizeY);

	// Plain black. Switching **games** is a level load and gets a loading screen; switching
	// **content** never does, and the strip's two zeroes say so all day (plan v6 §3).
	DrawPanel(0.0f, 0.0f, W, H, FLinearColor(0.0f, 0.0f, 0.0f, Alpha));

	if (Alpha > 0.55f && !Shell->GetFadeEn().IsEmpty())
	{
		const float Fade = FMath::Clamp((Alpha - 0.55f) / 0.35f, 0.0f, 1.0f);
		DrawBilingual(W * 0.5f, H * 0.5f - 30.0f * UiScale, Shell->GetFadeJp(),
			Shell->GetFadeEn(), FLinearColor(1.0f, 1.0f, 1.0f, Fade), UiScale * 1.3f);
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
