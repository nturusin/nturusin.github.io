At ANNA, our transaction classifier returns a JSON object with a category, a confidence score, two explanations and a citation. The category and confidence, the only fields the application acts on, fit in roughly the first thirty output tokens. The remaining couple of hundred tokens are prose written for people who may read it later, or never. Until recently we still waited for the closing brace before doing anything.

When we reordered the schema so the decision fields come first, and committed them as soon as they were provably complete, median time-to-act on our production path fell from 2.03 to 0.99 seconds. The explanation still arrives; it just no longer blocks anything. This article describes how we did it, what "provably complete" means for a half-received JSON document, and what we had to handle once the request path and the response lifetime came apart.

## How the response got slow

The classifier started with one job: look at a bank transaction and return a category. Coffee in, `04_meals` out. The response was a few tokens and felt instant.

Then the requirements grew, each for a good reason. The app needed to explain a category to the customer, so we added a customer-facing explanation. Our accountants wanted a technical explanation and a pointer to the relevant guidance for reviewing odd cases, so we added an internal explanation and a citation. Finally we added a confidence score to route uncertain transactions to a review queue.

Each field had a real consumer, but not the same deadline. The category and confidence are needed right away; the explanations are read later, on another screen or during an investigation. Because each field was appended as it was requested, confidence ended up last, and the moment the application could act moved to the end of the response.

![Four cumulative bars, one per version of the schema. In v1 the whole response is a single purple category field, and the earliest safe commit sits just after it. v2 appends a grey customer explanation; v3 appends a grey internal explanation and citation. Through all three versions the commit marker stays at the left, just after category. In v4 a second purple field, confidence, is appended at the very end, and the commit marker jumps to the far right, past the entire essay.](figures/fig1.png)

*Figure 1 — How product requests moved the commit point. The field order followed the order of requests, not the order of urgency. Image by the author.*

A typical response, lightly redacted:

```json
{
  "category": "09_general_purchase",
  "confidence": 75,
  "customer_friendly_explanation": "This purchase has been categorised as a general business purchase. If it was for stock, office equipment, or personal use, you can update the category.",
  "internal_explanation": "The description denotes a payment to a general online marketplace. No invoice or line-item detail is attached and the amount is small, so the safest default for an ambiguous generic merchant is a general business purchase.",
  "citation": "Internal bookkeeping guidance, general business purchase."
}
```

I'll call the first two fields the *verdict* and the rest the *essay*. The obvious fixes were unattractive. Splitting the work into two model calls would double per-call overhead and rate-limit usage, and the second call could explain a different verdict from the one already committed. Shortening the essay meant taking features away from accountants. What we changed instead was how we read the response we already had.

## What already exists

