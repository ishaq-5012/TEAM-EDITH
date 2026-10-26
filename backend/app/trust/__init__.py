"""Trust and authentication checks.

Four separate questions, never merged into one verdict:

- file integrity: is the stored file byte-for-byte the one that was uploaded? (SHA-256)
- signature integrity: do the bytes covered by an embedded PDF signature still match it, and is the
  cryptographic signature valid? (pyHanko)
- certificate trust: does the signer's certificate chain to a trust anchor configured by this deployment, and
  was it revoked or outside its validity period? (pyhanko-certvalidator)
- external-source verification: does an approved issuer or registry integration confirm the document's details?

Each check reports one of: verified, failed, unsupported, inconclusive — together with the method used, the
evidence, what it establishes, and what it does *not* establish.
"""
