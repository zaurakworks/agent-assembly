import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { completeSimple } from "@oh-my-pi/pi-ai";

const REQUEST_VERSION = "agent-assembly.omp-completion/v1";
const RESULT_PREFIX = "__AGENT_ASSEMBLY_OMP_RESULT__";
const MODEL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\/[A-Za-z0-9][A-Za-z0-9._/+:-]{0,191}$/;

interface CompletionRequest {
	schema_version: string;
	model: string;
	prompt: string;
	max_tokens: number;
}

function parseRequest(value: unknown): CompletionRequest {
	if (!value || typeof value !== "object" || Array.isArray(value)) {
		throw new Error("request must be an object");
	}
	const request = value as Record<string, unknown>;
	const keys = Object.keys(request).sort();
	if (keys.join(",") !== "max_tokens,model,prompt,schema_version") {
		throw new Error("request fields are invalid");
	}
	if (request.schema_version !== REQUEST_VERSION) {
		throw new Error("request version is unsupported");
	}
	if (typeof request.model !== "string" || !MODEL_PATTERN.test(request.model)) {
		throw new Error("model must be an explicit provider/model selector");
	}
	if (typeof request.prompt !== "string" || request.prompt.length === 0) {
		throw new Error("prompt must be non-empty");
	}
	if (!Number.isInteger(request.max_tokens) || (request.max_tokens as number) < 1 ||
		(request.max_tokens as number) > 512) {
		throw new Error("max_tokens must be an integer from 1 to 512");
	}
	return request as unknown as CompletionRequest;
}

export default function agentAssemblyVerifier(pi: ExtensionAPI) {
	pi.registerCommand("agent-assembly-verifier", {
		description: "Run one stateless, toolless verifier completion",
		handler: async (args, ctx) => {
			const requestPath = args.trim();
			if (!requestPath) throw new Error("request path is required");
			const request = parseRequest(await Bun.file(requestPath).json());
			const model = ctx.models.resolve(request.model);
			if (!model || `${model.provider}/${model.id}` !== request.model) {
				throw new Error("requested model is unavailable or resolved ambiguously");
			}

			const response = await completeSimple(
				model,
				{
					systemPrompt: [
						"Score both trajectories against the supplied criteria. End with exactly one <score_A> and one <score_B> tag using uppercase A-T tokens.",
					],
					messages: [
						{
							role: "user",
							content: [{ type: "text", text: request.prompt }],
							timestamp: Date.now(),
						},
					],
				},
				{
					apiKey: ctx.modelRegistry.resolver(model),
					maxTokens: request.max_tokens,
					disableReasoning: true,
				},
			);

			const text = response.content
				.filter(block => block.type === "text")
				.map(block => block.text)
				.join("");
			const result = {
				schema_version: REQUEST_VERSION,
				requested_model: request.model,
				model: `${response.provider}/${response.model}`,
				stop_reason: response.stopReason,
				usage: response.usage,
				text,
			};
			process.stdout.write(`${RESULT_PREFIX}${JSON.stringify(result)}\n`);
			ctx.shutdown();
		},
	});
}
