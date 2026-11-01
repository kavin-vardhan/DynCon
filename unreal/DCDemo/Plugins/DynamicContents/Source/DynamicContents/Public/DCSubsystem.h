// The client half of the invention: the thing that asks a backend what belongs in a slot and
// puts it there while the game is running.
//
// One UDCSubsystem per game instance. It owns
//
//   * the backend address and the region (command line, `-DCBackend=` / `-DCRegion=`);
//   * GET /client-config once, for the poll interval and the RS256 **public key**;
//   * GET /changes on a loop - a slot whose alloc_key changed is the only slot that needs
//     resolving, so a quiet booth makes one small request every 1.5 s and nothing else;
//   * GET /resolve, and the signature check over the exact bytes the server signed;
//   * the downloads (every file fetched as byte ranges, so resuming is the normal path),
//     the SHA-256 of each file, the LRU pack cache and the mounting;
//   * telemetry batching (mount, view).
//
// It does not own the slot lifecycle - ADCSlot does. This class decides *when* a slot has to
// change and does the I/O; the slot decides what is on screen and when it is safe to swap.
//
// Nothing here starts by itself: ADCRuntimeGameMode calls Start(). That is what keeps the
// brief-006 pack round-trip run (ADCSpikeGameMode, which has no backend) exactly as it was.

#pragma once

#include "CoreMinimal.h"
#include "Containers/Ticker.h"
#include "DCManifest.h"
#include "DCPackCache.h"
#include "Interfaces/IHttpRequest.h"
#include "Subsystems/GameInstanceSubsystem.h"

#include "DCSubsystem.generated.h"

class ADCSlot;
class UTexture2D;
enum class EDCSlotState : uint8;

/**
 * Frame times, as the status file and the preview soak test read them.
 *
 * The counters are cumulative since the run's four-second mark, which is what lets a script
 * difference two readings and get the average over any window it likes - "while the preview
 * window was on screen", for instance. The percentiles are over the whole run.
 */
struct FDCFrameStats
{
	int32 Frames = 0;
	double SumMs = 0.0;
	float WorstMs = 0.0f;
	int32 Over16 = 0;
	int32 Over25 = 0;
	int32 Over33 = 0;
	float AverageMs = 0.0f;
	float MedianMs = 0.0f;
	float Worst1PercentMs = 0.0f;
};

/**
 * One step of one slot's lifecycle, with what it cost. The X-ray's lifecycle log.
 *
 * It is a ring of the last few, not a history: the point on screen is "watch a swap happen
 * and see where the milliseconds went", and a booth day is eight hours long.
 */
struct FDCLifecycleNote
{
	/** FPlatformTime::Seconds() when it happened - the graph lines the marks up on this. */
	double Seconds = 0.0;
	FString SlotId;

	/** resolve · download · verify · mount · spawn · unload · fallback */
	FString Phase;
	float Ms = 0.0f;
	FString Note;
};

/** One sample of the rolling frame-time graph. */
struct FDCFrameSample
{
	double Seconds = 0.0;
	float Ms = 0.0f;
};

/** A tick on that graph: a mount, a spawn or an unload, so a swap is visible on it. */
struct FDCFrameMark
{
	double Seconds = 0.0;
	FString Phase;
	FString SlotId;
};

/** One queued telemetry event. Batched: the booth never needs a request per event. */
struct FDCTelemetryEvent
{
	FString Type;
	FString SlotId;
	FString AllocKey;
	double Value = 1.0;
	FString TimestampUtc;
};

/** Everything in flight for one slot. One job at a time per slot. */
struct FDCSlotJob
{
	TWeakObjectPtr<ADCSlot> Slot;
	FString SlotId;

	/** The key that started this job. If /changes moves on, the job is stale. */
	FString AllocKey;

	FDCManifest Manifest;
	FString CacheDir;

	/** Which file of the pack, and how much of it is already on disk. */
	int32 FileIndex = 0;
	int64 FileHave = 0;

	double StartedSeconds = 0.0;
	double ResolveMs = 0.0;
	double DownloadMs = 0.0;
	double VerifyMs = 0.0;
	double MountMs = 0.0;
	double LoadMs = 0.0;
	double DownloadStartSeconds = 0.0;

	int64 NetworkBytes = 0;
	int32 CachedFiles = 0;
	int32 RangeRequests = 0;
	int32 Resumes = 0;

	FHttpRequestPtr InFlight;
	bool bCancelled = false;
};

