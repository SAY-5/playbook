/* Port of playbook/agent/loop.py: the bounded tool-calling loop, producing a full RunTrace. */
import type { Message, MessageBlock, RuleEngine } from "./engine";
import type { Prng } from "./prng";
import { API_TO_DOTTED, type ToolExecutor } from "./tools";
import type { JsonObject, RunTrace, ToolUse } from "./types";

export interface RunOptions {
  procedureSlug: string;
  promptVersion: number;
  scenarioId: string;
  model?: string;
  maxSteps?: number;
}

/** Drive the model until it stops calling tools or the step budget is exhausted. */
export function runAgent(
  engine: RuleEngine,
  prng: Prng,
  systemPrompt: string,
  userMessage: string,
  executor: ToolExecutor,
  opts: RunOptions,
): RunTrace {
  const maxSteps = opts.maxSteps ?? 12;
  const model = opts.model ?? "claude-sonnet-5";
  const trace: RunTrace = {
    runId: prng.hex(12),
    procedureSlug: opts.procedureSlug,
    promptVersion: opts.promptVersion,
    scenarioId: opts.scenarioId,
    mode: "offline",
    model,
    systemPrompt,
    userMessage,
    turns: [],
    toolCalls: [],
    finalText: "",
    status: "running",
    error: null,
  };
  const messages: Message[] = [{ role: "user", content: userMessage }];

  try {
    let exhausted = true;
    for (let turn = 1; turn <= maxSteps; turn++) {
      const response = engine.respond({ model, system: systemPrompt, messages });
      const toolUses: ToolUse[] = response.content
        .filter((b) => b.type === "tool_use")
        .map((b) => ({ id: b.id ?? "", name: b.name ?? "", input: b.input ?? {} }));
      const text = response.content.filter((b) => b.type === "text").map((b) => b.text ?? "").join("");
      trace.turns.push({
        turn,
        stopReason: response.stop_reason,
        text,
        toolUses,
        inputTokens: response.usage.input_tokens,
        outputTokens: response.usage.output_tokens,
      });
      if (response.stop_reason !== "tool_use" || !toolUses.length) {
        trace.finalText = text;
        trace.status = "completed";
        exhausted = false;
        break;
      }

      messages.push({ role: "assistant", content: response.content });
      const results: MessageBlock[] = [];
      for (const block of toolUses) {
        let result: JsonObject | null = null;
        let error: string | null = null;
        try {
          result = executor.execute(block.name, { ...block.input });
        } catch (exc) {
          // tool failures are data, not crashes
          error = exc instanceof Error ? exc.message : String(exc);
        }
        // Simulated latency, seeded: the real loop measures wall time around an HTTP call.
        const elapsed = 4 + prng.int(28);
        trace.toolCalls.push({
          turn,
          toolUseId: block.id,
          name: API_TO_DOTTED[block.name] ?? block.name,
          args: { ...block.input },
          result,
          error,
          durationMs: elapsed,
        });
        results.push({
          type: "tool_result",
          tool_use_id: block.id,
          content: JSON.stringify(error === null ? result : { error }),
          is_error: error !== null,
        });
      }
      messages.push({ role: "user", content: results });
    }
    if (exhausted) trace.status = "max_steps";
  } catch (exc) {
    trace.status = "error";
    trace.error = exc instanceof Error ? `${exc.name}: ${exc.message}` : String(exc);
  }
  return trace;
}

export function toolNames(trace: RunTrace): string[] {
  return trace.toolCalls.map((c) => c.name);
}

export function callsNamed(trace: RunTrace, name: string) {
  return trace.toolCalls.filter((c) => c.name === name);
}
