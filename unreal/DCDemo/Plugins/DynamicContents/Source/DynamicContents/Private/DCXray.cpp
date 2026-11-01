#include "DCXray.h"

#include "DCManifest.h"
#include "DCShell.h"
#include "DCSlot.h"
#include "DCSubsystem.h"
#include "DynamicContents.h"

#include "CanvasItem.h"
#include "CanvasTypes.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "HAL/PlatformTime.h"

namespace
{
	constexpr float DCMargin = 18.0f;
	constexpr float DCPad = 10.0f;

	/** Segments in a pre-fetch ring. Forty reads as a circle at 60 m and costs forty lines. */
	constexpr int32 DCRingSegments = 40;

	/**
	 * …and a post every this many segments, 2.5 m tall.
	 *
	 * A 60 m circle drawn flat on the ground and seen from a third-person camera 1.5 m up
	 * is a *horizontal line near the horizon*, whatever colour it is - which is what the
	 * first version of this looked like. The posts are what make it read at a glance: they
	 * project as uprights, so the boundary is a fence rather than a scratch on the screen.
	 */
	constexpr int32 DCRingPostEvery = 5;
	constexpr float DCRingPostHeight = 250.0f;

	/** The graph's ceiling, and the two lines drawn across it. */
	constexpr float DCGraphTopMs = 40.0f;
	constexpr float DCGraphLine1 = 16.7f;
	constexpr float DCGraphLine2 = 33.0f;

	/** How many columns the graph is reduced to. Each one is the worst frame in its slice,
	 *  because a graph that is there to show "no spike" must not average a spike away. */
	constexpr int32 DCGraphColumns = 150;

	const FLinearColor DCInk(0.86f, 0.93f, 1.0f, 1.0f);
	const FLinearColor DCDim(0.62f, 0.72f, 0.84f, 1.0f);
	const FLinearColor DCPanelFill(0.02f, 0.03f, 0.05f, 0.74f);

	/** One colour per lifecycle state, so the rings read at a glance from third person. */
	FLinearColor StateColour(EDCSlotState State)
	{
		switch (State)
		{
		case EDCSlotState::Idle:        return FLinearColor(0.55f, 0.60f, 0.66f, 0.85f);
		case EDCSlotState::Resolving:   return FLinearColor(0.55f, 0.78f, 1.00f, 0.95f);
		case EDCSlotState::Downloading: return FLinearColor(0.20f, 0.90f, 0.95f, 0.95f);
		case EDCSlotState::Verifying:   return FLinearColor(0.98f, 0.86f, 0.25f, 0.95f);
		case EDCSlotState::Mounting:    return FLinearColor(1.00f, 0.60f, 0.18f, 0.95f);
		case EDCSlotState::Active:      return FLinearColor(0.35f, 0.92f, 0.45f, 0.95f);
		case EDCSlotState::SwapPending: return FLinearColor(0.90f, 0.45f, 0.95f, 0.95f);
		case EDCSlotState::Error:
		case EDCSlotState::Fallback:
		default:                        return FLinearColor(0.98f, 0.33f, 0.30f, 0.95f);
		}
	}

	FString Bytes(int64 N)
	{
		if (N >= 1024 * 1024)
		{
			return FString::Printf(TEXT("%.1f MB"), N / 1048576.0);
		}
		if (N >= 1024)
		{
			return FString::Printf(TEXT("%.0f kB"), N / 1024.0);
		}
		return FString::Printf(TEXT("%lld B"), N);
	}

	/** Everything a panel needs: measure, box, heading, rows. */
	struct FPanel
	{
		UCanvas* Canvas = nullptr;
		UFont* Head = nullptr;
		UFont* Body = nullptr;
		float Scale = 1.0f;
		float X = 0.0f;
		float Y = 0.0f;
		float Width = 0.0f;

		/** When set, the panel hangs off this right edge instead of starting at X - so a
		 *  long row widens it leftwards instead of running off the screen. */
		float RightEdge = -1.0f;

		TArray<TPair<FString, FLinearColor>> Rows;
		FString HeadingJp;
		FString HeadingEn;

		void Row(const FString& Text, const FLinearColor& Colour = DCInk)
		{
			Rows.Emplace(Text, Colour);
		}

