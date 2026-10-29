# balanced60, Skill v12, and RAG v12/v13 audit

Date: 2026-10-27 (Asia/Tokyo)

This is a development audit, not an acceptance result. balanced60 was previously exposed and all v12/v13 tasks were authored development fixtures. Model reasoning is used only as a diagnostic clue; code, messages, hashes, public checks, and scored outputs determine outcomes.

## 1. Mechanical audit

The read-only audit is implemented by [`audit_campaign.py`](audit_campaign.py) and saved in [`campaign-audit.json`](campaign-audit.json). Full reasoning text is indexed separately in [`reasoning-index.json`](reasoning-index.json).

- balanced60: 120/120 solves and 120/120 grades; 184 generation calls checked.
- Skill v12: 96/96 attempts and 48/48 pairs.
- RAG v12: 180/180 attempts and 90/90 pairs.
- RAG v13: 80/80 attempts and 40/40 pairs.
- All actual generation requests enabled thinking, used temperature 0, the frozen seed and output allowance, and had non-empty reasoning.
- Every functionally scored v12/v13 draft matched the recorded draft, selected solution, judge input before execution, judge input after execution, and public judge source hash.
- Checker-rejected drafts were not scored by falling back to the old candidate.
- balanced60 grade inputs matched the selected current-run solution before and after grading.
- No planned job was missing or extra, no experiment recorded an infrastructure error, and no duplicate-context shortcut was used.

## 2. balanced60

### 2.1 What this comparison actually measured

The off and `rag-on` arms were identical for all 60 tasks:

- 60/60 request sequences equal;
- 60/60 responses equal;
- 60/60 selected code hashes equal;
- 60/60 final scores equal;
- no RAG card was sent.

The `rag-on` path returned `unknown` for 82 assembly decisions and `not_needed` for 10; the off path recorded 92 disabled decisions. Therefore balanced60 is evidence that conservative empty return preserved the baseline, not evidence that injected RAG helps or hurts.

### 2.2 Outcome and cost

| Outcome | Unique tasks | Delivered | Tokens, one arm |
| --- | ---: | ---: | ---: |
| L3 functional pass | 36 | 36 | 366,944 |
| L1 compile pass, function fail | 7 | 7 | 66,400 |
| L0 | 17 | 1 | 612,030 |
| Total | 60 | 44 | 1,045,374 |

Sixteen tasks delivered no complete final draft. They used 580,214 tokens, 55.5% of the arm's total, in 32 calls. One additional task (`sequence_generator`) delivered code that redeclared its ANSI output and failed compilation. Thus the largest observed loss is non-delivery and delivery validation, not missing RAG coverage.

### 2.3 Failure-to-method audit

The seven L1 failures are best treated as method execution or temporal-contract failures, not automatically as missing knowledge:

| Task | Observable failure | Diagnostic interpretation from code and reasoning |
| --- | --- | --- |
| `rtllm_pulse_detect` | 1 functional mismatch | FSM timing/overlap implementation did not match the public temporal contract despite repeatedly checking the `01010` example. |
| `settable_counter` | 19/273 mismatches | A separate `cnt` register made `number` and `zero` observe the old count, introducing an extra cycle. |
| `pulse_synchronization_circuit` | 140/1009 mismatches | The toggle synchronizer's pulse timing did not match the required slow-domain observation contract. |
| `comparison_of_three_input_numbers` | 408/421 mismatches | The selected hierarchy and output register introduced the wrong latency/structure relative to the task contract. |
| `full_subtractor_using_decoder` | 50/57 mismatches | Reasoning listed the correct active-low minterms, but final RTL combined them with NOR instead of the required active-low sum-of-minterms operation. |
| `data_serial-to-parallel` | 89/151 mismatches | Bit placement and/or `valid_b` cycle alignment did not match the stream contract. |
| `chapter12_ctrl` | 8/223 mismatches | At least one stall mask/priority mapping was wrong despite a syntactically complete combinational implementation. |

The 16 non-deliveries include both large designs (AES, systolic GEMM, asynchronous FIFOs, division units, Newton square root, CP0, gshare, Booth multiplication, Conway Life, wide stream conversion) and smaller local tasks (Gray counter, fractional divider, ALU). In many final reasoning tails the model had already described a plausible implementation, then continued reconsidering latency, reset, unknown inputs, reference expectations, or alternative architectures until the output allowance ended. This is evidence of failure to stop and deliver; it is not proof that the proposed implementation would have passed.