UCLASS()
class DYNAMICCONTENTS_API UDCSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	/** The subsystem for whatever world this object is in, or nullptr. */
	static UDCSubsystem* Get(const UObject* WorldContext);

	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** Reads the command line, checks the crypto, and starts polling. Safe to call twice. */
	void Start();
	bool IsStarted() const { return bStarted; }

	// ---------------------------------------------------------------- slots

	void RegisterSlot(ADCSlot* Slot);
	void UnregisterSlot(ADCSlot* Slot);
	TArray<ADCSlot*> GetSlots() const;

	// ---------------------------------------------------------------- what the UI reads

	const FString& GetBackendUrl() const { return BackendUrl; }
	const FString& GetRegion() const { return Region; }
	const FString& GetGame() const { return Game; }

	/**
	 * The Player switched game (brief 018). Every slot of the old map is gone or about to
	 * be, so this only has to point the poll at the other game before the new map's slots
	 * register - otherwise the first `GET /changes` of the new world asks about the old
	 * game's slots and nothing matches.
	 */
	void SetGame(const FString& NewGame, const FString& Why);

	/** The cache, for the X-ray's list of what is on disk. */
	const FDCPackCache& GetCache() const { return Cache; }
	bool IsPackMounted(const FString& PackId) const { return MountedPackIds.Contains(PackId); }

	/** Where the eye is: the Player's pawn when there is one, else the camera. What the
	 *  X-ray measures the pre-fetch rings from. */
	bool GetViewerLocation(FVector& Out) const;

	/**
	 * Is there a **Player** here, as plan v6 §9 means the word?
	 *
	 * False in the region preview window and false in the attract loop, where the camera
	 * stands in front of a piece of content for a quarter of a minute at a time and would
	 * otherwise post a `view` nobody saw. It is asked before a view is counted as well as
	 * inside QueueTelemetry, because a slot that queued a view and had it dropped would
	 * still have marked it reported and never post the real one.
	 */
	bool IsPlayerPresent() const;

	/**
	 * This copy is the region preview window (`-DCPreview`): no input, no audio, no
	 * telemetry, and it auto-pilots its camera to whatever slot the server says the visitor
	 * has just been bidding on.
	 */
	bool IsPreview() const { return bPreview; }

	/** How the region is named, for the preview window's bilingual caption. Both come from
	 *  GET /preview/region, so the booth's labels live in the server's config and not in two
	 *  string tables (`server/config/demo.json`, and `portal/strings.js` for the portal). */
	const FString& GetRegionLabel() const { return RegionLabel; }
	const FString& GetRegionLabelJp() const { return RegionLabelJp; }

	/** The slot the preview window should be looking at, and why the server picked it. */
	const FString& GetFocusGame() const { return FocusGame; }
	const FString& GetFocusSlot() const { return FocusSlot; }
	const FString& GetFocusReason() const { return FocusReason; }

	/** "ok", "waiting for the backend", or the last sentence that went wrong. */
	const FString& GetBackendStatus() const { return BackendStatus; }

	double GetUptimeSeconds() const;

	/** Both of these are the point of the status strip, and both are always zero. */
	int32 GetRestartCount() const { return 0; }
	int32 GetLoadingScreenCount() const { return 0; }

	static const TCHAR* GetBuildConfigName();

	const FString& GetCryptoApi() const { return CryptoApi; }
	bool IsCryptoAvailable() const { return bCryptoOk; }

	float GetRetryBaseSeconds() const { return RetryBaseSeconds; }
	float GetRetryMaxSeconds() const { return RetryMaxSeconds; }
	int32 GetMountedPackCount() const { return MountedPaks.Num(); }
	float GetPollIntervalSeconds() const { return PollIntervalSeconds; }
	int32 GetPollCount() const { return PollCount; }
	int32 GetChangeCount() const { return ChangeCount; }

	/** The lines ADCStatusHud draws. */
	TArray<FString> GetStatusLines() const;

	// ---------------------------------------------------------------- services for the slot

	/** The base game owns the eight emblems; a brand picks one by name. */
	UTexture2D* GetEmblemTexture(const FString& Emblem);

	/**
	 * The base game also owns the screen images a piece cycles through (art/samples/screens,
	 * imported to /Game/DCCore/Screens/T_DC_Screen_<n>). 1-based; nullptr when the set is not
	 * in this build, which simply leaves a pack's own default image on the screen.
	 */
	UTexture2D* GetScreenImage(int32 Index);

	/** How many there are. 0 in a build without the set. */
	int32 GetScreenImageCount();

	void QueueTelemetry(const FString& Type, const FString& SlotId, const FString& AllocKey,
		double Value);

	/**
	 * One frame's time, for the status file and the soak test. Fed by the game mode, so
	 * there is one sampling rule rather than two: frames within half a second of a
	 * screenshot are left out, and so are the first four seconds of the run.
	 */
	void NoteFrame(float Ms);
	FDCFrameStats GetFrameStats();

	/**
	 * One step of a slot's lifecycle, for the X-ray's log and for the tick on its graph.
	 *
	 * The numbers are the same ones the activation record already carries; this is where
	 * they are kept in the order they happened, which is what somebody watching a swap
	 * wants to read.
	 */
	void NoteLifecycle(const FString& SlotId, const TCHAR* Phase, float Ms, const FString& Note);
	const TArray<FDCLifecycleNote>& GetLifecycle() const { return Lifecycle; }

	/** The rolling ~10 s of frame times and the marks on it, newest last. */
	const TArray<FDCFrameSample>& GetFrameGraph() const { return Graph; }
	const TArray<FDCFrameMark>& GetFrameMarks() const { return GraphMarks; }

	/** How many seconds of samples the graph keeps. */
	static float GetFrameGraphSeconds();

	// ---------------------------------------------------------------- hooks for the game mode

	DECLARE_MULTICAST_DELEGATE_TwoParams(FDCSlotActiveSignature, ADCSlot*, const FDCManifest&);
	DECLARE_MULTICAST_DELEGATE_TwoParams(FDCSlotFallbackSignature, ADCSlot*, const FString&);

	/** A slot just put something new on screen. */
	FDCSlotActiveSignature OnSlotActive;

	/** A slot kept what it had and will try again. */
	FDCSlotFallbackSignature OnSlotFallback;

	/** The game mode says which screenshot belongs to which activation. */
	void NoteShot(int32 ActivationSeq, const FString& ShotFile);

	/** The sequence number of the activation that has just been broadcast. */
	int32 GetLastActivationSeq() const { return Activations.Num() > 0 ? Activations.Last().Seq : 0; }

	/** -DCStatusFile=<path>: a JSON file a test script can watch. Empty = off. */
	const FString& GetStatusFilePath() const { return StatusFilePath; }
	void WriteStatusFile();

	/** Everything that has happened, newest last - also what goes into the status file. */
	struct FActivation
	{
		int32 Seq = 0;
		FString SlotId;
		FString Piece;
		FString Version;
		FString AllocKey;
		FString BrandColour;
		FString BrandEmblem;
		FString Kind;
		FString Source;
		FString PackId;
		FString VisibleUtc;
		FString Shot;
		double ResolveMs = 0.0;
		double DownloadMs = 0.0;
		double VerifyMs = 0.0;
		double MountMs = 0.0;
		double LoadMs = 0.0;
		double SpawnMs = 0.0;
		double TotalMs = 0.0;
		int64 NetworkBytes = 0;
		int32 CachedFiles = 0;
		int32 RangeRequests = 0;
	};
	const TArray<FActivation>& GetActivations() const { return Activations; }

	struct FFallbackNote
	{
		int32 Seq = 0;
		FString SlotId;
		FString Reason;
		FString Utc;
	};
	const TArray<FFallbackNote>& GetFallbacks() const { return Fallbacks; }

