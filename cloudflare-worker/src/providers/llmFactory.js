import { GeminiProvider } from "./geminiProvider.js";

/**
 * Factory to instantiate the configured LLM Provider.
 * Allows seamless switching between Gemini, OpenAI, Anthropic, etc.
 * 
 * @param {Object} env - Cloudflare Worker environment variables.
 * @returns {import("./baseLlmProvider.js").BaseLlmProvider}
 */
export function createLlmProvider(env) {
  const providerName = (env.LLM_PROVIDER || "gemini").toLowerCase();

  switch (providerName) {
    case "gemini":
    default:
      return new GeminiProvider(
        env.GEMINI_API_KEY, 
        env.GEMINI_MODEL || "gemini-3.5-flash-lite"
      );
  }
}
