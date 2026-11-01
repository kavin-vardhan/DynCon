// The two checks the game does before it mounts anything, both with the engine's own crypto.
//
// Which API, exactly (this is the question specs\unreal_spec_v1.md §3 left open):
//
//   * `IPlatformCrypto::Get().CreateContext()` -> `FEncryptionContext`, which on Win64 is
//     `FEncryptionContextOpenSSL` (Engine\Plugins\Experimental\PlatformCrypto, OpenSSL
//     underneath). That plugin is EnabledByDefault and is the modular feature the engine's
//     own `FRSA` facade - the one pak signing uses - is built on.
//   * public key:  `FEncryptionContext::GetPublicKey_RSA(pem)`  (PEM_read_bio_RSA_PUBKEY, so
//     the server's "-----BEGIN PUBLIC KEY-----" SubjectPublicKeyInfo is read as-is; no
//     base64 or DER walking of our own).
//   * digest:      `FEncryptionContext::CalcSHA256` / `FSHA256Hasher` (Init/Update/Finalize)
//   * signature:   `FEncryptionContext::DigestVerify_RS256(digest, signature, key)`
//                  (RSA_verify with NID_sha256 - PKCS#1 v1.5 + SHA-256, i.e. RS256).
//
// Note that DigestVerify_RS256 takes the **digest**, not the message: the 32 bytes of
// SHA-256 over the payload. Hence the two-step VerifyRs256 below.

#pragma once

#include "CoreMinimal.h"

/** RS256 manifest verification and SHA-256 file hashing. */
class DYNAMICCONTENTS_API FDCCrypto
{
public:
	/**
	 * Is the platform crypto plugin there? Checked once at startup and logged, because
	 * without it a Shipping build would otherwise discover the problem the hard way at the
	 * first resolve. OutDetail is a sentence either way.
	 */
	static bool IsAvailable(FString& OutDetail);

	/** The exact API chain, for the log and the report. */
	static const TCHAR* ApiName();

	/**
	 * RS256 over the exact bytes of the signed payload.
	 *
	 * @param PublicKeyPem    public_key_pem from GET /client-config
	 * @param Payload         the UTF-8 bytes of the signed_payload string, unmodified
	 * @param SignatureBase64 the envelope's "signature"
	 */
	static bool VerifyRs256(const FString& PublicKeyPem, const TArray<uint8>& Payload,
		const FString& SignatureBase64, FString& OutError);

	/** Lower-case hex SHA-256 of a file, read a megabyte at a time. */
	static bool Sha256OfFile(const FString& Path, FString& OutHex, FString& OutError);

	/** Lower-case hex SHA-256 of a buffer. Empty on failure. */
	static FString Sha256Hex(TArrayView<const uint8> Data);

	/** How much of a file is read per Update() call when hashing. */
	static constexpr int32 HashBlockBytes = 1 << 20;
};
