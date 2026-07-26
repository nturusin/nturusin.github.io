# Early commit on a streamed structured LLM response

Reference implementation for *Act on the Verdict. Stream the Rest.*

A structured LLM response can become useful before it becomes complete. If the
decision fields come first in the schema, an application can act as soon as
those fields are **provably final**, and drain the explanation in the background.

Committing early is only safe with three structural proofs:

| Proof | Question | Evidence required |
|---|---|---|
| Completion | Has the value finished arriving? | Closing quote, or a JSON terminator for a number |
| Membership | Is it a legal value? | Present in the enum declared in the schema |
| Order | Did the verdict come first? | No later field seen before the verdict closed |

No dependencies beyond the standard library.

## Run

```bash
python3 test_early_commit.py   # 8 structural tests
python3 demo.py                # field order vs. time-to-act
```

`demo.py` replays a synthetic response at a fixed token rate. Same bytes, same
token count — only the field order differs:

```
schema A - verdict split around the essay (confidence last)
  early commit              not possible (essay field arrived before the verdict)
  time to act                0.65s
  removed from critical path 0%

schema B - verdict first
  time to act                0.33s
  time to complete           0.65s
  removed from critical path 49%
```

This is a **mechanism demo, not a benchmark**. The ratio you get depends on your
model, your provider, and above all the ratio of verdict tokens to essay tokens.
Measure your own payload.

## The hazard this guards against

An unterminated number is not a value:

```
{"category": "04_meals", "confidence": 8
```

`confidence` is visible, but the next chunk may be `7,` — the real value is
`87`. Rendering `8` for a moment is harmless; writing it to a database or
routing on it is not. `test_the_8_that_becomes_87` pins this behaviour.

## Applying it

1. Split your fields into a verdict (what the system acts on) and an essay
   (what humans read later).
2. Put the verdict first in the schema and confirm your provider preserves
   field order while streaming.
3. Parse the **accumulated buffer**, never an individual frame.
4. Require completion, membership, and order before committing.
5. Drain the rest in a bounded background worker, then verify the finished
   object still agrees with what you committed.
6. Keep a deterministic fallback: a missing early verdict must be recoverable.