balanced60 can now be used as a development failure-discovery set, but not as a holdout. The useful next artifacts are small public temporal checks for the seven L1 cases and a separate delivery intervention for the 16 non-deliveries. Hidden results and references must not become RAG cards.

## 3. Skill v12

### 3.1 Paired result

For the 36 fact-gap pairs (12 authored tasks across three feedback views):

| Metric | No Skill | Fixed local Skill |
| --- | ---: | ---: |
| Complete draft | 36/36 | 36/36 |
| Full attempt success | 35/36 | 36/36 |
| Total tokens | 152,110 | 167,261 |
| Tokens per success | 4,346 | 4,646 |
| Sum of attempt wall time | 1,940.7 s | 2,160.0 s |

Skill increased tokens by 10.0% and wall time by 11.3%. The only success delta was `masked-priority3` with a first-counterexample feedback. Control reasoning found the correct eligibility relation but emitted illegal expression indexing, `(req & mask)[0]`; the Skill arm emitted explicit per-bit conditions and passed. The other two feedback views passed without Skill as well. This is a narrow code-expression rescue, not robust evidence that the method text taught a missing concept.

### 3.2 By Skill body

- Width-local method: 18/18 succeeded in both arms; tokens rose 84,183 to 96,222 (+14.3%). The largest increases were `window13` and the full-log `straddle5` pair. In those logs, the injected arm repeatedly reconsidered shift, variable part-select, signedness, and out-of-contract behavior after already finding the correct bit mapping.
- Combinational-local method: success rose 17/18 to 18/18; tokens rose 67,927 to 71,039 (+4.6%). The one rescue was the syntax case above. Most tasks already had enough task and counterexample evidence to derive the right relation.
- FSM method: not exercised in this campaign. balanced60 FSM/protocol failures cannot be used as a fixed-Skill comparison.

All 12 method-already-provided pairs had identical actual messages and identical responses. Eleven had identical code; the remaining pair produced identical non-delivery. This validates exact duplicate rejection for these fixtures, not general semantic redundancy detection.

### 3.3 Skill disposition

- Keep the combinational body offline and revise it around a mechanically checkable eligible relation plus safe final expression forms. Re-test on independent tasks where feedback does not already give the relation.
- Do not restore width Skill auto-injection. Add a demand predicate and a stop condition before another fixed comparison.
- Keep FSM split into output-state, counter-boundary, pulse, and recovery submethods; first add public short-sequence checks. No current result supports automatic FSM injection.
- The candidate router should often choose no Skill. High topical coverage is not the objective.

## 4. RAG v12

### 4.1 Aggregate fact-gap result

Across 72 pairs:

| Metric | Control | Card injected |
| --- | ---: | ---: |
| Complete draft | 69/72 | 69/72 |
| Full attempt success | 66/72 | 67/72 |
| Total tokens | 572,062 | 538,148 |
| Tokens per success | 8,668 | 8,032 |
| Sum of attempt wall time | 10,124.5 s | 9,404.4 s |

This is a net +1 success and -5.9% tokens, but it combines two different roles. The 18 new B02 tasks had equal success (50/54 versus 50/54) and -8.3% tokens; three pairs improved and three regressed. The six previously exposed confirmation tasks improved 16/18 to 17/18, but lost one delivery and changed tokens by only +0.5%.

### 4.2 Card-level evidence

- `slice-signedness`: 4/6 to 6/6, with fewer tokens. Both rescued confirmation cases avoided malformed replication/concatenation syntax, but these are previously exposed fixtures and the benefit is partly expression choice rather than a clean signedness causal result. Retain as promising offline evidence only.
- `remainder-sign`: 7/9 to 8/9 and one extra delivery. It rescued the first- and three-counterexample views of `remainder-variable-sign`, but the full-log card arm consumed the allowance without delivery while control passed. Revise and re-test; the current effect is feedback-view unstable.
- `mixed-sign-arithmetic`: 8/9 in both arms and substantially fewer tokens, but one view improved and one regressed. The regression used malformed `$signed({2{a[3]}, a})`. Retain as an efficiency hypothesis, not correctness evidence.
- `division-rounding`: 8/9 to 7/9. The injected full-log arm selected malformed manual sign extension while control's direct bit formula passed. Reject the current card as promotion evidence.
- `concat-signedness`: 6/6 to 5/6 because an injected confirmation arm never delivered. Reject current promotion evidence.
- `sign-conversion-width`: 6/6 in both arms, but card tokens rose about 30%. Do not promote.
- `arithmetic-right-sign`, `boolean-versus-bitwise`, and `unsigned-negative-check`: no correctness change. Cost effects were small or unfavorable; retain offline pending genuinely missing-fact tasks.