		float LineHeight() const
		{
			float W = 0.0f;
			float H = 0.0f;
			Canvas->TextSize(Body, TEXT("Ag"), W, H, Scale, Scale);
			return H;
		}

		/** Draws it and returns the Y just under it. */
		float Flush()
		{
			const float Line = LineHeight();
			float HeadW = 0.0f;
			float HeadH = 0.0f;
			const FString Heading = HeadingJp + TEXT("  ·  ") + HeadingEn;
			Canvas->TextSize(Head, Heading, HeadW, HeadH, Scale, Scale);

			float Widest = HeadW;
			for (const TPair<FString, FLinearColor>& Each : Rows)
			{
				float W = 0.0f;
				float H = 0.0f;
				Canvas->TextSize(Body, Each.Key, W, H, Scale, Scale);
				Widest = FMath::Max(Widest, W);
			}
			const float BoxW = FMath::Max(Width, Widest + DCPad * 2.0f * Scale);
			const float BoxH = HeadH + Line * Rows.Num() + DCPad * 2.6f * Scale;
			if (RightEdge >= 0.0f)
			{
				X = RightEdge - BoxW;
			}

			FCanvasTileItem Box(FVector2D(X, Y), FVector2D(BoxW, BoxH), DCPanelFill);
			Box.BlendMode = SE_BLEND_Translucent;
			Canvas->DrawItem(Box);

			float At = Y + DCPad * Scale;
			FCanvasTextItem Title(FVector2D(X + DCPad * Scale, At), FText::FromString(Heading),
				Head, FLinearColor(0.60f, 0.86f, 1.0f, 1.0f));
			Title.Scale = FVector2D(Scale, Scale);
			Title.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
			Canvas->DrawItem(Title);
			At += HeadH + DCPad * 0.4f * Scale;

			for (const TPair<FString, FLinearColor>& Each : Rows)
			{
				FCanvasTextItem Item(FVector2D(X + DCPad * Scale, At),
					FText::FromString(Each.Key), Body, Each.Value);
				Item.Scale = FVector2D(Scale, Scale);
				Item.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
				Canvas->DrawItem(Item);
				At += Line;
			}
			Rows.Reset();
			return Y + BoxH;
		}
	};

	/** The pre-fetch rings. World space, so they are the one part of the overlay that says
	 *  where in the map the lifecycle is happening. */
	void DrawRings(UCanvas* Canvas, const UDCSubsystem* Subsystem, UFont* Font, float Scale,
		const ADCSlot* Nearest)
	{
		for (const ADCSlot* Slot : Subsystem->GetSlots())
		{
			const FLinearColor Colour = StateColour(Slot->GetState());
			const FVector Centre = Slot->GetActorLocation();
			const float Radius = FMath::Max(Slot->PrefetchRadius, 100.0f);
			const float Thickness = (Slot == Nearest ? 3.0f : 2.0f) * Scale;

			FVector2D Previous(0.0f, 0.0f);
			bool bHavePrevious = false;
			for (int32 i = 0; i <= DCRingSegments; ++i)
			{
				const float Angle = 2.0f * PI * i / DCRingSegments;
				const FVector World = Centre
					+ FVector(FMath::Cos(Angle) * Radius, FMath::Sin(Angle) * Radius, 4.0f);
				const FVector P = Canvas->Project(World, /*bClampToZeroPlane=*/false);
				if (P.Z <= 0.0f)
				{
					bHavePrevious = false;    // behind the camera: no line through the viewer
					continue;
				}
				const FVector2D Here(P.X, P.Y);
				if (bHavePrevious)
				{
					FCanvasLineItem Line(Previous, Here);
					Line.SetColor(Colour);
					Line.LineThickness = Thickness;
					Canvas->DrawItem(Line);
				}
				if (i % DCRingPostEvery == 0)
				{
					const FVector Top = Canvas->Project(
						World + FVector(0.0f, 0.0f, DCRingPostHeight), false);
					if (Top.Z > 0.0f)
					{
						FCanvasLineItem Post(Here, FVector2D(Top.X, Top.Y));
						Post.SetColor(FLinearColor(Colour.R, Colour.G, Colour.B,
							Colour.A * 0.75f));
						Post.LineThickness = Thickness;
						Canvas->DrawItem(Post);
					}
				}
				Previous = Here;
				bHavePrevious = true;
			}

			// A short mast from the slot to its label, so a ring and its name cannot be read
			// apart when two of them overlap.
			const FVector Top = Canvas->Project(Centre + FVector(0, 0, Slot->GetClassLimits().Z
				+ 150.0f), false);
			if (Top.Z > 0.0f && Font != nullptr)
			{
				const FString Label = FString::Printf(TEXT("%s  %s  %s"),
					*Slot->SlotId.ToString(), *Slot->GetSizeClassName(),
					DCSlotStateName(Slot->GetState()));
				float W = 0.0f;
				float H = 0.0f;
				Canvas->TextSize(Font, Label, W, H, Scale, Scale);

				FCanvasTileItem Box(FVector2D(Top.X - W * 0.5f - 5.0f, Top.Y - H * 0.5f - 3.0f),
					FVector2D(W + 10.0f, H + 6.0f), FLinearColor(0.0f, 0.0f, 0.0f, 0.58f));
				Box.BlendMode = SE_BLEND_Translucent;
				Canvas->DrawItem(Box);

				FCanvasTextItem Text(FVector2D(Top.X - W * 0.5f, Top.Y - H * 0.5f),
					FText::FromString(Label), Font, Colour);
				Text.Scale = FVector2D(Scale, Scale);
				Text.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
				Canvas->DrawItem(Text);
			}
		}
	}

