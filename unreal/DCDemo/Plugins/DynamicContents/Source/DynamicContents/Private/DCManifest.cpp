#include "DCManifest.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

namespace
{
	/** FJsonObject has no int64 getter; every number in the payload fits a double exactly. */
	int64 NumberAsInt64(const TSharedPtr<FJsonObject>& Object, const FString& Field)
	{
		double Value = 0.0;
		if (Object.IsValid() && Object->TryGetNumberField(Field, Value))
		{
			return static_cast<int64>(Value);
		}
		return 0;
	}

	FString StringOr(const TSharedPtr<FJsonObject>& Object, const FString& Field,
		const FString& Fallback = FString())
	{
		FString Value;
		if (Object.IsValid() && Object->TryGetStringField(Field, Value))
		{
			return Value;
		}
		return Fallback;
	}
}

FLinearColor FDCBrand::ToLinearColour() const
{
	if (!bValid || ColourHex.IsEmpty())
	{
		return FLinearColor::White;
	}

	// The server sends "#RRGGBB" (sRGB, the way a designer picks a colour); the material
	// parameter is linear, and FColor::FromHex + FromSRGBColor is the same curve
	// unreal\Tools\import_content.py applies when it bakes a preview identity.
	FString Hex = ColourHex;
	Hex.RemoveFromStart(TEXT("#"));
	if (Hex.Len() == 6)
	{
		Hex += TEXT("FF");
	}
	return FLinearColor::FromSRGBColor(FColor::FromHex(Hex));
}

FString FDCBrand::Describe() const
{
	return bValid ? FString::Printf(TEXT("%s %s"), *ColourHex, *Emblem) : FString(TEXT("no-brand"));
}

bool FDCManifest::IsValid() const
{
	return !Slot.IsEmpty() && !AllocKey.IsEmpty() && !ClassPath.IsEmpty()
		&& !PackId.IsEmpty() && Files.Num() > 0;
}

int64 FDCManifest::TotalFileBytes() const
{
	int64 Total = 0;
	for (const FDCPackFile& File : Files)
	{
		Total += File.Size;
	}
	return Total;
}

FString FDCManifest::Describe() const
{
	return FString::Printf(TEXT("%s %s %s (%s)"), *Piece, *Version, *Brand.Describe(),
		ShowingKind.IsEmpty() ? TEXT("?") : *ShowingKind);
}

bool FDCManifest::FromJson(const TSharedPtr<FJsonObject>& Payload, FDCManifest& Out, FString& OutError)
{
	if (!Payload.IsValid())
	{
		OutError = TEXT("the signed payload was not a JSON object");
		return false;
	}

	Out = FDCManifest();

	Out.Slot = StringOr(Payload, TEXT("slot"));
	Out.Game = StringOr(Payload, TEXT("game"));
	Out.Region = StringOr(Payload, TEXT("region"));
	Out.AllocKey = StringOr(Payload, TEXT("alloc_key"));
	Payload->TryGetBoolField(TEXT("is_default"), Out.bIsDefault);
	Out.ServerTime = StringOr(Payload, TEXT("server_time"));
	Out.ValidUntil = StringOr(Payload, TEXT("valid_until"));

	const TSharedPtr<FJsonObject>* Content = nullptr;
	if (!Payload->TryGetObjectField(TEXT("content"), Content) || !Content)
	{
		OutError = TEXT("the manifest has no 'content' object");
		return false;
	}
	Out.Piece = StringOr(*Content, TEXT("piece"));
	Out.Version = StringOr(*Content, TEXT("version"));
	Out.SizeClass = StringOr(*Content, TEXT("size_class"));
	Out.ClassPath = StringOr(*Content, TEXT("class_path"));
	Out.StateSchemaVersion = static_cast<int32>(NumberAsInt64(*Content, TEXT("state_schema_version")));
	if (Out.StateSchemaVersion <= 0)
	{
		Out.StateSchemaVersion = 1;
	}
	const TArray<TSharedPtr<FJsonValue>>* Schema = nullptr;
	if ((*Content)->TryGetArrayField(TEXT("state_schema"), Schema) && Schema)
	{
		for (const TSharedPtr<FJsonValue>& Entry : *Schema)
		{
			FString Name;
			if (Entry.IsValid() && Entry->TryGetString(Name))
			{
				Out.StateSchema.Add(Name);
			}
		}
	}

	const TSharedPtr<FJsonObject>* Pack = nullptr;
	if (!Payload->TryGetObjectField(TEXT("pack"), Pack) || !Pack)
	{
		OutError = TEXT("the manifest has no 'pack' object");
		return false;
	}
	Out.PackId = StringOr(*Pack, TEXT("id"));
	Out.PackTotalBytes = NumberAsInt64(*Pack, TEXT("total_bytes"));

	const TArray<TSharedPtr<FJsonValue>>* FileList = nullptr;
	if (!(*Pack)->TryGetArrayField(TEXT("files"), FileList) || !FileList || FileList->Num() == 0)
	{
		OutError = TEXT("the manifest's pack lists no files");
		return false;
	}
	for (const TSharedPtr<FJsonValue>& Entry : *FileList)
	{
		const TSharedPtr<FJsonObject>* Object = nullptr;
		if (!Entry.IsValid() || !Entry->TryGetObject(Object) || !Object)
		{
			continue;
		}
		FDCPackFile File;
		File.Name = StringOr(*Object, TEXT("name"));
		File.Size = NumberAsInt64(*Object, TEXT("size"));
		File.Sha256 = StringOr(*Object, TEXT("sha256"));
		File.Url = StringOr(*Object, TEXT("url"));
		if (File.Name.IsEmpty() || File.Url.IsEmpty() || File.Sha256.IsEmpty())
		{
			OutError = FString::Printf(TEXT("a file entry is incomplete (name='%s')"), *File.Name);
			return false;
		}
		// Never let a name out of the manifest reach outside its own cache folder.
		File.Name = FPaths::GetCleanFilename(File.Name);
		Out.Files.Add(MoveTemp(File));
	}

	const TSharedPtr<FJsonObject>* Brand = nullptr;
	if (Payload->TryGetObjectField(TEXT("brand"), Brand) && Brand && Brand->IsValid())
	{
		Out.Brand.ColourHex = StringOr(*Brand, TEXT("colour"));
		Out.Brand.Emblem = StringOr(*Brand, TEXT("emblem"));
		Out.Brand.bValid = !Out.Brand.ColourHex.IsEmpty();
	}

	const TSharedPtr<FJsonObject>* Showing = nullptr;
	if (Payload->TryGetObjectField(TEXT("showing"), Showing) && Showing)
	{
		Out.ShowingKind = StringOr(*Showing, TEXT("kind"));
		Out.ShowingSource = StringOr(*Showing, TEXT("source"));
		Out.ShowingEndsAt = StringOr(*Showing, TEXT("ends_at"));
		Out.ShowingReason = StringOr(*Showing, TEXT("reason"));
		Out.ShowingLot = StringOr(*Showing, TEXT("lot"));
		double Block = -1.0;
		if ((*Showing)->TryGetNumberField(TEXT("block"), Block))
		{
			Out.ShowingBlock = static_cast<int32>(Block);
		}
	}

	if (!Out.IsValid())
	{
		OutError = FString::Printf(
			TEXT("the manifest is incomplete: slot='%s' key='%s' class='%s' pack='%s' files=%d"),
			*Out.Slot, *Out.AllocKey, *Out.ClassPath, *Out.PackId, Out.Files.Num());
		return false;
	}
	return true;
}