private:
	// ---- plumbing
	bool Tick(float DeltaSeconds);
	void ParseCommandLine();
	FHttpRequestRef MakeRequest(const FString& PathOrUrl, const FString& Verb) const;

	/** A manifest's file links are relative ("/files/…"); this makes them absolute. */
	FString AbsoluteUrl(const FString& PathOrUrl) const;
	void SetBackendStatus(const FString& Status);

	// ---- the loop
	void FetchClientConfig();
	void OnClientConfig(FHttpResponsePtr Response, bool bOk);
	void Poll();
	void OnChanges(FHttpResponsePtr Response, bool bOk);

	/** The live flip of plan v6 §11, carried on /changes. Ignored by the preview copy. */
	void ApplyLiveFlip(const TSharedPtr<class FJsonObject>& Changes);
	void PollPreviewRegion();
	void OnPreviewRegion(FHttpResponsePtr Response, bool bOk);
	void SetRegion(const FString& NewRegion, const FString& Why);

	// ---- one slot's pipeline
	void StartJob(ADCSlot* Slot, const FString& AllocKey);
	void StartResolve(TSharedPtr<FDCSlotJob> Job);
	void OnResolved(TSharedPtr<FDCSlotJob> Job, FHttpResponsePtr Response, bool bOk);
	void StartDownloads(TSharedPtr<FDCSlotJob> Job);
	void NextFile(TSharedPtr<FDCSlotJob> Job);
	void RequestRange(TSharedPtr<FDCSlotJob> Job);
	void OnRange(TSharedPtr<FDCSlotJob> Job, FHttpResponsePtr Response, bool bOk);
	void VerifyPack(TSharedPtr<FDCSlotJob> Job);
	void MountAndSpawn(TSharedPtr<FDCSlotJob> Job);
	void FailJob(TSharedPtr<FDCSlotJob> Job, const FString& Reason);
	void FinishJob(const FString& SlotId);
	bool IsJobStale(const TSharedPtr<FDCSlotJob>& Job) const;

	// ---- mounting
	bool EnsurePackMounted(const FString& PackDir, double& OutMountMs, FString& OutError);

	// ---- telemetry
	void FlushTelemetry(bool bForce);

	static FString PartPathFor(const FString& FinalPath) { return FinalPath + TEXT(".part"); }

	// ---- configuration
	FString BackendUrl = TEXT("http://127.0.0.1:8700");
	FString Region = TEXT("r1");
	FString Game = TEXT("A");
	FString StatusFilePath;
	bool bFollowPreviewRegion = false;
	bool bPreview = false;
	bool bNoLiveFlip = false;

	/** While a live flip is on, the region this copy goes back to when it ends. */
	FString FlipBackTo;
	int32 RangeBytes = 256 * 1024;
	float RetryBaseSeconds = 2.0f;
	float RetryMaxSeconds = 15.0f;
	float PollIntervalSeconds = 1.5f;
	float TelemetryFlushSeconds = 2.0f;
	int32 TelemetryBatchSize = 16;

	// ---- state
	bool bStarted = false;
	bool bCryptoOk = false;
	FString CryptoApi;
	FString PublicKeyPem;
	FString BackendStatus = TEXT("not started");
	double StartSeconds = 0.0;
	double LastPollSeconds = 0.0;
	double LastTelemetrySeconds = 0.0;
	double LastStatusSeconds = 0.0;
	bool bPollInFlight = false;
	bool bPreviewRegionInFlight = false;
	bool bConfigInFlight = false;
	double NextConfigAttemptSeconds = 0.0;
	int32 ConfigAttempts = 0;
	int32 PollCount = 0;
	int32 ChangeCount = 0;
	int32 ResetGeneration = -1;

	TArray<TWeakObjectPtr<ADCSlot>> Slots;
	TMap<FString, TSharedPtr<FDCSlotJob>> Jobs;
	TSet<FString> MountedPaks;
	TSet<FString> MountedPackIds;

	FString RegionLabel;
	FString RegionLabelJp;
	FString FocusGame;
	FString FocusSlot;
	FString FocusReason;

	TArray<FDCTelemetryEvent> Telemetry;
	bool bTelemetryInFlight = false;
	int32 TelemetrySent = 0;
	int32 TelemetryDropped = 0;

	/** Every sampled frame, for the percentiles. Capped: ten minutes at 90 fps is 54,000. */
	TArray<float> FrameSamples;
	FDCFrameStats Frames;
	double LastPercentileSeconds = 0.0;
	int32 PercentileFrames = 0;

	/**
	 * The last ten seconds of them, with a timestamp, for the X-ray's graph; and the mounts,
	 * spawns and unloads that happened inside that window.
	 *
	 * Appended to on every frame and trimmed from the front, so drawing it costs no sorting
	 * and no allocation - the graph is there to show that a swap does not cost frame time,
	 * and a graph that cost frame time would be a liar.
	 */
	TArray<FDCFrameSample> Graph;
	TArray<FDCFrameMark> GraphMarks;
	TArray<FDCLifecycleNote> Lifecycle;

	TArray<FActivation> Activations;
	TArray<FFallbackNote> Fallbacks;
	int32 EventSeq = 0;

	UPROPERTY(Transient)
	TMap<FString, TObjectPtr<UTexture2D>> Emblems;

	UPROPERTY(Transient)
	TArray<TObjectPtr<UTexture2D>> ScreenImages;

	bool bScreenImagesLoaded = false;

	FDCPackCache Cache;

	FTSTicker::FDelegateHandle TickerHandle;
};
