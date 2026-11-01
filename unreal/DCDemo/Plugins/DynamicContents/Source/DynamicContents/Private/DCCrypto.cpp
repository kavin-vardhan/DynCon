#include "DCCrypto.h"

#include "DynamicContents.h"

#include "HAL/FileManager.h"
#include "Misc/Base64.h"
#include "Serialization/Archive.h"

#include "IPlatformCrypto.h"
#include "PlatformCryptoTypes.h"

namespace
{
	/**
	 * One context per call. Creating one is cheap (it holds no state of its own - the OpenSSL
	 * handles are per-operation), and it keeps the lifetime question out of the subsystem.
	 */
	TUniquePtr<FEncryptionContext> MakeContext()
	{
		return IPlatformCrypto::Get().CreateContext();
	}

	FString ToHex(const TArray<uint8>& Bytes)
	{
		FString Out;
		Out.Reserve(Bytes.Num() * 2);
		for (uint8 Byte : Bytes)
		{
			Out += FString::Printf(TEXT("%02x"), Byte);
		}
		return Out;
	}
}

const TCHAR* FDCCrypto::ApiName()
{
	return TEXT("IPlatformCrypto::CreateContext -> FEncryptionContext"
		"{GetPublicKey_RSA, CalcSHA256, DigestVerify_RS256}  (PlatformCrypto / OpenSSL)");
}

bool FDCCrypto::IsAvailable(FString& OutDetail)
{
	TUniquePtr<FEncryptionContext> Context = MakeContext();
	if (!Context.IsValid())
	{
		OutDetail = TEXT("IPlatformCrypto::CreateContext returned nothing - is the "
			"PlatformCrypto plugin enabled?");
		return false;
	}

	// A self-test with a known answer, so "the crypto is there" is not a guess: the SHA-256
	// of the three bytes "abc" is the first vector in FIPS 180-4.
	static const uint8 Abc[3] = { 'a', 'b', 'c' };
	const FString Digest = Sha256Hex(MakeArrayView(Abc, 3));
	const FString Expected = TEXT("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
	if (Digest != Expected)
	{
		OutDetail = FString::Printf(TEXT("SHA-256 self-test failed: got '%s'"), *Digest);
		return false;
	}

	OutDetail = FString::Printf(TEXT("%s; SHA-256 self-test ok"), ApiName());
	return true;
}

FString FDCCrypto::Sha256Hex(TArrayView<const uint8> Data)
{
	TUniquePtr<FEncryptionContext> Context = MakeContext();
	if (!Context.IsValid())
	{
		return FString();
	}
	TArray<uint8> Hash;
	if (!Context->CalcSHA256(Data, Hash))
	{
		return FString();
	}
	return ToHex(Hash);
}

bool FDCCrypto::VerifyRs256(const FString& PublicKeyPem, const TArray<uint8>& Payload,
	const FString& SignatureBase64, FString& OutError)
{
	if (PublicKeyPem.IsEmpty())
	{
		OutError = TEXT("no public key yet (GET /client-config has not answered)");
		return false;
	}
	if (Payload.Num() == 0)
	{
		OutError = TEXT("the signed payload was empty");
		return false;
	}

	TArray<uint8> Signature;
	if (!FBase64::Decode(SignatureBase64, Signature) || Signature.Num() == 0)
	{
		OutError = TEXT("the signature was not valid base64");
		return false;
	}

	TUniquePtr<FEncryptionContext> Context = MakeContext();
	if (!Context.IsValid())
	{
		OutError = TEXT("no platform crypto context");
		return false;
	}

	const FRSAKeyHandle Key = Context->GetPublicKey_RSA(PublicKeyPem);
	if (Key == nullptr)
	{
		OutError = TEXT("the public key PEM would not parse");
		return false;
	}

	// RS256 = RSASSA-PKCS1-v1_5 over SHA-256, and DigestVerify_RS256 wants the digest.
	TArray<uint8> Digest;
	bool bOk = Context->CalcSHA256(Payload, Digest);
	if (!bOk)
	{
		OutError = TEXT("SHA-256 of the payload failed");
	}
	else
	{
		bOk = Context->DigestVerify_RS256(Digest, Signature, Key);
		if (!bOk)
		{
			OutError = FString::Printf(
				TEXT("RS256 did not verify (%d payload bytes, %d signature bytes, key %d bytes)"),
				Payload.Num(), Signature.Num(), Context->GetKeySize_RSA(Key));
		}
	}

	Context->DestroyKey_RSA(Key);
	return bOk;
}

bool FDCCrypto::Sha256OfFile(const FString& Path, FString& OutHex, FString& OutError)
{
	TUniquePtr<FArchive> Reader(IFileManager::Get().CreateFileReader(*Path));
	if (!Reader.IsValid())
	{
		OutError = FString::Printf(TEXT("cannot read %s"), *FPaths::GetCleanFilename(Path));
		return false;
	}

	TUniquePtr<FEncryptionContext> Context = MakeContext();
	if (!Context.IsValid())
	{
		OutError = TEXT("no platform crypto context");
		return false;
	}

	FSHA256Hasher Hasher = Context->CreateSHA256Hasher();
	if (Hasher.Init() != EPlatformCryptoResult::Success)
	{
		OutError = TEXT("could not start a SHA-256 hasher");
		return false;
	}

	int64 Left = Reader->TotalSize();
	TArray<uint8> Block;
	Block.SetNumUninitialized(FMath::Min<int64>(Left > 0 ? Left : 1, HashBlockBytes));
	while (Left > 0)
	{
		const int32 Want = static_cast<int32>(FMath::Min<int64>(Left, Block.Num()));
		Reader->Serialize(Block.GetData(), Want);
		if (Hasher.Update(MakeArrayView(Block.GetData(), Want)) != EPlatformCryptoResult::Success)
		{
			OutError = TEXT("SHA-256 update failed");
			return false;
		}
		Left -= Want;
	}
	Reader->Close();

	TArray<uint8> Hash;
	Hash.SetNumUninitialized(FSHA256Hasher::OutputByteLength);
	if (Hasher.Finalize(Hash) != EPlatformCryptoResult::Success)
	{
		OutError = TEXT("SHA-256 finalize failed");
		return false;
	}

	OutHex = ToHex(Hash);
	return true;
}