	void DrawGraph(UCanvas* Canvas, const UDCSubsystem* Subsystem, UFont* Head, UFont* Body,
		float Scale, float X, float Y, float W, float H)
	{
		FCanvasTileItem Box(FVector2D(X, Y), FVector2D(W, H), DCPanelFill);
		Box.BlendMode = SE_BLEND_Translucent;
		Canvas->DrawItem(Box);

		const FDCFrameStats Stats = const_cast<UDCSubsystem*>(Subsystem)->GetFrameStats();
		const FString Heading = FString::Printf(
			TEXT("フレーム時間  ·  frame time  ·  %.0f s  ·  avg %.1f ms  ·  worst 1%% %.1f ms"),
			UDCSubsystem::GetFrameGraphSeconds(), Stats.AverageMs, Stats.Worst1PercentMs);
		float HW = 0.0f;
		float HH = 0.0f;
		Canvas->TextSize(Head, Heading, HW, HH, Scale, Scale);
		FCanvasTextItem Title(FVector2D(X + DCPad * Scale, Y + DCPad * 0.6f * Scale),
			FText::FromString(Heading), Head, FLinearColor(0.60f, 0.86f, 1.0f, 1.0f));
		Title.Scale = FVector2D(Scale, Scale);
		Title.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
		Canvas->DrawItem(Title);

		const float PlotX = X + DCPad * Scale;
		const float PlotY = Y + HH + DCPad * 1.1f * Scale;
		const float PlotW = W - DCPad * 2.0f * Scale;
		const float PlotH = H - (PlotY - Y) - DCPad * Scale;
		if (PlotW <= 4.0f || PlotH <= 4.0f)
		{
			return;
		}

		auto AtMs = [PlotY, PlotH](float Ms)
		{
			return PlotY + PlotH * (1.0f - FMath::Clamp(Ms / DCGraphTopMs, 0.0f, 1.0f));
		};

		// 60 fps and 30 fps, named rather than left as two anonymous lines.
		const float Lines[2] = { DCGraphLine1, DCGraphLine2 };
		for (int32 i = 0; i < 2; ++i)
		{
			const float LineY = AtMs(Lines[i]);
			FCanvasLineItem Rule(FVector2D(PlotX, LineY), FVector2D(PlotX + PlotW, LineY));
			Rule.SetColor(FLinearColor(1.0f, 1.0f, 1.0f, i == 0 ? 0.30f : 0.22f));
			Rule.LineThickness = 1.0f;
			Canvas->DrawItem(Rule);

			const FString Tag = FString::Printf(TEXT("%.1f ms"), Lines[i]);
			FCanvasTextItem Text(FVector2D(PlotX + PlotW - 54.0f * Scale, LineY - 13.0f * Scale),
				FText::FromString(Tag), Body, FLinearColor(1.0f, 1.0f, 1.0f, 0.45f));
			Text.Scale = FVector2D(Scale * 0.85f, Scale * 0.85f);
			Canvas->DrawItem(Text);
		}

		const TArray<FDCFrameSample>& Samples = Subsystem->GetFrameGraph();
		if (Samples.Num() < 2)
		{
			return;
		}
		const double Newest = Samples.Last().Seconds;
		const double Window = UDCSubsystem::GetFrameGraphSeconds();

		// One column per slice of the window, holding the worst frame in that slice: the
		// point of this graph is that a swap produces no spike, so a spike must not be
		// averaged out of it.
		TArray<float> Columns;
		Columns.Init(-1.0f, DCGraphColumns);
		for (const FDCFrameSample& Sample : Samples)
		{
			const double Age = Newest - Sample.Seconds;
			const int32 Column = FMath::Clamp(
				static_cast<int32>((1.0 - Age / Window) * (DCGraphColumns - 1)),
				0, DCGraphColumns - 1);
			Columns[Column] = FMath::Max(Columns[Column], Sample.Ms);
		}

		FVector2D Previous(0.0f, 0.0f);
		bool bHave = false;
		for (int32 i = 0; i < DCGraphColumns; ++i)
		{
			if (Columns[i] < 0.0f)
			{
				continue;
			}
			const FVector2D Here(PlotX + PlotW * i / float(DCGraphColumns - 1), AtMs(Columns[i]));
			if (bHave)
			{
				FCanvasLineItem Line(Previous, Here);
				Line.SetColor(Columns[i] > DCGraphLine2
					? FLinearColor(0.98f, 0.40f, 0.33f, 1.0f)
					: FLinearColor(0.45f, 0.95f, 0.70f, 1.0f));
				Line.LineThickness = 1.6f * Scale;
				Canvas->DrawItem(Line);
			}
			Previous = Here;
			bHave = true;
		}

		// A tick at every mount, spawn and unload in the window, with its initial on it.
		for (const FDCFrameMark& Mark : Subsystem->GetFrameMarks())
		{
			const double Age = Newest - Mark.Seconds;
			if (Age < 0.0 || Age > Window)
			{
				continue;
			}
			const float MarkX = PlotX + PlotW * static_cast<float>(1.0 - Age / Window);
			FCanvasLineItem Tick(FVector2D(MarkX, PlotY), FVector2D(MarkX, PlotY + PlotH));
			Tick.SetColor(FLinearColor(1.0f, 0.85f, 0.35f, 0.75f));
			Tick.LineThickness = 1.4f * Scale;
			Canvas->DrawItem(Tick);

			const FString Tag = FString::Printf(TEXT("%s %s"),
				*Mark.Phase.Left(1).ToUpper(), *Mark.SlotId);
			FCanvasTextItem Text(FVector2D(MarkX + 3.0f, PlotY + 1.0f), FText::FromString(Tag),
				Body, FLinearColor(1.0f, 0.85f, 0.35f, 0.95f));
			Text.Scale = FVector2D(Scale * 0.85f, Scale * 0.85f);
			Text.EnableShadow(FLinearColor(0.0f, 0.0f, 0.0f, 0.85f));
			Canvas->DrawItem(Text);
		}
	}
}

