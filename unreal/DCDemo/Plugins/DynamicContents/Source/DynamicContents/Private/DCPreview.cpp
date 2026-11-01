#include "DCPreview.h"

#include "DynamicContents.h"

#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Framework/Application/SlateApplication.h"
#include "GenericPlatform/GenericApplication.h"
#include "GenericPlatform/GenericWindow.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "Misc/CommandLine.h"
#include "Misc/DateTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonWriter.h"
#include "Widgets/SWindow.h"

#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <Windows.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

const TCHAR* FDCPreviewWindow::DefaultTitle()
{
	// booth/pad_helper.py matches this exactly (PREVIEW_TITLE), so nothing else on the
	// desktop can be moved by the helper.
	return TEXT("DynamicContents region preview");
}

void* FDCPreviewWindow::GetGameWindowHandle()
{
	if (GEngine == nullptr || GEngine->GameViewport == nullptr)
	{
		return nullptr;
	}
	const TSharedPtr<SWindow> Window = GEngine->GameViewport->GetWindow();
	if (!Window.IsValid())
	{
		return nullptr;
	}
	const TSharedPtr<const FGenericWindow> Native = Window->GetNativeWindow();
	return Native.IsValid() ? Native->GetOSWindowHandle() : nullptr;
}

FDCPreviewRect FDCPreviewWindow::ComputeHomeRect(FString& OutHow)
{
	FDCPreviewRect Rect;

	FString Spec;
	if (FParse::Value(FCommandLine::Get(), TEXT("DCPreviewRect="), Spec, false)
		&& !Spec.IsEmpty())
	{
		TArray<FString> Parts;
		Spec.TrimQuotes().ParseIntoArray(Parts, TEXT(","), true);
		if (Parts.Num() == 4)
		{
			Rect.X = FCString::Atoi(*Parts[0]);
			Rect.Y = FCString::Atoi(*Parts[1]);
			Rect.W = FMath::Max(FCString::Atoi(*Parts[2]), 64);
			Rect.H = FMath::Max(FCString::Atoi(*Parts[3]), 64);
			OutHow = TEXT("-DCPreviewRect");
			return Rect;
		}
		DC_LOG(Warning, TEXT("PREVIEW -DCPreviewRect='%s' is not x,y,w,h - ignored"), *Spec);
	}

	FDisplayMetrics Metrics;
	FDisplayMetrics::RebuildDisplayMetrics(Metrics);

	int32 Wanted = 0;
	FParse::Value(FCommandLine::Get(), TEXT("DCPreviewMonitor="), Wanted);

	const FMonitorInfo* Chosen = nullptr;
	if (Wanted >= 1 && Wanted <= Metrics.MonitorInfo.Num())
	{
		Chosen = &Metrics.MonitorInfo[Wanted - 1];
		OutHow = FString::Printf(TEXT("-DCPreviewMonitor=%d"), Wanted);
	}
	else
	{
		// The booth's portal screen is the second monitor, so prefer the right-most monitor
		// that is not the primary one; fall back to the right-most of all of them, which is
		// what a one-monitor PC has.
		for (const FMonitorInfo& Monitor : Metrics.MonitorInfo)
		{
			if (Monitor.bIsPrimary)
			{
				continue;
			}
			if (Chosen == nullptr || Monitor.DisplayRect.Left > Chosen->DisplayRect.Left)
			{
				Chosen = &Monitor;
			}
		}
		if (Chosen != nullptr)
		{
			OutHow = TEXT("the right-most monitor that is not the primary one");
		}
		else
		{
			for (const FMonitorInfo& Monitor : Metrics.MonitorInfo)
			{
				if (Chosen == nullptr || Monitor.DisplayRect.Left > Chosen->DisplayRect.Left)
				{
					Chosen = &Monitor;
				}
			}
			OutHow = TEXT("the only monitor (no second screen on this PC)");
		}
	}

	if (Chosen == nullptr)
	{
		OutHow = TEXT("no monitor was reported - a 1080p default");
		Rect.X = 960;
		Rect.Y = 270;
		return Rect;
	}

	const int32 Left = Chosen->DisplayRect.Left;
	const int32 Top = Chosen->DisplayRect.Top;
	const int32 Width = Chosen->DisplayRect.Right - Chosen->DisplayRect.Left;
	const int32 Height = Chosen->DisplayRect.Bottom - Chosen->DisplayRect.Top;

	// The one rule, also in portal/style.css and booth/pad_helper.py: the right half,
	// vertically centred, half the monitor's width and height.
	Rect.W = Width / 2;
	Rect.H = Height / 2;
	Rect.X = Left + Width - Rect.W;
	Rect.Y = Top + (Height - Rect.H) / 2;
	OutHow += FString::Printf(TEXT(" (%dx%d at %d,%d)"), Width, Height, Left, Top);
	return Rect;
}

#if PLATFORM_WINDOWS

namespace
{
	HWND DCHwnd()
	{
		return static_cast<HWND>(FDCPreviewWindow::GetGameWindowHandle());
	}
}

bool FDCPreviewWindow::HideAtBoot()
{
	HWND Hwnd = DCHwnd();
	if (Hwnd == nullptr)
	{
		return false;
	}
	// Before any of the rest: the booth must never see this window flash up at its home
	// position while the engine is still starting.
	::ShowWindow(Hwnd, SW_HIDE);
	return true;
}