Streaming structured output is not new. [Instructor](https://python.useinstructor.com/concepts/partial/) yields partially filled Pydantic models as tokens arrive, the [Vercel AI SDK](https://ai-sdk.dev/v5/cookbook/node/stream-object) exposes a `partialObjectStream`, and libraries such as [partial-json](https://www.npmjs.com/package/partial-json) parse incomplete JSON directly. These tools are built mainly for rendering: show the user something as early as possible.

Rendering and acting are different problems. A partial object tells you a field has *appeared*, not that its value is *final*, and showing a half-finished value for a moment is fine while writing it to a database is not. The rest of this article is about that gap: deciding when a streamed field is safe to act on, and what has to happen after you act on it.

## Field order is part of the latency budget

When a provider enforces a JSON schema during decoding, the field order in the schema is also the order in which values are generated. The last verdict field therefore sets the earliest point at which the application can act. Our fix started with a one-line change in the schema: move `confidence` up next to `category`.

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "category":   { "type": "string", "enum": ["01_income_employment", "...", "08_personal"] },
    "confidence": { "type": "number", "minimum": 0, "maximum": 100 },
    "customer_friendly_explanation": { "type": "string" },
    "internal_explanation": { "type": "string" },
    "citation": { "type": "string" }
  }
}
```

How the order is expressed differs by provider: some have an explicit ordering property, others follow the order of `properties`. Strict modes usually also require every property to be listed in `required` and reject `additionalProperties`. Whatever the API, check that the order survives on the exact model and endpoint you run in production, because this is the assumption everything else rests on. Also make every field `required`: in our tests, when only the verdict was required and `confidence` came last, Gemini skipped the explanations entirely and wrote `confidence` straight after `category`.

![Two token bars of equal length. In schema A the fields sit in the order they were added: a small indigo category segment first, striped essay in the middle, a small indigo confidence segment last, and the commit flag points at the closing brace. In schema B both verdict fields sit first and the commit flag points at token 30.](figures/fig2.png)

*Figure 2 — Same fields and tokens; only the commit point moves. Image by the author.*

Nothing is generated faster. The tokens the application needs simply arrive earlier.

Moving a field ahead of the text that explains it can, in principle, change what the model outputs, since an autoregressive model conditions each token on everything before it. We checked this separately; see the measurements below.

## When is a streamed value final?

A stream arrives as a sequence of chunks, and their boundaries are arbitrary: a chunk can end inside a string, after the first digit of a number, or just before the comma that closes a value. So the parser always works on the accumulated buffer, never on an individual chunk.

The hard part is knowing when a value can no longer change. Suppose the buffer currently holds:

```json
{
  "category": "04_meals",
  "confidence": 8
```

A partial parser will happily report `confidence = 8`, but the next chunk might be `7,`, and the real value is 87. A number is final only once it is followed by a terminator (a comma, a closing brace or whitespace); a string is final only after its closing quote.

We wanted the early path to be conservative. Missing an early verdict is fine, since the system can wait for the full response or fall back to a deterministic categorizer. Acting on a misparsed verdict is not. Before committing, the parser therefore requires three things:

1. **The value is complete.** A closing quote for `category`, a terminator after `confidence`.
2. **The value is in the allowed set.** We check `category` against the same enum used in the schema, even though constrained decoding should already guarantee it. This also covers prefix ambiguity: if both `04_meals` and `04_meals_entertainment` exist, seeing `04_meals` proves nothing until the closing quote arrives.
3. **The order is intact.** If an essay field appears before the verdict is complete, the provider has broken the ordering contract. We don't try to recover; we abandon the early path and let the normal pipeline handle the request.

![Three buffers with their structural evidence and outcome. A complete verdict with its terminator commits. A number without a terminator waits. An essay field arriving before the verdict aborts.](figures/fig3.png)

*Figure 3 — Commit, wait, abort. The middle buffer waits because the next chunk may turn 8 into 87. Image by the author.*

The core of the parser:

```python
DECISION_RE = re.compile(
    r'"category"\s*:\s*"(?P<category>[A-Za-z0-9_]+)"\s*,\s*'
    r'"confidence"\s*:\s*(?P<confidence>\d+(?:\.\d+)?)'
    r'\s*[,}\s]'   # check 1: terminator required
)

class DecisionParser:
    def __init__(self) -> None:
        self.buffer = ""

    def feed(self, chunk: str) -> Optional[Decision]:
        self.buffer += chunk
        match = DECISION_RE.search(self.buffer)
        if match:
            category = match.group("category")
            if category not in CATEGORY_ENUM:          # check 2: membership
                raise AbortEarlyCommit(category)
            confidence = float(match.group("confidence"))
            if not 0 <= confidence <= 100:
                raise AbortEarlyCommit(confidence)
            return Decision(category, confidence)
        # order check only after the match attempt: one chunk may hold
        # the end of the verdict and the start of the essay
        if any(m in self.buffer for m in ESSAY_MARKERS):  # check 3: order
            raise AbortEarlyCommit("essay before verdict")
        return None
```

The order of the checks inside `feed` matters. A single chunk can contain both the end of `confidence` and the start of the first explanation, so checking for essay fields first would reject a valid stream. The full listing and tests are in [github.com/nturusin/llm-streaming-early-commit](https://github.com/nturusin/llm-streaming-early-commit); it uses only the standard library.

## After the commit

In our app, a deterministic categorizer shows a provisional category immediately. At a median of about one second the model's verdict replaces it, while the response keeps streaming for roughly another second.

The open stream is handed to a bounded background worker, which drains the remaining chunks, assembles and validates the complete JSON, checks that the final verdict matches the one already committed, and stores the explanations. The guarantee comes from the structural checks above; the worker is a second line of defence that would surface a mismatch if a provider update ever broke the ordering. If the stream fails during the drain, the verdict stands and the explanation slot stays empty.

There is one race that has nothing to do with JSON. While the essay is still streaming, a person can change the category.

![Timeline: at 0.99s the model commits 04_meals, at 1.40s a human changes it to 08_personal, at 2.03s the explanation finishes, at 2.04s the stale explanation is discarded.](figures/fig4-override.png)

*Figure 4 — The application state can change while the stream is still open. Image by the author.*

So before storing the essay, the worker checks whether the model still owns the decision. If a person has overridden it, the explanation is discarded: it would justify a category the transaction no longer has.

The parser turned out to be the small part. Most of the work was in the operational details around it:

| Risk | Policy |
|---|---|
| Slow verdict | A hard 2-second deadline for the verdict; on expiry the deterministic pipeline answers. In production this happens for about 7% of live requests. |
| Caller disconnects | Before the commit, cancel the upstream generation. After it, the drain is expected to outlive the request. |
| Retries | Never retry a live stream: a retry is a second generation, a second bill and a race between two commits. |
| Proxy buffering | Any layer in between can silently batch the stream. Everything still works, just late, so test incrementality end to end. |
| Connection pressure | Bound the background drains (we run 64) and size connection pools for the full response lifetime, not the verdict time. |
| Deploys | Decide explicitly what happens to in-flight drains. The verdicts are safe; only explanations are lost. |
| Usage accounting | Token usage often arrives in the final chunk, so a stream closed early makes cost dashboards undercount. |
| Cost | Closing the stream right after the verdict saves output tokens but loses the essay. That is a separate trade-off with different product semantics. |

## What we measured

We measured on the production path, not in a test harness. The classifier calls Gemini 3.5 Flash through Vertex AI in `europe-west2`, behind our internal LLM proxy, with the real prompt (about 28,000 input tokens of categorization rules and merchant context) and the real schema, with a median of about 220 output tokens per response. The numbers below cover 288,298 live requests between August and early October 2026 that received an early verdict. Times are measured inside our service, from receiving the request, so they include the proxy and network as well as the model.

| Metric | Median | p90 | p99 |
|---|---|---|---|
| Time to early verdict | 0.99s | 1.29s | 1.89s |
| Time to complete response | 2.03s | 2.50s | 3.68s |

Across those requests the early verdict never differed from the completed JSON, and no request was aborted for out-of-order fields, an unknown category or an unparseable verdict. About 7% of all live requests (22,926 of 328,675) missed the 2-second verdict deadline and were answered by the deterministic pipeline instead; the time to the complete response is what every request would have waited without early commit.

Zero disagreements in 288,298 requests doesn't prove the rate is zero. By the rule of three, the 95% upper bound is about 0.001%. The real guarantee is structural (closing quote, terminator, enum membership); the counts only show that production never contradicted it.

Did moving `confidence` ahead of the explanations change the answers? We replayed 400 recent production requests through the same model at temperature 0 with the same prompts, using four schemas: the verdict-first order (A), the same schema again (A′, to measure the model's own run-to-run noise), the legacy order with `confidence` last (B), and a placebo (C) that keeps the verdict first but shuffles the three essay fields. All fields were required in every variant, so only the order differed.

| Comparison | Category changed | Confidence changed | Review routing changed |
|---|---|---|---|
| A vs A′ (same schema twice) | 1.8% | 5.0% | 0.3% |
| A vs B (`confidence` first vs last) | 7.8% | 36% | 1.3% |
| A vs C (placebo: essay fields shuffled) | 7.3% | 25% | 1.5% |

Moving `confidence` did not shift it in either direction: the mean change was −0.2 points (sign test p = 0.62), and review routing changed about as often as with the placebo. The category column is the more useful lesson. `category` comes first in every variant, yet it changed in 7.8% of requests with the legacy order and 7.3% with the placebo, compared with 1.8% from noise alone. The model is sensitive to *any* change in the schema, presumably because the schema is part of its input. A reorder should therefore be evaluated like a prompt change, not treated as a free refactor. Very few of these transactions have been corrected by a person, so this test measures stability, not which order is more accurate.


The shape of the workload explains the size of the gain. With about 28,000 input tokens and 220 output tokens, prefill is a fixed cost we can't do much about, while the decode tail is the part we control, and early commit removes most of it. The ratio will be different for other systems: it depends on how many tokens come after the last verdict field, not on how fast the model is. If the full response already fits your latency budget, there's nothing here worth the extra complexity.

## When not to do this

- **The decision can't be made a short, closed-set value.** Free-form answers have no reliable point at which they are final, and a verdict that needs later fields to be interpreted is not a verdict.
- **The provider doesn't give you constrained decoding with stable field order on streamed output.** Then there is nothing safe to commit early, and the right behaviour is to wait.
- **There is no deterministic fallback, or the full response is already fast enough.** Early commit adds concurrency, parsing and lifecycle management, and only pays off when the latency matters.

## Trying it on your system

Put a closed-set decision first and the long explanation last, stream the response, and record when the decision becomes structurally final compared with when the response completes. The repository includes a probe that does this against a real model and reports whether the field order held, whether the early verdict matched the final object, and how much time came off the critical path.

Before relying on it, check schema enforcement, field ordering and chunk behaviour in your provider's documentation and on the exact model you plan to ship:

- **OpenAI** — [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) · [Streaming Responses](https://developers.openai.com/api/docs/guides/streaming-responses)
- **Anthropic** — [Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) · [Streaming Messages](https://platform.claude.com/docs/en/build-with-claude/streaming)
- **Google Gemini** — [Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- **Amazon Bedrock** — [Structured Outputs](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html)
- **vLLM** — [Structured Outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/)

None of the individual pieces is new: constrained decoding, incremental parsing, background work and fallbacks are all standard. What changes is *when* the system is allowed to act. A structured response doesn't have to be complete for part of it to be final.