void FDCXray::Draw(UCanvas* Canvas, const UDCSubsystem* Subsystem, float UiScale, float TopY)
{
	if (Canvas == nullptr || Subsystem == nullptr || GEngine == nullptr)
	{
		return;
	}
	UFont* Head = GEngine->GetMediumFont();
	UFont* Body = GEngine->GetSmallFont();
	if (Head == nullptr || Body == nullptr)
	{
		return;
	}

	// Smaller than the status strip: the strip is read from across a booth, this is read by
	// somebody who has walked up to the screen because they asked how it works.
	const float Scale = FMath::Max(UiScale * 0.78f, 0.7f);
	const float W = static_cast<float>(Canvas->SizeX);
	const float H = static_cast<float>(Canvas->SizeY);

	// ---- which slot the panels are about: the nearest to whoever is looking ------------
	FVector Viewer;
	const bool bHaveViewer = Subsystem->GetViewerLocation(Viewer);
	const ADCSlot* Nearest = nullptr;
	float NearestCm = TNumericLimits<float>::Max();
	for (const ADCSlot* Slot : Subsystem->GetSlots())
	{
		const float Distance = bHaveViewer
			? FVector::Dist(Viewer, Slot->GetActorLocation()) : 0.0f;
		if (Nearest == nullptr || Distance < NearestCm)
		{
			Nearest = Slot;
			NearestCm = Distance;
		}
	}

	DrawRings(Canvas, Subsystem, Body, Scale, Nearest);

	// ---- the manifest of the nearest slot ----------------------------------------------
	FPanel Panel;
	Panel.Canvas = Canvas;
	Panel.Head = Head;
	Panel.Body = Body;
	Panel.Scale = Scale;
	Panel.Width = W * 0.26f;
	Panel.RightEdge = W - DCMargin;
	Panel.Y = TopY + DCMargin;

	Panel.HeadingJp = TEXT("マニフェスト");
	Panel.HeadingEn = TEXT("manifest");
	if (Nearest == nullptr)
	{
		Panel.Row(TEXT("no slots in this map"), DCDim);
	}
	else
	{
		const FDCManifest& M = Nearest->GetActiveManifest();
		Panel.Row(FString::Printf(TEXT("slot      %s  %s   %s"), *Nearest->SlotId.ToString(),
			*Nearest->GetSizeClassName(), DCSlotStateName(Nearest->GetState())),
			StateColour(Nearest->GetState()));
		if (M.Piece.IsEmpty())
		{
			Panel.Row(TEXT("nothing resolved here yet"), DCDim);
		}
		else
		{
			Panel.Row(FString::Printf(TEXT("content   %s %s   %s"), *M.Piece, *M.Version,
				*M.Brand.Describe()));
			Panel.Row(FString::Printf(TEXT("pack      %s   %s in %d file(s)"), *M.PackId,
				*Bytes(M.TotalFileBytes()), M.Files.Num()));

			// The .ucas is where the content actually is; the .pak next to it is a few
			// hundred bytes of index (unreal/README.md). Show the hash of the big one.
			const FDCPackFile* Biggest = nullptr;
			for (const FDCPackFile& File : M.Files)
			{
				if (Biggest == nullptr || File.Size > Biggest->Size)
				{
					Biggest = &File;
				}
			}
			if (Biggest != nullptr)
			{
				Panel.Row(FString::Printf(TEXT("sha-256   %s  %s…"), *Biggest->Name,
					*Biggest->Sha256.Left(16)));
			}
			Panel.Row(FString::Printf(TEXT("signature %s"),
				M.bSignatureVerified ? TEXT("RS256 ok, checked on this machine")
					: TEXT("not checked")),
				M.bSignatureVerified ? FLinearColor(0.35f, 0.92f, 0.45f, 1.0f)
					: FLinearColor(0.98f, 0.33f, 0.30f, 1.0f));
			Panel.Row(FString::Printf(TEXT("region    %s   game %s"), *M.Region, *M.Game));
			Panel.Row(FString::Printf(TEXT("lot/block %s   block %s   (%s)"),
				M.ShowingLot.IsEmpty() ? TEXT("-") : *M.ShowingLot,
				M.ShowingBlock >= 0 ? *FString::FromInt(M.ShowingBlock) : TEXT("-"),
				*M.ShowingSource));
			Panel.Row(FString::Printf(TEXT("alloc key %s   %s"), *M.AllocKey, *M.ShowingKind));
			Panel.Row(FString::Printf(TEXT("ends      %s"),
				M.ShowingEndsAt.IsEmpty() ? TEXT("-") : *M.ShowingEndsAt), DCDim);
			Panel.Row(FString::Printf(TEXT("valid to  %s"),
				M.ValidUntil.IsEmpty() ? TEXT("-") : *M.ValidUntil), DCDim);
		}
		if (bHaveViewer)
		{
			Panel.Row(FString::Printf(TEXT("pre-fetch %.0f m ring, viewer %.0f m away%s"),
				Nearest->PrefetchRadius / 100.0f, NearestCm / 100.0f,
				NearestCm <= Nearest->PrefetchRadius ? TEXT("  (inside)") : TEXT("")), DCDim);
		}
	}
	float NextY = Panel.Flush() + DCMargin * 0.6f;

	// ---- the cache ----------------------------------------------------------------------
	Panel.Y = NextY;
	Panel.HeadingJp = TEXT("キャッシュ");
	Panel.HeadingEn = TEXT("pack cache, most recently used first");
	{
		// Pack id -> what was in it, out of the activation history: a pack on disk is a hex
		// id and nothing else, and "rival2 v1" is what somebody reading this wants.
		TMap<FString, FString> Names;
		for (const UDCSubsystem::FActivation& A : Subsystem->GetActivations())
		{
			Names.Add(A.PackId, FString::Printf(TEXT("%s %s"), *A.Piece, *A.Version));
		}
		const TArray<FDCCachedPack> Packs = Subsystem->GetCache().List();
		if (Packs.Num() == 0)
		{
			Panel.Row(TEXT("empty"), DCDim);
		}
		int64 Total = 0;
		for (int32 i = 0; i < Packs.Num(); ++i)
		{
			const FDCCachedPack& Pack = Packs[i];
			Total += Pack.Bytes;
			const FString* Name = Names.Find(Pack.PackId);
			const bool bMounted = Subsystem->IsPackMounted(Pack.PackId);
			Panel.Row(FString::Printf(TEXT("%d. %-14s %-12s %8s  %s"), i + 1,
				*Pack.PackId.Left(14), Name ? **Name : TEXT("-"), *Bytes(Pack.Bytes),
				bMounted ? TEXT("mounted") : TEXT("on disk")),
				bMounted ? DCInk : DCDim);
		}
		Panel.Row(FString::Printf(TEXT("%d pack(s), %s on disk"), Packs.Num(), *Bytes(Total)),
			DCDim);
	}
	Panel.Flush();

	// ---- the lifecycle log ---------------------------------------------------------------
	FPanel Log;
	Log.Canvas = Canvas;
	Log.Head = Head;
	Log.Body = Body;
	Log.Scale = Scale;
	Log.Width = W * 0.33f;
	Log.X = DCMargin;
	Log.Y = TopY + DCMargin;
	Log.HeadingJp = TEXT("ライフサイクル");
	Log.HeadingEn = TEXT("lifecycle, newest last");
	{
		const TArray<FDCLifecycleNote>& Notes = Subsystem->GetLifecycle();
		if (Notes.Num() == 0)
		{
			Log.Row(TEXT("nothing has happened yet"), DCDim);
		}
		const int32 First = FMath::Max(0, Notes.Num() - 10);
		const double Now = FPlatformTime::Seconds();
		for (int32 i = First; i < Notes.Num(); ++i)
		{
			const FDCLifecycleNote& Note = Notes[i];
			Log.Row(FString::Printf(TEXT("-%4.0f s  %-3s %-9s %7.1f ms  %s"),
				Now - Note.Seconds, *Note.SlotId, *Note.Phase, Note.Ms, *Note.Note),
				Note.Phase == TEXT("fallback") ? FLinearColor(0.98f, 0.33f, 0.30f, 1.0f)
					: DCInk);
		}
	}
	NextY = Log.Flush() + DCMargin * 0.6f;

	// ---- the session, including the one counter the strip must not carry ----------------
	Log.Y = NextY;
	Log.HeadingJp = TEXT("この回");
	Log.HeadingEn = TEXT("this session");
	{
		const FDCFrameStats Stats = const_cast<UDCSubsystem*>(Subsystem)->GetFrameStats();
		Log.Row(FString::Printf(TEXT("game %s   region %s   polls %d   changes %d"),
			*Subsystem->GetGame(), *Subsystem->GetRegion(), Subsystem->GetPollCount(),
			Subsystem->GetChangeCount()));
		Log.Row(FString::Printf(TEXT("packs mounted %d   content swaps %d   fallbacks %d"),
			Subsystem->GetMountedPackCount(), Subsystem->GetActivations().Num(),
			Subsystem->GetFallbacks().Num()));
		Log.Row(FString::Printf(TEXT("frames %d   over 16.7 ms %d   over 33 ms %d"),
			Stats.Frames, Stats.Over16, Stats.Over33));
		Log.Row(FString::Printf(TEXT("crypto    %s"), *Subsystem->GetCryptoApi()), DCDim);
	}
	Log.Flush();

	// ---- the graph -----------------------------------------------------------------------
	const float GraphW = W * 0.40f;
	const float GraphH = FMath::Clamp(H * 0.19f, 120.0f, 230.0f);
	DrawGraph(Canvas, Subsystem, Head, Body, Scale,
		(W - GraphW) * 0.5f, H - GraphH - DCMargin, GraphW, GraphH);
}
