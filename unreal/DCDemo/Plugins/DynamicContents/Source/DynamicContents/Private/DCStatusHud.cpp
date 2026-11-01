#include "DCStatusHud.h"

#include "DCSlot.h"
#include "DCSubsystem.h"
#include "DynamicContents.h"

#include "CanvasItem.h"
#include "CanvasTypes.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

namespace
{
	constexpr float DCMargin = 18.0f;
	constexpr float DCPadding = 12.0f;
}

ADCStatusHud::ADCStatusHud()
{
	PrimaryActorTick.bCanEverTick = false;
}

void ADCStatusHud::BeginPlay()
{
	Super::BeginPlay();

	float Scale = 0.0f;
	if (FParse::Value(FCommandLine::Get(), TEXT("DCUiScale="), Scale) && Scale > 0.1f)
	{
		UiScale = Scale;
	}
	bShowHUD = !FParse::Param(FCommandLine::Get(), TEXT("DCNoStrip"));
	DC_LOG(Log, TEXT("HUD status strip %s, scale %.2f"),
		bShowHUD ? TEXT("on") : TEXT("off"), UiScale);
}

void ADCStatusHud::DrawHUD()
{
	Super::DrawHUD();

	if (Canvas == nullptr || GEngine == nullptr)
	{
		return;
	}

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

	// The three-argument tile uses the engine's default white texture, so the panel needs no
	// asset of its own.
	FCanvasTileItem Panel(FVector2D(DCMargin, DCMargin),
		FVector2D(Width + DCPadding * 2.0f, Height + DCPadding * 2.0f), PanelColour);
	Panel.BlendMode = SE_BLEND_Translucent;
	Canvas->DrawItem(Panel);

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