bool FDCPreviewWindow::Apply(const FDCPreviewRect& Home, bool bShown, const FString& Title,
	FString& OutError)
{
	HWND Hwnd = DCHwnd();
	if (Hwnd == nullptr)
	{
		OutError = TEXT("the game has no top-level window yet");
		return false;
	}

	// Borderless. With WS_POPUP the window rectangle *is* the client rectangle, so a
	// 960 x 540 window renders exactly 960 x 540 pixels - no frame to subtract.
	LONG_PTR Style = ::GetWindowLongPtr(Hwnd, GWL_STYLE);
	Style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
		| WS_BORDER | WS_DLGFRAME);
	Style |= WS_POPUP;
	::SetWindowLongPtr(Hwnd, GWL_STYLE, Style);

	LONG_PTR Ex = ::GetWindowLongPtr(Hwnd, GWL_EXSTYLE);
	Ex &= ~(WS_EX_DLGMODALFRAME | WS_EX_CLIENTEDGE | WS_EX_STATICEDGE | WS_EX_WINDOWEDGE);
	::SetWindowLongPtr(Hwnd, GWL_EXSTYLE, Ex);

	if (GEngine != nullptr && GEngine->GameViewport != nullptr)
	{
		const TSharedPtr<SWindow> Window = GEngine->GameViewport->GetWindow();
		if (Window.IsValid())
		{
			Window->SetTitle(FText::FromString(Title));
		}
	}
	// Slate's title and the real one can disagree after a style change, and the pad helper
	// finds the window by its title, so set it on the window itself too.
	::SetWindowTextW(Hwnd, *Title);

	// SWP_FRAMECHANGED is what makes the style change take; the size has to be applied here
	// even when the window is about to be parked, so the back buffer is the right shape.
	::SetWindowPos(Hwnd, HWND_TOPMOST, Home.X, Home.Y, Home.W, Home.H,
		SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW);
	if (!bShown)
	{
		SetShown(Home, false);
	}
	return true;
}

bool FDCPreviewWindow::SetShown(const FDCPreviewRect& Home, bool bShown)
{
	HWND Hwnd = DCHwnd();
	if (Hwnd == nullptr)
	{
		return false;
	}
	if (bShown)
	{
		::SetWindowPos(Hwnd, HWND_TOPMOST, Home.X, Home.Y, Home.W, Home.H,
			SWP_NOACTIVATE | SWP_SHOWWINDOW);
	}
	else
	{
		// Off-screen and not topmost. Still visible as far as Windows is concerned, so the
		// engine keeps drawing it and it is instantly right when it comes back.
		::SetWindowPos(Hwnd, HWND_NOTOPMOST, OffScreenX, OffScreenY, 0, 0,
			SWP_NOACTIVATE | SWP_NOSIZE | SWP_SHOWWINDOW);
	}
	return true;
}

bool FDCPreviewWindow::GetWindowRect(FDCPreviewRect& Out)
{
	HWND Hwnd = DCHwnd();
	if (Hwnd == nullptr)
	{
		return false;
	}
	RECT Box{};
	if (!::GetWindowRect(Hwnd, &Box))
	{
		return false;
	}
	Out.X = Box.left;
	Out.Y = Box.top;
	Out.W = Box.right - Box.left;
	Out.H = Box.bottom - Box.top;
	return true;
}

#else  // !PLATFORM_WINDOWS

bool FDCPreviewWindow::HideAtBoot()
{
	return false;
}

bool FDCPreviewWindow::Apply(const FDCPreviewRect&, bool, const FString&, FString& OutError)
{
	OutError = TEXT("the preview window is only placed on Windows");
	return false;
}

bool FDCPreviewWindow::SetShown(const FDCPreviewRect&, bool)
{
	return false;
}

bool FDCPreviewWindow::GetWindowRect(FDCPreviewRect&)
{
	return false;
}

#endif

bool FDCPreviewWindow::WriteStateFile(const FString& Path, const FString& Title,
	const FDCPreviewRect& Home, bool bShown)
{
	if (Path.IsEmpty())
	{
		return false;
	}
	FDCPreviewRect Now = Home;
	const bool bHaveNow = GetWindowRect(Now);

	FString Text;
	const TSharedRef<TJsonWriter<TCHAR>> W = TJsonWriterFactory<TCHAR>::Create(&Text);
	W->WriteObjectStart();
	W->WriteValue(TEXT("title"), Title);
	W->WriteValue(TEXT("pid"), static_cast<int32>(FPlatformProcess::GetCurrentProcessId()));
	W->WriteValue(TEXT("shown"), bShown);
	W->WriteValue(TEXT("written_utc"), FDateTime::UtcNow().ToIso8601());
	W->WriteObjectStart(TEXT("home"));
	W->WriteValue(TEXT("x"), Home.X);
	W->WriteValue(TEXT("y"), Home.Y);
	W->WriteValue(TEXT("w"), Home.W);
	W->WriteValue(TEXT("h"), Home.H);
	W->WriteObjectEnd();
	if (bHaveNow)
	{
		W->WriteObjectStart(TEXT("now"));
		W->WriteValue(TEXT("x"), Now.X);
		W->WriteValue(TEXT("y"), Now.Y);
		W->WriteValue(TEXT("w"), Now.W);
		W->WriteValue(TEXT("h"), Now.H);
		W->WriteObjectEnd();
	}
	W->WriteObjectEnd();
	W->Close();

	IFileManager::Get().MakeDirectory(*FPaths::GetPath(Path), true);
	return FFileHelper::SaveStringToFile(Text, *Path,
		FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}