Thinking shows a repeated failure mode: the model often reached the correct simple operation (`%`, `/`, `>=`, a direct slice or shift) and then expanded into magnitude reconstruction, manual sign extension, or alternative implementations. A card sometimes shortened this enough to deliver and sometimes lengthened it past the limit. Card design therefore needs an explicit minimal action and stop condition, not more background explanation.

All 18 fact-already-provided pairs had identical messages, responses, and code. Exact correct-empty behavior passed.

## 5. RAG v13 ten-batch campaign

### 5.1 Aggregate fact-gap result

| Metric | Control | Card injected |
| --- | ---: | ---: |
| Complete draft | 20/20 | 19/20 |
| Full attempt success | 19/20 | 17/20 |
| Total tokens | 112,379 | 112,424 |
| Tokens per success | 5,915 | 6,613 |

The cards lost two net successes and increased tokens per success by 11.8%. The lower aggregate wall time is explained by one non-delivery and is not an efficiency win.

Important paired cases:

- `lhs-not-sign-coercion` rescued `destination-signed-offset`: control understood the need but emitted malformed replication syntax; the card arm used an outer concatenation and passed. On `destination-signed-quotient`, the card arm repeated the malformed replication form and was rejected while control passed. Net correctness was unchanged and the effect is unstable.
- `based-literal-sign` changed a correct bit-pattern implementation into `a < 4'shE`, which tests less than -2 instead of less than -1. The card addressed signedness but the model changed the mathematical boundary. This is a functional regression.
- `division-equality-boundary` caused `division-iterative-quotient` to expand a one-character `>` to `>=` fix into a new restoring-divider analysis and never deliver. This is the clearest over-expansion regression.
- `comparison-result-sign`, `size-cast-sign`, and `block-carry-chain` had no correctness delta and showed small two-task efficiency signals. They remain offline candidates because each has only two related authored contexts and one feedback view.
- BCD carry, signed overflow, unsigned borrow, and weighted partial products had no correctness delta and approximately neutral or higher costs. No promotion evidence exists.

All 20 fact-already-provided pairs had identical messages and responses; 19 produced identical code and one produced identical non-delivery. Exact correct-empty behavior passed.

## 6. Cross-line conclusion

1. The strongest verified framework result is safety: exact already-provided knowledge is declined without changing the model request in 50/50 Skill/RAG pairs, and balanced60 `rag-on` preserved the baseline when no card was admissible.
2. The strongest system bottleneck is delivery and stopping. balanced60 non-deliveries consumed more than half of all tokens, and several RAG/Skill regressions occurred after the reasoning had already identified a sufficient minimal fix.
3. Skill evidence is weakly positive only for one combinational syntax rescue and negative on cost. The width method should remain off; FSM remains untested.
4. RAG v12 contains narrow efficiency and rescue signals, but card behavior is not stable across feedback views. RAG v13 is net harmful on success and cost per success. Neither justifies default injection.
5. These campaigns manually inject fixed candidates. They do not compare exact, BM25, dense, or hybrid retrieval and do not validate automatic routing.

## 7. Recommended next work

1. Repair delivery first: add a separately testable stop-and-deliver policy that does not forward truncated thinking. Preserve thinking, record non-delivery, and compare against the same tasks/checkers.
2. Add mechanical micro-checks for the seven balanced60 L1 failures, using both arms equally. Use the resulting public counterexamples to classify method need; do not turn hidden answers into cards.
3. Revise only three RAG facts for the next small batch:
   - signed source coercion: prefer a signed temporary or direct cast and explicitly avoid malformed replication concatenations;
   - division equality: state the minimal comparison edit and stop after boundary verification;
   - signed remainder: normalize operand width, use the language remainder rule directly when applicable, and stop.
4. Re-test the combinational Skill on genuinely missing-method tasks plus already-given and inapplicable negatives. Keep width and FSM separate.
5. Only after single-item value is repeatable should routing and Skill+RAG joint use be tested. Keep production defaults off until then.
