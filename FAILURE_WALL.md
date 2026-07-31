# Seeker Failure Wall

Every investigation that broke or got something wrong, published in full. The inverse of a marketing page: here is where Seeker failed, how it caught it, and how it corrected. Failures are teaching documents.

---

## 2026-07-02T23:08:19.894957+00:00 — RECOVERED

**Question:** Does INT8 quantization degrade LLM output quality?
**Path followed:** Seeker fetch -> ingest finding -> Adversarial consensus check -> credibility penalty + node retraction
**Where it failed:** Ingestion accepted a low-quality source's claim that contradicts the corroborated map before it was challenged.

**Reasoning trail:**
1. Seeker fetched https://fast-ai-hacks.example/quantization-myth and ingested the claim as a finding (node find_45b89f35b921) without challenging it against the map. This is the failure: an unvetted claim entered the Memory Map.
2. Adversarial consensus check: contradicts multi-source consensus (consensus_size=5). The claim contradicts multiple independent sources already on the map that agree INT8 quantization causes negligible quality loss.
3. Recovery: source fast-ai-hacks.example credibility 0.5 -> 0.45; poisoned node find_45b89f35b921 retracted from the map. Verification came from OUTSIDE — the corroborated consensus of independent sources, not the model judging itself.

**Correction:** Poisoned finding retracted; source credibility lowered so the Adversarial pre-flight distrusts it next time. Map restored to the consensus position.

---

